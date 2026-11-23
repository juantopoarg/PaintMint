"""Efectos > Renderizar y Estilizar."""

from __future__ import annotations

from ..i18n import tr

import numpy as np
from scipy import ndimage

from .base import Effect, Param
from .filters import _premultiply, _unpremultiply
from .fxutil import (BLEND_CHOICES, grid, hsv_to_rgb, luma, render_blend, rng_noise, seed_param, with_rgb)


def _blend_param():
    return Param("blend", tr('Blend mode'), "choice", "overwrite", choices=BLEND_CHOICES)


class Clouds(Effect):
    key, label, category, group = "clouds", tr('Clouds'), "effect", "render"
    params = [Param("scale", tr('Scale'), "int", 250, 2, 1000), Param("roughness", tr('Roughness'), "int", 50, 0, 100),
              seed_param(), _blend_param()]

    def apply(self, pixels, scale, roughness, seed, blend):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        total, amp, norm = np.zeros((h, w), np.float32), 1.0, 0.0
        for o in range(8):
            if scale / (2 ** o) < 0.6:
                break
            total += amp * rng_noise(h, w, scale / (2 ** o) / 2.0, rng)
            norm += amp
            amp *= 0.3 + roughness / 100.0 * 0.6
        v = np.clip(0.5 + total / (2.5 * norm), 0, 1) * 255.0
        return render_blend(pixels, np.dstack([v, v, v]), blend)


def _fractal_rgb(it, escaped, n, factor):
    t = it / n
    hue = (t * factor / 3.0) % 1.0
    rgb = hsv_to_rgb(hue, np.full_like(hue, 0.9), np.where(escaped, 1.0, 0.0))
    return rgb


class JuliaFractal(Effect):
    key, label, category, group = "julia", tr('Julia fractal'), "effect", "render"
    params = [Param("factor", tr('Factor'), "float", 4.0, 1.0, 10.0), Param("zoom", tr('Zoom'), "float", 1.0, 0.1, 50.0),
              Param("angle", tr('Angle'), "float", 0.0, -180.0, 180.0), Param("quality", tr('Quality'), "int", 2, 1, 5),
              _blend_param()]

    def apply(self, pixels, factor, zoom, angle, quality, blend):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        s = min(h, w) / 2.0 * zoom
        a = np.deg2rad(angle)
        x, y = (xx - (w - 1) / 2) / s, (yy - (h - 1) / 2) / s
        z = (x * np.cos(a) - y * np.sin(a)) + 1j * (x * np.sin(a) + y * np.cos(a))
        z = z * 1.6
        c = -0.8 + 0.156j
        n = 24 * quality
        it = np.zeros(z.shape, np.float32)
        alive = np.ones(z.shape, bool)
        for i in range(n):
            z[alive] = z[alive] ** 2 + c
            esc = alive & (np.abs(z) > 2)
            it[esc] = i + 1
            alive &= ~esc
        return render_blend(pixels, _fractal_rgb(it, it > 0, n, factor), blend)


class MandelbrotFractal(Effect):
    key, label, category, group = "mandelbrot", tr('Mandelbrot fractal'), "effect", "render"
    params = [Param("factor", tr('Factor'), "float", 4.0, 1.0, 10.0), Param("zoom", tr('Zoom'), "float", 1.0, 0.1, 50.0),
              Param("angle", tr('Angle'), "float", 0.0, -180.0, 180.0), Param("quality", tr('Quality'), "int", 2, 1, 5),
              Param("invert", tr('Invert colors'), "bool", False), _blend_param()]

    def apply(self, pixels, factor, zoom, angle, quality, invert, blend):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        s = min(h, w) / 2.0 * zoom
        a = np.deg2rad(angle)
        x, y = (xx - (w - 1) / 2) / s, (yy - (h - 1) / 2) / s
        c = ((x * np.cos(a) - y * np.sin(a)) * 1.8 - 0.5) + 1j * ((x * np.sin(a) + y * np.cos(a)) * 1.8)
        z = np.zeros_like(c)
        n = 24 * quality
        it = np.zeros(c.shape, np.float32)
        alive = np.ones(c.shape, bool)
        for i in range(n):
            z[alive] = z[alive] ** 2 + c[alive]
            esc = alive & (np.abs(z) > 2)
            it[esc] = i + 1
            alive &= ~esc
        rgb = _fractal_rgb(it, it > 0, n, factor)
        if invert:
            rgb = 255 - rgb
        return render_blend(pixels, rgb, blend)


class Turbulence(Effect):
    key, label, category, group = "turbulence", tr('Turbulence'), "effect", "render"
    params = [Param("octaves", tr('Octaves'), "int", 4, 1, 8), Param("period", tr('Period'), "int", 100, 2, 500),
              Param("noise", tr('Noise'), "choice", "turbulence", choices=[("turbulence", tr('Turbulence')), ("fractal", tr('Fractal sum'))]),
              seed_param(), _blend_param()]

    def apply(self, pixels, octaves, period, noise, seed, blend):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        total, amp, norm = np.zeros((h, w), np.float32), 1.0, 0.0
        for o in range(octaves):
            n = rng_noise(h, w, max(0.6, period / (2 ** o) / 2.0), rng)
            total += amp * (np.abs(n) if noise == "turbulence" else n)
            norm += amp
            amp *= 0.5
        total /= norm
        v = (np.clip(total / 1.6, 0, 1) if noise == "turbulence" else np.clip(0.5 + total / 4, 0, 1)) * 255.0
        return render_blend(pixels, np.dstack([v, v, v]), blend)


# ------------------------------------------------------------------ Estilizar
def _gradient(y, kind):
    if kind == "prewitt":
        gy, gx = ndimage.prewitt(y, axis=0), ndimage.prewitt(y, axis=1)
    else:
        gy, gx = ndimage.sobel(y, axis=0), ndimage.sobel(y, axis=1)
    return gy, gx


class EdgeDetect(Effect):
    key, label, category, group = "edge_detect", tr('Edge detect'), "effect", "stylize"
    params = [Param("strength", tr('Strength'), "int", 50, 0, 100), Param("blurring", tr('Blurring'), "float", 0.0, 0.0, 10.0),
              Param("algorithm", tr('Algorithm'), "choice", "sobel", choices=[("sobel", "Sobel"), ("prewitt", "Prewitt")]),
              Param("overlay", tr('Overlay edges'), "bool", False)]

    def apply(self, pixels, strength, blurring, algorithm, overlay):
        y = luma(pixels)
        if blurring > 0:
            y = ndimage.gaussian_filter(y, blurring)
        gy, gx = _gradient(y, algorithm)
        mag = np.hypot(gy, gx) / 4.0
        dark = np.clip(mag * (strength / 25.0) / 255.0 * 4, 0, 1)
        if overlay:
            return with_rgb(pixels, pixels[..., :3].astype(np.float32) * (1 - dark)[..., None])
        g = 255 * (1 - dark)
        return with_rgb(pixels, np.dstack([g, g, g]))


def _emboss(y, angle):
    a = np.deg2rad(angle)
    gy, gx = ndimage.sobel(y, axis=0), ndimage.sobel(y, axis=1)
    return (gx * np.cos(a) - gy * np.sin(a)) / 4.0


class Emboss(Effect):
    key, label, category, group = "emboss", tr('Emboss'), "effect", "stylize"
    params = [Param("angle", tr('Angle'), "float", 45.0, -180.0, 180.0)]

    def apply(self, pixels, angle):
        g = np.clip(128 + _emboss(luma(pixels), angle), 0, 255)
        return with_rgb(pixels, np.dstack([g, g, g]))


class Relief(Effect):
    key, label, category, group = "relief", tr('Relief'), "effect", "stylize"
    params = [Param("angle", tr('Angle'), "float", 45.0, -180.0, 180.0)]

    def apply(self, pixels, angle):
        d = _emboss(luma(pixels), angle)
        return with_rgb(pixels, pixels[..., :3].astype(np.float32) + d[..., None])


class Outline(Effect):
    key, label, category, group = "outline", tr('Outline'), "effect", "stylize"
    params = [Param("thickness", tr('Thickness'), "int", 3, 1, 50), Param("intensity", tr('Intensity'), "int", 50, 0, 100)]

    def apply(self, pixels, thickness, intensity):
        y = luma(pixels)
        size = 2 * thickness + 1
        grad = ndimage.grey_dilation(y, size=size, mode="nearest") - ndimage.grey_erosion(y, size=size, mode="nearest")
        dark = np.clip(grad / 255.0 * (intensity / 25.0), 0, 1)
        return with_rgb(pixels, pixels[..., :3].astype(np.float32) * (1 - dark)[..., None])


class Halftone(Effect):
    key, label, category, group = "halftone", tr('Halftone'), "effect", "stylize"
    params = [Param("pattern", tr('Pattern'), "choice", "dots", choices=[("dots", tr('Dots')), ("lines", tr('Lines')), ("squares", tr('Squares'))]),
              Param("mono", tr('Monochrome'), "bool", False), Param("size", tr('Cell size'), "int", 8, 3, 100),
              Param("angle", tr('Angle'), "float", 45.0, 0.0, 180.0), Param("softness", tr('Softness'), "int", 20, 0, 100)]

    def apply(self, pixels, pattern, mono, size, angle, softness):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)

        def plane(tone, ang):
            a = np.deg2rad(ang)
            u = (xx * np.cos(a) + yy * np.sin(a)) / size
            v = (-xx * np.sin(a) + yy * np.cos(a)) / size
            fu, fv = u - np.floor(u) - 0.5, v - np.floor(v) - 0.5
            if pattern == "dots":
                d, rmax = np.hypot(fu, fv), 0.7071
            elif pattern == "lines":
                d, rmax = np.abs(fv), 0.5
            else:
                d, rmax = np.maximum(np.abs(fu), np.abs(fv)), 0.5
            r = np.sqrt(np.clip(1 - tone, 0, 1)) * rmax
            soft = 0.02 + softness / 100.0 * 0.25
            ink = np.clip((r - d) / soft + 0.5, 0, 1)
            return 255.0 * (1 - ink)

        smooth = ndimage.gaussian_filter(pixels[..., :3].astype(np.float32), (size / 2.0, size / 2.0, 0)) / 255.0
        if mono:
            g = plane(ndimage.gaussian_filter(luma(pixels), size / 2.0) / 255.0, angle)
            return with_rgb(pixels, np.dstack([g, g, g]))
        chans = [plane(smooth[..., c], angle + off) for c, off in enumerate((15, 75, 0))]
        return with_rgb(pixels, np.dstack(chans))


RENDER_FX = [Clouds(), JuliaFractal(), MandelbrotFractal(), Turbulence()]
STYLIZE_FX = [EdgeDetect(), Emboss(), Halftone(), Outline(), Relief()]
