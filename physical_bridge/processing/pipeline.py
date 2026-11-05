"""A pipeline is an ordered list of steps run on every frame of a stream."""
from __future__ import annotations

from ..frame import Frame
from .steps import Context, Limits, Step, build_step


class Pipeline:
    def __init__(self, steps: list[Step], tick_hz: float = 60.0, max_dt: float = 0.1):
        self.steps = steps
        self.nominal_dt = 1.0 / tick_hz
        self.max_dt = max_dt
        self._last_run: float | None = None
        self._was_settled = True
        # the leading run of static steps is cached per input frame
        n = 0
        while n < len(steps) and not steps[n].dynamic and steps[n].name != "rate_limit":
            n += 1
        self._prefix = n
        self._cache_key: Frame | None = None
        self._cache_val: Frame | None = None

    @classmethod
    def from_config(cls, specs: list, safety: dict | None = None, tick_hz: float = 60.0) -> "Pipeline":
        steps = [build_step(s) for s in (specs or [])]
        if safety:
            # stream-level safety limits always run last and cannot be bypassed
            steps.append(Limits(**safety))
        return cls(steps, tick_hz)

    @property
    def settled(self) -> bool:
        return all(s.settled for s in self.steps)

    @property
    def dynamic(self) -> bool:
        return any(s.dynamic or s.name == "rate_limit" for s in self.steps)

    def reset(self) -> None:
        for s in self.steps:
            s.reset()
        self._last_run = None
        self._cache_key = self._cache_val = None

    def run(self, frame: Frame, now: float) -> tuple[Frame, bool]:
        """Run all steps.  Returns ``(frame, emit)``; ``emit`` is False when a
        rate limiter asked to hold this frame back."""
        if self._last_run is None or self._was_settled:
            dt = self.nominal_dt
        else:
            dt = min(max(now - self._last_run, 0.0), self.max_dt)
        self._last_run = now
        ctx = Context(now=now, dt=dt)

        if frame is self._cache_key and self._cache_val is not None:
            out = self._cache_val
        else:
            out = frame
            for step in self.steps[: self._prefix]:
                out = step(out, ctx)
            self._cache_key, self._cache_val = frame, out
        for step in self.steps[self._prefix:]:
            out = step(out, ctx)
        self._was_settled = self.settled
        return out, not ctx.suppress
