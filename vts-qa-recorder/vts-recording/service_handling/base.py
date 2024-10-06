from abc import ABC, abstractmethod
from pathlib import Path


class ServiceHandlerBase(ABC):
    @property
    @abstractmethod
    def name(self):
        pass

    @staticmethod
    @abstractmethod
    def detect(data: bytes) -> bool:
        pass

    @staticmethod
    @abstractmethod
    def parse_data(data: bytes, is_request: bool):
        pass

    @staticmethod
    @abstractmethod
    def save_to_new_test_case(
        service_base_dir: Path,
        recorded_communications: list,
        owner_uid: int,
        owner_gid: int,
    ):
        pass
