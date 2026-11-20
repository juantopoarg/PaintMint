import numpy as np
import pytest

from paintmint.core.blend import BLEND_MODES, blend_channels, composite
from paintmint.core.layer import Layer


def L(color, **kw):
    px = np.zeros((2, 2, 4), np.uint8)
    px[...] = color
    return Layer(px, **kw)


@pytest.mark.parametrize("mode", list(BLEND_MODES))
def test_every_blend_mode_runs_and_stays_in_range(mode):
    rng = np.random.default_rng(0)
    cb, cs = rng.random((8, 8, 3), dtype=np.float32), rng.random((8, 8, 3), dtype=np.float32)
    out = blend_channels(mode, cb, cs)
    assert out.shape == cb.shape
    assert np.isfinite(out).all()
    assert out.min() >= -1e-5 and out.max() <= 1 + 1e-5


def test_multiply_and_screen_known_values():
    base = L((128, 128, 128, 255))
    top = L((128, 128, 128, 255), blend_mode="multiply")
    assert composite([base, top], 2, 2)[0, 0, 0] == 64
    top2 = L((128, 128, 128, 255), blend_mode="screen")
    assert composite([base, top2], 2, 2)[0, 0, 0] == 192


def test_difference_of_equal_colors_is_black():
    out = composite([L((90, 120, 200, 255)), L((90, 120, 200, 255), blend_mode="difference")], 2, 2)
    assert tuple(out[0, 0]) == (0, 0, 0, 255)


def test_transparent_layers_compose_to_transparent():
    assert composite([L((0, 0, 0, 0))], 2, 2)[..., 3].max() == 0


def test_normal_over_semi_transparent_backdrop_alpha_math():
    out = composite([L((255, 0, 0, 128)), L((0, 0, 255, 128))], 2, 2)
    assert out[0, 0, 3] == 192  # 0.5 + 0.5*(1-0.5) = 0.75


def test_region_and_background():
    out = composite([L((10, 20, 30, 255))], 2, 2, region=(1, 1, 2, 2))
    assert out.shape == (1, 1, 4)
    flat = composite([L((0, 0, 0, 0))], 2, 2, background=(255, 255, 255, 255))
    assert tuple(flat[0, 0]) == (255, 255, 255, 255)


def test_large_image_strips_match_single_pass():
    rng = np.random.default_rng(1)
    a = Layer(rng.integers(0, 256, (600, 40, 4), dtype=np.uint8))
    b = Layer(rng.integers(0, 256, (600, 40, 4), dtype=np.uint8), blend_mode="overlay", opacity=0.7)
    full = composite([a, b], 40, 600)
    part = composite([a, b], 40, 600, region=(0, 300, 40, 330))
    assert np.array_equal(full[300:330], part)
