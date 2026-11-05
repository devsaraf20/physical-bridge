"""Streams: turn raw input messages into frames, process them, fan them out."""
from __future__ import annotations

import asyncio
import fnmatch
import logging
import math
import time
from collections import deque
from typing import TYPE_CHECKING, Any

import numpy as np

from .frame import Frame, frames_equal
from .processing import Pipeline

if TYPE_CHECKING:
    from .outputs.base import Output

log = logging.getLogger(__name__)


class InputError(ValueError):
    pass


# ------------------------------------------------------------------ coercion


def _flatten(raw: Any) -> list:
    if isinstance(raw, (list, tuple)):
        out: list = []
        for r in raw:
            out.extend(_flatten(r))
        return out
    if isinstance(raw, np.ndarray):
        return raw.ravel().tolist()
    return [raw]


def _numbers(values: list) -> list[float]:
    out = []
    for v in values:
        if isinstance(v, bool):
            out.append(float(v))
        elif isinstance(v, (int, float, np.number)):
            out.append(float(v))
        elif isinstance(v, str):
            try:
                out.append(float(v))
            except ValueError:
                raise InputError(f"not a number: {v!r}") from None
        elif v is None:
            continue
        else:
            raise InputError(f"unexpected value {type(v).__name__}")
    return out


def coerce_2d(raw: Any, input_size: list | None) -> np.ndarray:
    """Accepts a nested 2D list, ``{w, h, data}``, ``[w, h, v...]``,
    ``[w, h, blob]``, a blob, or a flat list (with ``input_size`` or square)."""
    w = h = None
    if isinstance(raw, dict):
        w = raw.get("w", raw.get("width"))
        h = raw.get("h", raw.get("height"))
        raw = raw.get("data", [])
    if isinstance(raw, np.ndarray) and raw.ndim == 2:
        return raw.astype(np.float32)
    if isinstance(raw, (list, tuple)) and raw and all(isinstance(r, (list, tuple)) for r in raw):
        rows = [_numbers(r) for r in raw]
        if len({len(r) for r in rows}) != 1:
            raise InputError("rows of the 2D list have different lengths")
        return np.asarray(rows, dtype=np.float32)

    if isinstance(raw, (bytes, bytearray)):
        values = list(raw)
    else:
        items = list(raw) if isinstance(raw, (list, tuple)) else [raw]
        blob = next((x for x in items if isinstance(x, (bytes, bytearray))), None)
        if blob is not None:
            ints = [x for x in items[: items.index(blob)] if isinstance(x, (int, float))]
            if len(ints) >= 2 and w is None:
                w, h = int(ints[0]), int(ints[1])
            values = list(blob)
        else:
            values = _numbers(_flatten(items))

    if w is None and input_size:
        w, h = int(input_size[0]), int(input_size[1])
    if w is None and len(values) >= 3:
        cw, ch = values[0], values[1]
        if float(cw).is_integer() and float(ch).is_integer() and cw > 0 and ch > 0 \
                and len(values) == 2 + int(cw) * int(ch):
            w, h = int(cw), int(ch)
            values = values[2:]
    if w is None:
        side = int(round(math.sqrt(len(values))))
        if side * side != len(values) or side == 0:
            raise InputError(f"cannot infer grid size from {len(values)} values; "
                             "send [w, h, ...] or set input_size in the stream config")
        w = h = side
    if w * h != len(values):
        raise InputError(f"expected {w}x{h}={w * h} values, got {len(values)}")
    return np.asarray(values, dtype=np.float32).reshape(h, w)


def coerce(kind: str, raw: Any, cfg: dict) -> Any:
    rng = cfg.get("input_range")
    if kind == "value":
        nums = _numbers(_flatten(raw.get("data") if isinstance(raw, dict) else raw))
        if not nums:
            raise InputError("no numeric value in message")
        return nums[0]
    if kind == "angles":
        nums = _numbers(_flatten(raw.get("data") if isinstance(raw, dict) else raw))
        if not nums:
            raise InputError("no values in message")
        return np.asarray(nums, dtype=np.float32)
    grid = coerce_2d(raw, cfg.get("input_size"))
    if grid.shape[0] > 1024 or grid.shape[1] > 1024:
        raise InputError("input grid larger than 1024x1024")
    if kind == "grid":
        lo, hi = rng if rng else (0.0, 255.0)
        if (lo, hi) != (0.0, 255.0):
            grid = (grid - lo) / (hi - lo) * 255.0
        return np.clip(grid, 0, 255).astype(np.float32)
    # bits
    if rng:
        return (grid >= (rng[0] + rng[1]) / 2).astype(np.uint8)
    return (grid > 0).astype(np.uint8)


# -------------------------------------------------------------------- stream


class RateMeter:
    def __init__(self, window: float = 2.0):
        self.window = window
        self.times: deque[float] = deque()

    def mark(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.times.append(now)
        self._trim(now)

    def _trim(self, now: float) -> None:
        while self.times and now - self.times[0] > self.window:
            self.times.popleft()

    @property
    def rate(self) -> float:
        self._trim(time.monotonic())
        return len(self.times) / self.window


class Stream:
    def __init__(self, name: str, cfg: dict, outputs: list[tuple["Output", dict]],
                 tick_hz: float = 60.0, bridge=None):
        self.name = name
        self.cfg = cfg
        self.kind: str = cfg["type"]
        src = cfg["source"]
        self.sources: list[str] = src if isinstance(src, list) else [src]
        self.multi = isinstance(src, list)
        self.pipeline = Pipeline.from_config(cfg.get("pipeline"), cfg.get("safety"), tick_hz)
        self.outputs = outputs
        self.tick = 1.0 / tick_hz
        self.keepalive = float(cfg.get("keepalive", 0) or 0)
        self.bridge = bridge
        self.input: Frame | None = None
        self.output: Frame | None = None
        self.last_sent: Frame | None = None
        self.last_sent_at = 0.0
        self.error: str | None = None
        self.in_rate = RateMeter()
        self.out_rate = RateMeter()
        self._multi_values: list[float] = []
        self._event = asyncio.Event()
        self._task: asyncio.Task | None = None

    # -- routing ---------------------------------------------------------
    def match(self, address: str) -> int | None:
        """Return the source index matching ``address`` or None."""
        for i, pattern in enumerate(self.sources):
            if address == pattern or (any(c in pattern for c in "*?[") and fnmatch.fnmatchcase(address, pattern)):
                return i
        return None

    def push(self, raw: Any, address: str = "", index: int = 0, origin: str = "") -> None:
        try:
            if self.multi:
                value = coerce("value", raw, self.cfg)
                if len(self._multi_values) < len(self.sources):
                    self._multi_values += [0.0] * (len(self.sources) - len(self._multi_values))
                self._multi_values[index] = value
                data = np.asarray(self._multi_values, dtype=np.float32)
            else:
                data = coerce(self.kind, raw, self.cfg)
        except Exception as exc:  # noqa: BLE001 - report any bad input to the dashboard
            self.error = f"bad input from {origin or '?'} {address}: {exc}"
            log.warning("stream %s: %s", self.name, self.error)
            return
        self.input = Frame(self.kind, data, source=origin or address)
        self.in_rate.mark()
        self._event.set()

    # -- processing loop -------------------------------------------------
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"stream:{self.name}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            busy = self.input is not None and not self.pipeline.settled
            timeout = self.tick if busy else (self.keepalive or None)
            try:
                if timeout is None:
                    await self._event.wait()
                else:
                    await asyncio.wait_for(self._event.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            self._event.clear()
            self.step(time.monotonic())

    def step(self, now: float) -> Frame | None:
        """Run the pipeline once and send the result if it changed."""
        if self.input is None:
            return None
        try:
            out, emit = self.pipeline.run(self.input, now)
        except Exception as exc:  # noqa: BLE001
            self.error = f"processing error: {exc}"
            log.warning("stream %s: %s", self.name, self.error)
            self.input = None
            self.pipeline.reset()
            return None
        self.output = out
        if not emit:
            return None
        due = self.keepalive and now - self.last_sent_at >= self.keepalive
        if frames_equal(out, self.last_sent) and not due:
            return None
        self.last_sent, self.last_sent_at = out, now
        self.out_rate.mark(now)
        self.error = None
        for output, ref in self.outputs:
            if self.bridge is not None and not self.bridge.armed and output.physical:
                continue
            output.submit(self, out, ref)
        return out

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "sources": self.sources,
            "pipeline": [s.name for s in self.pipeline.steps],
            "outputs": [ref["name"] for _, ref in self.outputs],
            "input": self.input.to_json() if self.input is not None else None,
            "output": self.output.to_json() if self.output is not None else None,
            "in_rate": round(self.in_rate.rate, 1),
            "out_rate": round(self.out_rate.rate, 1),
            "settled": self.pipeline.settled,
            "input_range": self.cfg.get("input_range"),
            "error": self.error,
        }
