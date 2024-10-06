import re
import logging

from abc import ABC, abstractmethod
from collections import defaultdict
from flask import Flask, Response, request
from werkzeug.datastructures import EnvironHeaders

LOGGER = logging.getLogger("target_emulator")


class HTTPEndpoint(ABC):
    @abstractmethod
    def deploy(self, app: Flask):
        pass

    @abstractmethod
    def _request_handler(self):
        pass


class SimpleHTTPEndpoint(HTTPEndpoint):
    def __init__(self, file_path: str, uri: str):
        self._file_path = file_path
        self._uri = uri

    def deploy(self, app: Flask):
        app.add_url_rule(self._uri, view_func=self._request_handler, methods=["GET"])

    def _request_handler(self):
        with open(self._file_path, "r", encoding="utf-8") as file:
            file_content = file.read()
            response = Response(file_content)
        return response


class ComplexHTTPEndpoint(HTTPEndpoint):
    def __init__(self, endpoint_info: dict):
        self._parse_endpoint_info(endpoint_info)
        self._same_request_diff_response_tracker = defaultdict(int)
        self._user_agent_version_regex = re.compile(r"OpenVAS-VT\s[0-9.]+((~dev)[0-9]+)?")

    def _parse_endpoint_info(self, endpoint_info):
        self._uri = endpoint_info["URI"]
        LOGGER.info("Setting up URI: %s", self._uri)
        self._methods_dict = endpoint_info["Methods"]
        self._allowed_methods = list(self._methods_dict.keys())

    def deploy(self, app: Flask):
        app.add_url_rule(
            self._uri,
            endpoint=self._uri,
            view_func=self._request_handler,
            methods=self._allowed_methods,
        )

    def _preprocess_headers(self, headers: dict) -> dict:
        processed_headers = dict()
        for key, value in headers.items():
            key = key.lower()
            # Only remove versions like OpenVAS-VT 21.4.5~dev1 so that it's not dependent
            if key == "user-agent":
                # Get rid of version numbers
                # OpenVAS-VT 21.4.5~dev1 -> OpenVAS-VT
                value = self._user_agent_version_regex.sub(r"OpenVAS-VT\2", value)
            processed_headers[key] = value
        return processed_headers

    def _matching_url_parameters(
        self, request_url_parameters: str, criterion_url_parameters: str
    ) -> bool:
        """Check if the request URL parameters match a specific criterion's URL parameters.

        Arguments:
            request_url_parameters (dict): The URL parameters parsed from an incoming HTTP request.
            criterion_url_parameters (dict): The URL parameters to compare to.

        Returns:
            bool: Whether this criterion matches or not.
        """
        LOGGER.info("Request URL parameters -> %s", request_url_parameters)
        LOGGER.info("Criterion URL parameters -> %s", criterion_url_parameters)
        return request_url_parameters == criterion_url_parameters

    def _matching_headers(self, request_headers: dict, criterion_headers: dict) -> bool:
        """Check if the request headers match to a specific criterion's headers.

        Arguments:
            request_headers (dict): The headers parsed from an incoming HTTP request.
            criterion_headers (dict): The headers to look and check for.

        Returns:
            bool: Whether this criterion matches or not.
        """
        criterion_headers = self._preprocess_headers(criterion_headers)
        LOGGER.info("Request headers -> %s", request_headers)
        LOGGER.info("Criterion headers -> %s", criterion_headers)
        for header_key, header_value in criterion_headers.items():
            corresponding_request_header_value = request_headers.get(header_key)
            if (
                corresponding_request_header_value is None
                or corresponding_request_header_value != header_value
            ):
                LOGGER.info("Header '%s' was not found or incorrect!", header_key)
                return False
        return True

    def _matching_body(self, request_body: str, criterion_body: list) -> bool:
        """Check if the request body matches the snippets we are looking for in this criterion.

        Arguments:
            request_body (str): The body from an incoming HTTP request.
            criterion_content (list): A list of snippets to look for.

        Returns:
            bool: Whether this criterion matches or not.
        """
        request_body_lines = request_body.splitlines()
        for line_num, line_text in criterion_body.items():
            line_num = int(line_num)
            # Try finding this exact line in the request body
            try:
                request_line_text = request_body_lines[line_num]
                if request_line_text != line_text:
                    LOGGER.info("Line '%s' was different to the expected one!", line_text)
                    LOGGER.info("Expected '%s', got '%s'", line_text, request_line_text)
                    return False
            except IndexError:
                LOGGER.info("Line '%s' was not found!", line_text)
                return False
        return True

    def _determine_next_response_index(self, criterion_id: str, criterion_responses: list) -> int:
        # Important: This tracks the next index in the "responses" list of the criterion
        next_response_index = self._same_request_diff_response_tracker[criterion_id]
        if next_response_index > len(criterion_responses) - 1:
            return None
        self._same_request_diff_response_tracker[criterion_id] += 1
        # Returns the actual index of the next response
        return criterion_responses[next_response_index]

    def _check_criteria_list(
        self,
        criteria: list,
        responses: list,
        request_headers: EnvironHeaders,
        request_body: str,
        request_url_parameters: str,
    ) -> Response:
        request_headers = self._preprocess_headers(request_headers)
        for criterion_info in criteria:
            LOGGER.info("Criterion -> %s", criterion_info)
            # Check to make sure that the URL parameters match
            matching_url_parameters = self._matching_url_parameters(
                request_url_parameters, criterion_info["URL_Parameters"]
            )
            # Check all sent HTTP headers and compare them to expected ones
            matching_headers = self._matching_headers(request_headers, criterion_info["Headers"])
            # Check the body to differentiate by certain important substrings/lines
            matching_body = self._matching_body(request_body, criterion_info["Body"])
            # We have only found the correct criterion if everything matches!
            if all([matching_url_parameters, matching_headers, matching_body]):
                possible_responses_in_order = criterion_info["Responses"]
                LOGGER.info("%s", possible_responses_in_order)
                criterion_id = criterion_info["ID"]
                response_index = self._determine_next_response_index(
                    criterion_id, possible_responses_in_order
                )
                if response_index is None:
                    response = Response(
                        "Error. Could not handle this request.",
                        status=404,
                    )
                    LOGGER.error(
                        "The following request came an unexpected amount of times:\n%s", request
                    )
                    return response
                response_info = responses[response_index]
                response = Response(
                    response_info["Body"],
                    status=response_info["Status"],
                    headers=response_info["Headers"],
                )
                return response
        # Nothing matched
        return None

    def _request_handler(self) -> Response:
        uri = request.url
        LOGGER.info("Request URI: %s\nEndpoint URI: %s", uri, self._uri)

        method = request.method
        request_url_parameters = request.url.replace(request.base_url, "")
        request_headers = request.headers

        response_handling_info = self._methods_dict[method]

        criteria = response_handling_info["Criteria"]
        criteria_superset = criteria["Superset"]
        criteria_subset = criteria["Subset"]

        responses = response_handling_info["Responses"]

        request_body = request.get_data().decode("utf-8", "ignore")

        LOGGER.info("%s", dict(request_headers))
        LOGGER.info("%s", request_body)

        LOGGER.info("Trying the superset...")
        response = self._check_criteria_list(
            criteria_superset, responses, request_headers, request_body, request_url_parameters
        )
        if not response:
            # The superset of criteria didn't match. As a last effort, try the subset
            LOGGER.info("Trying the subset...")
            response = self._check_criteria_list(
                criteria_subset, responses, request_headers, request_body, request_url_parameters
            )
            if not response:
                response = Response(
                    "Error. Could not handle this request.",
                    status=404,
                )
                LOGGER.error("No criterion could match the following request:\n%s", request)
        LOGGER.info("Response headers -> %s", response.headers)
        return response
