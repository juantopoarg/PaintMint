"""Utilidades comunes de los efectos: remapeo de píxeles, celdas de Voronoi, mezcla y ruido."""

from __future__ import annotations

from ..i18n import tr

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from .base import Param
from .filters import _premultiply, _unpremultiply

LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)

EDGE_CHOICES = [("clamp", tr('Clamp')), ("wrap", tr('Wrap')), ("mirror", tr('Mirror')), ("transparent", tr('Transparent'))]
_MODE = {"clamp": "nearest", "wrap": "grid-wrap", "mirror": "mirror", "transparent": "constant"}
BLEND_CHOICES = [("overwrite", tr('Overwrite')), ("multiply", tr('Multiply')), ("screen", tr('Screen')),
                 ("overlay", tr('Overlay')), ("additive", tr('Additive'))]


def edge_param(default="clamp"):
    return Param("edge", tr('Edge behavior'), "choice", default, choices=EDGE_CHOICES)


def center_params():
    return [Param("cx", tr('Center X (%)'), "float", 50.0, 0.0, 100.0),
            Param("cy", tr('Center Y (%)'), "float", 50.0, 0.0, 100.0)]


def seed_param():
    return Param("seed", tr('Seed'), "int", 0, 0, 2**31 - 1)


def luma(pixels) -> np.ndarray:
    return pixels[..., :3].astype(np.float32) @ LUMA


def grid(h, w):
    yy, xx = np.mgrid[0:h, 0:w]
    return yy.astype(np.float32), xx.astype(np.float32)


def center_of(h, w, cx, cy):
    return (h - 1) * cy / 100.0, (w - 1) * cx / 100.0


def warp(pixels, sy, sx, edge="clamp", order=1):
    """Muestrea ``pixels`` en las coordenadas (sy, sx) con alfa premultiplicado."""
    pm = _premultiply(pixels)
    out = np.empty_like(pm)
    for c in range(4):
        out[..., c] = ndimage.map_coordinates(pm[..., c], [sy, sx], order=order, mode=_MODE[edge], cval=0.0)
    return _unpremultiply(out)


def shifted_average(pixels, offsets, edge="clamp"):
    """Promedio de copias desplazadas (dy, dx) — base de varios desenfoques."""
    h, w = pixels.shape[:2]
    yy, xx = grid(h, w)
    pm = _premultiply(pixels)
    acc = np.zeros_like(pm)
    for dy, dx in offsets:
        for c in range(4):
            acc[..., c] += ndimage.map_coordinates(pm[..., c], [yy + dy, xx + dx], order=1, mode=_MODE[edge])
    return _unpremultiply(acc / max(1, len(offsets)))


def mix(a, b, t):
    """Mezcla uint8 de ``a`` hacia ``b`` con t en 0..1 (solo RGB; conserva el alfa de ``a``)."""
    out = a.copy()
    out[..., :3] = np.clip(np.rint(a[..., :3].astype(np.float32) * (1 - t) + b[..., :3].astype(np.float32) * t),
                           0, 255).astype(np.uint8)
    return out


def gray_to_rgba(g, alpha):
    g = np.clip(np.rint(g), 0, 255).astype(np.uint8)
    return np.dstack([g, g, g, alpha])


def with_rgb(pixels, rgb):
    out = pixels.copy()
    out[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    return out


def rng_noise(h, w, scale, rng):
    """Ruido suave (cúbico sobre una malla aleatoria) con desviación ≈ 1; ``scale`` ≈ sigma en píxeles."""
    cell = max(1.0, scale * 2.5)
    gh, gw = int(h / cell) + 4, int(w / cell) + 4
    low = rng.standard_normal((gh, gw)).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    coords = [yy.astype(np.float32) / cell + 1, xx.astype(np.float32) / cell + 1]
    n = ndimage.map_coordinates(low, coords, order=3, mode="nearest")
    return n / 0.85 if cell > 1.0 else n


# -- Voronoi ----------------------------------------------------------------
def jitter_centers(h, w, size, jitter, rng, hexagonal=False):
    size = max(2.0, float(size))
    dy = size * (0.866 if hexagonal else 1.0)
    ys = np.arange(-dy, h + dy, dy)
    pts = []
    for i, y in enumerate(ys):
        off = size / 2 if hexagonal and i % 2 else 0.0
        xs = np.arange(-size + off, w + size, size)
        for x in xs:
            pts.append((y, x))
    pts = np.array(pts, dtype=np.float32)
    pts += (rng.random(pts.shape).astype(np.float32) - 0.5) * size * jitter
    return pts


def voronoi(h, w, centers):
    """Índice de la celda más cercana y distancia aproximada al borde de la celda."""
    tree = cKDTree(centers)
    yy, xx = np.mgrid[0:h, 0:w]
    pts = np.column_stack([yy.ravel(), xx.ravel()]).astype(np.float32)
    d, idx = tree.query(pts, k=2)
    return idx[:, 0].reshape(h, w), ((d[:, 1] - d[:, 0]) / 2).reshape(h, w).astype(np.float32), d[:, 0].reshape(h, w)


def cell_means(pm, labels, n):
    counts = np.maximum(np.bincount(labels.ravel(), minlength=n), 1)
    out = np.empty((n, pm.shape[2]), dtype=np.float32)
    for c in range(pm.shape[2]):
        out[:, c] = np.bincount(labels.ravel(), weights=pm[..., c].ravel(), minlength=n) / counts
    return out


# -- Mezcla de efectos de renderizado -----------------------------------------
def render_blend(base, rgb, mode):
    b = base[..., :3].astype(np.float32)
    if mode == "overwrite":
        return np.dstack([np.clip(np.rint(rgb), 0, 255).astype(np.uint8), np.full(base.shape[:2], 255, np.uint8)])
    if mode == "multiply":
        c = b * rgb / 255.0
    elif mode == "screen":
        c = 255.0 - (255.0 - b) * (255.0 - rgb) / 255.0
    elif mode == "overlay":
        c = np.where(b < 128, 2 * b * rgb / 255.0, 255.0 - 2 * (255.0 - b) * (255.0 - rgb) / 255.0)
    else:
        c = b + rgb
    return with_rgb(base, c)


def hsv_to_rgb(hh, ss, vv):
    i = np.floor(hh * 6).astype(int) % 6
    f = hh * 6 - np.floor(hh * 6)
    p, q, t = vv * (1 - ss), vv * (1 - f * ss), vv * (1 - (1 - f) * ss)
    r = np.choose(i, [vv, q, p, p, t, vv])
    g = np.choose(i, [t, vv, vv, q, p, p])
    b = np.choose(i, [p, p, t, vv, vv, q])
    return np.dstack([r, g, b]) * 255.0
