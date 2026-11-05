"""Physical Bridge wire protocol (PBP v1).

A tiny binary framing shared by the Python host and the Arduino / ESP32
firmware in ``firmware/libraries/PhysicalBridge``.  Every frame looks like::

    +------+------+------+------+--------+--------+-----------+------+
    | 'P'  | 'B'  | TYPE | ADDR | LEN_LO | LEN_HI | PAYLOAD.. | CRC8 |
    +------+------+------+------+--------+--------+-----------+------+

* ``'P' 'B'`` (0x50 0x42) are sync bytes so a receiver can recover from noise.
* ``TYPE``   is one of the ``MsgType`` values below.
* ``ADDR``   is the device address (0-254).  255 means "broadcast": every
  device accepts it.  On a plain USB serial link just leave it at 255; on an
  RS485 bus give every device its own address.
* ``LEN``    is the payload length, little endian.
* ``CRC8``   is CRC-8/ATM (poly 0x07, init 0x00) over TYPE, ADDR, LEN and the
  payload (i.e. everything except the two sync bytes and the CRC itself).

Payloads (all multi-byte numbers are little endian):

=========  ====  ===========================================================
type       code  payload
=========  ====  ===========================================================
VALUE      0x01  float32
ANGLES     0x02  N x float32 (degrees, N = LEN / 4)
BITS       0x03  W(u8) H(u8) + ceil(W*H/8) bytes, row-major, MSB first
GRID       0x04  W(u8) H(u8) + W*H bytes (0-255), row-major
PING       0x10  empty (host -> device)
HELLO      0x20  UTF-8 text "name" or "name;key=value;..." (device -> host)
PONG       0x21  empty (device -> host)
LOG        0x22  UTF-8 text (device -> host, shown in the dashboard)
=========  ====  ===========================================================
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterator

import numpy as np

SYNC = b"PB"
BROADCAST = 0xFF
HEADER_LEN = 6  # sync(2) + type + addr + len(2)
MAX_PAYLOAD = 65535


class MsgType(IntEnum):
    VALUE = 0x01
    ANGLES = 0x02
    BITS = 0x03
    GRID = 0x04
    PING = 0x10
    HELLO = 0x20
    PONG = 0x21
    LOG = 0x22


def _make_crc_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        table.append(crc)
    return table


_CRC_TABLE = _make_crc_table()
_KNOWN_TYPES = frozenset(int(t) for t in MsgType)


def crc8(data: bytes, crc: int = 0) -> int:
    for b in data:
        crc = _CRC_TABLE[crc ^ b]
    return crc


def encode_frame(msg_type: int, payload: bytes = b"", addr: int = BROADCAST) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large ({len(payload)} bytes)")
    if not 0 <= addr <= 255:
        raise ValueError("address must be 0-255")
    body = struct.pack("<BBH", int(msg_type), addr, len(payload)) + payload
    return SYNC + body + bytes([crc8(body)])


# ---------------------------------------------------------------- payloads

def pack_value(value: float) -> bytes:
    return struct.pack("<f", float(value))


def pack_angles(angles) -> bytes:
    arr = np.asarray(angles, dtype="<f4").ravel()
    return arr.tobytes()


def pack_grid(grid) -> bytes:
    arr = np.asarray(grid)
    h, w = arr.shape
    _check_dims(w, h)
    data = np.clip(np.rint(arr), 0, 255).astype(np.uint8)
    return bytes([w, h]) + data.tobytes()


def pack_bits(bits) -> bytes:
    arr = np.asarray(bits)
    h, w = arr.shape
    _check_dims(w, h)
    packed = np.packbits((arr > 0).astype(np.uint8).ravel(), bitorder="big")
    return bytes([w, h]) + packed.tobytes()


def _check_dims(w: int, h: int) -> None:
    if not (0 < w <= 255 and 0 < h <= 255):
        raise ValueError(f"grid size {w}x{h} not supported (1-255 per side)")


def unpack_payload(msg_type: int, payload: bytes):
    """Decode a payload back into Python / numpy values (used by the virtual
    device and tests)."""
    t = MsgType(msg_type)
    if t == MsgType.VALUE:
        return struct.unpack("<f", payload)[0]
    if t == MsgType.ANGLES:
        return np.frombuffer(payload, dtype="<f4").astype(float).tolist()
    if t == MsgType.GRID:
        w, h = payload[0], payload[1]
        return np.frombuffer(payload[2:2 + w * h], dtype=np.uint8).reshape(h, w)
    if t == MsgType.BITS:
        w, h = payload[0], payload[1]
        bits = np.unpackbits(np.frombuffer(payload[2:], dtype=np.uint8), bitorder="big")
        return bits[: w * h].reshape(h, w)
    if t in (MsgType.HELLO, MsgType.LOG):
        return payload.decode("utf-8", errors="replace")
    return None


@dataclass
class Packet:
    type: int
    addr: int
    payload: bytes

    def decode(self):
        return unpack_payload(self.type, self.payload)


class FrameParser:
    """Incremental, resynchronising parser.  Feed it raw bytes, iterate packets."""

    def __init__(self, max_payload: int = MAX_PAYLOAD):
        self.buf = bytearray()
        self.max_payload = max_payload
        self.crc_errors = 0

    def feed(self, data: bytes) -> Iterator[Packet]:
        self.buf.extend(data)
        while True:
            idx = self.buf.find(SYNC)
            if idx < 0:
                # keep a trailing 'P' in case the 'B' arrives next time
                del self.buf[: max(0, len(self.buf) - 1)]
                return
            if idx:
                del self.buf[:idx]
            if len(self.buf) < HEADER_LEN:
                return
            msg_type, addr, length = struct.unpack_from("<BBH", self.buf, 2)
            # an unknown type means this 'PB' was a false sync inside other data
            if msg_type not in _KNOWN_TYPES or length > self.max_payload:
                del self.buf[:2]
                continue
            total = HEADER_LEN + length + 1
            if len(self.buf) < total:
                return
            body = bytes(self.buf[2:HEADER_LEN + length])
            if crc8(body) != self.buf[total - 1]:
                self.crc_errors += 1
                del self.buf[:2]
                continue
            del self.buf[:total]
            yield Packet(msg_type, addr, body[4:])


def encode_data_frame(kind: str, data, addr: int = BROADCAST) -> bytes:
    """Encode a processed :class:`~physical_bridge.frame.Frame` payload."""
    if kind == "value":
        return encode_frame(MsgType.VALUE, pack_value(data), addr)
    if kind == "angles":
        return encode_frame(MsgType.ANGLES, pack_angles(data), addr)
    if kind == "grid":
        return encode_frame(MsgType.GRID, pack_grid(data), addr)
    if kind == "bits":
        return encode_frame(MsgType.BITS, pack_bits(data), addr)
    raise ValueError(f"unknown frame kind {kind!r}")
