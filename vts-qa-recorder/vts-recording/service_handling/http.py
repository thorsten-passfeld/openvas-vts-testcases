import os
import json
import gzip

from pathlib import Path
from collections import defaultdict, OrderedDict

import ncompress
import brotli
from dpkt.http import Request
from dpkt import dpkt

from . import ServiceHandlerBase
from ..models import CustomResponse


class ServiceHandlerHTTP(ServiceHandlerBase):
    name = "HTTP"

    @staticmethod
    def detect(data: bytes) -> bool:
        # Try parsing it as an HTTP request
        try:
            Request(data)
            return True
        except dpkt.UnpackError:
            return False

    @staticmethod
    def parse_data(data: bytes, is_request: bool):
        try:
            if is_request:
                parsed_data = Request(data)
            else:
                parsed_data = CustomResponse(data)
        except dpkt.UnpackError:
            print(f"{'Request' if is_request else 'Response'}: The HTTP data is missing chunks.")
            return None

        return parsed_data

    @staticmethod
    def save_to_new_test_case(
        service_base_dir: Path,
        recorded_communications: list,
        owner_uid: int,
        owner_gid: int,
    ):
        endpoint_mapping = dict()
        endpoint_mapping["Endpoints"] = list()

        # First, group all communications by what URI they are for
        communications_by_uri = preprocess_and_group_communications(recorded_communications)

        # Create the dict for each URI with instructions on how to serve it as the target emulator
        for base_uri, communications_for_method in communications_by_uri.items():
            endpoint_info = OrderedDict()
            endpoint_info["URI"] = base_uri
            # HTTP methods like GET, POST, etc.
            endpoint_info["Methods"] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

            for method, communications in communications_for_method.items():
                print(method)
                criteria_superset = list()
                criteria_subset = list()
                responses = list()

                all_handled_requests = list()
                criterion_id_num = 1
                for i, current_request_response_info in enumerate(communications):
                    print(f"Current index -> i = {i}")
                    # This is the request to check and the response to store
                    current_request_info = current_request_response_info["Client"]
                    current_response_info = current_request_response_info["Server"]

                    responses.append(create_response_for_json(current_response_info))

                    # Make sure that we only handle each unique request as its own criterion once
                    stringified_current_request = str(current_request_info)
                    if stringified_current_request in all_handled_requests:
                        continue
                    else:
                        all_handled_requests.append(stringified_current_request)

                    current_request_criterion = OrderedDict()

                    # Criterion ID
                    criterion_id = f"{method}{criterion_id_num}"
                    current_request_criterion["ID"] = criterion_id
                    criterion_id_num += 1

                    # URL parameters
                    base_uri_and_parameters = current_request_info.uri.split("?", 1)
                    if len(base_uri_and_parameters) > 1:
                        url_parameters = "?" + base_uri_and_parameters[1]
                    else:
                        url_parameters = ""
                    current_request_criterion["URL_Parameters"] = url_parameters

                    # Deep copy to avoid messing with other dicts using the headers
                    current_request_criterion["Headers"] = OrderedDict(current_request_info.headers)

                    current_request_body_text = current_request_info.body.decode(
                        "utf-8", errors="ignore"
                    )
                    # To uniquely identify each request's body, every line number and text matters
                    current_request_body_lines = dict(
                        enumerate(current_request_body_text.splitlines())
                    )
                    # The deep copy here is intentional, to check if this request is a subset later
                    current_request_criterion["Body"] = OrderedDict(current_request_body_lines)

                    current_request_related_responses = [i]

                    # Iterate over other elements and compare them all to find the differences
                    other_communications = {
                        j: info for j, info in enumerate(communications) if j != i
                    }
                    for j, other_request_response_info in other_communications.items():
                        other_request_info = other_request_response_info["Client"]
                        other_request_headers = other_request_info.headers

                        # If the request is the same as another one, we can link the request
                        # to multiple responses
                        print("Current Request ->", stringified_current_request)
                        print("Other Request ->", str(other_request_info))
                        if stringified_current_request == str(other_request_info):
                            print("Requests are the same!")
                            current_request_related_responses.append(j)
                            continue

                        # Check if any stored header of the current request is not unique
                        for (
                            current_header_key,
                            current_header_value,
                        ) in dict(current_request_criterion["Headers"]).items():
                            # Try to find the exact same header and delete it
                            other_header_value = other_request_headers.get(current_header_key)
                            if other_header_value and current_header_value == other_header_value:
                                # We have proven that this header does not identify the request
                                del current_request_criterion["Headers"][current_header_key]

                        if current_request_body_text:
                            other_request_body_text = other_request_info.body.decode(
                                "utf-8", errors="ignore"
                            )

                            other_request_body_lines = dict(
                                enumerate(other_request_body_text.splitlines())
                            )

                            # Find all unique lines of the current request body
                            # With every comparison to other requests, the unique strings
                            # will probably become less and less
                            # print("Before ->", current_request_criterion["Body"])
                            # print("Other ->", other_request_body_lines)
                            for line_num, line_text in dict(
                                current_request_criterion["Body"]
                            ).items():
                                line_in_other_request_body = other_request_body_lines.get(line_num)
                                if (
                                    line_in_other_request_body
                                    and line_text == line_in_other_request_body
                                ):
                                    del current_request_criterion["Body"][line_num]
                            # print("After ->", current_request_criterion["Body"])

                    is_subset = False
                    # If every value in the criterion is empty, be strict and use all data from the request
                    if (
                        not current_request_criterion["Headers"]
                        and not current_request_criterion["Body"]
                    ):
                        is_subset = True

                    if not current_request_criterion["Headers"]:
                        current_request_criterion["Headers"] = OrderedDict(
                            current_request_info.headers
                        )
                    if not current_request_criterion["Body"]:
                        current_request_criterion["Body"] = dict(
                            enumerate(current_request_body_text.splitlines())
                        )

                    assembled_criterion = create_criterion_for_json(
                        current_request_criterion["ID"],
                        current_request_criterion["URL_Parameters"],
                        current_request_criterion["Headers"],
                        current_request_criterion["Body"],
                        current_request_related_responses,
                    )
                    if is_subset:
                        criteria_subset.append(assembled_criterion)
                    else:
                        criteria_superset.append(assembled_criterion)

                # For the responses, we have to remap the indexes
                unique_responses = list()
                for current_response_index, response in enumerate(responses):
                    # Try finding this response in the unique responses
                    try:
                        new_response_index = unique_responses.index(response)
                    except ValueError:
                        # This response is unique
                        unique_responses.append(response)
                        new_response_index = len(unique_responses) - 1
                    # Remap the criteria depending on this response index
                    for criterion in criteria_superset + criteria_subset:
                        linked_responses = criterion["Responses"]
                        # Update the existing linked responses in-place
                        linked_responses[:] = [
                            new_response_index if current_response_index == i else i
                            for i in linked_responses
                        ]
                responses = unique_responses

                endpoint_info["Methods"][method]["Criteria"]["Superset"] = list(criteria_superset)
                endpoint_info["Methods"][method]["Criteria"]["Subset"] = list(criteria_subset)
                endpoint_info["Methods"][method]["Responses"] = list(responses)
            endpoint_mapping["Endpoints"].append(endpoint_info)

        print("Done processing all endpoint data.")
        print(json.dumps(endpoint_mapping, sort_keys=False, indent=2))
        save_endpoint_mapping_to_test_case(service_base_dir, endpoint_mapping, owner_uid, owner_gid)


def decompress_body(http_headers: dict, body_bytes: bytes) -> str:
    # According to https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Encoding
    lowercase_headers = dict((k.lower(), v) for k, v in http_headers.items())
    content_encoding = lowercase_headers.get("content-encoding")
    if content_encoding:
        # e.g. gzip,deflate
        content_encodings = content_encoding.lower().replace(" ", "").split(",")
        for encoding_method in content_encodings:
            # Decode/decompress it
            if encoding_method == "gzip":
                # Should also handle deflate automatically
                body_bytes = gzip.decompress(body_bytes)
            elif encoding_method == "deflate" and not "gzip" in content_encodings:
                # NOTE: If this is deflate on its own without gzip, probably use gzip?
                # This is just a guess what's best
                body_bytes = gzip.decompress(body_bytes)
            elif encoding_method == "compress":
                body_bytes = ncompress.decompress(body_bytes)
            elif encoding_method == "br":
                body_bytes = brotli.decompress(body_bytes)
    return body_bytes


def preprocess_request(request_info: Request):
    # Connection is only in here, because it caused inconsistencies between the recorder & emulator
    # Basically, OpenVAS internally recognizes the recorder's socket a bit differently
    # compared to that of e.g. the target emulator
    keys_to_delete = ["host", "connection"]
    # Remove all identifying info related to this specific target
    for key in OrderedDict(request_info.headers).keys():
        if key in keys_to_delete:
            del request_info.headers[key]

    request_info.body = decompress_body(request_info.headers, request_info.body)


def preprocess_response(response_info: CustomResponse):
    # Remove any headers that will be generated by the target emulator anyways
    keys_to_delete = ["date", "content-length", "connection"]
    for key in OrderedDict(response_info.headers).keys():
        if key.lower() in keys_to_delete:
            del response_info.headers[key]

    decompressed_body = decompress_body(response_info.headers, response_info.body)
    response_info.body = decompressed_body.decode("utf-8", errors="ignore")


def preprocess_and_group_communications(recorded_communications: list) -> dict:
    communications_by_uri = defaultdict(lambda: defaultdict(list))
    for current_request_response_info in recorded_communications:
        current_request_info = current_request_response_info["Client"]
        current_response_info = current_request_response_info["Server"]
        preprocess_request(current_request_info)
        preprocess_response(current_response_info)
        base_url = current_request_info.uri.split("?", 1)[0]
        communications_by_uri[base_url][current_request_info.method].append(
            current_request_response_info
        )
    return communications_by_uri


def create_response_for_json(response_info: CustomResponse) -> dict:
    # To preserve the order of keys in the generated JSON file
    response = OrderedDict()
    response["Status"] = response_info.status
    response["Headers"] = OrderedDict(response_info.headers)
    response["Body"] = response_info.body
    return response


def create_criterion_for_json(
    criterion_id: str,
    url_parameters: str,
    headers: OrderedDict,
    request_unique_body_lines: list,
    response_indexes: list,
):
    # To preserve the order of keys in the generated JSON file
    criterion = OrderedDict()
    criterion["ID"] = criterion_id
    criterion["URL_Parameters"] = url_parameters
    criterion["Headers"] = OrderedDict(headers)
    criterion["Body"] = dict(request_unique_body_lines)
    criterion["Responses"] = response_indexes
    return criterion


def save_endpoint_mapping_to_test_case(
    service_base_dir: Path,
    endpoint_mapping: dict,
    owner_uid: int,
    owner_gid: int,
):
    print("Saving endpoint mapping...")
    try:
        service_base_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        exit(f"Error while creating the dir '{service_base_dir}': Already exists.")
    endpoint_mapping_path = service_base_dir / "endpoint_mapping.json"
    with open(endpoint_mapping_path, "w", encoding="utf-8") as endpoint_mapping_file:
        json.dump(endpoint_mapping, endpoint_mapping_file, indent=2)

    os.chown(service_base_dir, owner_uid, owner_gid)
    os.chown(endpoint_mapping_path, owner_uid, owner_gid)
