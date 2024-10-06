import argparse

from pathlib import Path
from typing import List, Optional


class CliParser:
    def __init__(self) -> None:
        parser = argparse.ArgumentParser(description="VTs Recorder")

        parser.add_argument(
            type=str,  # TODO: Check if valid IP
            dest="target_ip",
            help=('the IP of the target for this scan. Example: "127.0.0.1"'),
        )

        parser.add_argument(
            nargs="+",
            type=str,
            dest="vts_to_execute",
            help="file names of all VTs that should be executed for this run",
        )

        parser.add_argument(
            "-o",
            "--output-dir",
            type=self.dir_path,
            default="recorder_output",
            dest="output_dir",
            help="path to the directory where the output should be written to",
        )

        parser.add_argument(
            "-k",
            "--kb",
            type=str,
            dest="kb_set_values",
            action="append",
            help="set OpenVAS KB key to value. Can be used multiple times",
        )

        parser.add_argument(
            "--store-under-oid",
            type=str,
            dest="output_oid",
            default=None,
            help="use this OID for choosing the directory of the resulting TestCase",
        )

        parser.add_argument(
            "--owner-uid",
            type=int,
            dest="owner_uid",
            default=-1,
            help="the UID of the user who should own the generated files",
        )

        parser.add_argument(
            "--owner-gid",
            type=int,
            dest="owner_gid",
            default=-1,
            help="the GID of the user who should own the generated files",
        )

        self.parser = parser

    def dir_path(self, string: str) -> Path:
        """Check if a given string is a valid path to a directory,
        relative or absolute.

        Arguments:
            string: A string to check.

        Returns:
            The Path to the directory if it is a valid directory.
        """
        path = Path(string)
        if path.is_dir():
            return path

        exit(f"Error: {string} is not a valid directory!")

    def file_paths(self, file_path_string: str) -> str:
        """Check if a given string references a file that exists.

        Arguments:
            file_path_string: A string to check, possibly pointing to a file.

        Returns:
            The unchanged string pointing to an existing file.
        """
        file_path = Path(file_path_string)
        if file_path.is_file():
            return file_path_string
        exit(f"Error: {file_path_string} is not a file or does not exist!")

    def parse_args(self, args: Optional[List[str]] = None):
        return self.parser.parse_args(args)


def create_parser_get_args():
    cli_parser = CliParser()
    args = cli_parser.parse_args()
    return args
