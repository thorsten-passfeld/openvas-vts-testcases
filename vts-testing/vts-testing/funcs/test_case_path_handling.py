import os
import re

from pathlib import Path

TEST_CASE_PATTERN = re.compile(r"TestCase[0-9]+")


def is_valid_test_case_path(string: str) -> bool:
    path = Path(string)
    if path.is_dir():
        # Make sure that the test case is valid
        last_dir_name = path.name
        if TEST_CASE_PATTERN.match(last_dir_name):
            return True
        else:
            return False
    else:
        return False


def get_all_test_cases_in_dir(base_path: Path) -> list:
    valid_test_case_paths = list()
    if base_path.name == "test_cases":
        with os.scandir(base_path) as files_in_dir:
            for entry in files_in_dir:
                if entry.is_dir():
                    entry_path = entry.path
                    all_test_cases_in_subdir = get_all_test_cases_in_dir(Path(entry_path))
                    valid_test_case_paths.extend(all_test_cases_in_subdir)
    else:
        with os.scandir(base_path) as files_in_dir:
            for entry in files_in_dir:
                if entry.is_dir():
                    entry_path = entry.path
                    if is_valid_test_case_path(entry_path):
                        valid_test_case_paths.append(entry_path)
    return valid_test_case_paths
