import numpy as np
import pytest

from paintmint.core.errors import PaintMintError
from paintmint.effects import REGISTRY
from paintmint.effects.adjustments import curve_lut


@pytest.fixture
def img():
    return np.random.default_rng(3).integers(0, 256, (30, 40, 4), dtype=np.uint8)


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_every_effect_preserves_shape_dtype_and_runs_with_defaults(key, img):
    out = REGISTRY[key].apply(img, **REGISTRY[key].resolve({}))
    assert out.shape == img.shape and out.dtype == np.uint8


@pytest.mark.parametrize("key", ["brightness_contrast", "levels", "curves", "hue_saturation", "invert",
                                 "grayscale", "sepia", "posterize"])
def test_adjustments_keep_alpha(key, img):
    e = REGISTRY[key]
    params = {"brightness": 40} if key == "brightness_contrast" else {}
    assert np.array_equal(e.apply(img, **e.resolve(params))[..., 3], img[..., 3])


def test_default_brightness_contrast_levels_curves_are_identity(img):
    for key in ("brightness_contrast", "levels", "curves"):
        e = REGISTRY[key]
        assert np.array_equal(e.apply(img, **e.resolve({})), img), key


def test_brightness_and_contrast_direction():
    flat = np.full((4, 4, 4), 100, np.uint8); flat[..., 3] = 255
    e = REGISTRY["brightness_contrast"]
    assert e.apply(flat, **e.resolve({"brightness": 50}))[0, 0, 0] > 100
    assert e.apply(flat, **e.resolve({"brightness": -50}))[0, 0, 0] < 100
    grad = np.zeros((1, 2, 4), np.uint8); grad[0, 0] = (100, 100, 100, 255); grad[0, 1] = (160, 160, 160, 255)
    hi = e.apply(grad, **e.resolve({"contrast": 50}))
    assert int(hi[0, 1, 0]) - int(hi[0, 0, 0]) > 60


def test_levels_clip_and_gamma():
    ramp = np.zeros((1, 256, 4), np.uint8); ramp[0, :, :3] = np.arange(256)[:, None]; ramp[..., 3] = 255
    e = REGISTRY["levels"]
    out = e.apply(ramp, **e.resolve({"in_black": 50, "in_white": 200}))
    assert out[0, 50, 0] == 0 and out[0, 200, 0] == 255 and out[0, 0, 0] == 0 and out[0, 255, 0] == 255
    bright = e.apply(ramp, **e.resolve({"gamma": 2.0}))
    assert bright[0, 128, 0] > 128


def test_curves_lut_passes_through_control_points_and_is_monotone():
    pts = [(0, 0), (64, 30), (192, 220), (255, 255)]
    lut = curve_lut(pts)
    assert lut[64] == 30 and lut[192] == 220 and lut[0] == 0 and lut[255] == 255
    assert (np.diff(lut.astype(int)) >= 0).all()


def test_curves_invert_via_points(img):
    e = REGISTRY["curves"]
    out = e.apply(img, **e.resolve({"points": [(0, 255), (255, 0)]}))
    assert np.array_equal(out[..., :3], 255 - img[..., :3])


def test_invert_twice_is_identity(img):
    e = REGISTRY["invert"]
    assert np.array_equal(e.apply(e.apply(img)), img)


def test_grayscale_makes_channels_equal(img):
    out = REGISTRY["grayscale"].apply(img)
    assert (out[..., 0] == out[..., 1]).all() and (out[..., 1] == out[..., 2]).all()


def test_hue_shift_180_turns_red_into_cyan():
    red = np.zeros((2, 2, 4), np.uint8); red[...] = (255, 0, 0, 255)
    e = REGISTRY["hue_saturation"]
    out = e.apply(red, **e.resolve({"hue": 180}))
    assert out[0, 0, 0] < 5 and out[0, 0, 1] > 250 and out[0, 0, 2] > 250
    assert e.apply(red, **e.resolve({"saturation": 0}))[0, 0, 1] == 255  # sin saturación -> gris/blanco


def test_gaussian_blur_smooths_and_preserves_flat_areas():
    img = np.zeros((40, 40, 4), np.uint8); img[..., 3] = 255; img[:, 20:, :3] = 255
    e = REGISTRY["gaussian_blur"]
    out = e.apply(img, **e.resolve({"radius": 6}))
    assert 20 < out[20, 20, 0] < 235            # borde difuminado
    assert out[20, 2, 0] < 5 and out[20, 37, 0] > 250
    assert np.array_equal(e.apply(img, **e.resolve({"radius": 0})), img)


def test_blur_does_not_bleed_color_from_transparent_pixels():
    img = np.zeros((20, 20, 4), np.uint8)
    img[5:15, 5:15] = (255, 0, 0, 255)
    img[..., :3][img[..., 3] == 0] = (0, 255, 0)           # color basura bajo alfa 0
    out = REGISTRY["gaussian_blur"].apply(img, radius=4)
    visible = out[..., 3] > 20
    assert out[..., 1][visible].max() <= 2                 # sin verde


def test_sharpen_increases_edge_contrast():
    img = np.zeros((30, 30, 4), np.uint8); img[..., 3] = 255; img[:, 15:, :3] = 150; img[:, :15, :3] = 100
    out = REGISTRY["sharpen"].apply(img, amount=200, radius=2.0)
    assert int(out[15, 16, 0]) > 150 and int(out[15, 13, 0]) < 100
    same = REGISTRY["sharpen"].apply(img, amount=0, radius=2.0)
    assert np.array_equal(same, img)


def test_pixelate_makes_uniform_cells(img):
    out = REGISTRY["pixelate"].apply(img, size=8)
    assert (out[0:8, 0:8] == out[0, 0]).all()


def test_noise_is_deterministic_per_seed(img):
    e = REGISTRY["noise"]
    a, b = e.apply(img, **e.resolve({"seed": 5})), e.apply(img, **e.resolve({"seed": 5}))
    assert np.array_equal(a, b) and not np.array_equal(a, img)


def test_resolve_clamps_and_validates():
    e = REGISTRY["brightness_contrast"]
    assert e.resolve({"brightness": 999})["brightness"] == 100
    with pytest.raises(PaintMintError):
        e.resolve({"nope": 1})


def test_apply_effect_respects_selection_and_undo(session):
    session.active_layer.pixels[...] = (100, 100, 100, 255)
    session.select_rect(0, 0, 50, 80)
    assert session.apply_effect(REGISTRY["invert"], {})
    assert session.active_layer.pixels[10, 10, 0] == 155 and session.active_layer.pixels[10, 70, 0] == 100
    session.undo()
    assert (session.active_layer.pixels[..., 0] == 100).all()


def test_effect_error_leaves_layer_untouched(session):
    class Boom:
        label = "boom"
        def resolve(self, v): return {}
        def apply(self, px): raise MemoryError()
    before = session.active_layer.pixels.copy()
    from paintmint.core.errors import OutOfMemoryAppError
    with pytest.raises(OutOfMemoryAppError):
        session.apply_effect(Boom(), {})
    assert np.array_equal(session.active_layer.pixels, before) and session.history.labels == []
