import argparse
import re

from pathlib import Path
from typing import List, Optional

TEST_CASE_PATTERN = re.compile(r"TestCase[0-9]+")


class CliParser:
    def __init__(self) -> None:
        parser = argparse.ArgumentParser(description="Scan Target Emulator")

        parser.add_argument(
            type=self.test_case_path,
            dest="test_case_to_use",
            help=(
                "path to the test case to use for deploying emulated services. "
                'Example: "$TEST_CASE_DIR/1.3.6.1.4.1.25623.1.0.117269/TestCase1"'
            ),
        )

        parser.add_argument(
            "--host",
            type=str,
            default="localhost",
            dest="host",
            help="the (local) IP/hostname to bind services to. Example: localhost",
        )

        parser.add_argument(
            "--log-dir",
            type=str,
            default=None,
            dest="log_dir",
            help="a directory where to write logs to.",
        )

        self.parser = parser

    def test_case_path(self, string: str) -> Path:
        """Check if a given string is a valid path to a test case directory,
        relative or absolute.

        Arguments:
            string: A string to check.

        Returns:
            The Path to the directory if it is a valid directory.
        """
        path = Path(string)
        if path.is_dir():
            # Make sure that the test case is valid
            last_dir_name = path.name
            if TEST_CASE_PATTERN.match(last_dir_name):
                return path
            else:
                exit(f"Error: The path '{path}' does not point to a test case!")
            return path

        exit(f"Error: '{string}' is not a valid directory!")

    def parse_args(self, args: Optional[List[str]] = None):
        return self.parser.parse_args(args)


def create_parser_get_args():
    cli_parser = CliParser()
    args = cli_parser.parse_args()
    return args
