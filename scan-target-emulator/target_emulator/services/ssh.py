from . import Service


class SSH(Service):
    name = "SSH"

    def _parse_data_for_test_case(self):
        print("Parsing data for SSH...")

    def deploy(self):
        print("Deploying SSH server...")
