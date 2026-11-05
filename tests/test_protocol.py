import struct

import numpy as np
import pytest

from physical_bridge.protocol import (BROADCAST, FrameParser, MsgType, crc8, encode_data_frame,
                                      encode_frame, pack_bits, unpack_payload)


def test_crc8_known_vector():
    # CRC-8/ATM ("SMBus") check value for "123456789"
    assert crc8(b"123456789") == 0xF4


def test_frame_layout():
    f = encode_frame(MsgType.VALUE, struct.pack("<f", 1.5), addr=7)
    assert f[:2] == b"PB"
    assert f[2] == MsgType.VALUE and f[3] == 7
    assert struct.unpack_from("<H", f, 4)[0] == 4
    assert f[-1] == crc8(f[2:-1])


@pytest.mark.parametrize("kind,data", [
    ("value", 42.25),
    ("angles", [0.0, 90.5, -180.0, 720.0]),
    ("grid", np.arange(12, dtype=np.float32).reshape(3, 4) * 20),
    ("bits", np.eye(5, dtype=np.uint8)),
])
def test_roundtrip(kind, data):
    pkts = list(FrameParser().feed(encode_data_frame(kind, data)))
    assert len(pkts) == 1 and pkts[0].addr == BROADCAST
    out = pkts[0].decode()
    if kind == "value":
        assert out == pytest.approx(data)
    else:
        np.testing.assert_allclose(np.asarray(out), np.asarray(data), atol=1e-4)


def test_bits_packing_msb_first():
    bits = np.zeros((1, 9), dtype=np.uint8)
    bits[0, 0] = bits[0, 8] = 1
    assert pack_bits(bits) == bytes([9, 1, 0b10000000, 0b10000000])


def test_parser_resyncs_after_noise_and_corruption():
    good = encode_data_frame("value", 1.0)
    bad = bytearray(encode_data_frame("value", 2.0))
    bad[-2] ^= 0xFF  # corrupt payload
    stream = b"\x00PPB\xff" + bytes(bad) + good + b"P"
    parser = FrameParser()
    pkts = []
    for i in range(0, len(stream), 3):  # arrive in small chunks
        pkts += list(parser.feed(stream[i:i + 3]))
    assert [p.decode() for p in pkts] == [1.0]
    assert parser.crc_errors >= 1


def test_grid_values_are_clipped_and_rounded():
    payload = encode_data_frame("grid", np.array([[-5.0, 127.6, 300.0]]))
    grid = list(FrameParser().feed(payload))[0].decode()
    assert grid.tolist() == [[0, 128, 255]]


def test_rejects_oversized_grids():
    with pytest.raises(ValueError):
        encode_data_frame("grid", np.zeros((10, 300)))


def test_text_payloads():
    assert unpack_payload(MsgType.HELLO, b"pb_servos") == "pb_servos"
