"""Capa de imagen y especificación de texto editable."""

from __future__ import annotations

from ..i18n import tr

import dataclasses
import itertools
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .blend import BLEND_MODES
from .errors import PaintMintError

_ids = itertools.count(1)


@dataclass
class TextSpec:
    """Parámetros de una capa de texto. Mientras exista, la capa es re-editable."""

    text: str = tr('Text')
    family: str = "Sans"
    size: int = 32                      # alto de fuente en píxeles
    bold: bool = False
    italic: bool = False
    color: Tuple[int, int, int, int] = (0, 0, 0, 255)
    x: float = 0.0                      # esquina superior izquierda en coordenadas de imagen
    y: float = 0.0
    align: str = "left"                 # left | center | right

    def copy(self) -> "TextSpec":
        return dataclasses.replace(self, color=tuple(self.color))


class Layer:
    """Capa RGBA uint8 (alto, ancho, 4) con alfa recto y del tamaño del lienzo."""

    def __init__(
        self,
        pixels: np.ndarray,
        name: str = tr('Layer'),
        visible: bool = True,
        opacity: float = 1.0,
        blend_mode: str = "normal",
        text: Optional[TextSpec] = None,
        layer_id: Optional[int] = None,
    ):
        if pixels.ndim != 3 or pixels.shape[2] != 4 or pixels.dtype != np.uint8:
            raise PaintMintError('Layer pixels must be an RGBA uint8 array.')
        self.pixels = pixels
        self.name = name
        self.visible = visible
        self.opacity = float(opacity)
        self.blend_mode = blend_mode
        self.text: Optional[TextSpec] = text
        self.id = layer_id if layer_id is not None else next(_ids)

    # -- propiedades -----------------------------------------------------
    @property
    def width(self) -> int:
        return self.pixels.shape[1]

    @property
    def height(self) -> int:
        return self.pixels.shape[0]

    @property
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = min(1.0, max(0.0, float(value)))

    @property
    def blend_mode(self) -> str:
        return self._blend

    @blend_mode.setter
    def blend_mode(self, value: str) -> None:
        if value not in BLEND_MODES:
            raise PaintMintError(f"Unknown blend mode: {value}")
        self._blend = value

    @property
    def is_text(self) -> bool:
        return self.text is not None

    # -- utilidades --------------------------------------------------------
    def props(self) -> dict:
        """Propiedades no-píxel (para historial y ORA)."""
        return {
            "name": self.name,
            "visible": self.visible,
            "opacity": self.opacity,
            "blend_mode": self.blend_mode,
        }

    def apply_props(self, props: dict) -> None:
        for key, value in props.items():
            setattr(self, key, value)

    def clone(self, new_id: bool = False, copy_pixels: bool = True) -> "Layer":
        return Layer(
            self.pixels.copy() if copy_pixels else self.pixels,
            name=self.name,
            visible=self.visible,
            opacity=self.opacity,
            blend_mode=self.blend_mode,
            text=self.text.copy() if self.text else None,
            layer_id=None if new_id else self.id,
        )
