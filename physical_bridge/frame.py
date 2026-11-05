"""The data model that flows through the bridge.

A :class:`Frame` is one snapshot of a stream.  There are four kinds:

``bits``    2D numpy ``uint8`` array of 0/1            (LED matrix on/off, flip dots)
``grid``    2D numpy ``float32`` array in 0..255        (greyscale / brightness maps)
``angles``  1D numpy ``float32`` array, degrees         (servos, steppers)
``value``   python ``float``                            (a single dimmer, a speed, ...)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

KINDS = ("bits", "grid", "angles", "value")


@dataclass
class Frame:
    kind: str
    data: Any
    source: str = ""
    ts: float = field(default_factory=time.monotonic)

    def copy(self, **changes) -> "Frame":
        data = changes.pop("data", self.data)
        if isinstance(data, np.ndarray) and "data" not in changes:
            data = data.copy()
        return Frame(changes.pop("kind", self.kind), data,
                     changes.pop("source", self.source), changes.pop("ts", self.ts))

    def to_json(self) -> dict:
        """Compact JSON-safe representation used by the dashboard."""
        d = self.data
        if self.kind == "value":
            return {"kind": "value", "data": round(float(d), 4)}
        if self.kind == "angles":
            return {"kind": "angles", "data": [round(float(x), 3) for x in np.ravel(d)]}
        arr = np.asarray(d)
        h, w = arr.shape
        if self.kind == "bits":
            flat = "".join("1" if v else "0" for v in (arr > 0).ravel())
        else:
            flat = np.clip(np.rint(arr), 0, 255).astype(np.uint8).tobytes().hex()
        return {"kind": self.kind, "w": int(w), "h": int(h), "data": flat}


def frames_equal(a: Frame | None, b: Frame | None) -> bool:
    if a is None or b is None or a.kind != b.kind:
        return False
    if a.kind == "value":
        return float(a.data) == float(b.data)
    x, y = np.asarray(a.data), np.asarray(b.data)
    return x.shape == y.shape and bool(np.array_equal(x, y))
