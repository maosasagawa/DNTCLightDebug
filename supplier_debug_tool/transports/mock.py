from __future__ import annotations

from collections import deque

from .. import protocol
from .base import Transport


class MockTransport(Transport):
    """In-memory transport that auto-responds to HELLO/ACK-required packets."""

    def __init__(self, width: int, height: int, max_fps: int = 120) -> None:
        self.width = int(width)
        self.height = int(height)
        self.max_fps = int(max_fps)
        self.sent_packets: list[bytes] = []
        self._responses: deque[bytes] = deque()
        self._read_buffer = bytearray()
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False
        self._responses.clear()
        self._read_buffer.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, packet: bytes) -> None:
        if not self._open:
            raise RuntimeError("mock transport is closed")
        self.sent_packets.append(packet)
        parsed = protocol.parse_packet(packet)
        if parsed.msg_type == protocol.MessageType.HELLO:
            payload = protocol.HELLO_ACK_PAYLOAD_STRUCT.pack(
                self.width,
                self.height,
                protocol.Encoding.RGB24,
                0,
                self.max_fps,
                1024 * 1024,
            )
            self._responses.append(
                protocol.build_packet(
                    msg_type=protocol.MessageType.HELLO_ACK,
                    seq=parsed.seq,
                    payload=payload,
                    flags=protocol.Flag.RESPONSE,
                )
            )
            return
        if parsed.flags & protocol.Flag.ACK_REQUIRED:
            ack_payload = protocol.ACK_PAYLOAD_STRUCT.pack(parsed.seq, 0, b"\x00\x00\x00")
            self._responses.append(
                protocol.build_packet(
                    msg_type=protocol.MessageType.ACK,
                    seq=parsed.seq,
                    payload=ack_payload,
                    flags=protocol.Flag.RESPONSE,
                )
            )

    def read(self, max_len: int, timeout_s: float) -> bytes:
        if not self._read_buffer and self._responses:
            self._read_buffer.extend(self._responses.popleft())
        if not self._read_buffer:
            return b""
        size = max(1, min(max_len, len(self._read_buffer)))
        out = bytes(self._read_buffer[:size])
        del self._read_buffer[:size]
        return out
