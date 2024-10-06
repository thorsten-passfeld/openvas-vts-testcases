#!/usr/bin/env python

import os
import re
import threading
import queue
import itertools
import traceback
import json
import tarfile

from collections import defaultdict
from pathlib import Path
from io import BytesIO

import docker
from docker.models.containers import Container
from natsort import natsorted

from .cli_parsing import create_parser_get_args
from .models import TestCase, TestExecutor

# https://python-patterns.guide/python/sentinel-object/
_SENTINEL_NO_MORE_DATA = object()
TARGET_EMULATOR_IMAGE_NAME = "test_environment_docker_target-emulator"

# To only show e.g. "1.3.6.1.4.1.25623.1.0.103689/TestCase2" instead of the full path
PATH_EXTRACTION_REGEX = re.compile(r"((?:[0-9]+\.)+[0-9]+/TestCase[0-9]+)")

# poetry run vts-test /test_cases/1.3.6.1.4.1.25623.1.0.103689/TestCase19/ --num-scans 1


def perform_scan_testing(
    docker_client,
    path_task_queue: queue.Queue,
    openvas_scanner_container: Container,
    thread_num: int,
    test_results: dict,
    oid_filename_mapping: dict,
    test_cases_base_path: str,
) -> None:
    current_target_emulator_container_name = f"testing_target_emulator_{thread_num}"
    current_target_emulator_hostname = f"target_emulator_{thread_num}"
    docker_network_name = "test_environment_docker_scan_testing_net"
    target_emulator_code_path = os.path.abspath("test_environment_docker/scan-target-emulator/")
    current_target_emulator_volumes = [
        f"{target_emulator_code_path}:/code",
        f"{test_cases_base_path}:{test_cases_base_path}",
    ]
    current_target_emulator_container = docker_client.containers.run(
        TARGET_EMULATOR_IMAGE_NAME,
        command="sleep infinity",
        name=current_target_emulator_container_name,
        hostname=current_target_emulator_hostname,
        volumes=current_target_emulator_volumes,
        network=docker_network_name,
        detach=True,
    )
    current_target_emulator_container.reload()
    current_target_emulator_ip = current_target_emulator_container.attrs["NetworkSettings"][
        "Networks"
    ][docker_network_name]["IPAddress"]

    test_executor = TestExecutor(
        openvas_scanner_container,
        current_target_emulator_container,
        current_target_emulator_container_name,
        current_target_emulator_hostname,
        docker_network_name,
        current_target_emulator_ip,
        oid_filename_mapping,
        thread_num,
    )
    while True:
        test_case_path = path_task_queue.get()
        if test_case_path is _SENTINEL_NO_MORE_DATA:
            # Make sure that other remaining threads terminate
            print(f"{thread_num}: No more test cases to handle! Telling others to terminate...")
            path_task_queue.put(_SENTINEL_NO_MORE_DATA)
            break
        print(f"\n{thread_num}: TestCase -> {test_case_path}")
        # Create a TestCase object for handling the gathering of information for each service
        test_case = TestCase(Path(test_case_path))
        try:
            has_passed, conclusion = test_executor.test_and_report(test_case_path, test_case)
        except Exception:  # pylint: disable=broad-except
            print(f"{thread_num}: Encountered exception:")
            print(traceback.format_exc())
            break
        test_results[test_case_path] = (has_passed, conclusion)
    print(f"{thread_num}: Stopping and removing container...")
    # Clean up by removing the container
    current_target_emulator_container.remove(force=True)
    print(f"{thread_num}: Removed container.")


def start_scan_testing_threads(
    docker_client,
    path_task_queue: queue.Queue,
    num_concurrent_scans: int,
    openvas_scanner_container: Container,
    test_results: dict,
    oid_filename_mapping: dict,
    test_cases_base_path: str,
) -> list:
    test_executor_threads = list()
    for thread_num in range(num_concurrent_scans):
        test_executor_thread = threading.Thread(
            target=perform_scan_testing,
            args=[
                docker_client,
                path_task_queue,
                openvas_scanner_container,
                thread_num,
                test_results,
                oid_filename_mapping,
                test_cases_base_path,
            ],
        )
        test_executor_thread.start()
        test_executor_threads.append(test_executor_thread)
    return test_executor_threads


def get_oid_filename_mapping(docker_client) -> dict:
    oid_filename_mapping_container = docker_client.containers.get("testing_oid_filename_mapper")

    mapping_stream = oid_filename_mapping_container.get_archive(
        "/oid_mapping_data/oid_filename_map.json"
    )
    bits, _ = mapping_stream
    temp_file = BytesIO()
    for bit_i in bits:
        temp_file.write(bit_i)
    temp_file.seek(0)
    mapping_tar = tarfile.open(mode="r", fileobj=temp_file)
    mapping_file = mapping_tar.extractfile("oid_filename_map.json")

    oid_filename_mapping = json.load(mapping_file)
    return oid_filename_mapping


# NOTE: This is unused, because this step should be done outside the runtime
# docker build -t test_environment_docker_target-emulator . -f Dockerfile_Target_Emulator
# (assuming you are in the test_environment_docker directory)
def create_target_emulator_image(docker_client):
    docker_client.images.build(
        path="test_environment_docker/",
        dockerfile=os.path.abspath("test_environment_docker/Dockerfile_Target_Emulator"),
        tag=TARGET_EMULATOR_IMAGE_NAME,
    )


def determine_test_cases_base_path(test_cases_to_use: list) -> str:
    # Take any test case and extract the base path from it
    test_case_path = Path(test_cases_to_use[0])
    # Pieces of the path
    parts = test_case_path.parts
    # Find the base dir name's index
    base_dir_name_index = parts.index("test_cases")

    test_cases_base_path = "/".join(parts[: base_dir_name_index + 1])
    # Absolute paths will contain "//" at the start. We need to fix that
    if (
        len(test_cases_base_path) >= 2
        and test_cases_base_path[0] == "/"
        and test_cases_base_path[1] == "/"
    ):
        test_cases_base_path = test_cases_base_path.replace("/", "", 1)

    return test_cases_base_path


def main():
    args = create_parser_get_args()
    num_concurrent_scans = args.num_concurrent_scans
    # Make sure that all paths are unique
    test_cases_to_use = list(set(itertools.chain.from_iterable(args.test_cases_to_use)))
    # Make sure that all paths are absolute
    test_cases_to_use = [os.path.abspath(p) for p in test_cases_to_use]

    # e.g. "/home/username/test_cases"
    test_cases_base_path = determine_test_cases_base_path(test_cases_to_use)

    num_test_cases = len(test_cases_to_use)
    # If there is only e.g. 1 test case to check, only start 1 container for it
    if num_test_cases < num_concurrent_scans:
        num_concurrent_scans = num_test_cases

    print(
        f"{num_test_cases} test case(s) to check "
        f"during {num_concurrent_scans} concurrent scan(s):\n"
        f"{test_cases_to_use}"
    )

    docker_client = docker.from_env()

    openvas_scanner_container = docker_client.containers.get("testing_openvas_scanner")

    path_task_queue = queue.Queue(maxsize=num_concurrent_scans)

    oid_filename_mapping = get_oid_filename_mapping(docker_client)

    test_results = defaultdict(tuple)
    test_executor_threads = start_scan_testing_threads(
        docker_client,
        path_task_queue,
        num_concurrent_scans,
        openvas_scanner_container,
        test_results,
        oid_filename_mapping,
        test_cases_base_path,
    )

    for test_case_path in test_cases_to_use:
        path_task_queue.put(test_case_path)

    print("Terminating all executor threads...")

    # Signal the end of the tasks
    path_task_queue.put(_SENTINEL_NO_MORE_DATA)

    for test_executor_thread in test_executor_threads:
        test_executor_thread.join()

    has_passed_count = 0
    total_count = 0
    print("Results:")
    for test_case_path, results_tuple in natsorted(test_results.items()):
        relevant_path_match = PATH_EXTRACTION_REGEX.search(test_case_path)
        if relevant_path_match:
            test_case_path = relevant_path_match.group(1)
        has_passed, conclusion = results_tuple
        total_count += 1
        print(f"{test_case_path}: ", end="")
        if has_passed:
            has_passed_count += 1
            print("✅")
        else:
            print("❌")
            print(f"↳ {conclusion}")

    num_failed_tests = total_count - has_passed_count
    print(f"\nConclusion: {num_failed_tests}/{total_count} tests have failed!")
    if has_passed_count < total_count:
        exit(1)


if __name__ == "__main__":
    main()
