from __future__ import annotations

import time

from .base import Transport, TransportError

try:
    import serial
except Exception:  # pragma: no cover - depends on optional dependency
    serial = None


class SerialTransport(Transport):
    def __init__(self, port: str, baudrate: int, timeout_s: float = 0.1) -> None:
        self.port = port.strip()
        self.baudrate = max(1200, int(baudrate))
        self.timeout_s = max(0.01, float(timeout_s))
        self._serial = None

    def open(self) -> None:
        if serial is None:
            raise TransportError("pyserial is not installed")
        if not self.port:
            raise TransportError("serial port is empty")
        self._serial = serial.Serial(
            self.port,
            self.baudrate,
            timeout=self.timeout_s,
            write_timeout=max(self.timeout_s, 0.5),
        )

    def close(self) -> None:
        if self._serial is None:
            return
        try:
            self._serial.close()
        finally:
            self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and bool(self._serial.is_open)

    def write(self, packet: bytes) -> None:
        if self._serial is None:
            raise TransportError("serial transport is closed")
        self._serial.write(packet)
        self._serial.flush()

    def read(self, max_len: int, timeout_s: float) -> bytes:
        if self._serial is None:
            raise TransportError("serial transport is closed")
        deadline = time.time() + max(0.01, float(timeout_s))
        data = bytearray()
        while len(data) < max_len and time.time() < deadline:
            chunk = self._serial.read(max_len - len(data))
            if chunk:
                data.extend(chunk)
            elif data:
                break
        return bytes(data)
