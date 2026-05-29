from __future__ import annotations

import time
from threading import RLock
from dataclasses import dataclass
from typing import Callable, Mapping

from . import protocol
from .transports import Transport, TransportError


LogFn = Callable[[str], None]


@dataclass(frozen=True)
class StreamConfig:
    channel_id: int = 1
    led_count: int = 60
    fps: int = 30
    brightness: float = 1.0


class DebugClient:
    def __init__(self, transport: Transport, *, require_ack: bool, log: LogFn) -> None:
        self.transport = transport
        self.require_ack = bool(require_ack)
        self.log = log
        self.seq = protocol.SequenceCounter()
        self.frame_id = 0
        self._lock = RLock()

    def open(self) -> None:
        with self._lock:
            self.transport.open()
            self.log("transport opened")

    def close(self) -> None:
        with self._lock:
            self.transport.close()
            self.log("transport closed")

    def handshake(self, *, led_count: int, fps: int) -> bool:
        with self._lock:
            last_error: Exception | None = None
            for _attempt in range(3):
                seq = self.seq.next()
                payload = protocol.build_hello_payload(width=led_count, height=1, fps=fps)
                packet = protocol.build_packet(
                    msg_type=protocol.MessageType.HELLO,
                    seq=seq,
                    payload=payload,
                    flags=protocol.Flag.ACK_REQUIRED,
                )
                self.transport.write(packet)
                self.log(f"HELLO sent seq={seq}, strip_led_count={led_count}, fps={fps}")
                if not self.require_ack:
                    self.log("ACK disabled: HELLO response skipped")
                    return True
                try:
                    response = self._read_packet(timeout_s=1.0, max_payload_len=protocol.HELLO_ACK_PAYLOAD_STRUCT.size)
                    ack = protocol.parse_hello_ack(response, expected_seq=seq)
                    expected_payload = protocol.STRIP_FRAME_META_STRUCT.size + led_count * 3
                    if ack.status != 0:
                        raise TransportError(f"HELLO_ACK status={ack.status}")
                    if ack.encoding != protocol.Encoding.RGB24:
                        raise TransportError("board does not report RGB24 support")
                    if ack.width not in (led_count, 0) or ack.height not in (1, 0):
                        raise TransportError(f"HELLO_ACK dimension mismatch: width={ack.width}, height={ack.height}")
                    if ack.max_payload_len < expected_payload:
                        raise TransportError(f"board max_payload_len too small: {ack.max_payload_len}")
                    self.log(f"HELLO_ACK ok max_fps={ack.max_fps}, max_payload={ack.max_payload_len}")
                    return True
                except Exception as exc:
                    last_error = exc
                    self.log(f"HELLO retry after error: {exc}")
                    time.sleep(0.05)
            raise TransportError(f"HELLO failed: {last_error}")

    def start_stream(self, *, led_count: int, fps: int) -> bool:
        payload = protocol.build_start_stream_payload(width=led_count, height=1, fps=fps)
        return self._send_reliable(protocol.MessageType.START_STREAM, payload, label="START_STREAM")

    def set_brightness(self, strip: float) -> bool:
        payload = protocol.build_brightness_payload(strip=strip, matrix=1.0)
        return self._send_reliable(protocol.MessageType.SET_BRIGHTNESS, payload, label=f"SET_BRIGHTNESS strip={strip:.3f}")

    def set_power(self, strip_on: bool) -> bool:
        payload = protocol.build_power_payload(strip_on=strip_on, matrix_on=True)
        return self._send_reliable(protocol.MessageType.SET_POWER, payload, label=f"SET_POWER strip={strip_on}")

    def set_mode(self, command: Mapping[str, object]) -> bool:
        payload = protocol.build_mode_payload(command)
        return self._send_reliable(protocol.MessageType.SET_MODE, payload, label="SET_MODE")

    def send_strip_frame(self, *, channel_id: int, led_count: int, duration_ms: int, rgb: bytes) -> None:
        self.frame_id = (self.frame_id + 1) & 0xFFFFFFFF
        if self.frame_id == 0:
            self.frame_id = 1
        payload = protocol.build_strip_frame_payload(
            frame_id=self.frame_id,
            channel_id=channel_id,
            led_count=led_count,
            duration_ms=duration_ms,
            rgb=rgb,
        )
        packet = protocol.build_packet(
            msg_type=protocol.MessageType.STRIP_FRAME,
            seq=self.seq.next(),
            payload=payload,
            flags=0,
        )
        with self._lock:
            self.transport.write(packet)

    def _send_reliable(self, msg_type: int, payload: bytes, *, label: str) -> bool:
        with self._lock:
            last_error: Exception | None = None
            for _attempt in range(3):
                seq = self.seq.next()
                packet = protocol.build_packet(
                    msg_type=msg_type,
                    seq=seq,
                    payload=payload,
                    flags=protocol.Flag.ACK_REQUIRED,
                )
                self.transport.write(packet)
                self.log(f"{label} sent seq={seq}, bytes={len(packet)}")
                if not self.require_ack:
                    self.log(f"ACK disabled: {label} accepted locally")
                    return True
                try:
                    response = self._read_packet(timeout_s=1.0, max_payload_len=protocol.ACK_PAYLOAD_STRUCT.size)
                    if (response.flags & protocol.Flag.RESPONSE) == 0:
                        raise TransportError(f"{label} ACK missing RESPONSE flag")
                    ack = protocol.parse_ack(response)
                    if ack.ack_seq != seq or ack.status != 0:
                        raise TransportError(f"{label} ACK failed: ack_seq={ack.ack_seq}, status={ack.status}")
                    self.log(f"{label} ACK ok")
                    return True
                except Exception as exc:
                    last_error = exc
                    self.log(f"{label} retry after error: {exc}")
                    time.sleep(0.05)
            raise TransportError(f"{label} failed: {last_error}")

    def _read_packet(self, timeout_s: float, max_payload_len: int) -> protocol.Packet:
        deadline = time.time() + max(0.05, timeout_s)
        window = bytearray()
        while time.time() < deadline:
            data = self.transport.read(1, timeout_s=0.05)
            if not data:
                continue
            window.extend(data)
            if len(window) > len(protocol.MAGIC):
                del window[0 : len(window) - len(protocol.MAGIC)]
            if bytes(window) == protocol.MAGIC:
                break
        else:
            raise TransportError("timed out waiting for packet magic")

        rest = self._read_exact(protocol.HEADER_LEN - len(protocol.MAGIC), deadline)
        header = protocol.MAGIC + rest
        _magic, _version, _msg_type, _flags, _header_len, _seq, payload_len, _crc = protocol.HEADER_STRUCT.unpack(header)
        safe_limit = min(max_payload_len, protocol.MAX_PAYLOAD_LEN)
        if payload_len > safe_limit:
            raise TransportError(f"response payload too large: {payload_len} > {safe_limit}")
        payload = self._read_exact(payload_len, deadline)
        return protocol.parse_packet(header + payload)

    def _read_exact(self, size: int, deadline: float) -> bytes:
        data = bytearray()
        while len(data) < size and time.time() < deadline:
            chunk = self.transport.read(size - len(data), timeout_s=0.05)
            if chunk:
                data.extend(chunk)
        if len(data) != size:
            raise TransportError(f"timed out reading {size} bytes")
        return bytes(data)
