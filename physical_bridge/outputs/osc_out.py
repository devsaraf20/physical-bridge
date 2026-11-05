"""Forward processed frames as OSC (to another app, a lighting desk, an ESP32
running an OSC library, a second bridge ...)."""
from __future__ import annotations

import asyncio
import socket

import numpy as np

from ..frame import Frame
from ..osc import build_message
from .base import Output, register_output


def frame_to_osc_args(frame: Frame, grid_format: str = "blob") -> list:
    if frame.kind == "value":
        return [float(frame.data)]
    if frame.kind == "angles":
        return [float(x) for x in np.ravel(frame.data)]
    arr = np.asarray(frame.data)
    h, w = arr.shape
    if frame.kind == "bits":
        flat = (arr > 0).astype(np.uint8)
    else:
        flat = np.clip(np.rint(arr), 0, 255).astype(np.uint8)
    if grid_format == "blob":
        return [int(w), int(h), flat.tobytes()]
    return [int(w), int(h), *(int(v) for v in flat.ravel())]


@register_output("osc")
class OSCOutput(Output):
    """Config keys: ``host`` (127.0.0.1), ``port`` (required),
    ``prefix`` (address prefix, default ``/pb/out/``), ``grid_format``
    (``blob`` = [w, h, bytes] or ``list`` = [w, h, v, v, ...])."""
    physical = True

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.host = cfg.get("host", "127.0.0.1")
        self.port = int(cfg["port"])
        self.prefix = cfg.get("prefix", "/pb/out/")
        self.grid_format = cfg.get("grid_format", "blob")
        self.transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=(self.host, self.port), family=socket.AF_INET)
        self.connected = True
        self.detail = f"udp://{self.host}:{self.port}"
        await super().start()

    async def send(self, stream_name: str, frame: Frame, ref: dict) -> int:
        address = ref.get("address") or f"{self.prefix.rstrip('/')}/{stream_name}"
        msg = build_message(address, *frame_to_osc_args(frame, self.grid_format))
        self.transport.sendto(msg)
        return len(msg)

    async def close(self) -> None:
        if self.transport:
            self.transport.close()
        self.connected = False
