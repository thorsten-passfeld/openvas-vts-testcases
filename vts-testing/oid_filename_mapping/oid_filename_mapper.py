#!/usr/bin/env python

import subprocess
import json
import re

import docker

PLUGINS_DIR = "/openvas_plugins"
OUTPUT_DIR = "/oid_mapping_data"

OID_PATTERN = re.compile(r"script_oid\(\"([0-9.]+)\"\)")

CONTAINER_TO_WAIT_FOR = "testing_vts"


def main():
    docker_client = docker.from_env()
    print(f"Waiting for the '{CONTAINER_TO_WAIT_FOR}' container to be done...")
    vts_container = docker_client.containers.get(CONTAINER_TO_WAIT_FOR)
    vts_container.wait()

    print("Generating the OID-filename map...")
    # NOTE: Searching for all OIDs is at least 2x as fast as only a select few specifically
    grep_cmd = [
        "grep",
        "-R",
        "-E",
        "-H",
        "-o",
        'script_oid\("[0-9.]+"\)',
        PLUGINS_DIR,
    ]
    try:
        # e.g. /openvas_plugins/gb_dlink_dir_detect.nasl:script_oid("1.3.6.1.4.1.25623.1.0.103689")
        grep_filenames_output = (
            subprocess.check_output(grep_cmd).decode("utf-8", errors="ignore").splitlines()
        )
    except subprocess.CalledProcessError as e:
        exit(f"Error while looking for OIDs and their filenames: {e.output}")

    if not grep_filenames_output:
        exit("Could not find any OIDs")

    oid_filename_info = dict()
    for line in grep_filenames_output:
        oid_filename = line.split(":")
        filename = oid_filename[0]
        # script_oid("1.3.6.1.4.1.25623.1.0.103689")
        raw_oid = oid_filename[1]
        oid = OID_PATTERN.sub(r"\1", raw_oid)

        oid_filename_info[oid] = filename

    print("Writing the OID-filename map...")
    with open(f"{OUTPUT_DIR}/oid_filename_map.json", "w", encoding="utf-8") as output_file:
        json.dump(oid_filename_info, output_file)
    print("Finished writing the OID-filename map!")


if __name__ == "__main__":
    main()
