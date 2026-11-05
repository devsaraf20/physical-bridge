import pytest

from physical_bridge.osc import OSCError, build_bundle, build_message, parse_message, parse_packet


def test_message_roundtrip():
    msg = build_message("/pb/arm", 1, 2.5, "hi", b"\x01\x02\x03", True, None)
    addr, args = parse_message(msg)
    assert addr == "/pb/arm"
    assert args[0] == 1 and args[1] == pytest.approx(2.5) and args[2] == "hi"
    assert args[3] == b"\x01\x02\x03" and args[4] is True and args[5] is None
    assert len(msg) % 4 == 0


def test_bundle():
    b = build_bundle([build_message("/a", 1), build_bundle([build_message("/b", 2.0)])])
    assert [(a, v) for a, v in parse_packet(b)] == [("/a", [1]), ("/b", [2.0])]


def test_message_without_typetag():
    assert parse_message(b"/x\x00\x00") == ("/x", [])


@pytest.mark.parametrize("data", [b"nope\x00\x00\x00\x00", b"/a\x00\x00,f\x00\x00\x00"])
def test_bad_packets(data):
    with pytest.raises(OSCError):
        list(parse_packet(data))
