"""OSC over UDP input (TouchDesigner OSC Out, Unreal OSC plugin, Max, Pd, ...)."""
from __future__ import annotations

import asyncio
import logging

from ..osc import OSCError, parse_packet
from .base import Input

log = logging.getLogger(__name__)


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, owner: "OSCInput"):
        self.owner = owner

    def datagram_received(self, data, addr):
        self.owner.on_datagram(data, addr)

    def error_received(self, exc):  # pragma: no cover
        self.owner.last_error = str(exc)


class OSCInput(Input):
    """Config: ``host`` (0.0.0.0), ``port`` (9000).

    Every OSC message is routed by its address.  Arguments are passed on as a
    list, so ``/pb/arm 90.0 45.0`` feeds ``[90.0, 45.0]`` to the stream whose
    source is ``/pb/arm``."""
    type_name = "osc"

    def __init__(self, cfg, dispatch):
        super().__init__(cfg, dispatch)
        self.transport = None
        self.peers: set = set()

    async def start(self) -> None:
        host, port = self.cfg.get("host", "0.0.0.0"), int(self.cfg.get("port", 9000))
        loop = asyncio.get_running_loop()
        try:
            self.transport, _ = await loop.create_datagram_endpoint(
                lambda: _Protocol(self), local_addr=(host, port))
        except OSError as exc:
            self.last_error = f"cannot listen on udp {host}:{port}: {exc}"
            log.error(self.last_error)
            return
        self.port = self.transport.get_extra_info("sockname")[1]
        self.listening = True
        self.detail = f"udp://{host}:{self.port}"
        log.info("OSC input listening on %s", self.detail)

    def on_datagram(self, data: bytes, addr) -> None:
        self.peers.add(addr[0])
        self.clients = len(self.peers)
        try:
            for address, args in parse_packet(data):
                self.dispatch(address, args)
        except OSCError as exc:
            self.last_error = f"bad OSC packet from {addr[0]}: {exc}"

    async def stop(self) -> None:
        if self.transport:
            self.transport.close()
        self.listening = False
