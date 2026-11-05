"""Template for your own output plugin.

Enable it in the YAML config (path is relative to the config file):

    bridge:
      plugins: [../plugins/console_output.py]     # or an importable module name
    outputs:
      console:
        type: console
        every: 10          # print every 10th frame

Copy this file to support new hardware: DMX, a motor controller's own
protocol, an HTTP API, a database logger ...
"""
import numpy as np

from physical_bridge.outputs import Output, register_output


@register_output("console")
class ConsoleOutput(Output):
    physical = True          # False = keeps running while the bridge is DISARMED

    def __init__(self, name, cfg):
        super().__init__(name, cfg)              # handles queueing, stats, max_fps
        self.every = int(cfg.get("every", 1))
        self.count = 0

    async def start(self):
        # open sockets / ports here; set self.connected and self.detail for the dashboard
        self.connected = True
        self.detail = "stdout"
        await super().start()

    async def send(self, stream_name, frame, ref):
        """Called with the newest processed frame. ``ref`` holds per-stream
        options from the stream's ``outputs:`` entry (e.g. ``address``)."""
        self.count += 1
        if self.count % self.every == 0:
            if frame.kind in ("bits", "grid"):
                desc = f"{frame.kind} {np.asarray(frame.data).shape[1]}x{np.asarray(frame.data).shape[0]}"
            else:
                desc = f"{frame.kind} {np.round(frame.data, 2).tolist() if frame.kind == 'angles' else round(frame.data, 2)}"
            print(f"[{self.name}] {stream_name}: {desc}")
        return 0                                  # bytes written (for the dashboard)

    async def close(self):
        self.connected = False
