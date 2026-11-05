import numpy as np
import pytest

from physical_bridge.frame import Frame
from physical_bridge.processing import Pipeline, build_step
from physical_bridge.processing import grid as G
from physical_bridge.processing.easing import EASINGS
from physical_bridge.processing.steps import ConfigError, Context


def run(step, frame, now=0.0, dt=1 / 60):
    return step(frame, Context(now=now, dt=dt))


# ------------------------------------------------------------------ grid ops
def test_resize_area_averages():
    g = np.array([[0, 255], [255, 255]], dtype=np.float32)
    assert G.resize(g, 1, 1, "area")[0, 0] == pytest.approx(191.25)


def test_resize_area_non_integer_ratio_preserves_mean():
    g = np.random.default_rng(0).uniform(0, 255, (30, 17)).astype(np.float32)
    out = G.resize(g, 7, 11, "area")
    assert out.shape == (11, 7)
    assert out.mean() == pytest.approx(g.mean(), rel=1e-4)


@pytest.mark.parametrize("mode", ["nearest", "bilinear", "area"])
def test_resize_upscale_shapes(mode):
    out = G.resize(np.eye(4) * 255, 16, 8, mode)
    assert out.shape == (8, 16)
    assert 0 <= out.min() and out.max() <= 255


@pytest.mark.parametrize("method", ["floyd_steinberg", "atkinson", "bayer"])
def test_dither_preserves_average_brightness(method):
    g = np.full((32, 32), 64, dtype=np.float32)
    out = G.dither(g, method)
    assert set(np.unique(out)) <= {0.0, 255.0}
    # Atkinson diffuses only 6/8 of the error by design, so midtones come out darker
    tol = 0.1 if method == "atkinson" else 0.04
    assert out.mean() / 255 == pytest.approx(64 / 255, abs=tol)


def test_dither_levels_quantises():
    out = G.dither(np.linspace(0, 255, 64).reshape(8, 8), "bayer", levels=4)
    assert set(np.round(np.unique(out))) <= {0, 85, 170, 255}


def test_threshold_and_invert():
    f = Frame("grid", np.array([[10, 200]], dtype=np.float32))
    bits = run(build_step({"threshold": {"level": 100}}), f)
    assert bits.kind == "bits" and bits.data.tolist() == [[0, 1]]
    assert run(build_step("invert"), bits).data.tolist() == [[1, 0]]


def test_dither_step_outputs_bits():
    out = run(build_step({"dither": {"method": "bayer"}}), Frame("grid", np.full((4, 4), 128.0)))
    assert out.kind == "bits" and out.data.sum() == 8


def test_flip_and_rotate():
    f = Frame("bits", np.array([[1, 0], [0, 0]], dtype=np.uint8))
    assert run(build_step({"flip": {"horizontal": True}}), f).data.tolist() == [[0, 1], [0, 0]]
    assert run(build_step({"flip": {"rotate": 90}}), f).data.tolist() == [[0, 1], [0, 0]]
    assert run(build_step({"flip": {"vertical": True}}), f).data.tolist() == [[0, 0], [1, 0]]


def test_gamma():
    out = run(build_step({"gamma": {"value": 2.0}}), Frame("grid", np.array([[0, 127.5, 255]])))
    np.testing.assert_allclose(out.data, [[0, 63.75, 255]], atol=0.01)


# ------------------------------------------------------------------- numeric
def test_map_scalar_and_per_element():
    step = build_step({"map": {"in": [0, 1], "out": [0, 180]}})
    assert run(step, Frame("value", 0.5)).data == pytest.approx(90)
    assert run(step, Frame("value", 2.0)).data == pytest.approx(180)  # clamped
    per = build_step({"map": {"in": [0, 1], "out": [[0, 180], [180, 0]]}})
    np.testing.assert_allclose(run(per, Frame("angles", np.array([0.25, 0.25]))).data, [45, 135])


def test_map_mismatched_lengths_is_reported():
    per = build_step({"map": {"out": [[0, 1], [0, 1]]}})
    with pytest.raises(ConfigError):
        run(per, Frame("angles", np.array([0.1, 0.2, 0.3])))


def test_deadband_ignores_small_changes():
    step = build_step({"deadband": {"threshold": 1.0}})
    vals = [run(step, Frame("angles", np.array([v]))).data[0] for v in (10, 10.5, 10.9, 11.2)]
    assert vals == [10, 10, 10, pytest.approx(11.2)]


def test_smooth_converges_and_settles():
    step = build_step({"smooth": {"time": 0.1}})
    run(step, Frame("value", 0.0))
    v = 0.0
    for i in range(1, 200):
        v = run(step, Frame("value", 100.0), dt=1 / 60).data
        if i == 6:  # 0.1 s = one time constant -> ~63 %
            assert v == pytest.approx(63.2, abs=2)
    assert v == 100.0 and step.settled


def test_ease_follows_curve_and_duration():
    step = build_step({"ease": {"duration": 1.0, "curve": "linear"}})
    run(step, Frame("value", 0.0))
    out = run(step, Frame("value", 10.0))  # new target, t=0
    assert out.data == 0.0 and not step.settled
    for _ in range(30):
        out = run(step, Frame("value", 10.0), dt=1 / 60)
    assert out.data == pytest.approx(5.0, abs=0.01)
    for _ in range(40):
        out = run(step, Frame("value", 10.0), dt=1 / 60)
    assert out.data == 10.0 and step.settled


def test_easing_curves_hit_endpoints():
    for name, fn in EASINGS.items():
        assert fn(0.0) == pytest.approx(0.0), name
        assert fn(1.0) == pytest.approx(1.0), name


def test_limits_clamp_and_max_speed():
    step = build_step({"limits": {"min": 10, "max": 170, "max_speed": 90}})
    assert run(step, Frame("angles", np.array([0.0]))).data[0] == 10  # first frame: clamped target
    out = None
    for _ in range(30):  # 0.5 s at 90 deg/s -> 45 deg
        out = run(step, Frame("angles", np.array([180.0])), dt=1 / 60)
    assert out.data[0] == pytest.approx(55, abs=0.01)
    assert not step.settled


def test_limits_per_motor_lists():
    step = build_step({"limits": {"min": [0, 50], "max": [10, 60]}})
    np.testing.assert_allclose(run(step, Frame("angles", np.array([20.0, 20.0]))).data, [10, 50])


def test_limits_max_mean_scales_grid():
    step = build_step({"limits": {"max_mean": 50}})
    out = run(step, Frame("grid", np.full((4, 4), 200.0)))
    assert out.data.mean() == pytest.approx(50)


def test_rate_limit_suppresses_then_releases():
    step = build_step({"rate_limit": {"hz": 10}})
    ctx = Context(now=0.0, dt=0)
    step(Frame("value", 1.0), ctx)
    assert not ctx.suppress
    ctx = Context(now=0.05, dt=0)
    step(Frame("value", 2.0), ctx)
    assert ctx.suppress and not step.settled
    ctx = Context(now=0.1, dt=0)
    step(Frame("value", 2.0), ctx)
    assert not ctx.suppress and step.settled


@pytest.mark.parametrize("spec", [
    {"nope": {}},
    {"resize": {"width": 0, "height": 4}},
    {"dither": {"method": "magic"}},
    {"ease": {"curve": "wobbly"}},
    {"limits": {"min": 10, "max": 0}},
    {"map": {"in": [1, 1], "out": [0, 1]}},
    {"smooth": {"alpha": 2}},
    {"resize": {"width": 4}},
    ["not", "a", "step"],
])
def test_bad_steps_raise_config_error(spec):
    with pytest.raises(ConfigError):
        build_step(spec)


def test_step_rejects_wrong_kind():
    with pytest.raises(ConfigError):
        run(build_step({"resize": {"width": 2, "height": 2}}), Frame("value", 1.0))


# ------------------------------------------------------------------ pipeline
def test_pipeline_safety_runs_last_and_settles():
    p = Pipeline.from_config([{"map": {"in": [0, 1], "out": [0, 180]}}],
                             safety={"min": 20, "max": 160, "max_speed": 60}, tick_hz=60)
    assert p.steps[-1].name == "limits"
    out, emit = p.run(Frame("angles", np.array([0.0])), now=0.0)
    assert emit and out.data[0] == 20
    target = Frame("angles", np.array([1.0]))
    now = 0.0
    p.run(target, now)
    while not p.settled:
        now += 1 / 60
        out, _ = p.run(target, now)
        assert now < 3
    assert out.data[0] == 160
    assert now == pytest.approx(140 / 60, abs=0.05)  # 140 deg at 60 deg/s


def test_pipeline_first_step_after_idle_is_not_a_jump():
    p = Pipeline.from_config([], safety={"max_speed": 60}, tick_hz=60)
    p.run(Frame("value", 0.0), now=0.0)
    out, _ = p.run(Frame("value", 100.0), now=10.0)  # long idle, then a big change
    assert out.data == pytest.approx(1.0)  # one nominal tick worth of motion


def test_pipeline_grid_to_bits_chain():
    p = Pipeline.from_config([{"resize": {"width": 8, "height": 8}}, {"dither": {"method": "floyd_steinberg"}}])
    out, _ = p.run(Frame("grid", np.full((64, 64), 255.0)), 0.0)
    assert out.kind == "bits" and out.data.shape == (8, 8) and out.data.all()
