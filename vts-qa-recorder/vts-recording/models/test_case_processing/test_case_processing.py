import os
import re
import glob
import json

from pathlib import Path

from ...constants import DUMMY_TARGET_RESERVED_IP_ADDRESS
from ...service_handling import ServiceHandlerHTTP


def _sanitize_result(result: str, recorded_ports: list) -> str:
    # Make the output independent of the host that was used
    # e.g. 127.0.0.1:8080 -> :8080
    result = re.sub(rf"{DUMMY_TARGET_RESERVED_IP_ADDRESS}(:[0-9]+)?", "", result)
    return result


def _build_scan_info(
    result: str, recorded_ports: dict, kb_arguments_string: str, oids_for_vts: dict
) -> dict:
    scan_info = dict()
    scan_info["RecordedHost"] = DUMMY_TARGET_RESERVED_IP_ADDRESS
    scan_info["RecordedPorts"] = recorded_ports
    scan_info["RecordedPlugins"] = list(oids_for_vts.values())
    scan_info["KbArgs"] = kb_arguments_string
    scan_info["Result"] = _sanitize_result(result, recorded_ports)

    return scan_info


def _get_next_test_case_id(test_cases_for_oid_dir_path: Path) -> int:
    full_base_path_for_test_case = str(test_cases_for_oid_dir_path) + "/TestCase"
    existing_test_cases_in_dir = glob.glob(full_base_path_for_test_case + "*")
    # e.g. 2 if there are TestCases 1 and 2
    maximum_test_case_id = max(
        [
            int(file_path.replace(full_base_path_for_test_case, ""))
            for file_path in existing_test_cases_in_dir
        ],
        default=0,
    )
    next_test_case_id = maximum_test_case_id + 1
    return next_test_case_id


def _save_scan_info_to_new_test_case(
    test_case_dir_path: Path,
    scan_info: dict,
    owner_uid: int,
    owner_gid: int,
):
    try:
        test_case_dir_path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        exit(f"Error while creating the new TestCase dir '{test_case_dir_path}': Already exists.")

    scan_info_path = test_case_dir_path / "scan_info.json"
    with open(scan_info_path, "w", encoding="utf-8") as scan_info_file:
        json.dump(scan_info, scan_info_file, indent=2)

    os.chown(test_case_dir_path, owner_uid, owner_gid)
    os.chown(scan_info_path, owner_uid, owner_gid)


def process_and_store_parsed_data_into_test_case(
    result: str,
    parsed_recorded_data: dict,
    recorded_ports: dict,
    output_dir: Path,
    kb_arguments_string: str,
    oids_for_vts: dict,
    output_oid: str,
    owner_uid: int,
    owner_gid: int,
):
    # Make sure that file permissions don't get messed up by the container
    os.umask(0o000)

    # Assign the next TestCase number based on existing ones
    test_cases_for_oid_dir_path = output_dir / output_oid
    next_test_case_id = _get_next_test_case_id(test_cases_for_oid_dir_path)

    scan_info = _build_scan_info(result, recorded_ports, kb_arguments_string, oids_for_vts)
    test_case_dir_path = test_cases_for_oid_dir_path / f"TestCase{next_test_case_id}"
    # Save scan info
    _save_scan_info_to_new_test_case(test_case_dir_path, scan_info, owner_uid, owner_gid)

    for service_name, recorded_communications in parsed_recorded_data.items():
        print(service_name)
        service_base_dir = test_case_dir_path / service_name
        if service_name == ServiceHandlerHTTP.name:
            ServiceHandlerHTTP.save_to_new_test_case(
                service_base_dir, recorded_communications, owner_uid, owner_gid
            )
