"""Processing steps.

Every step takes a :class:`Frame` and returns a (possibly new) frame.  Steps
are configured from YAML as ``- name: {params}`` (or just ``- name``).

*Static* steps (resize, threshold, map, ...) are pure functions of their
input.  *Dynamic* steps (smooth, ease, limits) keep internal state and keep
producing new frames over time until they have ``settled`` on their target;
the stream calls the pipeline on every tick while any step is unsettled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from ..frame import Frame
from . import grid as G
from .easing import get_easing

STEPS: dict[str, type["Step"]] = {}


class ConfigError(ValueError):
    pass


def register(name: str) -> Callable[[type["Step"]], type["Step"]]:
    def deco(cls):
        cls.name = name
        STEPS[name] = cls
        return cls
    return deco


@dataclass
class Context:
    now: float
    dt: float
    suppress: bool = False  # set by rate_limit: run steps but do not emit


class Step:
    name = "step"
    kinds: tuple[str, ...] = ("bits", "grid", "angles", "value")
    dynamic = False

    def __init__(self, **params: Any):
        self.params = params

    @property
    def settled(self) -> bool:
        return True

    def reset(self) -> None:
        pass

    def check(self, frame: Frame) -> None:
        if frame.kind not in self.kinds:
            raise ConfigError(f"step '{self.name}' cannot process '{frame.kind}' frames "
                              f"(accepts: {', '.join(self.kinds)})")

    def __call__(self, frame: Frame, ctx: Context) -> Frame:
        self.check(frame)
        return self.process(frame, ctx)

    def process(self, frame: Frame, ctx: Context) -> Frame:  # pragma: no cover
        raise NotImplementedError


def _as_grid(frame: Frame) -> np.ndarray:
    a = np.asarray(frame.data, dtype=np.float32)
    return a * 255.0 if frame.kind == "bits" else a


def _numeric(frame: Frame) -> np.ndarray:
    if frame.kind == "bits":
        return np.asarray(frame.data, dtype=np.float64) * 255.0
    return np.asarray(frame.data, dtype=np.float64)


def _wrap(frame: Frame, arr: np.ndarray) -> Frame:
    """Put a float array back into a frame of the matching kind."""
    if frame.kind == "value":
        return frame.copy(data=float(arr))
    if frame.kind == "angles":
        return frame.copy(data=arr.astype(np.float32).ravel())
    # bits that went through numeric processing become a grid
    return frame.copy(kind="grid", data=arr.astype(np.float32))


def _param_array(value, name: str) -> np.ndarray | None:
    if value is None:
        return None
    try:
        return np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        raise ConfigError(f"'{name}' must be a number or a list of numbers") from None


# ===================================================================== grid


@register("resize")
class Resize(Step):
    """``resize: {width: 16, height: 16, mode: area|nearest|bilinear}``"""
    kinds = ("bits", "grid")

    def __init__(self, width: int, height: int, mode: str = "area"):
        super().__init__()
        if mode not in ("area", "nearest", "bilinear"):
            raise ConfigError(f"resize mode must be area, nearest or bilinear (got {mode!r})")
        if not (0 < int(width) <= 255 and 0 < int(height) <= 255):
            raise ConfigError("resize width/height must be 1-255")
        self.w, self.h, self.mode = int(width), int(height), mode

    def process(self, frame, ctx):
        out = G.resize(_as_grid(frame), self.w, self.h, self.mode)
        if frame.kind == "bits":
            return frame.copy(data=(out >= 127.5).astype(np.uint8))
        return frame.copy(data=out)


@register("threshold")
class Threshold(Step):
    """``threshold: {level: 128, invert: false}`` -> converts a grid to bits."""
    kinds = ("grid", "bits")

    def __init__(self, level: float = 128, invert: bool = False):
        super().__init__()
        self.level, self.invert = float(level), bool(invert)

    def process(self, frame, ctx):
        bits = _as_grid(frame) >= self.level
        if self.invert:
            bits = ~bits
        return frame.copy(kind="bits", data=bits.astype(np.uint8))


@register("dither")
class Dither(Step):
    """``dither: {method: floyd_steinberg|atkinson|bayer, levels: 2, size: 4}``

    ``levels: 2`` produces bits.  More levels produce a quantised grid (e.g.
    ``levels: 4`` for a 2-bit greyscale display)."""
    kinds = ("grid", "bits")

    def __init__(self, method: str = "floyd_steinberg", levels: int = 2, size: int = 4):
        super().__init__()
        if method not in G.DITHER_METHODS:
            raise ConfigError(f"dither method must be one of {G.DITHER_METHODS}")
        if int(levels) < 2:
            raise ConfigError("dither levels must be >= 2")
        if size not in (2, 4, 8, 16):
            raise ConfigError("bayer size must be 2, 4, 8 or 16")
        self.method, self.levels, self.size = method, int(levels), int(size)

    def process(self, frame, ctx):
        out = G.dither(_as_grid(frame), self.method, self.levels, self.size)
        if self.levels == 2:
            return frame.copy(kind="bits", data=(out > 127).astype(np.uint8))
        return frame.copy(kind="grid", data=out)


@register("invert")
class Invert(Step):
    kinds = ("grid", "bits")

    def process(self, frame, ctx):
        if frame.kind == "bits":
            return frame.copy(data=(1 - np.asarray(frame.data)).astype(np.uint8))
        return frame.copy(data=255.0 - np.asarray(frame.data, np.float32))


@register("gamma")
class Gamma(Step):
    """``gamma: {value: 2.2}`` - perceptual brightness correction for LEDs."""
    kinds = ("grid",)

    def __init__(self, value: float = 2.2):
        super().__init__()
        if value <= 0:
            raise ConfigError("gamma value must be > 0")
        self.value = float(value)

    def process(self, frame, ctx):
        g = np.clip(np.asarray(frame.data, np.float32), 0, 255) / 255.0
        return frame.copy(data=(g ** self.value * 255.0).astype(np.float32))


@register("flip")
class Flip(Step):
    """``flip: {horizontal: true, vertical: false, rotate: 0|90|180|270}``"""
    kinds = ("grid", "bits")

    def __init__(self, horizontal: bool = False, vertical: bool = False, rotate: int = 0):
        super().__init__()
        if rotate % 90:
            raise ConfigError("flip.rotate must be a multiple of 90")
        self.h, self.v, self.k = bool(horizontal), bool(vertical), (int(rotate) // 90) % 4

    def process(self, frame, ctx):
        a = np.asarray(frame.data)
        if self.h:
            a = a[:, ::-1]
        if self.v:
            a = a[::-1, :]
        if self.k:
            a = np.rot90(a, -self.k)  # clockwise
        return frame.copy(data=np.ascontiguousarray(a))


# ================================================================== numeric


@register("map")
class Map(Step):
    """``map: {in: [0, 1], out: [0, 180], clamp: true}``

    ``in`` / ``out`` may also be a list of ranges, one per element, e.g.
    ``out: [[0, 180], [30, 150]]`` for two servos with different travel."""
    kinds = ("grid", "angles", "value")

    def __init__(self, out, clamp: bool = True, **kw):
        super().__init__()
        src = kw.pop("in", kw.pop("in_", [0, 1]))
        if kw:
            raise ConfigError(f"unknown map parameters: {', '.join(kw)}")
        self.src = _param_array(src, "map.in")
        self.dst = _param_array(out, "map.out")
        for arr, label in ((self.src, "in"), (self.dst, "out")):
            if arr.shape[-1:] != (2,) or arr.ndim > 2:
                raise ConfigError(f"map.{label} must be [low, high] or a list of them")
        if np.any(self.src[..., 1] == self.src[..., 0]):
            raise ConfigError("map.in low and high must differ")
        self.clamp = bool(clamp)

    def process(self, frame, ctx):
        x = _numeric(frame)
        lo_i, hi_i = self.src[..., 0], self.src[..., 1]
        lo_o, hi_o = self.dst[..., 0], self.dst[..., 1]
        try:
            t = (x - lo_i) / (hi_i - lo_i)
            if self.clamp:
                t = np.clip(t, 0, 1)
            return _wrap(frame, lo_o + t * (hi_o - lo_o))
        except ValueError:
            raise ConfigError(f"map has {self.src.shape[0] if self.src.ndim > 1 else 1} ranges "
                              f"but frame has {x.size} values") from None


@register("deadband")
class Deadband(Step):
    """``deadband: {threshold: 1.0}`` - ignore changes smaller than threshold
    (stops servo jitter from noisy sensors / tracking)."""
    kinds = ("grid", "angles", "value")

    def __init__(self, threshold: float = 1.0):
        super().__init__()
        self.threshold = float(threshold)
        self.held: np.ndarray | None = None

    def reset(self):
        self.held = None

    def process(self, frame, ctx):
        x = _numeric(frame)
        if self.held is None or self.held.shape != x.shape:
            self.held = x.copy()
        else:
            moved = np.abs(x - self.held) >= self.threshold
            self.held = np.where(moved, x, self.held)
        return _wrap(frame, self.held.copy())


class _Dynamic(Step):
    dynamic = True
    kinds = ("grid", "angles", "value", "bits")

    def __init__(self, **params):
        super().__init__(**params)
        self.state: np.ndarray | None = None
        self._settled = True

    @property
    def settled(self) -> bool:
        return self._settled

    def reset(self):
        self.state = None
        self._settled = True


@register("smooth")
class Smooth(_Dynamic):
    """Exponential smoothing.  ``smooth: {time: 0.2}`` (seconds to cover ~63%
    of a change, frame-rate independent) or ``smooth: {alpha: 0.2}`` (fraction
    per tick)."""

    def __init__(self, time: float | None = None, alpha: float | None = None,
                 epsilon: float = 0.01):
        super().__init__()
        if time is None and alpha is None:
            time = 0.15
        if alpha is not None and not 0 < alpha <= 1:
            raise ConfigError("smooth.alpha must be in (0, 1]")
        if time is not None and time < 0:
            raise ConfigError("smooth.time must be >= 0")
        self.time, self.alpha, self.eps = time, alpha, float(epsilon)

    def process(self, frame, ctx):
        target = _numeric(frame)
        if self.state is None or self.state.shape != target.shape:
            self.state = target.copy()
        else:
            if self.alpha is not None:
                k = self.alpha
            else:
                k = 1.0 if self.time == 0 else 1 - math.exp(-ctx.dt / self.time)
            self.state += (target - self.state) * k
            done = np.abs(target - self.state) < self.eps
            self.state = np.where(done, target, self.state)
        self._settled = bool(np.all(self.state == target))
        return _wrap(frame, self.state.copy())


@register("ease")
class Ease(_Dynamic):
    """``ease: {duration: 0.5, curve: ease_in_out}`` - whenever the target
    changes, glide from the current value to the new target over ``duration``
    seconds following an easing curve."""

    def __init__(self, duration: float = 0.5, curve: str = "ease_in_out"):
        super().__init__()
        try:
            self.curve = get_easing(curve)
        except ValueError as exc:
            raise ConfigError(str(exc)) from None
        if duration < 0:
            raise ConfigError("ease.duration must be >= 0")
        self.duration = float(duration)
        self.start = self.target = None
        self.t = 1.0

    def reset(self):
        super().reset()
        self.start = self.target = None
        self.t = 1.0

    def process(self, frame, ctx):
        target = _numeric(frame)
        if self.state is None or self.state.shape != target.shape:
            self.state, self.start, self.target, self.t = target.copy(), target.copy(), target.copy(), 1.0
        elif not np.array_equal(target, self.target):
            self.start, self.target, self.t = self.state.copy(), target.copy(), 0.0
        else:
            self.t = 1.0 if self.duration == 0 else min(1.0, self.t + ctx.dt / self.duration)
        if self.duration == 0:
            self.t = 1.0
        e = self.curve(self.t)
        self.state = self.start + (self.target - self.start) * e
        if self.t >= 1.0:
            self.state = self.target.copy()
        self._settled = self.t >= 1.0
        return _wrap(frame, self.state.copy())


@register("limits")
class Limits(_Dynamic):
    """Safety limits.  ``limits: {min: 0, max: 180, max_speed: 90, max_mean: 60}``

    * ``min`` / ``max``   clamp every value (lists allowed: one per motor)
    * ``max_speed``       units per second (deg/s for angles); motion towards
                          the target is capped so a motor never jumps
    * ``max_mean``        grids only: scale the whole frame down so the
                          average brightness never exceeds this (LED power budget)
    """
    kinds = ("grid", "angles", "value")

    def __init__(self, min=None, max=None, max_speed=None, max_mean=None):  # noqa: A002
        super().__init__()
        self.lo = _param_array(min, "limits.min")
        self.hi = _param_array(max, "limits.max")
        self.speed = _param_array(max_speed, "limits.max_speed")
        if self.speed is not None and np.any(self.speed <= 0):
            raise ConfigError("limits.max_speed must be > 0")
        if self.lo is not None and self.hi is not None and np.any(self.lo > self.hi):
            raise ConfigError("limits.min must be <= limits.max")
        self.max_mean = None if max_mean is None else float(max_mean)

    def clamp(self, x: np.ndarray) -> np.ndarray:
        if self.lo is not None:
            x = np.maximum(x, self.lo)
        if self.hi is not None:
            x = np.minimum(x, self.hi)
        return x

    def process(self, frame, ctx):
        try:
            target = self.clamp(_numeric(frame))
        except ValueError:
            raise ConfigError("limits min/max list length does not match the frame") from None
        if self.max_mean is not None and frame.kind == "grid":
            mean = float(target.mean()) if target.size else 0.0
            if mean > self.max_mean:
                target = target * (self.max_mean / mean)
        if self.speed is None:
            self.state = target
            self._settled = True
            return _wrap(frame, target.copy())
        if self.state is None or self.state.shape != target.shape:
            # first frame ever: we do not know where the motor is, start at the target
            self.state = target.copy()
        else:
            step = self.speed * ctx.dt
            self.state = self.state + np.clip(target - self.state, -step, step)
        self._settled = bool(np.allclose(self.state, target, atol=1e-6))
        if self._settled:
            self.state = target.copy()
        return _wrap(frame, self.state.copy())


@register("rate_limit")
class RateLimit(Step):
    """``rate_limit: {hz: 30}`` - emit at most ``hz`` frames per second.
    Frames in between are not dropped silently: the most recent state is sent
    as soon as the interval has elapsed."""

    def __init__(self, hz: float = 30):
        super().__init__()
        if hz <= 0:
            raise ConfigError("rate_limit.hz must be > 0")
        self.interval = 1.0 / float(hz)
        self.last = -math.inf
        self.pending = False

    @property
    def settled(self):
        return not self.pending

    def reset(self):
        self.last, self.pending = -math.inf, False

    def process(self, frame, ctx):
        if ctx.now - self.last + 1e-9 < self.interval:
            self.pending = True
            ctx.suppress = True
        else:
            self.last, self.pending = ctx.now, False
        return frame


def build_step(spec) -> Step:
    """Build a step from ``"name"`` or ``{"name": {params}}``."""
    if isinstance(spec, str):
        name, params = spec, {}
    elif isinstance(spec, dict) and len(spec) == 1:
        name, params = next(iter(spec.items()))
        params = params or {}
        if not isinstance(params, dict):
            raise ConfigError(f"parameters of step '{name}' must be a mapping")
    else:
        raise ConfigError(f"invalid pipeline step {spec!r}; use '- name: {{...}}'")
    cls = STEPS.get(name)
    if cls is None:
        raise ConfigError(f"unknown processing step '{name}'. Available: {', '.join(sorted(STEPS))}")
    try:
        return cls(**params)
    except TypeError as exc:
        raise ConfigError(f"step '{name}': {exc}") from None
