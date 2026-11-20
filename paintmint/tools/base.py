"""Contrato común de las herramientas y opciones compartidas."""

from __future__ import annotations

from ..i18n import tr

from dataclasses import dataclass, field
from typing import Callable, FrozenSet, List, Optional, Tuple

from ..core.errors import InvalidOperationError
from ..core.session import EditSession

Color = Tuple[int, int, int, int]
NO_MODS: FrozenSet[str] = frozenset()


@dataclass
class ToolOptions:
    """Opciones compartidas por todas las herramientas (la interfaz las enlaza a controles)."""

    primary: Color = (0, 0, 0, 255)
    secondary: Color = (255, 255, 255, 255)
    size: float = 10.0               # diámetro de pincel/lápiz/borrador y grosor de formas
    hardness: float = 0.8            # 0..1, solo pincel y borrador
    opacity: float = 1.0             # 0..1
    antialias: bool = True
    tolerance: float = 30.0          # % para relleno y varita
    contiguous: bool = True
    sample_image: bool = False       # muestrear la imagen combinada en vez de la capa
    shape: str = "rectangle"
    shape_mode: str = "outline"      # outline | fill | both
    corner_radius: float = 12.0
    fill_style: str = "solid"        # solid o un entramado (ver raster.HATCH_STYLES)
    line_style: str = "solid"        # solid, dash, dot, dash_dot, dash_dot_dot
    blend: str = "normal"            # normal | overwrite («sin mezcla alfa» de Paint.NET)
    gradient: str = "linear"
    select_mode: str = "replace"
    font_family: str = "Sans"
    font_size: int = 32
    font_bold: bool = False
    font_italic: bool = False
    text_align: str = "left"
    listeners: List[Callable[[], None]] = field(default_factory=list, repr=False)

    def notify(self) -> None:
        for fn in list(self.listeners):
            fn()

    def swap_colors(self) -> None:
        self.primary, self.secondary = self.secondary, self.primary
        self.notify()


@dataclass
class ToolContext:
    session: EditSession
    options: ToolOptions


class Tool:
    """Una herramienta recibe eventos en coordenadas de imagen (flotantes)."""

    key = "tool"
    label = tr('Tool')
    modifies_pixels = False   # exige capa activa visible

    def __init__(self):
        self.overlay: Optional[dict] = None   # vista previa para que la interfaz la dibuje

    def press(self, ctx: ToolContext, x: float, y: float, button: str = "primary", mods=NO_MODS) -> None: ...

    def move(self, ctx: ToolContext, x: float, y: float, mods=NO_MODS) -> None: ...

    def release(self, ctx: ToolContext, x: float, y: float, mods=NO_MODS) -> None: ...

    def cancel(self, ctx: ToolContext) -> None:
        self.overlay = None

    # herramientas con edición pendiente entre clics (polígono, curva): se confirman con ``finish``
    @property
    def pending(self) -> bool:
        return False

    def finish(self, ctx: ToolContext) -> None:
        """Confirma la edición pendiente (Intro, doble clic, cambiar de herramienta). Por defecto no hace nada."""

    # -- utilidades --------------------------------------------------------
    @staticmethod
    def colors(ctx: ToolContext, button: str):
        o = ctx.options
        return (o.primary, o.secondary) if button == "primary" else (o.secondary, o.primary)

    @staticmethod
    def require_drawable(ctx: ToolContext):
        layer = ctx.session.active_layer
        if not layer.visible:
            raise InvalidOperationError(tr('The active layer is hidden. Make it visible to draw on it.'))
        return layer
