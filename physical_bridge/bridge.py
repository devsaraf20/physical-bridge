"""The Bridge wires inputs -> streams -> outputs together."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any

from .inputs import INPUT_TYPES
from .inputs.base import Input
from .outputs import Output, create_output
from .processing.steps import ConfigError
from .stream import Stream

log = logging.getLogger(__name__)


class Bridge:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tick_hz = float(cfg["bridge"].get("tick_hz", 60))
        self.armed = bool(cfg["bridge"].get("start_armed", True))
        self.started_at = time.time()
        self.outputs: dict[str, Output] = {
            name: create_output(name, ocfg) for name, ocfg in cfg["outputs"].items()
        }
        self.streams: dict[str, Stream] = {}
        for name, scfg in cfg["streams"].items():
            refs = [(self.outputs[r["name"]], r) for r in scfg["outputs"]]
            try:
                self.streams[name] = Stream(name, scfg, refs, self.tick_hz, bridge=self)
            except ConfigError as exc:
                raise ConfigError(f"stream '{name}': {exc}") from None
        self.inputs: dict[str, Input] = {}
        for kind, icfg in cfg["inputs"].items():
            if icfg and icfg.get("enabled"):
                self.inputs[kind] = INPUT_TYPES[kind](icfg, self.dispatch)
        # addresses that arrived but matched no stream (shown in the dashboard)
        self.unrouted: OrderedDict[str, dict] = OrderedDict()

    # ---------------------------------------------------------------- routing
    def dispatch(self, address: str, raw: Any, origin: str = "") -> bool:
        matched = False
        if address.startswith("@"):
            stream = self.streams.get(address[1:])
            if stream is not None:
                stream.push(raw, address, 0, origin)
                matched = True
        else:
            for stream in self.streams.values():
                idx = stream.match(address)
                if idx is not None:
                    stream.push(raw, address, idx, origin)
                    matched = True
        if not matched:
            self._note_unrouted(address, raw, origin)
        return matched

    def _note_unrouted(self, address: str, raw: Any, origin: str) -> None:
        entry = self.unrouted.pop(address, {"count": 0})
        entry.update(count=entry["count"] + 1, origin=origin, at=time.monotonic(),
                     sample=_preview(raw))
        self.unrouted[address] = entry
        while len(self.unrouted) > 20:
            self.unrouted.popitem(last=False)

    def inject(self, stream_name: str, data: Any) -> bool:
        """Feed test data from the dashboard."""
        stream = self.streams.get(stream_name)
        if stream is None:
            return False
        stream.push(data, "@" + stream_name, 0, "dashboard")
        return True

    def set_armed(self, armed: bool) -> None:
        self.armed = bool(armed)
        log.warning("hardware outputs %s", "ARMED" if armed else "DISARMED (holding last position)")

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        for out in self.outputs.values():
            await out.start()
        for stream in self.streams.values():
            stream.start()
        for inp in self.inputs.values():
            await inp.start()

    async def stop(self) -> None:
        for inp in self.inputs.values():
            await inp.stop()
        for stream in self.streams.values():
            await stream.stop()
        for out in self.outputs.values():
            await out.stop()

    # -------------------------------------------------------------- dashboard
    def snapshot(self) -> dict:
        now = time.monotonic()
        return {
            "armed": self.armed,
            "uptime": round(time.time() - self.started_at),
            "config_path": self.cfg.get("_path"),
            "inputs": {k: i.snapshot() for k, i in self.inputs.items()},
            "outputs": {k: o.snapshot() for k, o in self.outputs.items()},
            "streams": {k: s.snapshot() for k, s in self.streams.items()},
            "unrouted": [
                {"address": a, "count": e["count"], "origin": e["origin"],
                 "ago": round(now - e["at"], 1), "sample": e["sample"]}
                for a, e in reversed(self.unrouted.items())
            ],
        }


def _preview(raw: Any) -> str:
    text = repr(raw)
    return text if len(text) <= 80 else text[:77] + "..."
