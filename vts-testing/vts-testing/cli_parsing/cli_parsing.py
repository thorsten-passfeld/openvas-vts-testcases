import argparse

from pathlib import Path
from typing import List, Optional


from ..funcs import get_all_test_cases_in_dir, is_valid_test_case_path


class CliParser:
    def __init__(self) -> None:
        parser = argparse.ArgumentParser(description="VTs Testing")

        parser.add_argument(
            type=self.test_case_path,
            dest="test_cases_to_use",
            nargs="+",
            help=(
                "path to the test case(s) to use for deploying emulated services. "
                'Example: "$TEST_CASE_DIR/1.3.6.1.4.1.25623.1.0.117269/TestCase1", '
                'Or: "$TEST_CASE_DIR/1.3.6.1.4.1.25623.1.0.117269", '
                'Or: "$TEST_CASE_DIR"'
            ),
        )

        parser.add_argument(
            "-n",
            "--num-scans",
            type=int,
            dest="num_concurrent_scans",
            default=1,
            help="the number of scans to run in parallel.",
        )

        self.parser = parser

    def test_case_path(self, possible_test_case_path: str) -> list:
        """Check if a given strings is a valid path leading to a test case directory,
        relative or absolute.

        Arguments:
            possible_test_case_paths: A string to check.

        Returns:
            The Path to the directory if it is a valid directory.
        """
        test_case_paths = list()
        path = Path(possible_test_case_path)
        if not path.is_dir():
            exit(f"Error: '{possible_test_case_path}' is not a valid directory!")

        if is_valid_test_case_path(possible_test_case_path):
            test_case_paths.append(possible_test_case_path)
        else:
            all_test_cases_in_dir = get_all_test_cases_in_dir(path)
            if all_test_cases_in_dir:
                test_case_paths.extend(all_test_cases_in_dir)
            else:
                exit(f"Error: No test cases could be derived from '{possible_test_case_path}'")

        return test_case_paths

    def parse_args(self, args: Optional[List[str]] = None):
        return self.parser.parse_args(args)


def create_parser_get_args():
    cli_parser = CliParser()
    args = cli_parser.parse_args()
    return args
