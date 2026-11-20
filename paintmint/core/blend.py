"""Modos de fusión (los mismos 14 de Paint.NET, salvo nombres) y composición de capas.

Convenciones: los píxeles de capa son RGBA uint8 con alfa *recto* (no
premultiplicado). La composición se hace en float32 por franjas de filas para
acotar el uso de memoria en imágenes grandes.
"""

from __future__ import annotations

from ..i18n import tr

from typing import Iterable, Optional, Sequence, Tuple

import numpy as np

# clave -> etiqueta mostrada en la interfaz
BLEND_MODES = {
    "normal": "Normal",
    "multiply": tr('Multiply'),
    "additive": tr('Additive'),
    "color_burn": tr('Color Burn'),
    "color_dodge": tr('Color Dodge'),
    "reflect": tr('Reflect'),
    "glow": tr('Glow'),
    "overlay": tr('Overlay'),
    "difference": tr('Difference'),
    "negation": tr('Negation'),
    "lighten": tr('Lighten'),
    "darken": tr('Darken'),
    "screen": tr('Screen'),
    "xor": "XOR",
}

STRIP_ROWS = 256  # filas por franja de composición


def _safe_div(num, den):
    out = np.zeros_like(num)
    np.divide(num, den, out=out, where=den > 1e-6)
    return out


def blend_channels(mode: str, cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    """Fusiona color de fondo ``cb`` y de origen ``cs`` (float 0..1, mismo shape)."""
    if mode == "normal":
        return cs
    if mode == "multiply":
        return cb * cs
    if mode == "additive":
        return np.minimum(1.0, cb + cs)
    if mode == "color_burn":
        r = 1.0 - np.minimum(1.0, _safe_div(1.0 - cb, cs))
        return np.where(cb >= 1.0, 1.0, np.where(cs <= 1e-6, 0.0, r))
    if mode == "color_dodge":
        r = np.minimum(1.0, _safe_div(cb, 1.0 - cs))
        return np.where(cb <= 1e-6, 0.0, np.where(cs >= 1.0, 1.0, r))
    if mode == "reflect":
        r = np.minimum(1.0, _safe_div(cb * cb, 1.0 - cs))
        return np.where(cs >= 1.0, 1.0, r)
    if mode == "glow":
        r = np.minimum(1.0, _safe_div(cs * cs, 1.0 - cb))
        return np.where(cb >= 1.0, 1.0, r)
    if mode == "overlay":
        return np.where(cb <= 0.5, 2.0 * cb * cs, 1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))
    if mode == "difference":
        return np.abs(cb - cs)
    if mode == "negation":
        return 1.0 - np.abs(1.0 - cb - cs)
    if mode == "lighten":
        return np.maximum(cb, cs)
    if mode == "darken":
        return np.minimum(cb, cs)
    if mode == "screen":
        return cb + cs - cb * cs
    if mode == "xor":
        a = np.rint(cb * 255.0).astype(np.uint8)
        b = np.rint(cs * 255.0).astype(np.uint8)
        return (a ^ b).astype(np.float32) / 255.0
    raise ValueError(f"Unknown blend mode: {mode!r}")


def _composite_strip(layers: Sequence, y0: int, y1: int, x0: int, x1: int, background) -> np.ndarray:
    h, w = y1 - y0, x1 - x0
    acc = np.zeros((h, w, 3), dtype=np.float32)  # color premultiplicado
    acc_a = np.zeros((h, w), dtype=np.float32)
    if background is not None:
        ba = background[3] / 255.0
        acc[...] = np.asarray(background[:3], dtype=np.float32) / 255.0 * ba
        acc_a[...] = ba

    for layer in layers:
        if not layer.visible or layer.opacity <= 0.0:
            continue
        src = layer.pixels[y0:y1, x0:x1]
        sa = src[..., 3].astype(np.float32) * (layer.opacity / 255.0)
        if not sa.any():
            continue
        cs = src[..., :3].astype(np.float32) / 255.0
        if layer.blend_mode == "normal":
            mixed = cs
        else:
            safe_a = np.where(acc_a > 1e-6, acc_a, 1.0)[..., None]
            cb = np.clip(acc / safe_a, 0.0, 1.0)
            b = blend_channels(layer.blend_mode, cb, cs)
            ab = acc_a[..., None]
            mixed = (1.0 - ab) * cs + ab * b
        sa3 = sa[..., None]
        acc = (1.0 - sa3) * acc + sa3 * mixed
        acc_a = sa + acc_a * (1.0 - sa)

    out = np.zeros((h, w, 4), dtype=np.uint8)
    nz = acc_a > 1e-6
    rgb = np.zeros_like(acc)
    np.divide(acc, acc_a[..., None], out=rgb, where=nz[..., None])
    out[..., :3] = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(np.rint(acc_a * 255.0), 0, 255).astype(np.uint8)
    return out


def composite(
    layers: Iterable,
    width: int,
    height: int,
    region: Optional[Tuple[int, int, int, int]] = None,
    background: Optional[Tuple[int, int, int, int]] = None,
) -> np.ndarray:
    """Compone ``layers`` (de abajo a arriba) y devuelve RGBA uint8 recto.

    ``region`` = (x0, y0, x1, y1) limita el cálculo; el resultado tiene el
    tamaño de la región. ``background`` es un color RGBA opcional bajo todo.
    """
    layers = list(layers)
    if region is None:
        region = (0, 0, width, height)
    x0, y0, x1, y1 = region
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(width, int(x1)), min(height, int(y1))
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0, 4), dtype=np.uint8)
    out = np.empty((y1 - y0, x1 - x0, 4), dtype=np.uint8)
    for ys in range(y0, y1, STRIP_ROWS):
        ye = min(ys + STRIP_ROWS, y1)
        out[ys - y0:ye - y0] = _composite_strip(layers, ys, ye, x0, x1, background)
    return out
