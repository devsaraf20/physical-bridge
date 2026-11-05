"""Easing curves: functions mapping progress t in [0, 1] to [0, 1]."""
from __future__ import annotations

import math
from typing import Callable

EASINGS: dict[str, Callable[[float], float]] = {
    "linear": lambda t: t,
    "ease_in": lambda t: t * t,
    "ease_out": lambda t: 1 - (1 - t) * (1 - t),
    "ease_in_out": lambda t: 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2,
    "cubic_in": lambda t: t ** 3,
    "cubic_out": lambda t: 1 - (1 - t) ** 3,
    "cubic_in_out": lambda t: 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2,
    "sine_in_out": lambda t: -(math.cos(math.pi * t) - 1) / 2,
    "smoothstep": lambda t: t * t * (3 - 2 * t),
}


def get_easing(name: str) -> Callable[[float], float]:
    try:
        return EASINGS[name]
    except KeyError:
        raise ValueError(f"unknown easing {name!r}; choose from {sorted(EASINGS)}") from None
