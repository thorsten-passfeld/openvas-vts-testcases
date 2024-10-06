from abc import ABC, abstractmethod
from pathlib import Path


class Service(ABC):
    def __init__(self, service_base_path: Path, host: str, service_port: int, recorded_host: str):
        self._service_base_path = service_base_path
        self.host = host
        self.recorded_host = recorded_host
        self.port = service_port
        self._parse_data_for_test_case()

    @property
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def _parse_data_for_test_case(self):
        pass

    @abstractmethod
    def deploy(self):
        pass
