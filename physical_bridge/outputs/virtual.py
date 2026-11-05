"""A virtual device rendered in the dashboard.

It encodes every frame with the real wire protocol and decodes it again, so
what you see is exactly what a microcontroller would receive.  It also tells
you how much of a serial link the stream would use."""
from __future__ import annotations

from ..frame import Frame
from ..stream import RateMeter
from ..protocol import BROADCAST, FrameParser, encode_data_frame
from .base import Output, register_output


@register_output("virtual")
class VirtualOutput(Output):
    """Config keys: ``display`` (auto | matrix | servos | meter),
    ``baud`` (link speed used for the bandwidth estimate, default 115200),
    ``led_color`` (CSS colour for matrix pixels)."""
    physical = False

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.display = cfg.get("display", "auto")
        self.baud = int(cfg.get("baud", 115200))
        self.color = cfg.get("led_color", "#ff4d2e")
        self.devices: dict[str, dict] = {}

    async def start(self) -> None:
        self.connected = True
        self.detail = "dashboard"
        await super().start()

    async def send(self, stream_name: str, frame: Frame, ref: dict) -> int:
        packet = encode_data_frame(frame.kind, frame.data, int(ref.get("address", BROADCAST)))
        pkts = list(FrameParser().feed(packet))
        decoded = Frame(frame.kind, pkts[0].decode())
        meter = self.devices.get(stream_name, {}).get("_rate") or RateMeter()
        meter.mark()
        self.devices[stream_name] = {
            "_rate": meter,
            "frame": decoded.to_json(),
            "packet_bytes": len(packet),
            "packet_hex": packet[:24].hex(" ") + (" ..." if len(packet) > 24 else ""),
        }
        return len(packet)

    def snapshot(self) -> dict:
        snap = super().snapshot()
        devs = {}
        for name, d in self.devices.items():
            fps = d["_rate"].rate
            load = d["packet_bytes"] * 10 * fps / self.baud * 100 if self.baud else 0
            info = {k: v for k, v in d.items() if not k.startswith("_")}
            devs[name] = {**info, "fps": round(fps, 1), "link_load": round(load, 1)}
        snap.update(display=self.display, baud=self.baud, color=self.color, devices=devs)
        return snap
