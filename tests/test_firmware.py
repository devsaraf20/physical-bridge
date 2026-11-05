"""Compile the firmware with g++ on the host and check it against Python.

* the protocol header is compiled into a small harness and fed frames that
  the Python encoder produced (and vice versa);
* every example sketch is compiled against a tiny mock Arduino core
  (tests/firmware/mock) and run with real protocol frames on its "Serial".
"""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from physical_bridge.protocol import FrameParser, MsgType, encode_data_frame, encode_frame

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "firmware" / "libraries" / "PhysicalBridge" / "src"
MOCK = ROOT / "tests" / "firmware" / "mock"
GXX = shutil.which("g++")

pytestmark = pytest.mark.skipif(GXX is None, reason="g++ not installed")


def build(tmp_path, source, name, extra=()):
    exe = tmp_path / name
    cmd = [GXX, "-std=c++17", "-Wall", "-Werror", "-Wno-unused-variable", "-I", str(LIB), *extra,
           "-x", "c++", str(source), "-o", str(exe)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return exe


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    return build(tmp_path_factory.mktemp("h"), ROOT / "tests" / "firmware" / "protocol_harness.cpp", "harness")


def run(exe, data: bytes = b"", args=()):
    return subprocess.run([str(exe), *args], input=data, capture_output=True, check=True).stdout.decode()


def test_firmware_parses_python_frames(harness):
    bits = np.zeros((3, 10), dtype=np.uint8)
    bits[0, 0] = bits[2, 9] = 1
    grid = np.array([[0, 127, 128], [255, 1, 200]])
    data = (b"junkPB\x99" + encode_data_frame("value", -2.5, addr=3)
            + encode_data_frame("angles", [0, 90.25, -720])
            + encode_data_frame("bits", bits) + encode_data_frame("grid", grid))
    lines = run(harness, data).splitlines()
    assert lines[0] == "type=1 addr=3 len=4 value=-2.5000"
    assert lines[1] == "type=2 addr=255 len=12 angles=0.000,90.250,-720.000"
    assert lines[2].startswith("type=3 addr=255 len=6 w=10 h=3 bits=" + "1" + "0" * 28 + "1 ")
    assert "w=3 h=2 bits=001101 px=007f80ff01c8" in lines[3]
    assert lines[-1] == "crc_errors=0 too_long=0"


def test_firmware_rejects_corrupt_frames(harness):
    bad = bytearray(encode_data_frame("value", 1.0))
    bad[7] ^= 1
    out = run(harness, bytes(bad) + encode_data_frame("value", 2.0)).splitlines()
    assert out == ["type=1 addr=255 len=4 value=2.0000", "crc_errors=1 too_long=0"]


@pytest.mark.parametrize("payload", [b"", b"\x01\x02\x03", bytes(range(256)) * 3])
def test_firmware_encoder_matches_python(harness, payload):
    hexframe = run(harness, args=["encode", "34", "9", payload.hex()]).strip()
    assert bytes.fromhex(hexframe) == encode_frame(34, payload, 9)


# ---------------------------------------------------------------- sketches
SKETCHES = sorted((ROOT / "firmware").glob("*/*/*.ino"))


@pytest.fixture(scope="module")
def sketch_bins(tmp_path_factory):
    out = {}
    tmp = tmp_path_factory.mktemp("sketches")
    for s in SKETCHES:
        extra = ["-I", str(MOCK), f'-DSKETCH="{s}"']
        if "esp32" in s.parts:
            extra.append("-DMOCK_ESP32")
        out[s.stem] = build(tmp, MOCK / "runner.cpp", s.stem, extra)
    return out


def test_all_sketches_compile(sketch_bins):
    assert len(sketch_bins) == 6


def device_tx(output: str):
    hexdata = output.strip().splitlines()[-1].split()[-1] if "serial_tx" in output else ""
    return [(p.type, p.decode()) for p in FrameParser().feed(bytes.fromhex(hexdata))]


def test_servo_sketch(sketch_bins):
    data = encode_frame(MsgType.PING) + encode_data_frame("angles", [0, 90, 400])
    out = run(sketch_bins["pb_servos"], data)
    assert "servo 3 us 544" in out and "servo 5 us 1472" in out
    assert "servo 6 us 2400" in out  # 400 deg clamped to 180 on the device
    replies = device_tx(out)
    assert (MsgType.HELLO, "pb_servos") in replies and (MsgType.PONG, None) in replies


def test_servo_sketch_ignores_other_addresses(sketch_bins):
    # the USB sketch has no address, so it accepts everything; check broadcast + addressed
    out = run(sketch_bins["pb_servos"], encode_data_frame("angles", [45], addr=9))
    assert "servo 3 us" in out


def test_esp32_servo_sketch(sketch_bins):
    out = run(sketch_bins["pb_servos_esp32"], encode_data_frame("angles", [0, 180]))
    # 500 us and 2500 us of a 20 ms period at 16 bit
    assert "ledc 13 1638" in out and "ledc 12 8191" in out


@pytest.mark.parametrize("name", ["pb_stepper", "pb_stepper_esp32"])
def test_stepper_sketches_reach_target(sketch_bins, name):
    out = run(sketch_bins[name], encode_data_frame("angles", [45, -22.5]))
    # 45 deg = 400 steps (+ dir HIGH each step) ; -22.5 deg = 200 steps, dir LOW
    assert "pin_high_events 1000" in out


def test_led_matrix_max7219(sketch_bins):
    bits = np.zeros((8, 8), dtype=np.uint8)
    bits[0, 0] = 1
    bits[7, 7] = 1
    out = run(sketch_bins["pb_led_matrix"], encode_data_frame("bits", bits))
    # init (5 regs + 8 clear rows) * 2 bytes + 8 rows * 2 bytes
    assert "shift_events 42" in out


def test_led_matrix_ws2812(sketch_bins):
    grid = np.zeros((16, 16))
    grid[0, 0] = 255
    grid[1, 0] = 255  # serpentine: row 1 col 0 is LED 31
    out = run(sketch_bins["pb_led_matrix_esp32"], encode_data_frame("grid", grid))
    shows = [line for line in out.splitlines() if line.startswith("show")]
    reds = [int(v) for v in shows[-1].split()[1:]]
    assert reds[0] == 255 and reds[31] == 255 and sum(reds) == 510
