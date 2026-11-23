"""El catálogo de Ajustes y Efectos debe coincidir con los menús de Paint.NET."""

import numpy as np
import pytest

from paintmint.effects import ADJUSTMENTS, EFFECTS, GROUPS, REGISTRY

PDN_ADJUSTMENTS = {"auto_level", "grayscale", "brightness_contrast", "curves", "exposure", "highlights_shadows",
                   "hue_saturation", "invert_alpha", "invert", "levels", "posterize", "sepia", "temperature_tint"}
PDN_EFFECTS = {
    "artistic": {"ink_sketch", "linocut", "mosaic", "oil_painting", "pencil_sketch", "pointillism", "stained_glass"},
    "blurs": {"bokeh_blur", "fragment_blur", "gaussian_blur", "median_blur", "motion_blur", "radial_blur", "sketch_blur",
              "square_blur", "surface_blur", "zoom_blur"},
    "color": {"ordered_dither", "quantize"},
    "distort": {"bulge", "crystalize", "dents", "frosted_glass", "morphology", "pixelate", "polar_inversion",
                "spherize", "tile_reflection", "twist", "waves"},
    "noise": {"noise", "reduce_noise"},
    "object": {"drop_shadow"},
    "photo": {"glow", "red_eye", "sharpen", "soften_portrait", "straighten", "vignette"},
    "render": {"clouds", "julia", "mandelbrot", "turbulence"},
    "stylize": {"edge_detect", "emboss", "halftone", "outline", "relief"},
}


def test_adjustments_match_paintnet():
    assert {e.key for e in ADJUSTMENTS} == PDN_ADJUSTMENTS


@pytest.mark.parametrize("group", sorted(PDN_EFFECTS))
def test_effect_submenus_match_paintnet(group):
    assert {e.key for e in EFFECTS if e.group == group} == PDN_EFFECTS[group]
    assert group in GROUPS


def test_every_effect_is_in_a_submenu():
    assert all(e.group in GROUPS for e in EFFECTS)


@pytest.fixture
def img():
    return np.random.default_rng(5).integers(0, 256, (40, 50, 4), dtype=np.uint8)


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_effects_run_on_tiny_and_transparent_images(key):
    e = REGISTRY[key]
    for shape, fill in (((1, 1, 4), 128), ((3, 5, 4), 0), ((12, 9, 4), 255)):
        px = np.full(shape, fill, np.uint8)
        out = e.apply(px, **e.resolve({}))
        assert out.shape == px.shape and out.dtype == np.uint8


@pytest.mark.parametrize("key", ["auto_level", "exposure", "highlights_shadows", "temperature_tint", "sepia"])
def test_new_adjustments_keep_alpha(key, img):
    e = REGISTRY[key]
    params = {"exposure": 1.0} if key == "exposure" else {}
    assert np.array_equal(e.apply(img, **e.resolve(params))[..., 3], img[..., 3])


def test_identity_defaults(img):
    for key in ("exposure", "highlights_shadows", "temperature_tint"):
        e = REGISTRY[key]
        assert np.array_equal(e.apply(img, **e.resolve({})), img), key


def test_exposure_direction_and_invert_alpha(img):
    e = REGISTRY["exposure"]
    assert e.apply(img, exposure=1.0)[..., :3].mean() > img[..., :3].mean() > e.apply(img, exposure=-1.0)[..., :3].mean()
    assert np.array_equal(REGISTRY["invert_alpha"].apply(img)[..., 3], 255 - img[..., 3])


def test_auto_level_stretches_a_flat_range():
    px = np.zeros((20, 20, 4), np.uint8)
    px[..., 3] = 255
    px[:, :10, :3] = 100
    px[:, 10:, :3] = 140
    out = REGISTRY["auto_level"].apply(px)
    assert out[..., 0].min() < 10 and out[..., 0].max() > 245


def test_temperature_warms_and_cools():
    px = np.full((4, 4, 4), 128, np.uint8)
    warm = REGISTRY["temperature_tint"].apply(px, temperature=50, tint=0)
    assert warm[0, 0, 0] > 128 > warm[0, 0, 2]


def test_sepia_intensity_zero_is_gray(img):
    out = REGISTRY["sepia"].apply(img, intensity=0)
    assert np.all(out[..., 0] == out[..., 1]) or np.abs(out[..., 0].astype(int) - out[..., 1]).max() <= 1


def test_blurs_smooth_and_morphology_directions(img):
    for key in ("square_blur", "median_blur", "motion_blur", "zoom_blur", "radial_blur", "bokeh_blur", "surface_blur"):
        e = REGISTRY[key]
        out = e.apply(img, **e.resolve({}))
        assert out[..., :3].std() < img[..., :3].std(), key
    gray = np.full((20, 20, 4), 255, np.uint8)
    gray[8:12, 8:12, :3] = 0
    e = REGISTRY["morphology"]
    assert e.apply(gray, mode="erode", width=3, height=3, linked=True)[..., 0].sum() < gray[..., 0].sum()   # el mínimo agranda lo oscuro
    assert e.apply(gray, mode="dilate", width=3, height=3, linked=True)[..., 0].sum() > gray[..., 0].sum()


def test_seeded_effects_are_reproducible_and_seed_matters(img):
    for key in ("clouds", "crystalize", "dents", "frosted_glass", "pointillism", "stained_glass", "turbulence", "linocut", "mosaic"):
        e = REGISTRY[key]
        a = e.apply(img, **e.resolve({"seed": 1}))
        assert np.array_equal(a, e.apply(img, **e.resolve({"seed": 1}))), key
        assert not np.array_equal(a, e.apply(img, **e.resolve({"seed": 2}))), key


def test_render_effects_overwrite_with_opaque_pixels():
    px = np.zeros((20, 20, 4), np.uint8)
    for key in ("clouds", "julia", "mandelbrot", "turbulence"):
        out = REGISTRY[key].apply(px, **REGISTRY[key].resolve({}))
        assert (out[..., 3] == 255).all() and out[..., :3].std() > 1, key


def test_drop_shadow_adds_shadow_outside_object():
    px = np.zeros((30, 30, 4), np.uint8)
    px[10:20, 10:20] = (255, 0, 0, 255)
    e = REGISTRY["drop_shadow"]
    out = e.apply(px, **e.resolve({"distance": 6, "radius": 2, "angle": -45}))
    assert out[22, 22, 3] > 0 and np.array_equal(out[15, 15], px[15, 15])
    only = e.apply(px, **e.resolve({"only": True}))
    assert only[15, 15, 3] < 255


def test_straighten_zero_is_identity_and_vignette_darkens_corners(img):
    assert np.array_equal(REGISTRY["straighten"].apply(img, angle=0.0, sampling=3), img)
    v = REGISTRY["vignette"].apply(img, **REGISTRY["vignette"].resolve({"strength": 100, "radius": 30}))
    assert v[0, 0, :3].sum() <= img[0, 0, :3].sum()
    assert np.array_equal(v[20, 25], img[20, 25]) or v[20, 25, :3].sum() >= img[20, 25, :3].sum() * 0.9


def test_quantize_limits_colors_and_ordered_dither_levels(img):
    q = REGISTRY["quantize"].apply(img, algorithm="median", colors=4, dither=0, threshold=0)
    assert len({tuple(p) for p in q[..., :3].reshape(-1, 3)}) <= 4
    d = REGISTRY["ordered_dither"].apply(img, matrix=4, levels=2, strength=100)
    assert set(np.unique(d[..., :3])) <= {0, 255}


def test_add_noise_coverage_zero_changes_nothing(img):
    assert np.array_equal(REGISTRY["noise"].apply(img, intensity=50, color=0, seed=1, coverage=0), img)
