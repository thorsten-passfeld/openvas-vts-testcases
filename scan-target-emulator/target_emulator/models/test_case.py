import os
import json
from pathlib import Path
from typing import List
from werkzeug.utils import cached_property

# Idea:
# - Represent one test case with all of its data
# - One attribute representing each service
#   - Each service object handles the parsing of its data accordingly
#   - e.g. HTTP goes through each folder and deploys the service
class TestCase:
    def __init__(self, test_case_path: Path):
        self._test_case_path = test_case_path

    @cached_property
    def required_services(self) -> List[Path]:
        services_paths = list()
        with os.scandir(self._test_case_path) as files_in_dir:
            for entry in files_in_dir:
                if entry.is_dir():
                    service_path = Path(entry.path)
                    services_paths.append(service_path)
        return services_paths

    @cached_property
    def scan_info(self) -> dict:
        scan_info_path = self._test_case_path / "scan_info.json"
        if scan_info_path.exists() and scan_info_path.is_file():
            with open(scan_info_path, "r", encoding="utf-8") as scan_info_file:
                # TODO: Exception handling
                scan_info = json.load(scan_info_file)
                return scan_info
        else:
            # The expected output for this TestCase is missing
            # TODO: Handle the error in the unit test program according to the None value
            return None
