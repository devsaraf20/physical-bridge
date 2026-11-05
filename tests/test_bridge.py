"""End-to-end tests: real sockets, real asyncio loop."""
import asyncio
import json
import socket
import struct
import threading
import time

import aiohttp
import numpy as np
import pytest

from physical_bridge.bridge import Bridge
from physical_bridge.config import normalize_config
from physical_bridge.dashboard import Dashboard
from physical_bridge.osc import build_message, parse_message
from physical_bridge.protocol import FrameParser, MsgType, encode_frame


def make_cfg(outputs=None, streams=None, **inputs):
    return normalize_config({
        "inputs": {"osc": {"port": 0}, "websocket": {"port": 0}, **inputs},
        "outputs": outputs or {"v": {"type": "virtual"}},
        "streams": streams or {},
    })


async def wait_for(cond, timeout=3.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


async def test_osc_to_virtual_device():
    cfg = make_cfg(streams={
        "m": {"type": "grid", "input_range": [0, 1],
              "pipeline": [{"resize": {"width": 4, "height": 4}}, {"threshold": {"level": 128}}],
              "outputs": ["v"]},
    })
    b = Bridge(cfg)
    await b.start()
    try:
        port = b.inputs["osc"].port
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(build_message("/pb/m", 8, 8, *([1.0] * 32 + [0.0] * 32)), ("127.0.0.1", port))
        sock.sendto(build_message("/not/routed", 1), ("127.0.0.1", port))
        v = b.outputs["v"]
        await wait_for(lambda: "m" in v.devices)
        frame = v.devices["m"]["frame"]
        assert frame["kind"] == "bits" and frame["data"] == "1" * 8 + "0" * 8
        await wait_for(lambda: b.unrouted)
        assert "/not/routed" in b.unrouted
    finally:
        await b.stop()


async def test_websocket_input_and_multi_source_angles():
    cfg = make_cfg(streams={
        "arm": {"type": "angles", "source": ["/s/0", "/s/1"], "outputs": ["v"]},
        "val": {"type": "value", "outputs": ["v"]},
    })
    b = Bridge(cfg)
    await b.start()
    try:
        port = b.inputs["websocket"].port
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{port}/") as ws:
                await ws.send_str(json.dumps([{"address": "/s/1", "data": 45},
                                              {"address": "/s/0", "data": 10},
                                              {"stream": "val", "data": 3.5}]))
                await ws.send_str("{not json")
                reply = await ws.receive_json(timeout=2)
                assert "error" in reply
                await ws.send_bytes(build_message("/pb/val", 7.0))
        v = b.outputs["v"]
        await wait_for(lambda: v.devices.get("arm", {}).get("frame", {}).get("data") == [10.0, 45.0])
        await wait_for(lambda: v.devices.get("val", {}).get("frame", {}).get("data") == 7.0)
    finally:
        await b.stop()


async def test_midi_messages_route():
    mido = pytest.importorskip("mido")
    from physical_bridge.inputs.midi_in import MIDIInput
    cfg = make_cfg(streams={"knob": {"type": "value", "source": "/midi/cc/2/7", "outputs": ["v"]}})
    b = Bridge(cfg)
    await b.start()
    try:
        midi = MIDIInput({"normalize": True}, b.dispatch)  # no hardware port needed
        midi.handle_message(mido.Message("control_change", channel=1, control=7, value=127))
        await wait_for(lambda: b.outputs["v"].devices.get("knob", {}).get("frame", {}).get("data") == 1.0)
    finally:
        await b.stop()


async def test_disarm_holds_hardware_but_not_virtual():
    cfg = make_cfg(outputs={"v": {"type": "virtual"}, "o": {"type": "osc", "host": "127.0.0.1", "port": 1}},
                   streams={"x": {"type": "value", "outputs": ["v", "o"]}})
    b = Bridge(cfg)
    await b.start()
    try:
        b.set_armed(False)
        b.inject("x", 1.0)
        await wait_for(lambda: "x" in b.outputs["v"].devices)
        await asyncio.sleep(0.05)
        assert b.outputs["o"].frames_sent == 0
        b.set_armed(True)
        b.inject("x", 2.0)
        await wait_for(lambda: b.outputs["o"].frames_sent == 1)
    finally:
        await b.stop()


async def test_osc_forwarding():
    recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv.bind(("127.0.0.1", 0))
    recv.settimeout(2)
    cfg = make_cfg(outputs={"fwd": {"type": "osc", "port": recv.getsockname()[1], "grid_format": "list"}},
                   streams={"g": {"type": "bits", "outputs": ["fwd"]}})
    b = Bridge(cfg)
    await b.start()
    try:
        b.inject("g", [[1, 0], [0, 1]])
        data = await asyncio.get_running_loop().run_in_executor(None, recv.recv, 4096)
        assert parse_message(data) == ("/pb/out/g", [2, 2, 1, 0, 0, 1])
    finally:
        await b.stop()
        recv.close()


async def test_dynamic_stream_keeps_emitting_until_settled():
    cfg = make_cfg(streams={"s": {"type": "value", "safety": {"max_speed": 100}, "outputs": ["v"]}},
                   )
    cfg["bridge"]["tick_hz"] = 100
    b = Bridge(cfg)
    await b.start()
    try:
        b.inject("s", 0.0)
        await asyncio.sleep(0.05)
        b.inject("s", 30.0)  # 0.3 s of motion at 100/s
        await wait_for(lambda: b.streams["s"].output is not None and b.streams["s"].output.data == 30.0)
        assert b.outputs["v"].frames_sent > 10
    finally:
        await b.stop()


# ----------------------------------------------------- serial with fake device
class FakeDevice(threading.Thread):
    """A TCP server speaking the device side of the protocol (like an ESP32 on
    Wi-Fi), so the serial output is exercised through pyserial socket://."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.packets = []

    def run(self):
        conn, _ = self.srv.accept()
        conn.sendall(encode_frame(MsgType.HELLO, b"fake_servos", 0xFF))
        parser = FrameParser()
        conn.settimeout(5)
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                for p in parser.feed(data):
                    self.packets.append(p)
                    if p.type == MsgType.PING:
                        conn.sendall(encode_frame(MsgType.PONG, b"", 0xFF))
                        conn.sendall(encode_frame(MsgType.LOG, b"pong!", 0xFF))
        except OSError:
            return


async def test_serial_output_to_fake_device():
    pytest.importorskip("serial")
    dev = FakeDevice()
    dev.start()
    cfg = make_cfg(outputs={"arduino": {"type": "serial", "port": f"socket://127.0.0.1:{dev.port}",
                                        "ping_interval": 0.1, "boot_wait": 1.0}},
                   streams={"arm": {"type": "angles", "outputs": [{"name": "arduino", "address": 5}]}})
    b = Bridge(cfg)
    await b.start()
    try:
        out = b.outputs["arduino"]
        await wait_for(lambda: out.ready)
        b.inject("arm", [12.5, 170.0])
        await wait_for(lambda: any(p.type == MsgType.ANGLES for p in dev.packets))
        pkt = next(p for p in dev.packets if p.type == MsgType.ANGLES)
        assert pkt.addr == 5 and pkt.decode() == [12.5, 170.0]
        await wait_for(lambda: any(d["alive"] for d in out.snapshot()["devices"]))
        snap = out.snapshot()
        assert snap["devices"][0]["name"] == "fake_servos"
        assert any("pong!" in line for line in snap["log"])
    finally:
        await b.stop()


async def test_serial_output_reports_missing_port():
    pytest.importorskip("serial")
    cfg = make_cfg(outputs={"a": {"type": "serial", "port": "/dev/does-not-exist", "reconnect": 0.05}},
                   streams={"x": {"type": "value", "outputs": ["a"]}})
    b = Bridge(cfg)
    await b.start()
    try:
        await wait_for(lambda: b.outputs["a"].last_error)
        b.inject("x", 1.0)
        await asyncio.sleep(0.05)
        assert not b.outputs["a"].connected
    finally:
        await b.stop()


# ------------------------------------------------------------------ dashboard
async def test_dashboard_http_and_ws():
    cfg = make_cfg(streams={"x": {"type": "value", "outputs": ["v"]}})
    b = Bridge(cfg)
    await b.start()
    dash = Dashboard(b, {"host": "127.0.0.1", "port": 0, "refresh_hz": 50})
    await dash.start()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(dash.url + "/") as r:
                assert r.status == 200 and "Physical Bridge" in await r.text()
            async with s.get(dash.url + "/static/app.js") as r:
                assert r.status == 200
            async with s.post(dash.url + "/api/inject/x", json={"data": 4}) as r:
                assert (await r.json())["ok"]
            async with s.post(dash.url + "/api/inject/missing", json={"data": 4}) as r:
                assert r.status == 404
            async with s.ws_connect(dash.url + "/ws") as ws:
                assert (await ws.receive_json(timeout=2))["type"] == "hello"
                await ws.send_json({"cmd": "arm", "armed": False})
                await ws.send_json({"cmd": "inject", "stream": "x", "data": 9})
                state = None
                for _ in range(50):
                    state = await ws.receive_json(timeout=2)
                    if state["streams"]["x"]["output"] and state["streams"]["x"]["output"]["data"] == 9:
                        break
                assert state["armed"] is False
                assert state["streams"]["x"]["output"]["data"] == 9
                assert state["inputs"]["osc"]["listening"]
    finally:
        await dash.stop()
        await b.stop()
