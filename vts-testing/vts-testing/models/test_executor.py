import socket
import re
import time

from docker.models.containers import Container

from .test_case import TestCase


# The TestExecutor class takes care of responding with "passed"/"not passed"
class TestExecutor:
    # NOTE: It is important to scan using the IP address!
    # Otherwise the scan will fork for both the hostname and container_name.network_name
    def __init__(
        self,
        openvas_scanner_container: Container,
        target_emulator_container: Container,
        target_emulator_container_name: str,
        target_emulator_hostname: str,
        docker_network_name: str,
        target_emulator_ip: str,
        oid_filename_mapping: dict,
        thread_num: int,
    ):
        self._openvas_scanner_container = openvas_scanner_container
        self._target_emulator_container = target_emulator_container
        self._target_emulator_container_name = target_emulator_container_name
        self._target_emulator_hostname = target_emulator_hostname
        self._docker_network_name = docker_network_name
        self._target_emulator_ip = target_emulator_ip
        self._oid_filename_mapping = oid_filename_mapping
        self._thread_num = thread_num

    def _wait_until_target_emulator_is_ready(self, recorded_ports_info: dict) -> None:
        ports_to_check = recorded_ports_info.values()
        print(f"{self._thread_num}: Waiting until all relevant ports are open...")
        for port in ports_to_check:
            while True:
                # print(f"Trying to connect to port {port}")
                try:
                    with socket.create_connection((self._target_emulator_ip, port)):
                        break
                except OSError:
                    # print(f"Port {port} is not yet available. Waiting...")
                    time.sleep(0.005)
        print(f"{self._thread_num}: All relevant ports are now open!")

    def test_and_report(self, test_case_path: str, test_case: TestCase) -> (bool, str):
        # Start the target emulator
        # TODO: Debug option that also prints the (debug) output of the target emulator and OpenVAS
        print(f"{self._thread_num}: Starting the target emulator at {self._target_emulator_ip}...")
        target_emulator_cmd = (
            f"python target-emulator.py {test_case_path} "
            f"--host {self._target_emulator_ip} --log-dir /target_emulator_logs/"
        )
        # TODO: Check for warnings like "Request came an unexpected number of times"
        # -> Only really possible through the log file of the target emulator
        self._target_emulator_container.exec_run(target_emulator_cmd, workdir="/code", detach=True)
        print(
            f"{self._thread_num}: The target emulator at {self._target_emulator_ip} has been started!"
        )

        # Start a scan with OpenVAS-scanner
        print(f"{self._thread_num}: Getting VT info...")
        scan_info = test_case.scan_info
        recorded_plugins_oids = scan_info["RecordedPlugins"]

        # Convert the OIDs to their current file names
        plugins_to_scan = [self._oid_filename_mapping[oid] for oid in recorded_plugins_oids]
        plugins_to_scan = " ".join(plugins_to_scan)
        print(f"{self._thread_num}: Plugins ->", plugins_to_scan)

        kb_args_for_scan = scan_info["KbArgs"]

        # NOTE: At this point, not all target services might have been started.
        # Therefore, not all relevant ports are guaranteed to be bound.
        # Sadly, our only option is to watch and wait. Otherwise the scan will fail.
        self._wait_until_target_emulator_is_ready(scan_info["RecordedPorts"])

        cmd = f"openvas-nasl -X -i /openvas_plugins -B {plugins_to_scan} -t {self._target_emulator_ip} {kb_args_for_scan}".strip()
        print(f"{self._thread_num}: {cmd}")
        (
            openvas_stdout,
            openvas_stderr,
        ) = self._openvas_scanner_container.exec_run(cmd, detach=False, demux=True).output
        if openvas_stderr:
            stderr_text = "".join(openvas_stderr.decode("utf-8").splitlines())
            raise Exception(f"Error while starting OpenVAS:\n{stderr_text}")
        if openvas_stdout:
            openvas_stdout_text = "".join(openvas_stdout.decode("utf-8").splitlines())
        else:
            # OpenVAS replied with nothing and didn't find anything
            openvas_stdout_text = ""

        print(f"{self._thread_num}: Openvas output ->\n", openvas_stdout_text)

        # Make sure that the target emulator process terminates
        # Kill all processes that are not the init process, so the container stays running
        self._terminate_target_emulator()

        # Analyze the results of the scan
        has_passed, conclusion = self._analyze_scan_result(openvas_stdout_text, scan_info)
        return (has_passed, conclusion)

    def _terminate_target_emulator(self) -> None:
        print(f"{self._thread_num}: Terminating the target emulator...")
        ps_output = self._target_emulator_container.exec_run(
            "ps -o pid", detach=False, demux=False
        ).output
        all_pids = ps_output.decode("utf-8").splitlines()[1:]
        # There can be a subprocess for each service. Just kill all running processes
        pids_to_kill = [pid.strip() for pid in all_pids if int(pid) != 1]
        # print(f"{self._thread_num}: Killing PIDs {pids_to_kill}...")
        self._target_emulator_container.exec_run(f"kill -9 {' '.join(pids_to_kill)}")

    def _analyze_scan_result(self, openvas_result: str, scan_info: dict) -> (bool, str):
        recorded_result = scan_info["Result"]
        recorded_host = scan_info["RecordedHost"]

        # Make the output independent of the host that was used
        # e.g. "127.0.0.1:8080" -> ""
        hosts_separated = "|".join(
            [
                recorded_host,
                self._target_emulator_ip,
                f"{self._target_emulator_container_name}.{self._docker_network_name}",
                self._target_emulator_hostname,
            ]
        )
        replace_pattern = re.compile(rf"(?:{hosts_separated})(:[0-9]+)?")
        openvas_sanitized_result = replace_pattern.sub("", openvas_result).strip()
        # Do the same for the recorded result - Just to be sure
        recorded_sanitized_result = replace_pattern.sub("", recorded_result).strip()

        has_passed = openvas_sanitized_result == recorded_sanitized_result
        conclusion = ""
        if not has_passed:
            conclusion = (
                "Result from OpenVAS differs from what has been recorded in the TestCase."
                f"\nSanitized result from OpenVAS:\n{openvas_sanitized_result}"
                f"\n\nExpected result from TestCase:\n{recorded_sanitized_result}"
            )
        return has_passed, conclusion
