import signal
import logging

from importlib import import_module
from multiprocessing import Process

from . import TestCase

LOGGER = logging.getLogger("target_emulator")


class ServiceManager:
    def __init__(self, test_case: TestCase, host: str):
        self._test_case = test_case
        self.host = host
        self._service_tasks = list()
        scan_info = test_case.scan_info
        self._recorded_ports_info = scan_info["RecordedPorts"]
        self._recorded_host = scan_info["RecordedHost"]

    def _gracefully_terminate_all_services(self) -> None:
        # Go through all tasks, send a termination signal and then join them
        for _, service_task in self._service_tasks:
            # First tell all services to terminate their process
            service_task.terminate()
        # Now wait for each one to fully terminate and then clean up each of them
        # It can happen that they just do not react to this signal and this program
        # doesn't terminate. That is okay, since this handler doesn't try to force it.
        for service_name, service_task in self._service_tasks:
            LOGGER.info("Waiting for service '%s' to terminate...", service_name)
            service_task.join()
            service_task.close()
        LOGGER.info("Shut down everything gracefully!")
        exit()

    def _signal_handler_termination(self, signum, frame) -> None:  # pylint: disable=unused-argument
        self._gracefully_terminate_all_services()

    def deploy_and_manage_services(self) -> None:
        self._prepare_services()
        self._start_and_manage_service_tasks()

    def _parse_and_deploy_service(self, service_module_class, service_path, service_port) -> None:
        # Instantiate the service object, if possible
        service_object = service_module_class(
            service_path, self.host, service_port, self._recorded_host
        )
        # TODO: Exception handling
        # Let each service deploy on its own, but abort on any error
        service_object.deploy()

    def _prepare_services(self):
        """Parse everything related to this test case and deploy all services"""

        services_to_deploy = self._test_case.required_services
        for service_path in services_to_deploy:
            service_module_name = service_path.name
            # TODO: Exception handling
            # Make sure that the service actually exists and is supported
            module_import = import_module(
                f".services.{service_module_name.lower()}", package="target_emulator"
            )
            # Get the class of the module
            module_class = getattr(module_import, service_module_name.upper())
            service_name = module_class.name
            service_port = self._recorded_ports_info[service_name]

            # Create the process to run for this service
            service_task = Process(
                name=f"Target Emulator {service_name} Service",
                target=self._parse_and_deploy_service,
                args=(module_class, service_path, service_port),
            )
            service_task.daemon = True
            self._service_tasks.append((service_name, service_task))

    def _start_and_manage_service_tasks(self) -> None:
        for service_name, service_task in self._service_tasks:
            LOGGER.info("Starting the process for '%s'...", service_task.name)
            service_task.start()

        # Signal handling
        # NOTE: This handling is just for the parent process!
        # Child processes are a copy of the parent process, so handling is defined afterwards
        signal.signal(signal.SIGINT, self._signal_handler_termination)  # CTRL+C
        signal.signal(signal.SIGTERM, self._signal_handler_termination)

        for service_name, service_task in self._service_tasks:
            service_task.join()
            # NOTE: This also kills all other services
            LOGGER.error(
                "The process '%s' finished or randomly got terminated. Aborting...", service_name
            )
            self._gracefully_terminate_all_services()
