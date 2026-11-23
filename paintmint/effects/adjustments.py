"""Ajustes de color: brillo/contraste, niveles, curvas, tono/saturación, etc."""

from __future__ import annotations

from ..i18n import tr

import numpy as np

from .base import Effect, Param, apply_lut, normalize_curve

_X = np.arange(256, dtype=np.float32)


def _to_lut(values: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(values), 0, 255).astype(np.uint8)


class BrightnessContrast(Effect):
    key, label, category = "brightness_contrast", tr('Brightness and contrast'), "adjust"
    params = [
        Param("brightness", tr('Brightness'), "int", 0, -100, 100),
        Param("contrast", tr('Contrast'), "int", 0, -100, 100),
    ]

    def apply(self, pixels, brightness, contrast):
        c = contrast * 2.55
        factor = (259.0 * (c + 255.0)) / (255.0 * (259.0 - c))
        lut = _to_lut((_X - 128.0) * factor + 128.0 + brightness * 2.55)
        return apply_lut(pixels, lut)


class Levels(Effect):
    """Niveles de entrada/salida y gamma (maestro)."""

    key, label, category = "levels", tr('Levels'), "adjust"
    params = [
        Param("in_black", tr('Input: black'), "int", 0, 0, 254),
        Param("in_white", tr('Input: white'), "int", 255, 1, 255),
        Param("gamma", "Gamma", "float", 1.0, 0.1, 5.0),
        Param("out_black", tr('Output: black'), "int", 0, 0, 254),
        Param("out_white", tr('Output: white'), "int", 255, 1, 255),
    ]

    def apply(self, pixels, in_black, in_white, gamma, out_black, out_white):
        if in_white <= in_black:
            in_white = min(255, in_black + 1)
        if out_white == out_black:
            out_white = min(255, out_black + 1)
        t = np.clip((_X - in_black) / float(in_white - in_black), 0.0, 1.0)
        t = t ** (1.0 / gamma)
        return apply_lut(pixels, _to_lut(out_black + t * (out_white - out_black)))


def curve_lut(points) -> np.ndarray:
    """LUT de 256 entradas por interpolación monótona (PCHIP) de los puntos de control."""
    from scipy.interpolate import PchipInterpolator

    pts = normalize_curve(points)
    xs, ys = zip(*pts)
    if len(pts) == 2:
        return _to_lut(np.interp(_X, xs, ys))
    return _to_lut(PchipInterpolator(xs, ys)(_X))


class Curves(Effect):
    key, label, category = "curves", tr('Curves'), "adjust"
    params = [Param("points", tr('Curve'), "curve", [(0, 0), (255, 255)])]

    def apply(self, pixels, points):
        return apply_lut(pixels, curve_lut(points))


class HueSaturation(Effect):
    key, label, category = "hue_saturation", tr('Hue and saturation'), "adjust"
    params = [
        Param("hue", tr('Hue (°)'), "int", 0, -180, 180),
        Param("saturation", tr('Saturation (%)'), "int", 100, 0, 200),
        Param("lightness", tr('Lightness'), "int", 0, -100, 100),
    ]

    def apply(self, pixels, hue, saturation, lightness):
        rgb = pixels[..., :3].astype(np.float32) / 255.0
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        mx, mn = rgb.max(axis=2), rgb.min(axis=2)
        d = mx - mn
        h = np.zeros_like(mx)
        nz = d > 1e-6
        rc = nz & (mx == r)
        gc = nz & (mx == g) & ~rc
        bc = nz & ~rc & ~gc
        h[rc] = ((g - b)[rc] / d[rc]) % 6.0
        h[gc] = (b - r)[gc] / d[gc] + 2.0
        h[bc] = (r - g)[bc] / d[bc] + 4.0
        h = (h / 6.0 + hue / 360.0) % 1.0
        s = np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1.0), 0.0) * (saturation / 100.0)
        s = np.clip(s, 0.0, 1.0)
        v = mx
        # HSV -> RGB
        hh = h * 6.0
        i = np.floor(hh).astype(np.int32) % 6
        f = hh - np.floor(hh)
        p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
        choices = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
        out = np.zeros_like(rgb)
        for k, (cr, cg, cb) in enumerate(choices):
            m = i == k
            out[..., 0][m], out[..., 1][m], out[..., 2][m] = cr[m], cg[m], cb[m]
        if lightness > 0:
            out = out + (1.0 - out) * (lightness / 100.0)
        elif lightness < 0:
            out = out * (1.0 + lightness / 100.0)
        res = pixels.copy()
        res[..., :3] = np.clip(np.rint(out * 255.0), 0, 255).astype(np.uint8)
        return res


class InvertColors(Effect):
    key, label, category = "invert", tr('Invert colors'), "adjust"
    params = []

    def apply(self, pixels):
        return apply_lut(pixels, 255 - np.arange(256))


class Grayscale(Effect):
    key, label, category = "grayscale", tr('Black and white'), "adjust"
    params = []

    def apply(self, pixels):
        rgb = pixels[..., :3].astype(np.float32)
        y = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        out = pixels.copy()
        out[..., :3] = np.clip(np.rint(y), 0, 255).astype(np.uint8)[..., None]
        return out


class Sepia(Effect):
    key, label, category = "sepia", "Sepia", "adjust"
    params = [Param("intensity", tr('Intensity'), "int", 100, 0, 100)]

    def apply(self, pixels, intensity=100):
        rgb = pixels[..., :3].astype(np.float32)
        m = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]], dtype=np.float32)
        gray = (rgb @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
        sep = rgb @ m.T
        t = intensity / 100.0
        out = pixels.copy()
        out[..., :3] = np.clip(np.rint(gray * (1 - t) + sep * t), 0, 255).astype(np.uint8)
        return out


class Posterize(Effect):
    key, label, category = "posterize", tr('Posterize'), "adjust"
    params = [Param("levels", tr('Levels'), "int", 4, 2, 64)]

    def apply(self, pixels, levels):
        step = 255.0 / (levels - 1)
        return apply_lut(pixels, _to_lut(np.rint(_X / 255.0 * (levels - 1)) * step))


ADJUSTMENTS = [BrightnessContrast(), Levels(), Curves(), HueSaturation(), InvertColors(),
               Grayscale(), Sepia(), Posterize()]
