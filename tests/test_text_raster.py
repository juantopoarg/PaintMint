import numpy as np
import pytest

from paintmint.core.layer import TextSpec
from paintmint.render import raster
from paintmint.render.text import render_text_layer, text_bounds


def test_text_renders_inside_bounds_with_color():
    spec = TextSpec(text="Hola", size=24, x=10, y=10, color=(255, 0, 0, 255))
    px = render_text_layer(spec, 100, 60)
    ys, xs = np.nonzero(px[..., 3])
    x0, y0, x1, y1 = text_bounds(spec)
    assert xs.min() >= x0 and xs.max() < x1 and ys.min() >= y0 and ys.max() < y1
    assert (px[..., :3][px[..., 3] > 200] == (255, 0, 0)).all()


def test_text_size_alignment_and_clipping():
    small = render_text_layer(TextSpec(text="A", size=10), 50, 50)[..., 3].sum()
    big = render_text_layer(TextSpec(text="A", size=30), 50, 50)[..., 3].sum()
    assert big > small * 3
    out = render_text_layer(TextSpec(text="Recortado", size=30, x=-20, y=-10), 40, 40)   # parcialmente fuera
    assert out.shape == (40, 40, 4)
    assert render_text_layer(TextSpec(text="", size=10), 10, 10)[..., 3].sum() == 0
    assert render_text_layer(TextSpec(text="x", x=500, y=500), 10, 10)[..., 3].sum() == 0


def test_multiline_text_is_taller():
    one = text_bounds(TextSpec(text="a", size=20))
    two = text_bounds(TextSpec(text="a\nb", size=20))
    assert (two[3] - two[1]) > (one[3] - one[1]) * 1.5


def test_flood_mask_bounds_and_empty():
    px = np.zeros((5, 5, 4), np.uint8)
    assert raster.flood_mask(px, 99, 99, 0).sum() == 0
    assert raster.flood_mask(px, 2, 2, 0).sum() == 25


def test_gradient_kinds_all_work():
    for k in raster.GRADIENT_KINDS:
        g = raster.gradient_rgba((0, 0, 20, 20), k, (10, 10), (19, 10), (0, 0, 0, 255), (255, 255, 255, 0))
        assert g.shape == (20, 20, 4)
    with pytest.raises(ValueError):
        raster.gradient_rgba((0, 0, 2, 2), "x", (0, 0), (1, 1), (0, 0, 0, 255), (0, 0, 0, 255))


def test_over_math_and_lerp_exactness():
    dst = np.zeros((1, 1, 4), np.uint8); dst[...] = (0, 0, 255, 255)
    out = raster.over(dst, (255, 0, 0), np.array([[0.5]], np.float32))
    assert tuple(out[0, 0]) == (128, 0, 128, 255)
    snap = np.full((2, 2, 4), 10, np.uint8); block = np.full((2, 2, 4), 200, np.uint8)
    t = np.array([[0.0, 1.0], [0.0, 1.0]], np.float32)
    res = raster.lerp_premult(snap, block, t)
    assert (res[0, 0] == 10).all() and (res[0, 1] == 200).all()


def test_dab_hardness_profile():
    _, _, hard = raster.dab(10, 10, 20, 1.0)
    _, _, soft = raster.dab(10, 10, 20, 0.0)
    assert hard.max() == 1.0 and soft.sum() < hard.sum()
