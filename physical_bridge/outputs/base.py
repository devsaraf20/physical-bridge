"""Output plugin base class and registry.

To add a new kind of hardware, subclass :class:`Output`, decorate it with
``@register_output("mytype")`` and implement :meth:`send`.  The base class
handles queueing: only the newest frame per stream is kept, so a slow device
never builds up latency - it simply skips stale frames.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from ..frame import Frame
from ..stream import RateMeter

if TYPE_CHECKING:
    from ..stream import Stream

log = logging.getLogger(__name__)

OUTPUT_TYPES: dict[str, type["Output"]] = {}


def register_output(name: str):
    def deco(cls):
        cls.type_name = name
        OUTPUT_TYPES[name] = cls
        return cls
    return deco


class Output:
    type_name = "output"
    physical = True  # False for outputs that never touch hardware (virtual)

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        self.max_fps = float(cfg.get("max_fps", 0) or 0)
        self.connected = False
        self.detail = ""
        self.last_error: str | None = None
        self.frames_sent = 0
        self.frames_dropped = 0
        self.bytes_sent = 0
        self.rate = RateMeter()
        # newest frame per (stream, destination); older ones are skipped
        self._pending: dict[tuple[str, int], tuple[str, Frame, dict]] = {}
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._last_send = 0.0

    # -- lifecycle ------------------------------------------------------
    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._writer(), name=f"output:{self.name}"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
        await self.close()

    async def close(self) -> None:
        pass

    # -- data path ------------------------------------------------------
    def submit(self, stream: "Stream", frame: Frame, ref: dict) -> None:
        key = (stream.name, id(ref))
        if key in self._pending:
            self.frames_dropped += 1
        self._pending[key] = (stream.name, frame, ref)
        self._wake.set()

    async def _writer(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            if self.max_fps:
                wait = 1.0 / self.max_fps - (time.monotonic() - self._last_send)
                if wait > 0:
                    await asyncio.sleep(wait)
            pending, self._pending = self._pending, {}
            for stream_name, frame, ref in pending.values():
                try:
                    n = await self.send(stream_name, frame, ref)
                    self.frames_sent += 1
                    self.bytes_sent += n or 0
                    self.rate.mark()
                except Exception as exc:  # noqa: BLE001
                    self.last_error = str(exc)
                    log.warning("output %s: %s", self.name, exc)
            self._last_send = time.monotonic()

    async def send(self, stream_name: str, frame: Frame, ref: dict) -> int:
        """Deliver one frame.  Return the number of bytes written."""
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_name,
            "physical": self.physical,
            "connected": self.connected,
            "detail": self.detail,
            "error": self.last_error,
            "frames_sent": self.frames_sent,
            "frames_dropped": self.frames_dropped,
            "bytes_sent": self.bytes_sent,
            "fps": round(self.rate.rate, 1),
        }
