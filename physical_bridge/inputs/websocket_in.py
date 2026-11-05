"""WebSocket input (JSON).

Send text messages like::

    {"stream": "led_matrix", "data": [[0, 255, ...], ...]}
    {"address": "/pb/arm", "data": [90, 45, 120]}
    [{"stream": "a", "data": 1}, {"stream": "b", "data": 2}]      # batch

Binary messages are parsed as OSC packets (OSC-over-WebSocket).
"""
from __future__ import annotations

import json
import logging

from aiohttp import WSMsgType, web

from ..osc import OSCError, parse_packet
from .base import Input

log = logging.getLogger(__name__)


class WebSocketInput(Input):
    type_name = "websocket"

    def __init__(self, cfg, dispatch):
        super().__init__(cfg, dispatch)
        self.runner: web.AppRunner | None = None
        self.port = None

    def make_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/{tail:.*}", self.handle)
        return app

    async def start(self) -> None:
        host, port = self.cfg.get("host", "0.0.0.0"), int(self.cfg.get("port", 9001))
        self.runner = web.AppRunner(self.make_app(), access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        try:
            await site.start()
        except OSError as exc:
            self.last_error = f"cannot listen on ws {host}:{port}: {exc}"
            log.error(self.last_error)
            return
        self.port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        self.listening = True
        self.detail = f"ws://{host}:{self.port}"
        log.info("WebSocket input listening on %s", self.detail)

    async def handle(self, request: web.Request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024 * 1024)
        if not ws.can_prepare(request).ok:
            return web.Response(text="Physical Bridge WebSocket input - connect with a WebSocket client.\n")
        await ws.prepare(request)
        self.clients += 1
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    reply = self.on_text(msg.data)
                    if reply:
                        await ws.send_json(reply)
                elif msg.type == WSMsgType.BINARY:
                    try:
                        for address, args in parse_packet(msg.data):
                            self.dispatch(address, args)
                    except OSCError as exc:
                        self.last_error = f"bad binary (OSC) message: {exc}"
        finally:
            self.clients -= 1
        return ws

    def on_text(self, text: str) -> dict | None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            self.last_error = f"invalid JSON: {exc}"
            return {"error": self.last_error}
        items = payload if isinstance(payload, list) else [payload]
        unrouted = []
        for item in items:
            if not isinstance(item, dict) or "data" not in item:
                self.last_error = "messages must be objects with 'data' and 'stream' or 'address'"
                return {"error": self.last_error}
            address = item.get("address") or ("@" + str(item["stream"]) if "stream" in item else None)
            if address is None:
                self.last_error = "message needs a 'stream' or 'address' field"
                return {"error": self.last_error}
            if not self.dispatch(address, item["data"]):
                unrouted.append(address)
        if unrouted and self.cfg.get("ack", False):
            return {"unrouted": unrouted}
        return None

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
        self.listening = False
