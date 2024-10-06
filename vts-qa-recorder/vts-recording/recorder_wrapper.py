import os
import sys
import signal

import docker


def _signal_handler_termination(signum, frame) -> None:  # pylint: disable=unused-argument
    terminate_recorder()


def terminate_recorder(recorder_container=None) -> None:
    if recorder_container is None:
        docker_client = docker.from_env()
        try:
            recorder_container = docker_client.containers.get("recording_recorder")
        except docker.errors.NotFound:
            exit("Error: The recorder container could not be found!")
    print("Terminating the recorder...")
    ps_output = recorder_container.exec_run("ps -o pid,comm", detach=False, demux=False).output
    all_pids = ps_output.decode("utf-8").splitlines()[1:]
    for pid_and_cmd in all_pids:
        pid, cmd = pid_and_cmd.split()
        if cmd == "python":
            print(f"Killing PID {pid}...")
            recorder_container.exec_run(f"kill -9 {pid}")


def main():
    docker_client = docker.from_env()
    try:
        recorder_container = docker_client.containers.get("recording_recorder")
    except docker.errors.NotFound:
        exit("Error: The recorder container could not be found!")

    # Signal handling
    signal.signal(signal.SIGINT, _signal_handler_termination)  # CTRL+C
    signal.signal(signal.SIGTERM, _signal_handler_termination)

    # For setting the correct owner of generated files
    caller_uid = os.getuid()
    caller_gid = os.getgid()

    args = " ".join(sys.argv[1:])
    exec_recording = recorder_container.exec_run(
        f"poetry run recorder {args} --owner-uid {caller_uid} --owner-gid {caller_gid}",
        workdir="/code",
        stream=True,
        tty=True,
    )
    recorder_output = exec_recording.output
    for line in recorder_output:
        if line:
            print(line.decode("utf-8", errors="ignore"), end="")

    terminate_recorder(recorder_container)


if __name__ == "__main__":
    main()
