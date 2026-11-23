"""Efectos: desenfoque, enfoque, pixelado y ruido (siempre con alfa premultiplicado)."""

from __future__ import annotations

from ..i18n import tr

import numpy as np
from scipy import ndimage

from .base import Effect, Param


def _premultiply(pixels):
    a = pixels[..., 3:4].astype(np.float32) / 255.0
    return np.concatenate([pixels[..., :3].astype(np.float32) * a, a * 255.0], axis=2)


def _unpremultiply(pm):
    a = pm[..., 3:4] / 255.0
    rgb = np.zeros_like(pm[..., :3])
    np.divide(pm[..., :3], a, out=rgb, where=a > 1e-6)
    out = np.concatenate([rgb, pm[..., 3:4]], axis=2)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def gaussian_blur_pm(pm: np.ndarray, radius: float) -> np.ndarray:
    # el «radio» de Paint.NET equivale aproximadamente a 2·sigma
    return ndimage.gaussian_filter(pm, sigma=(radius / 2.0, radius / 2.0, 0), mode="nearest")


class GaussianBlur(Effect):
    key, label, category, group = "gaussian_blur", tr('Gaussian blur'), "effect", "blurs"
    params = [Param("radius", tr('Radius'), "float", 4.0, 0.0, 200.0)]

    def apply(self, pixels, radius):
        if radius <= 0:
            return pixels.copy()
        return _unpremultiply(gaussian_blur_pm(_premultiply(pixels), radius))


class Sharpen(Effect):
    """Máscara de enfoque (unsharp mask)."""

    key, label, category, group = "sharpen", tr('Sharpen'), "effect", "photo"
    params = [
        Param("amount", tr('Amount (%)'), "int", 100, 0, 500),
        Param("radius", tr('Radius'), "float", 2.0, 0.1, 50.0),
    ]

    def apply(self, pixels, amount, radius):
        pm = _premultiply(pixels)
        blurred = gaussian_blur_pm(pm, radius)
        out = pm.copy()
        out[..., :3] = pm[..., :3] + (pm[..., :3] - blurred[..., :3]) * (amount / 100.0)
        out[..., :3] = np.clip(out[..., :3], 0, out[..., 3:4])  # el color no puede superar el alfa
        return _unpremultiply(out)


class Pixelate(Effect):
    key, label, category, group = "pixelate", tr('Pixelate'), "effect", "distort"
    params = [Param("size", tr('Cell size'), "int", 8, 1, 256)]

    def apply(self, pixels, size):
        h, w = pixels.shape[:2]
        pm = _premultiply(pixels)
        ph, pw = -(-h // size) * size, -(-w // size) * size
        padded = np.pad(pm, ((0, ph - h), (0, pw - w), (0, 0)), mode="edge")
        cells = padded.reshape(ph // size, size, pw // size, size, 4).mean(axis=(1, 3))
        big = np.repeat(np.repeat(cells, size, axis=0), size, axis=1)[:h, :w]
        return _unpremultiply(big)


class AddNoise(Effect):
    key, label, category, group = "noise", tr('Add noise'), "effect", "noise"
    params = [
        Param("intensity", tr('Intensity'), "int", 30, 0, 100),
        Param("color", tr('Color saturation'), "int", 0, 0, 100),
        Param("seed", tr('Seed'), "int", 0, 0, 2**31 - 1),
        Param("coverage", tr('Coverage'), "int", 100, 0, 100),
    ]

    def apply(self, pixels, intensity, color, seed, coverage=100):
        rng = np.random.default_rng(seed)
        h, w = pixels.shape[:2]
        sigma = intensity * 2.55 / 2.0
        luma = rng.normal(0.0, sigma, (h, w, 1)).astype(np.float32)
        chroma = rng.normal(0.0, sigma, (h, w, 3)).astype(np.float32)
        noise = luma * (1 - color / 100.0) + chroma * (color / 100.0)
        if coverage < 100:
            noise = noise * (rng.random((h, w, 1)) < coverage / 100.0)
        out = pixels.copy()
        out[..., :3] = np.clip(np.rint(pixels[..., :3].astype(np.float32) + noise), 0, 255).astype(np.uint8)
        return out


FILTERS = [GaussianBlur(), Sharpen(), Pixelate(), AddNoise()]
