"""MIDI input via mido (+ python-rtmidi backend).

Messages become addresses (channels are 1-16)::

    control_change  -> /midi/cc/<channel>/<control>     value
    note_on/off     -> /midi/note/<channel>/<note>       velocity (0 on note off)
    pitchwheel      -> /midi/pitchbend/<channel>         -8192..8191 (or -1..1)

With ``normalize: true`` (default) CC and velocity are scaled to 0..1, so a
``map: {in: [0, 1], out: [0, 180]}`` step works for MIDI, TouchDesigner and
Blender alike.
"""
from __future__ import annotations

import asyncio
import logging

from .base import Input

log = logging.getLogger(__name__)


def midi_to_address(msg, normalize: bool = True) -> tuple[str, float] | None:
    t = msg.type
    ch = getattr(msg, "channel", 0) + 1
    if t == "control_change":
        v = msg.value / 127.0 if normalize else float(msg.value)
        return f"/midi/cc/{ch}/{msg.control}", v
    if t in ("note_on", "note_off"):
        vel = 0 if t == "note_off" else msg.velocity
        return f"/midi/note/{ch}/{msg.note}", (vel / 127.0 if normalize else float(vel))
    if t == "pitchwheel":
        return f"/midi/pitchbend/{ch}", (msg.pitch / 8192.0 if normalize else float(msg.pitch))
    return None


class MIDIInput(Input):
    """Config: ``port`` (name or substring; null = first available),
    ``virtual`` (create a virtual port named 'Physical Bridge' - macOS/Linux),
    ``normalize`` (true)."""
    type_name = "midi"

    def __init__(self, cfg, dispatch):
        super().__init__(cfg, dispatch)
        self.port = None
        self.normalize = bool(cfg.get("normalize", True))
        self._loop = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            import mido
        except ImportError:
            self.last_error = "mido is not installed: pip install mido python-rtmidi"
            log.error(self.last_error)
            return
        try:
            if self.cfg.get("virtual"):
                self.port = mido.open_input("Physical Bridge", virtual=True, callback=self._callback)
            else:
                names = mido.get_input_names()
                wanted = self.cfg.get("port")
                match = [n for n in names if wanted is None or wanted.lower() in n.lower()]
                if not match:
                    raise RuntimeError(f"no MIDI input matching {wanted!r} (available: {names})")
                self.port = mido.open_input(match[0], callback=self._callback)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"cannot open MIDI input: {exc}"
            log.error(self.last_error)
            return
        self.listening = True
        self.detail = self.port.name
        log.info("MIDI input listening on %s", self.detail)

    def _callback(self, msg) -> None:  # called from the MIDI thread
        if self._loop:
            self._loop.call_soon_threadsafe(self.handle_message, msg)

    def handle_message(self, msg) -> None:
        mapped = midi_to_address(msg, self.normalize)
        if mapped:
            self.dispatch(*mapped)

    async def stop(self) -> None:
        if self.port is not None:
            self.port.close()
        self.listening = False
