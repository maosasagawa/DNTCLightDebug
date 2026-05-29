from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping, Sequence


MAGIC = b"ALPK"
VERSION = 1
HEADER_LEN = 20
MAX_PAYLOAD_LEN = 16 * 1024 * 1024

HEADER_STRUCT = struct.Struct(">4sBBBBIII")
HELLO_PAYLOAD_STRUCT = struct.Struct(">HHBBH")
HELLO_ACK_PAYLOAD_STRUCT = struct.Struct(">HHBBHI")
START_STREAM_PAYLOAD_STRUCT = struct.Struct(">HHBBH")
ACK_PAYLOAD_STRUCT = struct.Struct(">IB3s")
BRIGHTNESS_PAYLOAD_STRUCT = struct.Struct(">HH")
POWER_PAYLOAD_STRUCT = struct.Struct(">BB2s")
STRIP_FRAME_META_STRUCT = struct.Struct(">IHHII")


class Flag(IntEnum):
    ACK_REQUIRED = 0x01
    RESPONSE = 0x02
    ERROR = 0x04


class MessageType(IntEnum):
    HELLO = 0x01
    HELLO_ACK = 0x02
    START_STREAM = 0x03
    SET_BRIGHTNESS = 0x10
    SET_POWER = 0x11
    SET_MODE = 0x12
    MATRIX_FRAME = 0x20
    STRIP_FRAME = 0x21
    ERROR = 0x7E
    ACK = 0x7F


class Encoding(IntEnum):
    RGB24 = 1


@dataclass(frozen=True)
class Packet:
    msg_type: int
    seq: int
    flags: int
    payload: bytes


@dataclass(frozen=True)
class HelloAck:
    width: int
    height: int
    encoding: int
    status: int
    max_fps: int
    max_payload_len: int


@dataclass(frozen=True)
class Ack:
    ack_seq: int
    status: int


class SequenceCounter:
    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value = (self._value + 1) & 0xFFFFFFFF
        if self._value == 0:
            self._value = 1
        return self._value


def crc32(data: bytes | bytearray) -> int:
    if not data:
        return 0
    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


def build_packet(msg_type: int, seq: int, payload: bytes = b"", flags: int = 0) -> bytes:
    payload_bytes = bytes(payload)
    header = HEADER_STRUCT.pack(
        MAGIC,
        VERSION,
        msg_type & 0xFF,
        flags & 0xFF,
        HEADER_LEN,
        seq & 0xFFFFFFFF,
        len(payload_bytes),
        crc32(payload_bytes),
    )
    return header + payload_bytes


def parse_packet(data: bytes) -> Packet:
    if len(data) < HEADER_LEN:
        raise ValueError("packet too short")
    magic, version, msg_type, flags, header_len, seq, payload_len, payload_crc = HEADER_STRUCT.unpack(
        data[:HEADER_LEN]
    )
    if magic != MAGIC:
        raise ValueError("invalid magic")
    if version != VERSION:
        raise ValueError("unsupported version")
    if header_len != HEADER_LEN:
        raise ValueError("invalid header length")
    if payload_len > MAX_PAYLOAD_LEN:
        raise ValueError("payload too large")
    if len(data) < HEADER_LEN + payload_len:
        raise ValueError("incomplete payload")
    payload = data[HEADER_LEN : HEADER_LEN + payload_len]
    if crc32(payload) != payload_crc:
        raise ValueError("payload crc mismatch")
    return Packet(msg_type=msg_type, seq=seq, flags=flags, payload=payload)


def build_hello_payload(width: int, height: int, fps: int) -> bytes:
    return HELLO_PAYLOAD_STRUCT.pack(width, height, Encoding.RGB24, 0, max(1, min(65535, int(fps))))


def build_start_stream_payload(width: int, height: int, fps: int) -> bytes:
    return START_STREAM_PAYLOAD_STRUCT.pack(width, height, Encoding.RGB24, 0, max(1, min(65535, int(fps))))


def parse_hello_ack(packet: Packet, expected_seq: int) -> HelloAck:
    if packet.msg_type != MessageType.HELLO_ACK:
        raise ValueError("expected HELLO_ACK")
    if packet.seq != expected_seq:
        raise ValueError("HELLO_ACK seq mismatch")
    if (packet.flags & Flag.RESPONSE) == 0:
        raise ValueError("HELLO_ACK missing RESPONSE flag")
    if len(packet.payload) < HELLO_ACK_PAYLOAD_STRUCT.size:
        raise ValueError("HELLO_ACK payload too short")
    width, height, encoding, status, max_fps, max_payload_len = HELLO_ACK_PAYLOAD_STRUCT.unpack(
        packet.payload[: HELLO_ACK_PAYLOAD_STRUCT.size]
    )
    return HelloAck(width, height, encoding, status, max_fps, max_payload_len)


def parse_ack(packet: Packet) -> Ack:
    if packet.msg_type != MessageType.ACK:
        raise ValueError("expected ACK")
    if len(packet.payload) < ACK_PAYLOAD_STRUCT.size:
        raise ValueError("ACK payload too short")
    ack_seq, status, _reserved = ACK_PAYLOAD_STRUCT.unpack(packet.payload[: ACK_PAYLOAD_STRUCT.size])
    return Ack(ack_seq=ack_seq, status=status)


def build_brightness_payload(strip: float, matrix: float = 1.0) -> bytes:
    return BRIGHTNESS_PAYLOAD_STRUCT.pack(_permille(matrix), _permille(strip))


def build_power_payload(strip_on: bool, matrix_on: bool = True) -> bytes:
    return POWER_PAYLOAD_STRUCT.pack(1 if matrix_on else 0, 1 if strip_on else 0, b"\x00\x00")


def build_mode_payload(command: Mapping[str, object]) -> bytes:
    return json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_strip_frame_payload(
    *,
    frame_id: int,
    channel_id: int,
    led_count: int,
    duration_ms: int,
    rgb: bytes,
) -> bytes:
    expected_len = max(0, int(led_count) * 3)
    rgb_bytes = bytes(rgb)
    if len(rgb_bytes) < expected_len:
        rgb_bytes += bytes(expected_len - len(rgb_bytes))
    elif len(rgb_bytes) > expected_len:
        rgb_bytes = rgb_bytes[:expected_len]
    meta = STRIP_FRAME_META_STRUCT.pack(
        frame_id & 0xFFFFFFFF,
        max(0, min(65535, int(channel_id))),
        max(1, min(65535, int(led_count))),
        max(1, int(duration_ms)),
        len(rgb_bytes),
    )
    return meta + rgb_bytes


def frame_to_rgb24(frame: Sequence[Sequence[int]]) -> bytes:
    buf = bytearray()
    for rgb in frame:
        if len(rgb) != 3:
            continue
        buf.extend((_clamp_int(rgb[0]), _clamp_int(rgb[1]), _clamp_int(rgb[2])))
    return bytes(buf)


def _permille(value: float) -> int:
    return max(0, min(1000, int(round(float(value) * 1000))))


def _clamp_int(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except Exception:
        n = 0
    return max(0, min(255, n))
