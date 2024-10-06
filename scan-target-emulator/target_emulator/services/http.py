import os
import logging
import json
import gzip
import traceback

import ncompress
import brotli
from flask import Flask

from . import Service
from ..models import SimpleHTTPEndpoint, ComplexHTTPEndpoint

LOGGER = logging.getLogger("target_emulator")


class HTTP(Service):
    name = "HTTP"

    def _parse_data_for_test_case(self):
        LOGGER.info("Parsing data for HTTP...")
        self._endpoints = list()
        # NOTE: Not implemented yet in the recorder
        # Simple files that can only be accessed by GET
        # TODO: What about when e.g. /folder1/ should link to /folder/index.html?
        for path, _, files in os.walk(self._service_base_path):
            for file_name in files:
                file_path = os.path.join(path, file_name)
                relative_path = os.path.relpath(file_path, self._service_base_path)
                uri = f"/{relative_path}"
                if not file_name.lower().endswith(".json"):
                    endpoint = SimpleHTTPEndpoint(file_path, uri)
                    self._endpoints.append(endpoint)

        # More complex HTTP endpoints that can allow more than just GET
        with open(
            self._service_base_path / "endpoint_mapping.json", "r", encoding="utf-8"
        ) as endpoint_mapping_file:
            # TODO: Exception handling
            endpoint_mapping_json = json.load(endpoint_mapping_file)

        endpoints_info = endpoint_mapping_json["Endpoints"]
        self._preprocess_all_criteria(endpoints_info)

        for endpoint_info in endpoints_info:
            endpoint = ComplexHTTPEndpoint(endpoint_info)
            self._endpoints.append(endpoint)

    # TODO: Minimize duplicated code and make it more pretty
    def _preprocess_all_criteria(self, endpoints_info: list) -> None:
        # Replace all references to 192.0.2.123 in headers/bodies/responses with current host
        for endpoint_info in endpoints_info:
            for response_handling_info in endpoint_info["Methods"].values():
                criteria_info = response_handling_info["Criteria"]
                for criteria in criteria_info.values():
                    for criterion in criteria:
                        criterion["URL_Parameters"] = criterion["URL_Parameters"].replace(
                            self.recorded_host, self.host
                        )
                        for header_key, header_value in criterion["Headers"].items():
                            if isinstance(header_value, str):
                                criterion["Headers"][header_key] = header_value.replace(
                                    self.recorded_host, self.host
                                )
                            else:
                                for i, entry in enumerate(header_value):
                                    header_value[i] = entry.replace(self.recorded_host, self.host)
                        for line_num, line_text in criterion["Body"].items():
                            criterion["Body"][line_num] = line_text.replace(
                                self.recorded_host, self.host
                            )
                responses = response_handling_info["Responses"]
                for response in responses:
                    for header_key, header_value in response["Headers"].items():
                        if isinstance(header_value, str):
                            response["Headers"][header_key] = header_value.replace(
                                self.recorded_host, self.host
                            )
                        else:
                            for i, entry in enumerate(header_value):
                                header_value[i] = entry.replace(self.recorded_host, self.host)
                    response["Body"] = response["Body"].replace(self.recorded_host, self.host)
                    # It's okay if we pass the body as bytes to Flask later
                    response_body_bytes = response["Body"].encode("utf-8", errors="ignore")
                    response["Body"] = self._compress_body(response["Headers"], response_body_bytes)

    def _compress_body(self, http_headers: dict, body_bytes: bytes) -> str:
        # According to https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Encoding
        # If the recorded response was compressed/encoded, we do that as well
        lowercase_headers = dict((k.lower(), v) for k, v in http_headers.items())
        content_encoding = lowercase_headers.get("content-encoding")
        if content_encoding:
            # e.g. gzip,deflate
            content_encodings = content_encoding.lower().replace(" ", "").split(",")
            for encoding_method in content_encodings:
                # Decode/decompress it
                if encoding_method == "gzip":
                    # Should also handle deflate automatically
                    body_bytes = gzip.compress(body_bytes)
                elif encoding_method == "deflate" and not "gzip" in content_encodings:
                    # NOTE: If this is deflate on its own without gzip, probably use gzip?
                    # This is just a guess what's best
                    body_bytes = gzip.compress(body_bytes)
                elif encoding_method == "compress":
                    body_bytes = ncompress.compress(body_bytes)
                elif encoding_method == "br":
                    body_bytes = brotli.decompress(body_bytes)
                else:
                    LOGGER.error("Unknown encoding method '%s'", encoding_method)
                    exit(1)
        return body_bytes

    def deploy(self):
        LOGGER.info("Deploying HTTP server...")
        app = Flask("Target-Emulator")
        for endpoint in self._endpoints:
            endpoint.deploy(app)
        try:
            app.run(host=self.host, port=self.port, threaded=True)
        except:  # pylint: disable=bare-except
            stack_trace = traceback.format_exc()
            LOGGER.error("Error when setting up flask on port %s:\n%s", self.port, stack_trace)
