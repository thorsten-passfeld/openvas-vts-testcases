import socket
import select
import threading
import os
import re

from collections import defaultdict

import docker
from docker.models.containers import Container

from .constants import (
    RECORDER_PROXY_IP,
    DUMMY_TARGET_RESERVED_IP_ADDRESS,
    TPROXY_BIND_PORT_TCP,
    BUFSIZE,
)
from .models import test_case_processing
from .service_handling import service_handlers, ServiceHandlerBase
from .cli_parsing import create_parser_get_args

OID_EXTRACTION_PATTERN = re.compile(r"script_oid\(\"([0-9.]+)\"\)")

# e.g. poetry run recorder 192.168.188.32 gb_dlink_dir_detect.nasl --kb "Ports/tcp/8080=1"


def determine_service_handler(data: bytes) -> ServiceHandlerBase:
    for service_handler in service_handlers:
        if service_handler.detect(data):
            print(f"Detected data for this connection as {service_handler.name}.")
            return service_handler
    return None


def parse_and_store_data_pair(
    client_message: bytes,
    server_message: bytes,
    active_service_handler: ServiceHandlerBase,
    parsed_recorded_data: defaultdict,
    thread_id: int,
) -> None:
    client_parsed_message = active_service_handler.parse_data(client_message, is_request=True)
    server_parsed_message = active_service_handler.parse_data(server_message, is_request=False)
    if not client_parsed_message or not server_parsed_message:
        print(f"{thread_id}: WARNING: Parsing the request and/or response data was not successful.")
        return

    parsed_client_server_messages = dict()
    parsed_client_server_messages["Client"] = client_parsed_message
    parsed_client_server_messages["Server"] = server_parsed_message

    # Store data in dict
    service_name = active_service_handler.name
    parsed_recorded_data[service_name][thread_id].append(parsed_client_server_messages)


def handle_proxy_client(
    client_socket: socket.socket,
    target_ip: str,
    parsed_recorded_data: defaultdict,
    recorded_ports: dict,
    thread_id: int,
) -> None:
    dest_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _, dest_port = client_socket.getsockname()
    dest_address_and_port = (target_ip, dest_port)
    print(f"{thread_id}: Connecting to destination server {dest_address_and_port}")
    try:
        dest_server_socket.connect(dest_address_and_port)
    except ConnectionRefusedError:
        # TODO: Propagate the error to the main thread and abort!
        print(f"{thread_id}: Connection has been refused by the destination server.")
        client_socket.close()
        return None

    # For when the client uses this socket for multiple requests (e.g. http-keepalive)
    # We take advantage of the fact that the order of communication is Client -> Server -> Client...
    raw_client_messages = [b""]
    raw_server_messages = [b""]
    current_message_index = -1

    is_going_to_be_next_message = True

    client_is_done = False
    server_is_done = False
    handled_premature_end_client = False
    handled_premature_end_server = False
    while not (client_is_done and server_is_done):
        sockets_to_read = list()
        if not client_is_done and client_socket.fileno() != -1:
            sockets_to_read.append(client_socket)
        if not server_is_done and dest_server_socket.fileno() != -1:
            sockets_to_read.append(dest_server_socket)
        # print(f"Sockets to read -> {sockets_to_read}")
        readable_sockets, _, _ = select.select(
            sockets_to_read,
            [],
            [],
        )
        for readable_socket in readable_sockets:
            # TODO: TLS/SSL

            if readable_socket == client_socket:
                client_server = "Client"
            else:
                client_server = "Server"

            try:
                received_data = readable_socket.recv(BUFSIZE)
            except ConnectionResetError:
                # For some reason, the other side reset the connection
                # This is fatal.
                print(f"{thread_id}: Connection reset by {client_server}. Aborting...")
                readable_socket.close()
                client_is_done = True
                server_is_done = True
                if client_server == "Client":
                    # Probably do the same for the server messages, see below
                    del raw_server_messages[current_message_index]
                else:
                    # Delete the last request from the client that triggered the reset
                    del raw_client_messages[current_message_index]
                break

            # BUG: Somewhere in here there is still the possibility for a deadlock
            # It happened that we got a client message and somehow the server side didn't shutdown
            # Happened sometimes with this command:
            # 186.20.232.186 gb_dlink_dir_detect.nasl --kb="Ports/tcp/8080=1"
            if len(received_data) > 0:
                if client_server == "Client":
                    # TODO: This section assumes the client is the first one sending
                    # for e.g. SMTP, we might need to start this dynamically for the server instead
                    # A simple bool detecting whether client or server was first will do the trick.
                    if is_going_to_be_next_message:
                        # This is the next separate client request
                        current_message_index += 1
                        raw_client_messages.append(b"")
                        raw_server_messages.append(b"")
                        is_going_to_be_next_message = False
                    raw_client_messages[current_message_index] += received_data
                    other_socket = dest_server_socket
                else:
                    is_going_to_be_next_message = True
                    raw_server_messages[current_message_index] += received_data
                    other_socket = client_socket

                if client_server == "Client":
                    print(f"{thread_id}: Received from {client_server} '{received_data}'")
                else:
                    print(f"{thread_id}: Received data from {client_server}.")

                other_side_ended_prematurely = False
                if other_socket.fileno() != -1:
                    try:
                        other_socket.sendall(received_data)
                    except BrokenPipeError:
                        print(
                            f"{thread_id}: {client_server}: Can't send to other socket - Broken pipe!"
                        )
                        other_side_ended_prematurely = True
                else:
                    other_side_ended_prematurely = True
                    # print(f"{thread_id}: {client_server}: Can't send to closed socket!")

                if other_side_ended_prematurely:
                    if (
                        not handled_premature_end_client
                        and client_server == "Server"
                        and client_is_done
                    ):
                        print(f"{thread_id}: Server: Client ended prematurely!")
                        handled_premature_end_client = True
                        # The client closed too early. Avoid a potential deadlock
                        client_is_done = True
                        client_socket.close()
                        # Make sure to at least read until the end, the server side will terminate
                        if dest_server_socket.fileno() != -1:
                            dest_server_socket.shutdown(socket.SHUT_WR)
                    elif (
                        not handled_premature_end_server
                        and client_server == "Client"
                        and server_is_done
                    ):
                        print(f"{thread_id}: Client: Server ended prematurely!")
                        handled_premature_end_server = True
                        # The server closed too early. Not sure if this happens in reality
                        server_is_done = True
                        dest_server_socket.close()
                        # Read the current client message until the end
                        if client_socket.fileno() != -1:
                            client_socket.shutdown(socket.SHUT_WR)

            else:
                if client_server == "Client":
                    print(f"{thread_id}: Closing the client...")
                    client_is_done = True
                    client_socket.close()
                    if dest_server_socket.fileno() != -1:
                        try:
                            dest_server_socket.shutdown(socket.SHUT_WR)
                        except OSError:
                            # Socket not connected
                            print(f"{thread_id}: Server socket not connected when shutting down.")
                else:
                    print(f"{thread_id}: Closing the server...")
                    server_is_done = True
                    dest_server_socket.close()
                    if client_socket.fileno() != -1:
                        try:
                            client_socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            # Socket not connected
                            print(f"{thread_id}: Client socket not connected when shutting down.")

    # Make sure that in any case, the sockets are closed now
    client_socket.close()
    dest_server_socket.close()

    # Both lists end up with an extra b"" entry
    raw_client_messages = list(filter(None, raw_client_messages))
    raw_server_messages = list(filter(None, raw_server_messages))

    print(
        f"{thread_id}: All {len(raw_client_messages)} messages from client -> {raw_client_messages}"
    )
    for msg in raw_server_messages:
        # Because server responses can be very very large
        print(f"{thread_id}: Shortened message from server -> {msg[:200]}")

    if raw_client_messages:
        # Depends on the type of data received
        active_service_handler = determine_service_handler(raw_client_messages[0])
        if active_service_handler:
            # TODO: append port for e.g. HTTP
            # BUG: Assuming that there is just e.g. one target HTTP port used for this scan
            service_name = active_service_handler.name
            recorded_ports[service_name] = dest_port

            if len(raw_client_messages) == len(raw_server_messages):
                for raw_client_message, raw_server_message in zip(
                    raw_client_messages, raw_server_messages
                ):
                    parse_and_store_data_pair(
                        raw_client_message,
                        raw_server_message,
                        active_service_handler,
                        parsed_recorded_data,
                        thread_id,
                    )
            else:
                print(
                    f"{thread_id}: The number of messages from the client "
                    "was higher than those from the server."
                )
        else:
            print(
                f"{thread_id}: Warning: Could not detect service for "
                f"the following client message: {raw_client_messages[0]}"
            )
    else:
        print(f"{thread_id}: For some reason, there were no messages from the client.")
        return None


def execute_scan(
    scanner_container: Container, result_lines: list, openvas_cmd_and_args: str
) -> None:
    stdout, stderr = scanner_container.exec_run(openvas_cmd_and_args, demux=True).output
    if stdout:
        openvas_result = stdout.decode("utf-8")
    else:
        openvas_result = ""
    result_lines.extend(openvas_result.splitlines())

    # TODO: (Important!) Error handling for OpenVAS
    # NOTE: Debug information is written to stderr, if enabled
    if stderr:
        stderr_text = "".join(stderr.decode("utf-8").splitlines())
        print(f"Error while starting OpenVAS:\n{stderr_text}")
        # TODO: Report/propagate the OpenVAS error and exit!


def manage_proxy(
    proxy_socket: socket.socket,
    stop_signal_r_channel,
    target_ip: str,
    parsed_recorded_data: defaultdict,
    recorded_ports: dict,
):
    proxy_threads = list()
    done = False
    thread_id = 0
    while not done:
        read_fds, _, _ = select.select(
            [proxy_socket, stop_signal_r_channel],
            [],
            [],
        )
        for sock in read_fds:
            if sock == stop_signal_r_channel:
                print("Received a stop signal!")
                done = True
                continue
            client_socket, client_address = sock.accept()
            print(f"{thread_id}: Connection from {client_address}")
            proxy_handling_thread = threading.Thread(
                target=handle_proxy_client,
                args=[client_socket, target_ip, parsed_recorded_data, recorded_ports, thread_id],
            )
            proxy_threads.append(proxy_handling_thread)
            proxy_handling_thread.start()
            thread_id += 1

    print("Waiting for all proxy handling threads...")
    for proxy_handling_thread in proxy_threads:
        proxy_handling_thread.join()

    proxy_socket.close()


def create_openvas_cmd(
    vts_to_execute: list,
    kb_set_values: list,
) -> (str, str):
    expanded_file_names = " ".join(vts_to_execute)
    # TODO: Plugins folder as env var
    cmd = f"openvas-nasl -X -i /var/lib/openvas/plugins/ -B {expanded_file_names} -t {DUMMY_TARGET_RESERVED_IP_ADDRESS}"
    kb_arguments_string = ""
    for kb_set_value in kb_set_values:
        kb_argument = f' --kb="{kb_set_value}"'
        kb_arguments_string += kb_argument
    cmd += kb_arguments_string
    return cmd, kb_arguments_string.strip()


def get_oids_for_vts(scanner_container: Container, absolute_vt_filenames: list) -> dict:
    cmd = rf'grep -R -E -H -o "script_oid\(\"([0-9.]+)\"\)" {" ".join(absolute_vt_filenames)}'
    stdout, stderr = scanner_container.exec_run(cmd, demux=True).output
    if stderr:
        stderr_text = stderr.decode("utf-8")
        exit(f"Error while trying to get OIDs for the given filenames:\n{stderr_text}")

    oids_for_vts = dict()
    for matched_vt_name_oid in stdout.decode("utf-8").splitlines():
        vt_filename, raw_oid = matched_vt_name_oid.split(":")
        # Get rid of surrounding characters around the extracted OID
        full_oid = OID_EXTRACTION_PATTERN.sub(r"\1", raw_oid)
        oids_for_vts[vt_filename] = full_oid.strip()  # Could have a trailing newline
    # Check if grep returned an OID for every file
    for vt_filename in absolute_vt_filenames:
        if vt_filename not in oids_for_vts:
            exit(f"Missing OID information for file '{vt_filename}'")
    return oids_for_vts


def sort_recorded_data_chronologically(parsed_recorded_data: dict) -> dict:
    parsed_recorded_data_in_order = dict()
    for method, thread_communications in parsed_recorded_data.items():
        thread_communications_in_order = dict(sorted(thread_communications.items()))
        communications_in_order = list()
        # Goes through threads and their recordings in order. 0,1,2,...
        for communications_of_thread in thread_communications_in_order.values():
            communications_in_order.extend(communications_of_thread)
        parsed_recorded_data_in_order[method] = communications_in_order
    return parsed_recorded_data_in_order


def get_scanner_container(docker_client):
    running_containers = docker_client.containers.list()
    # Find the scanner
    for container in running_containers:
        if container.name == "recording_openvas_scanner":
            return container
    return None


# Idea: https://www.rfc-editor.org/rfc/rfc5737
# Give OpenVAS an imaginary IP or a special reserved IP as a target -> 192.0.2.123 (https://stackoverflow.com/questions/10456044/what-is-a-good-invalid-ip-address-to-use-for-unit-tests)
# Will get routed through the recorder. The recorder knows about the real target from its args -> e.g. 1.2.3.4
# Recorder talks to this one as the destination server
# Iptables rule doesn't need to change every time. It just looks for -s 10.5.0.6 -d 192.0.2.123
# OpenVAS will not know about the real IP and use 192.0.2.123 in its output
# Advantage/disadvantage: Real target IP isn't shown in the TestCase
# BUT -> Recorder knows about IP, so it can be included in the TestCase, if desired
# Advantage: No need to change iptables rule all the time!!


def main():
    args = create_parser_get_args()
    absolute_vt_filenames = [
        f"/var/lib/openvas/plugins/{vt_filename}" for vt_filename in args.vts_to_execute
    ]

    docker_client = docker.from_env()
    try:
        scanner_container = docker_client.containers.get("recording_openvas_scanner")
    except docker.errors.NotFound:
        exit("Error: The scanner container could not be found!")

    oids_for_vts = get_oids_for_vts(scanner_container, absolute_vt_filenames)
    output_oid = args.output_oid
    if not output_oid:
        # Choose the rightmost VT's OID
        rightmost_vt_name = absolute_vt_filenames[-1]
        output_oid = oids_for_vts[rightmost_vt_name]
    elif output_oid not in oids_for_vts.values():
        exit(f"The desired output OID '{args.output_oid}' isn't one of the given VTs.")

    proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_socket.setsockopt(socket.SOL_IP, socket.IP_TRANSPARENT, 1)

    try:
        proxy_socket.bind((RECORDER_PROXY_IP, TPROXY_BIND_PORT_TCP))
    except socket.error as e:
        error = e.strerror
        exit(error)

    proxy_socket.listen()

    if args.kb_set_values:
        kb_set_values = args.kb_set_values
    else:
        kb_set_values = list()
    # The scan using OpenVAS-scanner
    openvas_cmd_and_args, kb_arguments_string = create_openvas_cmd(
        absolute_vt_filenames, kb_set_values
    )
    result_lines = list()
    scan_thread = threading.Thread(
        target=execute_scan,
        args=[scanner_container, result_lines, openvas_cmd_and_args],
    )
    scan_thread.start()

    # Proxy manager
    parsed_recorded_data = defaultdict(lambda: defaultdict(list))
    recorded_ports = dict()
    # TODO: Simple UDP proxy
    stop_signal_r_channel, stop_signal_w_channel = os.pipe()
    proxy_manager_thread = threading.Thread(
        target=manage_proxy,
        args=[
            proxy_socket,
            stop_signal_r_channel,
            args.target_ip,
            parsed_recorded_data,
            recorded_ports,
        ],
    )
    proxy_manager_thread.start()

    print("Waiting for scan to be done...")
    scan_thread.join()

    print("Scan is done. Making sure that everything terminates...")
    os.write(stop_signal_w_channel, b"!")

    print("Waiting for proxy manager to be done...")
    proxy_manager_thread.join()

    result = "".join(result_lines)

    print("Processing recorded data...")
    # Sort the messages by their thread id, so we have them in proper order!
    # e.g. messages from thread 1 came before thread 2
    # Related problem: We need to know, in which order to send different responses for e.g. "/"
    parsed_recorded_data_in_order = sort_recorded_data_chronologically(parsed_recorded_data)

    test_case_processing.process_and_store_parsed_data_into_test_case(
        result,
        parsed_recorded_data_in_order,
        recorded_ports,
        args.output_dir,
        kb_arguments_string,
        oids_for_vts,
        output_oid,
        args.owner_uid,
        args.owner_gid,
    )

    print(f"Saved recorded data under OID '{output_oid}'")

    print("Result:")
    print(result)

    # Question: What happens to data that couldn't be parsed?
    # -> Put it in directory "TCP" or "UDP" and let it be served by a socket
    # NOTE: It may be best to just handle everything with TCP / UDP sockets
    # because e.g. find_service.nasl seems to send undefined bytes to the HTTP port


if __name__ == "__main__":
    main()
