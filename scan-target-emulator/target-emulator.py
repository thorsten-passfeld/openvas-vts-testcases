#!/usr/bin/env python3
import traceback
import logging

from pathlib import Path

from target_emulator.cli_parsing import create_parser_get_args
from target_emulator.models import TestCase, ServiceManager


def main():
    args = create_parser_get_args()
    # Create a TestCase object for handling the gathering of information for each service
    test_case_path = args.test_case_to_use
    test_case = TestCase(test_case_path)

    # Enable logging
    log_formatter = logging.Formatter("%(asctime)s [%(threadName)s] [%(levelname)s]  %(message)s")
    logger = logging.getLogger("target_emulator")
    logger.setLevel(logging.INFO)

    if args.log_dir:
        log_dir = args.log_dir.rstrip("/")
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(f"{log_dir}/target_emulator.log", mode="w")
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    else:
        log_dir = None

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    logger.info("Setting up for test case '%s'...", test_case_path)

    # The ServiceManager makes sure that all services can be deployed and terminated
    service_manager = ServiceManager(test_case, args.host)
    try:
        service_manager.deploy_and_manage_services()
    except Exception:
        stack_trace = traceback.format_exc()
        logger.fatal(
            "The target emulator encountered an unexpected exception in the service manager:\n"
            "%s",
            stack_trace,
        )
        exit(1)


if __name__ == "__main__":
    main()
