from pathlib import Path

import numpy as np
import pytest

from physical_bridge.bridge import Bridge
from physical_bridge.config import load_config, normalize_config
from physical_bridge.processing.steps import ConfigError
from physical_bridge.stream import InputError, coerce, coerce_2d

ROOT = Path(__file__).resolve().parent.parent


def test_root_config_matches_starter():
    starter = ROOT / "physical_bridge" / "starter_config.yaml"
    assert (ROOT / "config.yaml").read_text() == starter.read_text()


@pytest.mark.parametrize("path", sorted([ROOT / "config.yaml", *(ROOT / "examples" / "configs").glob("*.yaml")]),
                         ids=lambda p: p.name)
def test_shipped_configs_are_valid(path):
    Bridge(load_config(path))  # builds every step and output


@pytest.mark.parametrize("raw,msg", [
    ({"streams": {"s": {"type": "pixels"}}}, "type must be"),
    ({"streams": {"s": {"type": "value", "outputs": ["ghost"]}}}, "unknown output"),
    ({"outputs": {"o": {"type": "serial"}}}, "port"),
    ({"outputs": {"o": {"type": "laser"}}}, "type must be"),
    ({"bogus": 1}, "unknown top-level"),
    ({"streams": {"s": {"type": "grid", "source": ["/a", "/b"]}}}, "list of sources"),
    ({"streams": {"s": {"type": "grid", "input_range": [1, 1]}}}, "input_range"),
])
def test_config_errors(raw, msg):
    with pytest.raises(ConfigError, match=msg):
        normalize_config(raw)


def test_default_source_and_output_refs():
    cfg = normalize_config({"outputs": {"v": {"type": "virtual"}},
                            "streams": {"arm": {"type": "angles", "outputs": ["v", {"name": "v", "address": 3}]}}})
    st = cfg["streams"]["arm"]
    assert st["source"] == "/pb/arm"
    assert st["outputs"] == [{"name": "v"}, {"name": "v", "address": 3}]


# ------------------------------------------------------------------ coercion
def test_coerce_2d_forms():
    expected = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
    for raw, size in [
        ([[1, 2, 3], [4, 5, 6]], None),
        ({"w": 3, "h": 2, "data": [1, 2, 3, 4, 5, 6]}, None),
        ([3, 2, 1, 2, 3, 4, 5, 6], None),
        ([3, 2, bytes([1, 2, 3, 4, 5, 6])], None),
        ([1, 2, 3, 4, 5, 6], [3, 2]),
        (bytes([1, 2, 3, 4, 5, 6]), [3, 2]),
    ]:
        np.testing.assert_array_equal(coerce_2d(raw, size), expected)


def test_coerce_square_inference_and_errors():
    assert coerce_2d(list(range(16)), None).shape == (4, 4)
    with pytest.raises(InputError):
        coerce_2d([1, 2, 3, 4, 5], None)
    with pytest.raises(InputError):
        coerce_2d([[1, 2], [3]], None)


def test_coerce_ranges():
    cfg = {"input_range": [0, 1]}
    np.testing.assert_allclose(coerce("grid", [[0, 0.5, 1, 2]], cfg), [[0, 127.5, 255, 255]])
    assert coerce("bits", [[0, 0.4, 0.6]], cfg).tolist() == [[0, 0, 1]]
    assert coerce("bits", [[0, 3]], {}).tolist() == [[0, 1]]
    assert coerce("value", [0.25, 9], {}) == 0.25
    assert coerce("angles", {"data": [1, "2"]}, {}).tolist() == [1, 2]
    with pytest.raises(InputError):
        coerce("value", [], {})


def test_custom_output_plugin_from_file(tmp_path):
    plugin = (ROOT / "examples" / "plugins" / "console_output.py").resolve()
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(f"""
bridge: {{plugins: ["{plugin}"]}}
outputs: {{c: {{type: console, every: 1}}}}
streams: {{x: {{type: value, outputs: [c]}}}}
""")
    b = Bridge(load_config(cfg_file))
    assert type(b.outputs["c"]).__name__ == "ConsoleOutput"


def test_unknown_plugin_is_config_error():
    with pytest.raises(ConfigError, match="cannot load plugin"):
        normalize_config({"bridge": {"plugins": ["no_such_module_xyz"]}})
