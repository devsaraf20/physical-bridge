"""Serial output (USB serial to Arduino / ESP32) and RS485 bus output.

Uses pyserial's ``serial_for_url`` so ``port`` may be a device
(``/dev/ttyUSB0``, ``COM3``), ``auto`` (first USB serial device found), or a
pyserial URL such as ``socket://192.168.1.50:3333`` (ESP32 over Wi-Fi) or
``loop://`` (testing).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque

from ..frame import Frame
from ..protocol import BROADCAST, FrameParser, MsgType, encode_data_frame, encode_frame
from .base import Output, register_output

log = logging.getLogger(__name__)


def _serial_module():
    try:
        import serial  # noqa: F401
        import serial.tools.list_ports  # noqa: F401
    except ImportError:  # pragma: no cover - depends on environment
        raise RuntimeError("pyserial is not installed: pip install pyserial") from None
    return serial


def list_serial_ports() -> list[dict]:
    serial = _serial_module()
    return [{"device": p.device, "description": p.description, "vid": p.vid, "pid": p.pid}
            for p in serial.tools.list_ports.comports()]


def find_auto_port() -> str | None:
    usb = [p for p in list_serial_ports() if p["vid"] is not None]
    return usb[0]["device"] if usb else None


@register_output("serial")
class SerialOutput(Output):
    """Config keys: ``port``, ``baud`` (115200), ``address`` (255 = broadcast),
    ``boot_wait`` (s to wait for the board to reset, default 2),
    ``ping_interval`` (s, default 1, 0 = off), ``reconnect`` (s, default 2),
    ``max_fps``."""

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.port = str(cfg["port"])
        self.baud = int(cfg.get("baud", 115200))
        self.address = int(cfg.get("address", BROADCAST))
        self.boot_wait = float(cfg.get("boot_wait", 2.0))
        self.ping_interval = float(cfg.get("ping_interval", 1.0))
        self.reconnect_delay = float(cfg.get("reconnect", 2.0))
        self.ser = None
        self.ready = False
        self.devices: dict[int, dict] = {}
        self.logs: deque[str] = deque(maxlen=30)
        self.parser = FrameParser()
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._hello = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ connect
    def _open(self):
        serial = _serial_module()
        port = self.port
        if port == "auto":
            port = find_auto_port()
            if port is None:
                raise RuntimeError("no USB serial device found (port: auto)")
        ser = serial.serial_for_url(port, baudrate=self.baud, timeout=0.1, write_timeout=2)
        self._configure(ser)
        self.detail = f"{port} @ {self.baud}"
        return ser

    def _configure(self, ser) -> None:
        """Hook for subclasses (RS485)."""

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await super().start()
        self._tasks.append(asyncio.create_task(self._supervise(), name=f"serial:{self.name}"))

    async def _supervise(self) -> None:
        while True:
            if self.ser is None:
                try:
                    self.ser = await asyncio.to_thread(self._open)
                except Exception as exc:  # noqa: BLE001
                    self._set_error(f"cannot open {self.port}: {exc}")
                    await asyncio.sleep(self.reconnect_delay)
                    continue
                self.connected = True
                self.last_error = None
                self._stop.clear()
                self._hello.clear()
                self._reader = threading.Thread(target=self._read_loop, args=(self.ser,),
                                                daemon=True, name=f"pb-read-{self.name}")
                self._reader.start()
                # many Arduinos reset when the port opens - wait for HELLO or boot_wait
                try:
                    await asyncio.wait_for(self._hello.wait(), self.boot_wait)
                except asyncio.TimeoutError:
                    pass
                self.ready = True
                log.info("output %s ready on %s", self.name, self.detail)
            await self.heartbeat()
            await asyncio.sleep(self.ping_interval or 1.0)

    async def heartbeat(self) -> None:
        if self.ping_interval and self.ready:
            try:
                await self._write(encode_frame(MsgType.PING, b"", self.address))
            except Exception as exc:  # noqa: BLE001
                self._lost(exc)

    def _set_error(self, msg: str) -> None:
        if msg != self.last_error:
            log.warning("output %s: %s", self.name, msg)
        self.last_error = msg

    def _lost(self, exc: Exception) -> None:
        self._set_error(f"connection lost: {exc}")
        self._close_port()

    def _close_port(self) -> None:
        self._stop.set()
        ser, self.ser = self.ser, None
        self.connected = self.ready = False
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    async def close(self) -> None:
        self._close_port()

    # --------------------------------------------------------------- read
    def _read_loop(self, ser) -> None:
        while not self._stop.is_set():
            try:
                data = ser.read(ser.in_waiting or 1)
            except Exception as exc:  # noqa: BLE001
                if not self._stop.is_set() and self._loop:
                    self._loop.call_soon_threadsafe(self._lost, exc)
                return
            if data:
                for pkt in self.parser.feed(data):
                    if self._loop:
                        self._loop.call_soon_threadsafe(self._on_packet, pkt)

    def _on_packet(self, pkt) -> None:
        if pkt.type not in (MsgType.HELLO, MsgType.PONG, MsgType.LOG):
            return  # e.g. our own frames echoed by a half-duplex RS485 adapter
        dev = self.devices.setdefault(pkt.addr, {"name": None, "last_seen": 0.0})
        dev["last_seen"] = time.monotonic()
        if pkt.type == MsgType.HELLO:
            dev["name"] = pkt.decode()
            self._hello.set()
            self.logs.append(f"[{pkt.addr}] hello: {dev['name']}")
        elif pkt.type == MsgType.LOG:
            self.logs.append(f"[{pkt.addr}] {pkt.decode()}")

    # -------------------------------------------------------------- write
    async def _write(self, data: bytes) -> int:
        ser = self.ser
        if ser is None:
            raise RuntimeError("port not open")

        def _do():
            with self._lock:
                return ser.write(data)
        return await asyncio.to_thread(_do) or 0

    async def send(self, stream_name: str, frame: Frame, ref: dict) -> int:
        if not self.ready:
            self.frames_dropped += 1
            return 0
        addr = int(ref.get("address", self.address))
        packet = encode_data_frame(frame.kind, frame.data, addr)
        try:
            return await self._write(packet)
        except Exception as exc:
            self._lost(exc)
            raise

    def device_alive(self, dev: dict) -> bool:
        window = max(3 * (self.ping_interval or 1.0), 2.0)
        return time.monotonic() - dev["last_seen"] < window

    def snapshot(self) -> dict:
        snap = super().snapshot()
        snap["devices"] = [
            {"address": a, "name": d["name"], "alive": self.device_alive(d)}
            for a, d in sorted(self.devices.items())
        ]
        snap["log"] = list(self.logs)[-8:]
        snap["crc_errors"] = self.parser.crc_errors
        return snap


@register_output("rs485")
class RS485Output(SerialOutput):
    """Several devices on one half-duplex RS485 bus.

    Extra config keys: ``devices: [1, 2, 3]`` addresses to poll for the
    dashboard status, ``rts_control: true`` to drive the transceiver DE/RE pin
    from RTS (adapters with automatic direction control do not need this),
    ``turnaround`` seconds of bus idle after every frame (default 0.001).

    Each stream chooses its device with ``outputs: [{name: bus, address: 2}]``.
    """

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.poll = [int(a) for a in cfg.get("devices", [])]
        self.rts_control = bool(cfg.get("rts_control", False))
        self.turnaround = float(cfg.get("turnaround", 0.001))
        self.boot_wait = float(cfg.get("boot_wait", 0.0))
        self._poll_idx = 0

    def _configure(self, ser) -> None:
        if self.rts_control:
            import serial.rs485
            ser.rs485_mode = serial.rs485.RS485Settings(
                rts_level_for_tx=True, rts_level_for_rx=False,
                delay_before_tx=None, delay_before_rx=None)

    async def _write(self, data: bytes) -> int:
        n = await super()._write(data)
        # give the line time to drain and turn around before the next frame
        if self.turnaround:
            await asyncio.sleep(len(data) * 10 / self.baud + self.turnaround)
        return n

    async def heartbeat(self) -> None:
        # ping one device per interval, round-robin, so replies never collide
        if not (self.ping_interval and self.ready and self.poll):
            return
        addr = self.poll[self._poll_idx % len(self.poll)]
        self._poll_idx += 1
        self.devices.setdefault(addr, {"name": None, "last_seen": 0.0})
        try:
            await self._write(encode_frame(MsgType.PING, b"", addr))
        except Exception as exc:  # noqa: BLE001
            self._lost(exc)

    def device_alive(self, dev: dict) -> bool:
        window = max(3 * (self.ping_interval or 1.0) * max(len(self.poll), 1), 2.0)
        return time.monotonic() - dev["last_seen"] < window
