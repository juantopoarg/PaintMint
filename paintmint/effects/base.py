"""Infraestructura de efectos: parámetros declarativos para generar diálogos automáticamente."""

from __future__ import annotations

from ..i18n import tr

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

import numpy as np

from ..core.errors import PaintMintError


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    kind: str                      # int | float | bool | choice | curve
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[Sequence] = None   # para kind == "choice": [(valor, etiqueta), ...]


class Effect:
    """Un efecto recibe píxeles RGBA uint8 y devuelve otro arreglo del mismo tamaño."""

    key = "effect"
    label = tr('Effect')
    category = "effect"            # "adjust" | "effect"
    group = ""                     # submenú de Efectos (artistic, blurs, color, distort, noise, object, photo, render, stylize)
    params: List[Param] = []

    def resolve(self, values: Optional[dict] = None) -> dict:
        """Rellena valores por defecto, valida y recorta al rango de cada parámetro."""
        values = dict(values or {})
        known = {p.key for p in self.params}
        unknown = set(values) - known
        if unknown:
            raise PaintMintError(f"Unknown parameters for \"{self.label}\": {', '.join(sorted(unknown))}")
        out = {}
        for p in self.params:
            v = values.get(p.key, p.default)
            if p.kind == "int":
                v = int(round(v))
            elif p.kind == "float":
                v = float(v)
            elif p.kind == "bool":
                v = bool(v)
            elif p.kind == "choice":
                if v not in [c[0] for c in p.choices]:
                    raise PaintMintError(f"Invalid value for \"{p.label}\": {v!r}")
            elif p.kind == "curve":
                v = normalize_curve(v)
            if p.kind in ("int", "float"):
                if p.min is not None:
                    v = max(p.min, v)
                if p.max is not None:
                    v = min(p.max, v)
            out[p.key] = v
        return out

    def apply(self, pixels: np.ndarray, **params) -> np.ndarray:  # pragma: no cover - interfaz
        raise NotImplementedError


def normalize_curve(points) -> list:
    """Puntos (x, y) en 0..255 ordenados por x, con extremos garantizados."""
    pts = sorted((int(max(0, min(255, x))), int(max(0, min(255, y)))) for x, y in points)
    dedup = {}
    for x, y in pts:
        dedup[x] = y
    if 0 not in dedup:
        dedup[0] = 0
    if 255 not in dedup:
        dedup[255] = 255
    return sorted(dedup.items())


def apply_lut(pixels: np.ndarray, lut_r, lut_g=None, lut_b=None) -> np.ndarray:
    """Aplica una tabla de 256 entradas por canal (RGB) conservando el alfa."""
    lut_g = lut_r if lut_g is None else lut_g
    lut_b = lut_r if lut_b is None else lut_b
    out = pixels.copy()
    out[..., 0] = np.asarray(lut_r, dtype=np.uint8)[pixels[..., 0]]
    out[..., 1] = np.asarray(lut_g, dtype=np.uint8)[pixels[..., 1]]
    out[..., 2] = np.asarray(lut_b, dtype=np.uint8)[pixels[..., 2]]
    return out
