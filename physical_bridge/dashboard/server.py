"""Web dashboard: live input, processed output, connection status, test
signals and the global ARM / DISARM switch."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

from ..frame import KINDS

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class Dashboard:
    def __init__(self, bridge, cfg: dict):
        self.bridge = bridge
        self.host = cfg.get("host", "127.0.0.1")
        self.port = int(cfg.get("port", 8080))
        self.refresh = 1.0 / float(cfg.get("refresh_hz", 15))
        self.runner: web.AppRunner | None = None
        self.clients: set[web.WebSocketResponse] = set()
        self._task: asyncio.Task | None = None
        self.url = None

    def make_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.ws)
        app.router.add_get("/api/state", self.state)
        app.router.add_get("/api/config", self.config)
        app.router.add_post("/api/inject/{stream}", self.inject_http)
        app.router.add_post("/api/arm", self.arm_http)
        app.router.add_static("/static", STATIC)
        return app

    async def start(self) -> None:
        self.runner = web.AppRunner(self.make_app(), access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        shown = "localhost" if self.host in ("0.0.0.0", "127.0.0.1") else self.host
        self.url = f"http://{shown}:{port}"
        self._task = asyncio.create_task(self._broadcast())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        for ws in list(self.clients):
            await ws.close()
        if self.runner:
            await self.runner.cleanup()

    # ----------------------------------------------------------------- http
    async def index(self, request):
        return web.FileResponse(STATIC / "index.html")

    async def state(self, request):
        return web.json_response(self.bridge.snapshot())

    async def config(self, request):
        path = self.bridge.cfg.get("_path")
        text = Path(path).read_text(encoding="utf-8") if path else "# (config built in code)"
        return web.Response(text=text, content_type="text/plain")

    async def inject_http(self, request):
        body = await request.json()
        ok = self.bridge.inject(request.match_info["stream"], body.get("data"))
        return web.json_response({"ok": ok}, status=200 if ok else 404)

    async def arm_http(self, request):
        body = await request.json()
        self.bridge.set_armed(bool(body.get("armed")))
        return web.json_response({"armed": self.bridge.armed})

    # ------------------------------------------------------------ websocket
    async def ws(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_json({"type": "hello", "kinds": KINDS})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    cmd = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if cmd.get("cmd") == "inject":
                    self.bridge.inject(cmd.get("stream", ""), cmd.get("data"))
                elif cmd.get("cmd") == "arm":
                    self.bridge.set_armed(bool(cmd.get("armed")))
        finally:
            self.clients.discard(ws)
        return ws

    async def _broadcast(self) -> None:
        while True:
            await asyncio.sleep(self.refresh)
            if not self.clients:
                continue
            try:
                payload = json.dumps({"type": "state", **self.bridge.snapshot()})
            except Exception:  # noqa: BLE001
                log.exception("snapshot failed")
                continue
            for ws in list(self.clients):
                try:
                    await ws.send_str(payload)
                except (ConnectionResetError, RuntimeError):
                    self.clients.discard(ws)
