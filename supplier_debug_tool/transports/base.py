from __future__ import annotations

from abc import ABC, abstractmethod


class TransportError(RuntimeError):
    """Transport-level failure visible to the GUI."""


class Transport(ABC):
    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def write(self, packet: bytes) -> None:
        raise NotImplementedError

    def read(self, max_len: int, timeout_s: float) -> bytes:
        raise TransportError(f"{self.__class__.__name__} does not support read")

    @property
    @abstractmethod
    def is_open(self) -> bool:
        raise NotImplementedError
