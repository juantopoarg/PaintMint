"""Efectos > Distorsionar y Artístico."""

from __future__ import annotations

from ..i18n import tr

import numpy as np
from scipy import ndimage

from .base import Effect, Param
from .filters import _premultiply, _unpremultiply, gaussian_blur_pm
from .fxutil import (cell_means, center_of, center_params, edge_param, gray_to_rgba, grid, jitter_centers, luma, mix,
                     rng_noise, seed_param, voronoi, warp, with_rgb)


# ------------------------------------------------------------- Distorsionar
class Bulge(Effect):
    key, label, category, group = "bulge", tr('Bulge'), "effect", "distort"
    params = [Param("amount", tr('Bulge'), "int", 45, -200, 100)] + center_params() + [edge_param()]

    def apply(self, pixels, amount, cx, cy, edge):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = center_of(h, w, cx, cy)
        R = max(1.0, min(h, w) / 2.0)
        dy, dx = yy - y0, xx - x0
        r = np.hypot(dy, dx) / R
        f = np.where(r < 1, 1 - amount / 100.0 * (1 - r ** 2), 1.0)
        return warp(pixels, y0 + dy * f, x0 + dx * f, edge)


class Crystalize(Effect):
    key, label, category, group = "crystalize", tr('Crystalize'), "effect", "distort"
    params = [Param("size", tr('Cell size'), "int", 16, 2, 100), seed_param()]

    def apply(self, pixels, size, seed):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        lab, _, _ = voronoi(h, w, jitter_centers(h, w, size, 1.0, rng))
        pm = _premultiply(pixels)
        means = cell_means(pm, lab, lab.max() + 1)
        return _unpremultiply(means[lab])


class Dents(Effect):
    key, label, category, group = "dents", tr('Dents'), "effect", "distort"
    params = [Param("scale", tr('Scale'), "float", 25.0, 1.0, 200.0), Param("refraction", tr('Refraction'), "float", 10.0, 0.0, 100.0),
              Param("detail", tr('Detail'), "int", 2, 1, 5), seed_param()]

    def apply(self, pixels, scale, refraction, detail, seed):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        ny, nx = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
        for o in range(detail):
            k = 0.5 ** o
            ny += k * rng_noise(h, w, scale / (2 ** o), rng)
            nx += k * rng_noise(h, w, scale / (2 ** o), rng)
        yy, xx = grid(h, w)
        return warp(pixels, yy + ny * refraction / 2, xx + nx * refraction / 2, "mirror")


class FrostedGlass(Effect):
    key, label, category, group = "frosted_glass", tr('Frosted glass'), "effect", "distort"
    params = [Param("max_radius", tr('Maximum scatter radius'), "int", 4, 0, 100),
              Param("min_radius", tr('Minimum scatter radius'), "int", 0, 0, 100),
              Param("smoothness", tr('Smoothness'), "float", 0.0, 0.0, 20.0), seed_param()]

    def apply(self, pixels, max_radius, min_radius, smoothness, seed):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        hi, lo = max(max_radius, min_radius), min(max_radius, min_radius)
        r = rng.uniform(lo, hi, (h, w)).astype(np.float32)
        a = rng.uniform(0, 2 * np.pi, (h, w)).astype(np.float32)
        yy, xx = grid(h, w)
        out = warp(pixels, yy + r * np.sin(a), xx + r * np.cos(a), "clamp")
        if smoothness > 0:
            out = _unpremultiply(gaussian_blur_pm(_premultiply(out), smoothness))
        return out


class Morphology(Effect):
    key, label, category, group = "morphology", tr('Morphology'), "effect", "distort"
    params = [Param("mode", tr('Mode'), "choice", "erode", choices=[("erode", tr('Erode')), ("dilate", tr('Dilate'))]),
              Param("width", tr('Width'), "int", 3, 1, 50), Param("height", tr('Height'), "int", 3, 1, 50),
              Param("linked", tr('Linked'), "bool", True)]

    def apply(self, pixels, mode, width, height, linked):
        hh = width if linked else height
        fn = ndimage.grey_erosion if mode == "erode" else ndimage.grey_dilation
        pm = _premultiply(pixels)
        out = np.stack([fn(pm[..., c], size=(hh, width), mode="nearest") for c in range(4)], axis=2)
        return _unpremultiply(out)


class PolarInversion(Effect):
    key, label, category, group = "polar_inversion", tr('Polar inversion'), "effect", "distort"
    params = [Param("scale", tr('Scale'), "float", 2.0, 0.1, 10.0), Param("off_x", tr('Offset X (%)'), "float", 0.0, -100.0, 100.0),
              Param("off_y", tr('Offset Y (%)'), "float", 0.0, -100.0, 100.0), edge_param("mirror")]

    def apply(self, pixels, scale, off_x, off_y, edge):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = (h - 1) / 2.0 + off_y / 100.0 * h / 2, (w - 1) / 2.0 + off_x / 100.0 * w / 2
        dy, dx = yy - y0, xx - x0
        r2 = np.maximum(dy ** 2 + dx ** 2, 1e-3)
        k = (min(h, w) / 2.0) ** 2 * scale / r2
        return warp(pixels, y0 + dy * k, x0 + dx * k, edge)


class Spherize(Effect):
    key, label, category, group = "spherize", tr('Spherize'), "effect", "distort"
    params = [Param("amount", tr('Amount'), "float", 1.0, -2.0, 1.0), Param("radius", tr('Radius (%)'), "float", 100.0, 1.0, 200.0)] \
        + center_params() + [edge_param()]

    def apply(self, pixels, amount, radius, cx, cy, edge):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = center_of(h, w, cx, cy)
        R = max(1.0, min(h, w) / 2.0 * radius / 100.0)
        dy, dx = yy - y0, xx - x0
        r = np.minimum(np.hypot(dy, dx) / R, 1.0)
        z = np.sqrt(1 - r ** 2)
        f = np.where(np.hypot(dy, dx) < R, 1 - amount * (1 - z), 1.0)
        return warp(pixels, y0 + dy * f, x0 + dx * f, edge)


class TileReflection(Effect):
    key, label, category, group = "tile_reflection", tr('Tile reflection'), "effect", "distort"
    params = [Param("angle", tr('Angle'), "float", 45.0, -180.0, 180.0), Param("size", tr('Tile size'), "int", 40, 2, 200),
              Param("curvature", tr('Curvature'), "float", 8.0, 0.0, 50.0), edge_param("mirror")]

    def apply(self, pixels, angle, size, curvature, edge):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = (h - 1) / 2.0, (w - 1) / 2.0
        a = np.deg2rad(angle)
        c, s = np.cos(a), np.sin(a)
        u = (xx - x0) * c + (yy - y0) * s
        v = -(xx - x0) * s + (yy - y0) * c
        lu = (u / size) - np.floor(u / size) - 0.5
        lv = (v / size) - np.floor(v / size) - 0.5
        k = curvature / 50.0
        lu2 = lu * (1 + k * (4 * lu ** 2 - 1))
        lv2 = lv * (1 + k * (4 * lv ** 2 - 1))
        u2 = (np.floor(u / size) + 0.5 + lu2) * size
        v2 = (np.floor(v / size) + 0.5 + lv2) * size
        return warp(pixels, y0 + u2 * s + v2 * c, x0 + u2 * c - v2 * s, edge)


class Twist(Effect):
    key, label, category, group = "twist", tr('Twist'), "effect", "distort"
    params = [Param("amount", tr('Amount'), "float", 45.0, -720.0, 720.0), Param("size", tr('Size (%)'), "float", 100.0, 1.0, 200.0)] \
        + center_params() + [edge_param()]

    def apply(self, pixels, amount, size, cx, cy, edge):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = center_of(h, w, cx, cy)
        R = max(1.0, min(h, w) / 2.0 * size / 100.0)
        dy, dx = yy - y0, xx - x0
        r = np.minimum(np.hypot(dy, dx) / R, 1.0)
        t = np.deg2rad(amount) * (1 - r) ** 2
        c, s = np.cos(t), np.sin(t)
        return warp(pixels, y0 + dy * c - dx * s, x0 + dy * s + dx * c, edge)


class Waves(Effect):
    key, label, category, group = "waves", tr('Waves'), "effect", "distort"
    params = [Param("pattern", tr('Pattern'), "choice", "directional", choices=[("directional", tr('Directional')), ("ripple", tr('Ripple'))]),
              Param("waveform", tr('Waveform'), "choice", "sine", choices=[("sine", tr('Sine')), ("triangle", tr('Triangle'))]),
              Param("lobes", tr('Lobes'), "int", 5, 1, 50), Param("amount", tr('Amount'), "float", 10.0, 0.0, 100.0),
              Param("damping", tr('Damping'), "int", 0, 0, 100), Param("angle", tr('Angle'), "float", 0.0, 0.0, 360.0),
              Param("phase", tr('Phase'), "float", 0.0, 0.0, 360.0)] + center_params() + [edge_param()]

    def apply(self, pixels, pattern, waveform, lobes, amount, damping, angle, phase, cx, cy, edge):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        y0, x0 = center_of(h, w, cx, cy)
        dy, dx = yy - y0, xx - x0
        a = np.deg2rad(angle)
        if pattern == "ripple":
            r = np.hypot(dy, dx)
            pos, span = r, max(1.0, np.hypot(h, w) / 2.0)
        else:
            pos, span = dx * np.cos(a) + dy * np.sin(a), float(max(h, w))
        theta = 2 * np.pi * lobes * pos / span + np.deg2rad(phase)
        wave = np.sin(theta) if waveform == "sine" else 2 / np.pi * np.arcsin(np.sin(theta))
        wave = wave * amount * np.exp(-damping / 100.0 * 4 * np.abs(pos) / span)
        if pattern == "ripple":
            r = np.maximum(np.hypot(dy, dx), 1e-3)
            return warp(pixels, yy + dy / r * wave, xx + dx / r * wave, edge)
        return warp(pixels, yy - np.cos(a) * wave, xx + np.sin(a) * wave, edge)


# ----------------------------------------------------------------- Artístico
class InkSketch(Effect):
    key, label, category, group = "ink_sketch", tr('Ink sketch'), "effect", "artistic"
    params = [Param("outline", tr('Ink outline'), "int", 50, 0, 99), Param("coloring", tr('Coloring'), "int", 50, 0, 100)]

    def apply(self, pixels, outline, coloring):
        y = ndimage.gaussian_filter(luma(pixels), 0.8)
        mag = np.hypot(ndimage.sobel(y, axis=0), ndimage.sobel(y, axis=1)) / 4.0
        dark = np.clip(mag * (0.4 + outline / 12.0) / 255.0 * 4, 0, 1)
        base = 255 * (1 - coloring / 100.0) + pixels[..., :3].astype(np.float32) * (coloring / 100.0)
        return with_rgb(pixels, base * (1 - dark)[..., None])


class Linocut(Effect):
    key, label, category, group = "linocut", tr('Linocut'), "effect", "artistic"
    params = [Param("mode", tr('Line mode'), "choice", "parallel",
                    choices=[("parallel", tr('Parallel')), ("contour", tr('Contour')), ("cross", tr('Cross-hatch'))]),
              Param("angle", tr('Angle'), "float", 45.0, 0.0, 360.0), Param("spacing", tr('Line spacing'), "int", 8, 2, 60),
              Param("contrast", tr('Contrast'), "int", 50, 0, 100), Param("roughness", tr('Roughness'), "int", 20, 0, 100),
              seed_param()]

    def apply(self, pixels, mode, angle, spacing, contrast, roughness, seed):
        h, w = pixels.shape[:2]
        yy, xx = grid(h, w)
        rng = np.random.default_rng(seed)
        tone = np.clip(ndimage.gaussian_filter(luma(pixels), 1.5) / 255.0, 0, 1)
        tone = np.clip((tone - 0.5) * (1 + contrast / 25.0) + 0.5, 0, 1)

        def wave(a):
            t = np.deg2rad(a)
            u = (xx * np.cos(t) + yy * np.sin(t)) / spacing
            return np.abs(u - np.floor(u) - 0.5) * 2

        if mode == "contour":
            u = tone * 255 / (spacing * 2.0)
            pat = np.abs(u - np.floor(u) - 0.5) * 2
            ink = (1 - tone) > pat * 0.6
        else:
            pat = wave(angle)
            if mode == "cross":
                pat = np.minimum(pat, wave(angle + 90))
            pat = pat + (rng.random((h, w)).astype(np.float32) - 0.5) * roughness / 100.0
            ink = (1 - tone) > pat
        g = np.where(ink, 0, 255)
        return gray_to_rgba(g, pixels[..., 3])


class Mosaic(Effect):
    key, label, category, group = "mosaic", tr('Mosaic'), "effect", "artistic"
    params = [Param("shape", tr('Tile shape'), "choice", "square", choices=[("square", tr('Square')), ("hexagon", tr('Hexagon')), ("irregular", tr('Irregular'))]),
              Param("size", tr('Tile size'), "int", 16, 4, 100), Param("bevel", tr('Bevel depth'), "int", 30, 0, 100),
              Param("grout", tr('Grout width'), "int", 1, 0, 10), Param("jitter", tr('Lightness jitter'), "int", 10, 0, 100), seed_param()]

    def apply(self, pixels, shape, size, bevel, grout, jitter, seed):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        centers = jitter_centers(h, w, size, 0.9 if shape == "irregular" else 0.0, rng, hexagonal=shape == "hexagon")
        lab, edge, _ = voronoi(h, w, centers)
        pm = _premultiply(pixels)
        means = cell_means(pm, lab, len(centers))
        means[:, :3] *= (1 + (rng.random((len(centers), 1)) - 0.5) * jitter / 100.0 * 0.5)
        out = means[lab]
        shade = 1 - bevel / 100.0 * 0.6 * np.clip(1 - edge / max(1.0, size / 3.0), 0, 1)
        out[..., :3] *= shade[..., None]
        if grout > 0:
            g = edge < grout / 2.0
            out[g, :3] = 40.0 * out[g, 3:4] / 255.0
        return _unpremultiply(np.clip(out, 0, 255))


class OilPainting(Effect):
    key, label, category, group = "oil_painting", tr('Oil painting'), "effect", "artistic"
    params = [Param("brush", tr('Brush size'), "int", 3, 1, 8), Param("coarseness", tr('Coarseness'), "int", 30, 3, 255)]

    def apply(self, pixels, brush, coarseness):
        bins = int(min(coarseness, 32))
        size = 2 * brush + 1
        rgb = pixels[..., :3].astype(np.float32)
        q = np.minimum((luma(pixels) / 256.0 * bins).astype(int), bins - 1)
        best = np.full(q.shape, -1.0, np.float32)
        acc = np.zeros(pixels.shape[:2] + (3,), np.float32)
        for b in range(bins):
            m = (q == b).astype(np.float32)
            cnt = ndimage.uniform_filter(m, size=size, mode="nearest")
            upd = cnt > best
            if not upd.any():
                continue
            for c in range(3):
                s = ndimage.uniform_filter(m * rgb[..., c], size=size, mode="nearest")
                acc[..., c] = np.where(upd, s / np.maximum(cnt, 1e-6), acc[..., c])
            best = np.where(upd, cnt, best)
        return with_rgb(pixels, acc)


class PencilSketch(Effect):
    key, label, category, group = "pencil_sketch", tr('Pencil sketch'), "effect", "artistic"
    params = [Param("tip", tr('Pencil tip size'), "int", 2, 1, 20), Param("range", tr('Range'), "int", 0, -20, 20)]

    def apply(self, pixels, tip, range):
        g = luma(pixels)
        blur = ndimage.gaussian_filter(255 - g, tip * 2.0)
        sketch = np.clip(g * 255.0 / np.maximum(255.0 - blur, 1.0), 0, 255)
        sketch = np.clip(128 + (sketch - 128) * (1 + range / 20.0), 0, 255)
        return gray_to_rgba(sketch, pixels[..., 3])


class Pointillism(Effect):
    key, label, category, group = "pointillism", tr('Pointillism'), "effect", "artistic"
    params = [Param("size", tr('Cell size'), "int", 8, 3, 100), Param("fill", tr('Cell fill'), "int", 80, 10, 100),
              Param("jitter", tr('Placement jitter'), "int", 50, 0, 100), seed_param()]

    def apply(self, pixels, size, fill, jitter, seed):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        centers = jitter_centers(h, w, size, jitter / 100.0, rng)
        lab, _, dist = voronoi(h, w, centers)
        pm = _premultiply(pixels)
        means = cell_means(pm, lab, len(centers))
        inside = dist <= size / 2.0 * fill / 100.0
        out = np.where(inside[..., None], means[lab][..., :3], 255.0)
        a = np.where(inside, means[lab][..., 3], 255.0 * (pixels[..., 3] > 0))
        res = np.dstack([out, a])
        return np.clip(np.rint(res), 0, 255).astype(np.uint8)


class StainedGlass(Effect):
    key, label, category, group = "stained_glass", tr('Stained glass'), "effect", "artistic"
    params = [Param("size", tr('Cell size'), "int", 20, 4, 100), Param("border", tr('Border width'), "int", 2, 0, 20),
              Param("bevel", tr('Bevel depth'), "int", 40, 0, 100), seed_param()]

    def apply(self, pixels, size, border, bevel, seed):
        h, w = pixels.shape[:2]
        rng = np.random.default_rng(seed)
        centers = jitter_centers(h, w, size, 0.9, rng)
        lab, edge, _ = voronoi(h, w, centers)
        pm = _premultiply(pixels)
        out = cell_means(pm, lab, len(centers))[lab]
        out[..., :3] *= (1 - bevel / 100.0 * 0.5 * np.clip(1 - edge / max(1.0, size / 3.0), 0, 1))[..., None]
        if border > 0:
            g = edge < border / 2.0
            out[g, :3] = 20.0 * out[g, 3:4] / 255.0
        return _unpremultiply(np.clip(out, 0, 255))


DISTORT_FX = [Bulge(), Crystalize(), Dents(), FrostedGlass(), Morphology(), PolarInversion(), Spherize(),
              TileReflection(), Twist(), Waves()]
ARTISTIC_FX = [InkSketch(), Linocut(), Mosaic(), OilPainting(), PencilSketch(), Pointillism(), StainedGlass()]
