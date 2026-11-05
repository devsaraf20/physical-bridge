"""Minimal OSC 1.0 encoder / decoder (messages and bundles).

Written from the spec so the bridge has no extra dependency for its most used
input.  Supported argument tags: i f d h s S b T F N I c r m (and arrays are
flattened).
"""
from __future__ import annotations

import struct
from typing import Any, Iterator


class OSCError(ValueError):
    pass


def _pad(n: int) -> int:
    return (n + 3) & ~3


def _read_string(data: bytes, pos: int) -> tuple[str, int]:
    end = data.find(b"\x00", pos)
    if end < 0:
        raise OSCError("unterminated string")
    return data[pos:end].decode("utf-8", errors="replace"), _pad(end + 1)


def _read_blob(data: bytes, pos: int) -> tuple[bytes, int]:
    (size,) = struct.unpack_from(">i", data, pos)
    pos += 4
    if size < 0 or pos + size > len(data):
        raise OSCError("bad blob size")
    return bytes(data[pos:pos + size]), _pad(pos + size)


def parse_message(data: bytes) -> tuple[str, list[Any]]:
    address, pos = _read_string(data, 0)
    if not address.startswith("/"):
        raise OSCError(f"bad address {address!r}")
    if pos >= len(data):
        return address, []
    tags, pos = _read_string(data, pos)
    if not tags.startswith(","):
        raise OSCError("missing type tag string")
    args: list[Any] = []
    try:
        for tag in tags[1:]:
            if tag == "i":
                args.append(struct.unpack_from(">i", data, pos)[0]); pos += 4
            elif tag == "f":
                args.append(struct.unpack_from(">f", data, pos)[0]); pos += 4
            elif tag == "d":
                args.append(struct.unpack_from(">d", data, pos)[0]); pos += 8
            elif tag == "h":
                args.append(struct.unpack_from(">q", data, pos)[0]); pos += 8
            elif tag in "sS":
                s, pos = _read_string(data, pos); args.append(s)
            elif tag == "b":
                b, pos = _read_blob(data, pos); args.append(b)
            elif tag == "T":
                args.append(True)
            elif tag == "F":
                args.append(False)
            elif tag == "N":
                args.append(None)
            elif tag == "I":
                args.append(float("inf"))
            elif tag == "c":
                args.append(chr(struct.unpack_from(">i", data, pos)[0])); pos += 4
            elif tag in "rm":
                args.append(struct.unpack_from(">I", data, pos)[0]); pos += 4
            elif tag == "t":
                args.append(struct.unpack_from(">Q", data, pos)[0]); pos += 8
            elif tag in "[]":
                continue  # arrays are flattened
            else:
                raise OSCError(f"unsupported type tag {tag!r}")
    except struct.error as exc:
        raise OSCError("truncated message") from exc
    return address, args


def parse_packet(data: bytes) -> Iterator[tuple[str, list[Any]]]:
    """Yield ``(address, args)`` for a message or (nested) bundle."""
    if data.startswith(b"#bundle\x00"):
        pos = 16  # "#bundle\0" + 8 byte timetag
        while pos + 4 <= len(data):
            (size,) = struct.unpack_from(">i", data, pos)
            pos += 4
            if size <= 0 or pos + size > len(data):
                raise OSCError("bad bundle element size")
            yield from parse_packet(data[pos:pos + size])
            pos += size
    else:
        yield parse_message(data)


def _encode_string(s: str) -> bytes:
    raw = s.encode("utf-8") + b"\x00"
    return raw + b"\x00" * (_pad(len(raw)) - len(raw))


def build_message(address: str, *args: Any) -> bytes:
    tags = ","
    payload = b""
    for a in args:
        if a is True:
            tags += "T"
        elif a is False:
            tags += "F"
        elif a is None:
            tags += "N"
        elif isinstance(a, int):
            if -2**31 <= a < 2**31:
                tags += "i"; payload += struct.pack(">i", a)
            else:
                tags += "h"; payload += struct.pack(">q", a)
        elif isinstance(a, float):
            tags += "f"; payload += struct.pack(">f", a)
        elif isinstance(a, str):
            tags += "s"; payload += _encode_string(a)
        elif isinstance(a, (bytes, bytearray)):
            tags += "b"
            payload += struct.pack(">i", len(a)) + bytes(a) + b"\x00" * (_pad(len(a)) - len(a))
        else:
            # numpy scalars and friends
            try:
                if float(a).is_integer() and "int" in type(a).__name__:
                    tags += "i"; payload += struct.pack(">i", int(a))
                else:
                    tags += "f"; payload += struct.pack(">f", float(a))
            except (TypeError, ValueError) as exc:
                raise OSCError(f"cannot encode {a!r}") from exc
    return _encode_string(address) + _encode_string(tags) + payload


def build_bundle(messages: list[bytes], timetag: int = 1) -> bytes:
    out = b"#bundle\x00" + struct.pack(">Q", timetag)
    for m in messages:
        out += struct.pack(">i", len(m)) + m
    return out
