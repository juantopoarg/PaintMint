"""Primitivas de rasterizado con NumPy/Pillow (sin Qt).

Convención de coordenadas: el píxel ``(i, j)`` cubre el cuadrado
``[i, i+1) × [j, j+1)`` y su centro está en ``(i+0.5, j+0.5)``. Todas las
máscaras de cobertura son ``float32`` en 0..1 salvo que se indique ``uint8``.
"""

from __future__ import annotations

import math
from typing import Callable, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

Rect = Tuple[int, int, int, int]  # x0, y0, x1, y1 (x1/y1 exclusivos)

_SS_BUDGET = 24_000_000  # máx. de subpíxeles al supersamplear


# --------------------------------------------------------------------------
# Utilidades de rectángulos
# --------------------------------------------------------------------------
def clip_rect(rect: Rect, width: int, height: int) -> Rect:
    x0, y0, x1, y1 = rect
    return max(0, x0), max(0, y0), min(width, x1), min(height, y1)


def union_rect(a: Optional[Rect], b: Optional[Rect]) -> Optional[Rect]:
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def is_empty(rect: Optional[Rect]) -> bool:
    return rect is None or rect[2] <= rect[0] or rect[3] <= rect[1]


# --------------------------------------------------------------------------
# Supersampling con Pillow
# --------------------------------------------------------------------------
def _pick_ssaa(bw: int, bh: int) -> int:
    for s in (4, 2):
        if bw * bh * s * s <= _SS_BUDGET:
            return s
    return 1


def _supersample(region: Rect, draw_fn: Callable) -> np.ndarray:
    """Dibuja con ``draw_fn(draw, tx, ty, s)`` y devuelve cobertura float32 de la región.

    ``tx``/``ty`` convierten coordenadas de imagen a coordenadas del lienzo
    supersampleado (el centro de píxel de Pillow está en enteros, de ahí el -0.5).
    """
    x0, y0, x1, y1 = region
    bw, bh = x1 - x0, y1 - y0
    s = _pick_ssaa(bw, bh)
    img = Image.new("L", (bw * s, bh * s), 0)
    draw = ImageDraw.Draw(img)
    draw_fn(draw, lambda x: (x - x0) * s - 0.5, lambda y: (y - y0) * s - 0.5, s)
    arr = np.asarray(img, dtype=np.float32)
    if s > 1:
        arr = arr.reshape(bh, s, bw, s).mean(axis=(1, 3))
    return arr / 255.0


# --------------------------------------------------------------------------
# Máscaras para selecciones (uint8, tamaño completo)
# --------------------------------------------------------------------------
def rect_mask(h: int, w: int, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    m = np.zeros((h, w), dtype=np.uint8)
    xa, xb = sorted((int(round(x0)), int(round(x1))))
    ya, yb = sorted((int(round(y0)), int(round(y1))))
    xa, ya, xb, yb = clip_rect((xa, ya, xb, yb), w, h)
    if xb > xa and yb > ya:
        m[ya:yb, xa:xb] = 255
    return m


def ellipse_mask(h: int, w: int, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    m = np.zeros((h, w), dtype=np.uint8)
    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))
    rx, ry = (xb - xa) / 2.0, (yb - ya) / 2.0
    if rx < 0.5 or ry < 0.5:
        return m
    cx, cy = (xa + xb) / 2.0, (ya + yb) / 2.0
    rect = clip_rect((int(math.floor(xa)) - 1, int(math.floor(ya)) - 1,
                      int(math.ceil(xb)) + 1, int(math.ceil(yb)) + 1), w, h)
    if is_empty(rect):
        return m
    xs = np.arange(rect[0], rect[2], dtype=np.float32) + 0.5
    ys = np.arange(rect[1], rect[3], dtype=np.float32) + 0.5
    d = np.sqrt(((xs[None, :] - cx) / rx) ** 2 + ((ys[:, None] - cy) / ry) ** 2)
    cov = np.clip((1.0 - d) * min(rx, ry) + 0.5, 0.0, 1.0)
    m[rect[1]:rect[3], rect[0]:rect[2]] = np.rint(cov * 255).astype(np.uint8)
    return m


def polygon_mask(h: int, w: int, points: Sequence[Tuple[float, float]]) -> np.ndarray:
    m = np.zeros((h, w), dtype=np.uint8)
    if len(points) < 3:
        return m
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    rect = clip_rect((int(math.floor(min(xs))) - 1, int(math.floor(min(ys))) - 1,
                      int(math.ceil(max(xs))) + 1, int(math.ceil(max(ys))) + 1), w, h)
    if is_empty(rect):
        return m

    def draw(d, tx, ty, s):
        d.polygon([(tx(px), ty(py)) for px, py in points], fill=255)

    cov = _supersample(rect, draw)
    m[rect[1]:rect[3], rect[0]:rect[2]] = np.rint(cov * 255).astype(np.uint8)
    return m


# --------------------------------------------------------------------------
# Mezcla de color
# --------------------------------------------------------------------------
def over(dst: np.ndarray, src_rgb, src_a: np.ndarray) -> np.ndarray:
    """Compone ``src`` sobre ``dst`` (uint8 RGBA recto). ``src_a`` float 0..1 (h, w).

    ``src_rgb`` puede ser una tupla (r, g, b) o un arreglo (h, w, 3) en 0..255.
    """
    da = dst[..., 3].astype(np.float32) / 255.0
    sa = src_a.astype(np.float32)
    oa = sa + da * (1.0 - sa)
    w_dst = da * (1.0 - sa)
    src_rgb = np.asarray(src_rgb, dtype=np.float32)
    num = src_rgb * sa[..., None] + dst[..., :3].astype(np.float32) * w_dst[..., None]
    rgb = np.zeros_like(num)
    np.divide(num, oa[..., None], out=rgb, where=oa[..., None] > 1e-6)
    out = np.empty_like(dst)
    out[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(np.rint(oa * 255.0), 0, 255).astype(np.uint8)
    return out


def erase_alpha(dst: np.ndarray, amount: np.ndarray) -> np.ndarray:
    """Reduce el alfa de ``dst`` en ``amount`` (float 0..1)."""
    out = dst.copy()
    a = dst[..., 3].astype(np.float32) * (1.0 - amount.astype(np.float32))
    out[..., 3] = np.clip(np.rint(a), 0, 255).astype(np.uint8)
    return out


def lerp_premult(snap: np.ndarray, block: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Interpolación ``snap -> block`` con peso ``t`` (float 0..1) en espacio premultiplicado.

    Los píxeles con t=0 y t=1 se copian exactos para evitar deriva por redondeo.
    """
    out = np.where((t >= 1.0)[..., None], block, snap)
    part = (t > 0.0) & (t < 1.0)
    if part.any():
        s, b, tt = snap[part].astype(np.float32), block[part].astype(np.float32), t[part][:, None]
        sa, ba = s[:, 3:4] / 255.0, b[:, 3:4] / 255.0
        pa = sa + (ba - sa) * tt
        pc = s[:, :3] * sa + (b[:, :3] * ba - s[:, :3] * sa) * tt
        rgb = np.zeros_like(pc)
        np.divide(pc, pa, out=rgb, where=pa > 1e-6)
        res = np.concatenate([rgb, pa * 255.0], axis=1)
        out[part] = np.clip(np.rint(res), 0, 255).astype(np.uint8)
    return out


# --------------------------------------------------------------------------
# Pincel / lápiz
# --------------------------------------------------------------------------
def dab(cx: float, cy: float, size: float, hardness: float, antialias: bool = True):
    """Huella circular centrada en (cx, cy). Devuelve ``(x0, y0, cobertura)``."""
    r = max(0.5, size / 2.0)
    if not antialias:  # lápiz: un píxel entero se pinta o no se pinta
        cx, cy = math.floor(cx) + 0.5, math.floor(cy) + 0.5
    x0, y0 = int(math.floor(cx - r - 1)), int(math.floor(cy - r - 1))
    x1, y1 = int(math.ceil(cx + r + 1)), int(math.ceil(cy + r + 1))
    xs = np.arange(x0, x1, dtype=np.float32) + 0.5
    ys = np.arange(y0, y1, dtype=np.float32) + 0.5
    d = np.hypot(xs[None, :] - cx, ys[:, None] - cy)
    if not antialias:
        cov = (d <= r).astype(np.float32)
    else:
        edge = max(1.0, r * (1.0 - min(1.0, max(0.0, hardness))))
        cov = np.clip((r - d) / edge + 0.5, 0.0, 1.0).astype(np.float32)
    return x0, y0, cov


def stamp(cov: np.ndarray, cx: float, cy: float, size: float, hardness: float, antialias: bool) -> Optional[Rect]:
    """Estampa una huella en el búfer de cobertura (máximo, no acumula). Devuelve el área tocada."""
    h, w = cov.shape
    x0, y0, d = dab(cx, cy, size, hardness, antialias)
    rect = clip_rect((x0, y0, x0 + d.shape[1], y0 + d.shape[0]), w, h)
    if is_empty(rect):
        return None
    sub = d[rect[1] - y0:rect[3] - y0, rect[0] - x0:rect[2] - x0]
    region = cov[rect[1]:rect[3], rect[0]:rect[2]]
    np.maximum(region, sub, out=region)
    return rect


def stamp_segment(cov: np.ndarray, p0, p1, size: float, hardness: float, antialias: bool,
                  include_start: bool = True) -> Optional[Rect]:
    """Estampa huellas a lo largo de ``p0 -> p1`` con espaciado ~10 % del tamaño."""
    spacing = max(0.5, size * 0.1)
    dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = max(1, int(math.ceil(dist / spacing)))
    dirty = None
    for i in range(0 if include_start else 1, n + 1):
        t = i / n
        r = stamp(cov, p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t, size, hardness, antialias)
        dirty = union_rect(dirty, r)
    return dirty


# --------------------------------------------------------------------------
# Relleno por inundación
# --------------------------------------------------------------------------
def flood_mask(pixels: np.ndarray, x: int, y: int, tolerance: float, contiguous: bool = True) -> np.ndarray:
    """Máscara booleana de píxeles similares al de (x, y). ``tolerance`` en % (0..100)."""
    from scipy import ndimage

    h, w = pixels.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return np.zeros((h, w), dtype=bool)
    seed = pixels[y, x].astype(np.int16)
    diff = np.abs(pixels.astype(np.int16) - seed).max(axis=2)
    similar = diff <= (tolerance / 100.0) * 255.0
    if not contiguous:
        return similar
    labels, _ = ndimage.label(similar)
    lab = labels[y, x]
    return labels == lab if lab else np.zeros((h, w), dtype=bool)


# --------------------------------------------------------------------------
# Degradados
# --------------------------------------------------------------------------
GRADIENT_KINDS = ("linear", "reflected", "diamond", "radial", "conical")


def gradient_rgba(region: Rect, kind: str, p0, p1, c0, c1) -> np.ndarray:
    """Degradado RGBA uint8 de ``c0`` a ``c1`` sobre ``region`` (interpolación premultiplicada)."""
    x0, y0, x1, y1 = region
    xs = np.arange(x0, x1, dtype=np.float32) + 0.5 - p0[0]
    ys = np.arange(y0, y1, dtype=np.float32) + 0.5 - p0[1]
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    X, Y = np.meshgrid(xs, ys)
    if length < 1e-6:
        t = np.zeros_like(X)
    elif kind == "linear":
        t = (X * dx + Y * dy) / (length * length)
    elif kind == "reflected":
        t = np.abs((X * dx + Y * dy) / (length * length))
    elif kind == "radial":
        t = np.hypot(X, Y) / length
    elif kind == "diamond":
        t = (np.abs(X) + np.abs(Y)) / length
    elif kind == "conical":
        ang0 = math.atan2(dy, dx)
        t = ((np.arctan2(Y, X) - ang0) % (2 * math.pi)) / (2 * math.pi)
    else:
        raise ValueError(f"Unknown gradient type: {kind}")
    t = np.clip(t, 0.0, 1.0).astype(np.float32)[..., None]
    c0 = np.asarray(c0, dtype=np.float32)
    c1 = np.asarray(c1, dtype=np.float32)
    a0, a1 = c0[3] / 255.0, c1[3] / 255.0
    pa = a0 + (a1 - a0) * t
    pc = c0[:3] * a0 * (1 - t) + c1[:3] * a1 * t
    rgb = np.zeros_like(pc)
    np.divide(pc, pa, out=rgb, where=pa > 1e-6)
    out = np.concatenate([rgb, pa * 255.0], axis=2)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# Formas
# --------------------------------------------------------------------------
SHAPE_KINDS = ("line", "rectangle", "rounded_rectangle", "ellipse")


def shape_coverage(h: int, w: int, kind: str, p0, p1, width: float, want_outline: bool,
                   want_fill: bool, radius: float = 12.0):
    """Cobertura de una forma. Devuelve ``(rect, contorno|None, relleno|None)``.

    El contorno está centrado sobre el borde de la caja p0-p1.
    """
    if kind not in SHAPE_KINDS:
        raise ValueError(f"Unknown shape type: {kind}")
    width = max(1.0, float(width))
    xa, xb = sorted((p0[0], p1[0]))
    ya, yb = sorted((p0[1], p1[1]))
    pad = int(math.ceil(width / 2.0)) + 2
    rect = clip_rect((int(math.floor(xa)) - pad, int(math.floor(ya)) - pad,
                      int(math.ceil(xb)) + pad, int(math.ceil(yb)) + pad), w, h)
    if is_empty(rect):
        return None, None, None

    def box(d, tx, ty, s, grow, fill):
        ex0, ey0, ex1, ey1 = xa - grow, ya - grow, xb + grow, yb + grow
        if ex1 <= ex0 or ey1 <= ey0:
            return
        c = [(tx(ex0), ty(ey0)), (tx(ex1), ty(ey0)), (tx(ex1), ty(ey1)), (tx(ex0), ty(ey1))]
        if kind == "rectangle":
            # Pillow rellena de forma inclusiva en el borde alto: se compensa con media subpíxel
            i = 0.5 / s
            d.polygon([(tx(ex0 + i), ty(ey0 + i)), (tx(ex1 - i), ty(ey0 + i)),
                       (tx(ex1 - i), ty(ey1 - i)), (tx(ex0 + i), ty(ey1 - i))], fill=fill)
        elif kind == "rounded_rectangle":
            r = max(0.0, min(radius + grow, (ex1 - ex0) / 2, (ey1 - ey0) / 2)) * (c[1][0] - c[0][0]) / (ex1 - ex0)
            d.rounded_rectangle([c[0][0], c[0][1], c[2][0], c[2][1]], radius=max(0, r), fill=fill)
        else:  # ellipse
            d.ellipse([c[0][0], c[0][1], c[2][0], c[2][1]], fill=fill)

    outline = fill_cov = None
    if kind == "line":
        def draw_line(d, tx, ty, s):
            ax, ay, bx, by = p0[0], p0[1], p1[0], p1[1]
            L = math.hypot(bx - ax, by - ay)
            hw = width / 2.0
            if L > 1e-6:
                nx, ny = -(by - ay) / L * hw, (bx - ax) / L * hw
                d.polygon([(tx(ax + nx), ty(ay + ny)), (tx(bx + nx), ty(by + ny)),
                           (tx(bx - nx), ty(by - ny)), (tx(ax - nx), ty(ay - ny))], fill=255)
            for cx, cy in ((ax, ay), (bx, by)):  # puntas redondas
                d.ellipse([tx(cx - hw), ty(cy - hw), tx(cx + hw), ty(cy + hw)], fill=255)
        outline = _supersample(rect, draw_line)
        return rect, outline, None

    if want_fill:
        fill_cov = _supersample(rect, lambda d, tx, ty, s: box(d, tx, ty, s, 0.0, 255))
    if want_outline:
        def draw_ring(d, tx, ty, s):
            box(d, tx, ty, s, width / 2.0, 255)
            box(d, tx, ty, s, -width / 2.0, 0)
        outline = _supersample(rect, draw_ring)
    return rect, outline, fill_cov
