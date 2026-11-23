"""Efectos > Desenfoques, Color, Ruido, Objeto y Foto."""

from __future__ import annotations

from ..i18n import tr

import numpy as np
from scipy import ndimage, signal

from .base import Effect, Param
from .filters import _premultiply, _unpremultiply, gaussian_blur_pm
from .fxutil import (LUMA, center_of, center_params, edge_param, gray_to_rgba, grid, luma, mix, seed_param,
                     shifted_average, warp, with_rgb)


def _disk(radius):
    r = int(np.ceil(radius))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    k = (yy ** 2 + xx ** 2 <= radius ** 2 + 0.25).astype(np.float32)
    return k / k.sum()


def _conv_pm(pm, kernel):
    out = np.empty_like(pm)
    for c in range(pm.shape[2]):
        out[..., c] = signal.fftconvolve(pm[..., c], kernel, mode="same")
    return np.maximum(out, 0)


# ---------------------------------------------------------------- Desenfoques
class BokehBlur(Effect):
    key, label, category, group = "bokeh_blur", tr('Bokeh blur'), "effect", "blurs"
    params = [Param("radius", tr('Radius'), "float", 10.0, 0.0, 100.0),
              Param("boost", tr('Gamma boost'), "int", 0, 0, 100)]

    def apply(self, pixels, radius, boost):
        if radius < 0.5:
            return pixels.copy()
        wgt = (1.0 + boost / 10.0 * (luma(pixels) / 255.0) ** 2)[..., None]
        pm = _premultiply(pixels) * wgt
        k = _disk(radius)
        out = _conv_pm(pm, k)
        norm = np.maximum(_conv_pm(np.dstack([wgt, wgt, wgt, wgt]).astype(np.float32), k), 1e-6)
        return _unpremultiply(out / norm)


class FragmentBlur(Effect):
    key, label, category, group = "fragment_blur", tr('Fragment blur'), "effect", "blurs"
    params = [Param("count", tr('Fragment count'), "int", 4, 2, 50),
              Param("distance", tr('Distance'), "float", 10.0, 0.0, 100.0),
              Param("rotation", tr('Rotation'), "float", 0.0, 0.0, 360.0)]

    def apply(self, pixels, count, distance, rotation):
        a = np.deg2rad(rotation) + np.arange(count) * 2 * np.pi / count
        return shifted_average(pixels, [(distance * np.sin(t), distance * np.cos(t)) for t in a])


def _percentile_blur(pixels, radius, percentile):
    size = 2 * int(radius) + 1
    pm = _premultiply(pixels)
    out = np.empty_like(pm)
    for c in range(4):
        out[..., c] = ndimage.percentile_filter(pm[..., c], percentile, size=size, mode="nearest")
    return _unpremultiply(out)


class MedianBlur(Effect):
    key, label, category, group = "median_blur", tr('Median blur'), "effect", "blurs"
    params = [Param("radius", tr('Radius'), "int", 5, 1, 50), Param("percentile", tr('Percentile'), "int", 50, 0, 100)]

    def apply(self, pixels, radius, percentile):
        return _percentile_blur(pixels, radius, percentile)


class MotionBlur(Effect):
    key, label, category, group = "motion_blur", tr('Motion blur'), "effect", "blurs"
    params = [Param("angle", tr('Angle'), "float", 25.0, -180.0, 180.0),
              Param("distance", tr('Distance'), "int", 10, 1, 200),
              Param("centered", tr('Centered'), "bool", True), edge_param()]

    def apply(self, pixels, angle, distance, centered, edge):
        n = int(min(64, max(2, distance)))
        t = np.linspace(-0.5, 0.5, n) if centered else np.linspace(0, 1, n)
        a = np.deg2rad(angle)
        return shifted_average(pixels, [(-np.sin(a) * distance * s, np.cos(a) * distance * s) for s in t], edge)


class RadialBlur(Effect):
    key, label, category, group = "radial_blur", tr('Radial blur'), "effect", "blurs"
    params = [Param("angle", tr('Angle'), "float", 2.0, 0.0, 360.0)] + center_params()

    def apply(self, pixels, angle, cx, cy):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = center_of(h, w, cx, cy)
        acc = np.zeros((h, w, 4), np.float32)
        pm = _premultiply(pixels)
        n = 16
        for t in np.linspace(-0.5, 0.5, n):
            a = np.deg2rad(angle) * t
            c, s = np.cos(a), np.sin(a)
            sy = y0 + (yy - y0) * c - (xx - x0) * s
            sx = x0 + (yy - y0) * s + (xx - x0) * c
            for ch in range(4):
                acc[..., ch] += ndimage.map_coordinates(pm[..., ch], [sy, sx], order=1, mode="nearest")
        return _unpremultiply(acc / n)


class SketchBlur(Effect):
    key, label, category, group = "sketch_blur", tr('Sketch blur'), "effect", "blurs"
    params = [Param("radius", tr('Radius'), "int", 5, 1, 50), Param("percentile", tr('Percentile'), "int", 25, 0, 100),
              Param("smoothness", tr('Smoothness'), "float", 1.0, 0.0, 20.0)]

    def apply(self, pixels, radius, percentile, smoothness):
        out = _percentile_blur(pixels, radius, percentile)
        if smoothness > 0:
            out = _unpremultiply(gaussian_blur_pm(_premultiply(out), smoothness))
        return out


class SquareBlur(Effect):
    key, label, category, group = "square_blur", tr('Square blur'), "effect", "blurs"
    params = [Param("radius", tr('Radius'), "int", 5, 0, 200)]

    def apply(self, pixels, radius):
        if radius <= 0:
            return pixels.copy()
        pm = _premultiply(pixels)
        return _unpremultiply(ndimage.uniform_filter(pm, size=(2 * radius + 1, 2 * radius + 1, 1), mode="nearest"))


class SurfaceBlur(Effect):
    key, label, category, group = "surface_blur", tr('Surface blur'), "effect", "blurs"
    params = [Param("radius", tr('Radius'), "int", 6, 1, 100), Param("threshold", tr('Threshold'), "int", 15, 1, 100)]

    def apply(self, pixels, radius, threshold):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        pm = _premultiply(pixels)
        base = pm[..., :3]
        acc, wsum = pm.copy(), np.ones((h, w, 1), np.float32)
        golden = np.pi * (3 - np.sqrt(5))
        thr = threshold * 2.55
        for i in range(1, 25):
            r = radius * np.sqrt(i / 24.0)
            dy, dx = r * np.sin(i * golden), r * np.cos(i * golden)
            samp = np.stack([ndimage.map_coordinates(pm[..., c], [yy + dy, xx + dx], order=1, mode="nearest")
                             for c in range(4)], axis=2)
            diff = np.abs(samp[..., :3] - base).max(axis=2, keepdims=True)
            wgt = np.clip(1 - diff / thr, 0, 1)
            acc += samp * wgt
            wsum += wgt
        return _unpremultiply(acc / wsum)


class ZoomBlur(Effect):
    key, label, category, group = "zoom_blur", tr('Zoom blur'), "effect", "blurs"
    params = [Param("distance", tr('Distance'), "int", 10, 0, 100)] + center_params()

    def apply(self, pixels, distance, cx, cy):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = center_of(h, w, cx, cy)
        pm = _premultiply(pixels)
        acc = np.zeros_like(pm)
        n = 16
        for t in np.linspace(0, distance / 100.0, n):
            for c in range(4):
                acc[..., c] += ndimage.map_coordinates(pm[..., c], [y0 + (yy - y0) * (1 - t), x0 + (xx - x0) * (1 - t)],
                                                       order=1, mode="nearest")
        return _unpremultiply(acc / n)


# ---------------------------------------------------------------------- Color
_BAYER = {2: np.array([[0, 2], [3, 1]])}
_BAYER[4] = np.block([[4 * _BAYER[2] + v for v in row] for row in ([0, 2], [3, 1])])
_BAYER[8] = np.block([[4 * _BAYER[4] + v for v in row] for row in ([0, 2], [3, 1])])


class OrderedDither(Effect):
    key, label, category, group = "ordered_dither", tr('Ordered dither'), "effect", "color"
    params = [Param("matrix", tr('Matrix'), "choice", 4, choices=[(2, "2×2"), (4, "4×4"), (8, "8×8")]),
              Param("levels", tr('Levels'), "int", 2, 2, 16), Param("strength", tr('Strength'), "int", 100, 0, 100)]

    def apply(self, pixels, matrix, levels, strength):
        h, w = pixels.shape[:2]
        m = _BAYER[matrix]
        thr = (m + 0.5) / (matrix * matrix) - 0.5
        thr = np.tile(thr, (-(-h // matrix), -(-w // matrix)))[:h, :w].astype(np.float32)[..., None]
        v = pixels[..., :3].astype(np.float32) / 255.0 * (levels - 1) + thr
        q = np.clip(np.floor(v + 0.5), 0, levels - 1) / (levels - 1) * 255.0
        return with_rgb(pixels, pixels[..., :3] * (1 - strength / 100.0) + q * (strength / 100.0))


class QuantizeDither(Effect):
    key, label, category, group = "quantize", tr('Quantize / dither'), "effect", "color"
    params = [Param("algorithm", tr('Algorithm'), "choice", "median", choices=[("median", tr('Median cut')), ("octree", "Octree")]),
              Param("colors", tr('Colors'), "int", 64, 2, 256), Param("dither", tr('Dithering level'), "int", 0, 0, 8),
              Param("threshold", tr('Transparency threshold'), "int", 0, 0, 255)]

    def apply(self, pixels, algorithm, colors, dither, threshold):
        from PIL import Image
        method = Image.Quantize.MEDIANCUT if algorithm == "median" else Image.Quantize.FASTOCTREE
        img = Image.fromarray(np.ascontiguousarray(pixels[..., :3]), "RGB")
        plain = np.asarray(img.quantize(colors, method=method, dither=Image.Dither.NONE).convert("RGB"))
        out = plain
        if dither:
            d = np.asarray(img.quantize(colors, method=method, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB"))
            out = np.rint(plain * (1 - dither / 8.0) + d * (dither / 8.0)).astype(np.uint8)
        res = pixels.copy()
        res[..., :3] = out
        if threshold:
            res[..., 3] = np.where(pixels[..., 3] < threshold, 0, 255)
        return res


# ---------------------------------------------------------------------- Ruido
class ReduceNoise(Effect):
    key, label, category, group = "reduce_noise", tr('Reduce noise'), "effect", "noise"
    params = [Param("radius", tr('Radius'), "int", 6, 1, 20), Param("strength", tr('Strength'), "float", 0.4, 0.0, 1.0)]

    def apply(self, pixels, radius, strength):
        size = 2 * max(1, radius // 3) + 1
        pm = _premultiply(pixels)
        med = np.stack([ndimage.median_filter(pm[..., c], size=size, mode="nearest") for c in range(4)], axis=2)
        return _unpremultiply(pm * (1 - strength) + med * strength)


# --------------------------------------------------------------------- Objeto
class DropShadow(Effect):
    key, label, category, group = "drop_shadow", tr('Drop shadow'), "effect", "object"
    params = [Param("radius", tr('Shadow radius'), "int", 6, 0, 100), Param("distance", tr('Distance'), "int", 6, 0, 200),
              Param("angle", tr('Angle'), "float", 45.0, -180.0, 180.0), Param("opacity", tr('Opacity'), "int", 50, 0, 100),
              Param("red", tr('Shadow red'), "int", 0, 0, 255), Param("green", tr('Shadow green'), "int", 0, 0, 255),
              Param("blue", tr('Shadow blue'), "int", 0, 0, 255),
              Param("only", tr('Only draw shadow'), "bool", False)]

    def apply(self, pixels, radius, distance, angle, opacity, red, green, blue, only):
        a = np.deg2rad(angle)
        alpha = pixels[..., 3].astype(np.float32) / 255.0
        sh = ndimage.shift(alpha, (-np.sin(a) * distance, np.cos(a) * distance), order=1, mode="constant", cval=0.0)
        if radius > 0:
            sh = ndimage.gaussian_filter(sh, radius / 2.0)
        sa = np.clip(sh * opacity / 100.0, 0, 1)
        src = np.zeros_like(alpha) if only else alpha
        oa = src + sa * (1 - src)
        col = np.array([red, green, blue], np.float32)
        rgb = np.zeros(pixels.shape[:2] + (3,), np.float32)
        base = pixels[..., :3].astype(np.float32)
        num = base * src[..., None] + col * (sa * (1 - src))[..., None]
        np.divide(num, oa[..., None], out=rgb, where=oa[..., None] > 1e-6)
        return np.dstack([np.clip(np.rint(rgb), 0, 255), np.clip(np.rint(oa * 255), 0, 255)]).astype(np.uint8)


# ----------------------------------------------------------------------- Foto
class Glow(Effect):
    key, label, category, group = "glow", tr('Glow'), "effect", "photo"
    params = [Param("radius", tr('Radius'), "int", 6, 1, 100), Param("brightness", tr('Brightness'), "int", 10, -100, 100),
              Param("contrast", tr('Contrast'), "int", 10, -100, 100)]

    def apply(self, pixels, radius, brightness, contrast):
        blur = _unpremultiply(gaussian_blur_pm(_premultiply(pixels), radius))[..., :3].astype(np.float32)
        c = 1.0 + contrast / 100.0
        glow = np.clip((blur - 128) * c + 128 + brightness * 2.55, 0, 255)
        base = pixels[..., :3].astype(np.float32)
        glow = glow * 0.6
        return with_rgb(pixels, 255 - (255 - base) * (255 - glow) / 255.0)


class RedEyeRemoval(Effect):
    key, label, category, group = "red_eye", tr('Red eye removal'), "effect", "photo"
    params = [Param("strength", tr('Strength'), "int", 50, 0, 100)]

    def apply(self, pixels, strength):
        rgb = pixels[..., :3].astype(np.float32)
        excess = rgb[..., 0] - np.maximum(rgb[..., 1], rgb[..., 2])
        mask = np.clip((excess - 40) / 60.0, 0, 1) * (strength / 100.0)
        out = rgb.copy()
        out[..., 0] = rgb[..., 0] * (1 - mask) + (rgb[..., 1] + rgb[..., 2]) / 2 * mask
        return with_rgb(pixels, out)


class SoftenPortrait(Effect):
    key, label, category, group = "soften_portrait", tr('Soften portrait'), "effect", "photo"
    params = [Param("softness", tr('Softness'), "int", 5, 0, 10), Param("lighting", tr('Lighting'), "int", 0, -20, 20),
              Param("warmth", tr('Warmth'), "int", 10, 0, 20)]

    def apply(self, pixels, softness, lighting, warmth):
        blur = _unpremultiply(gaussian_blur_pm(_premultiply(pixels), 1.0 + softness * 1.5))
        soft = mix(pixels, blur, 0.6 * softness / 10.0)[..., :3].astype(np.float32)
        soft = soft + lighting * 2.55
        soft[..., 0] += warmth * 0.8
        soft[..., 2] -= warmth * 0.8
        return with_rgb(pixels, soft)


class Straighten(Effect):
    key, label, category, group = "straighten", tr('Straighten'), "effect", "photo"
    params = [Param("angle", tr('Angle'), "float", 0.0, -45.0, 45.0),
              Param("sampling", tr('Sampling'), "choice", 3,
                    choices=[(3, tr('Bicubic')), (1, tr('Bilinear')), (0, tr('Nearest neighbor'))])]

    def apply(self, pixels, angle, sampling):
        if angle == 0:
            return pixels.copy()
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = (h - 1) / 2.0, (w - 1) / 2.0
        a = np.deg2rad(angle)
        c, s = np.cos(a), np.sin(a)
        sy = y0 + (yy - y0) * c - (xx - x0) * s
        sx = x0 + (yy - y0) * s + (xx - x0) * c
        pm = _premultiply(pixels)
        out = np.stack([ndimage.map_coordinates(pm[..., k], [sy, sx], order=sampling, mode="constant", cval=0.0)
                        for k in range(4)], axis=2)
        return _unpremultiply(np.clip(out, 0, 255))


class Vignette(Effect):
    key, label, category, group = "vignette", tr('Vignette'), "effect", "photo"
    params = center_params() + [Param("radius", tr('Radius'), "int", 50, 1, 400), Param("strength", tr('Strength'), "int", 50, 0, 100)]

    def apply(self, pixels, cx, cy, radius, strength):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = center_of(h, w, cx, cy)
        r_px = max(1.0, radius / 100.0 * np.hypot(h, w) / 2.0)
        d = np.clip(np.hypot(yy - y0, xx - x0) / r_px, 0, 1) ** 2 * (strength / 100.0)
        return with_rgb(pixels, pixels[..., :3].astype(np.float32) * (1 - d)[..., None])


BLUR_FX = [BokehBlur(), FragmentBlur(), MedianBlur(), MotionBlur(), RadialBlur(), SketchBlur(), SquareBlur(),
           SurfaceBlur(), ZoomBlur()]
OTHER_FX = [OrderedDither(), QuantizeDither(), ReduceNoise(), DropShadow(), Glow(), RedEyeRemoval(), SoftenPortrait(),
            Straighten(), Vignette()]
