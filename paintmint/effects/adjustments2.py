"""Ajustes adicionales del menú Ajustes de Paint.NET."""

from __future__ import annotations

from ..i18n import tr

import numpy as np

from .base import Effect, Param, apply_lut
from .fxutil import LUMA, with_rgb

_X = np.arange(256, dtype=np.float64)


class AutoLevel(Effect):
    key, label, category = "auto_level", tr('Auto-level'), "adjust"
    params = []

    def apply(self, pixels):
        opaque = pixels[..., 3] > 0
        if not opaque.any():
            return pixels.copy()
        y = pixels[..., :3].astype(np.float32) @ LUMA
        lo, hi = np.percentile(y[opaque], [0.5, 99.5])
        if hi - lo < 1:
            return pixels.copy()
        lut = np.clip((_X - lo) * 255.0 / (hi - lo), 0, 255)
        return apply_lut(pixels, np.rint(lut).astype(np.uint8))


class Exposure(Effect):
    key, label, category = "exposure", tr('Exposure'), "adjust"
    params = [Param("exposure", tr('Exposure (stops)'), "float", 0.0, -5.0, 5.0)]

    def apply(self, pixels, exposure):
        lin = np.where(_X / 255 <= 0.04045, _X / 255 / 12.92, ((_X / 255 + 0.055) / 1.055) ** 2.4) * 2.0 ** exposure
        lin = np.clip(lin, 0, 1)
        srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055) * 255
        return apply_lut(pixels, np.rint(srgb).astype(np.uint8))


class HighlightsShadows(Effect):
    key, label, category = "highlights_shadows", tr('Highlights and shadows'), "adjust"
    params = [Param("shadows", tr('Shadows'), "int", 0, -100, 100),
              Param("highlights", tr('Highlights'), "int", 0, -100, 100)]

    def apply(self, pixels, shadows, highlights):
        rgb = pixels[..., :3].astype(np.float32)
        y = (rgb @ LUMA / 255.0)[..., None]
        delta = shadows / 100.0 * 0.5 * (1 - y) ** 2 * 255 + highlights / 100.0 * 0.5 * y ** 2 * 255
        return with_rgb(pixels, rgb + delta)


class InvertAlpha(Effect):
    key, label, category = "invert_alpha", tr('Invert alpha'), "adjust"
    params = []

    def apply(self, pixels):
        out = pixels.copy()
        out[..., 3] = 255 - pixels[..., 3]
        return out


class TemperatureTint(Effect):
    key, label, category = "temperature_tint", tr('Temperature and tint'), "adjust"
    params = [Param("temperature", tr('Temperature'), "int", 0, -100, 100),
              Param("tint", tr('Tint'), "int", 0, -100, 100)]

    def apply(self, pixels, temperature, tint):
        t, g = temperature / 100.0 * 0.25, tint / 100.0 * 0.25
        gains = np.array([1 + t, 1 - g, 1 - t], dtype=np.float32)
        return with_rgb(pixels, pixels[..., :3].astype(np.float32) * gains)


ADJUSTMENTS2 = [AutoLevel(), Exposure(), HighlightsShadows(), InvertAlpha(), TemperatureTint()]
