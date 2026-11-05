#!/usr/bin/env python3
"""Send animated test data to Physical Bridge - no creative software needed.

    python examples/python/send_test.py                 # OSC to localhost:9000
    python examples/python/send_test.py --ws            # WebSocket to localhost:9001
    python examples/python/send_test.py --only arm      # one stream only

Matches the streams in the default config.yaml: matrix, glow, arm, dimmer.
Uses only the standard library (+ numpy if present for speed).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import socket
import struct
import sys
import time


# ---------------------------------------------------------- tiny OSC encoder
def _s(text: str) -> bytes:
    raw = text.encode() + b"\0"
    return raw + b"\0" * (-len(raw) % 4)


def osc_message(address: str, *args) -> bytes:
    tags, data = ",", b""
    for a in args:
        if isinstance(a, int):
            tags += "i"; data += struct.pack(">i", a)
        else:
            tags += "f"; data += struct.pack(">f", float(a))
    return _s(address) + _s(tags) + data


# ------------------------------------------------ tiny WebSocket text client
class MiniWebSocket:
    def __init__(self, host: str, port: int):
        self.sock = socket.create_connection((host, port))
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.sock.recv(1024)
        if b" 101 " not in resp.split(b"\r\n")[0]:
            raise RuntimeError(f"WebSocket handshake failed: {resp[:80]!r}")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        assert accept in resp

    def send_text(self, text: str) -> None:
        payload = text.encode()
        mask = os.urandom(4)
        n = len(payload)
        header = bytes([0x81])
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)


# ------------------------------------------------------------------ patterns
def blob(t: float, w: int, h: int) -> list[float]:
    cx, cy = 0.5 + 0.3 * math.cos(t), 0.5 + 0.3 * math.sin(t * 1.3)
    out = []
    for y in range(h):
        for x in range(w):
            d = math.hypot(x / (w - 1) - cx, y / (h - 1) - cy)
            out.append(round(max(0.0, 1.0 - d * 2.5), 3))
    return out


def frames(t: float) -> dict[str, list]:
    return {
        "matrix": [32, 32, *blob(t, 32, 32)],
        "glow": [16, 16, *blob(t * 0.7 + 2, 16, 16)],
        "arm": [0.5 + 0.5 * math.sin(t + i * 1.2) for i in range(3)],
        "dimmer": [1.0 if int(t / 2) % 2 else 0.0],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, help="default 9000 (OSC) or 9001 (WebSocket)")
    ap.add_argument("--ws", action="store_true", help="send over WebSocket instead of OSC")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--only", help="comma separated stream names")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    if args.ws:
        port = args.port or 9001
        ws = MiniWebSocket(args.host, port)
        send = lambda name, data: ws.send_text(json.dumps({"stream": name, "data": data}))  # noqa: E731
    else:
        port = args.port or 9000
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send = lambda name, data: sock.sendto(osc_message(f"/pb/{name}", *data), (args.host, port))  # noqa: E731
    print(f"sending to {'ws' if args.ws else 'osc'}://{args.host}:{port} at {args.fps} fps - Ctrl+C to stop")

    t0 = time.monotonic()
    try:
        while True:
            t = time.monotonic() - t0
            for name, data in frames(t).items():
                if only is None or name in only:
                    send(name, data)
            time.sleep(1 / args.fps)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
