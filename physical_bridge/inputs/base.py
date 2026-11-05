"""Input plugin base class."""
from __future__ import annotations

import time
from typing import Any, Callable

from ..stream import RateMeter

Dispatch = Callable[[str, Any, str], bool]


class Input:
    type_name = "input"

    def __init__(self, cfg: dict, dispatch: Dispatch):
        self.cfg = cfg
        self.dispatch_fn = dispatch
        self.listening = False
        self.detail = ""
        self.last_error: str | None = None
        self.messages = 0
        self.last_address: str | None = None
        self.last_time: float | None = None
        self.rate = RateMeter()
        self.clients = 0

    def dispatch(self, address: str, raw: Any) -> bool:
        self.messages += 1
        self.last_address = address
        self.last_time = time.monotonic()
        self.rate.mark(self.last_time)
        return self.dispatch_fn(address, raw, self.type_name)

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        pass

    def snapshot(self) -> dict:
        ago = None if self.last_time is None else round(time.monotonic() - self.last_time, 1)
        return {
            "type": self.type_name,
            "listening": self.listening,
            "detail": self.detail,
            "error": self.last_error,
            "messages": self.messages,
            "rate": round(self.rate.rate, 1),
            "last_address": self.last_address,
            "last_seen_s": ago,
            "clients": self.clients,
        }
