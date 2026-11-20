"""Selección de píxeles: máscara uint8 (0..255) del tamaño del lienzo o ``None`` (sin selección)."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np

from ..render import raster

MODES = ("replace", "add", "subtract", "intersect", "xor")


class Selection:
    """``mask is None`` significa «sin selección»: todo el lienzo es editable."""

    def __init__(self, width: int, height: int, mask: Optional[np.ndarray] = None):
        self.width, self.height = width, height
        self.mask = mask

    # -- estado ------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.mask is not None

    def copy(self) -> "Selection":
        return Selection(self.width, self.height, None if self.mask is None else self.mask.copy())

    def clear(self) -> None:
        self.mask = None

    def resize_canvas(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.mask = None

    def bbox(self) -> Tuple[int, int, int, int]:
        """Caja (x0, y0, x1, y1) de la selección, o el lienzo entero si no hay selección."""
        if self.mask is None:
            return 0, 0, self.width, self.height
        rows = np.flatnonzero(self.mask.any(axis=1))
        cols = np.flatnonzero(self.mask.any(axis=0))
        if rows.size == 0:
            return 0, 0, 0, 0
        return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1

    def contains(self, x: int, y: int) -> bool:
        if self.mask is None:
            return 0 <= x < self.width and 0 <= y < self.height
        return 0 <= x < self.width and 0 <= y < self.height and self.mask[y, x] > 0

    # -- combinación -------------------------------------------------------
    def combine(self, new_mask: np.ndarray, mode: str = "replace") -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown selection mode: {mode}")
        if mode == "replace" or self.mask is None and mode in ("add", "xor"):
            result = new_mask
        elif self.mask is None and mode == "intersect":
            result = new_mask
        elif self.mask is None and mode == "subtract":
            result = (255 - new_mask).astype(np.uint8)  # restar de «todo»
        elif mode == "add":
            result = np.maximum(self.mask, new_mask)
        elif mode == "subtract":
            result = np.minimum(self.mask, 255 - new_mask)
        elif mode == "intersect":
            result = np.minimum(self.mask, new_mask)
        else:  # xor
            result = np.abs(self.mask.astype(np.int16) - new_mask.astype(np.int16)).astype(np.uint8)
        self.mask = result if result.any() else None

    # -- constructores -----------------------------------------------------
    def select_all(self) -> None:
        self.mask = np.full((self.height, self.width), 255, dtype=np.uint8)

    def select_rect(self, x0, y0, x1, y1, mode: str = "replace") -> None:
        self.combine(raster.rect_mask(self.height, self.width, x0, y0, x1, y1), mode)

    def select_ellipse(self, x0, y0, x1, y1, mode: str = "replace") -> None:
        self.combine(raster.ellipse_mask(self.height, self.width, x0, y0, x1, y1), mode)

    def select_polygon(self, points: Sequence[Tuple[float, float]], mode: str = "replace") -> None:
        self.combine(raster.polygon_mask(self.height, self.width, points), mode)

    def select_bool(self, region: np.ndarray, mode: str = "replace") -> None:
        self.combine((region.astype(np.uint8) * 255), mode)

    def invert(self) -> None:
        if self.mask is None:
            return  # «sin selección» ya equivale a todo; no hay nada que invertir
        inv = 255 - self.mask
        self.mask = inv if inv.any() else None

    def translate(self, dx: int, dy: int) -> None:
        """Desplaza la máscara (lo que sale del lienzo se pierde)."""
        if self.mask is None:
            return
        self.mask = shift_array(self.mask, dx, dy)
        if not self.mask.any():
            self.mask = None


def shift_array(arr: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """Desplaza ``arr`` (2D o 3D) rellenando con ceros; no hay envoltura."""
    out = np.zeros_like(arr)
    h, w = arr.shape[:2]
    sx0, sx1 = max(0, -dx), min(w, w - dx)
    sy0, sy1 = max(0, -dy), min(h, h - dy)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 + dy:sy1 + dy, sx0 + dx:sx1 + dx] = arr[sy0:sy1, sx0:sx1]
    return out
