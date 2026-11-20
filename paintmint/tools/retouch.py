"""Retoque: tampón de clonar y cambio de color."""

from __future__ import annotations

import numpy as np

from ..core.errors import InvalidOperationError
from ..i18n import tr
from ..render import raster
from .base import NO_MODS
from .paint import StrokeTool, _region_view


class CloneStampTool(StrokeTool):
    """Ctrl+clic fija el origen; al arrastrar se copian los píxeles del origen (con el mismo desplazamiento)."""

    key, label, undo_label = "clone", tr('Clone stamp'), tr('Clone stamp')

    def __init__(self):
        super().__init__()
        self.source = None
        self.offset = (0, 0)

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        if "ctrl" in mods:
            self.source = (x, y)
            self.overlay = {"type": "cross", "p": self.source}
            return
        if self.source is None:
            raise InvalidOperationError(tr('Ctrl+click on the image to set the source point first.'))
        self.require_drawable(ctx)
        self.offset = (int(round(self.source[0] - x)), int(round(self.source[1] - y)))
        super().press(ctx, x, y, button, mods)

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:     # el Ctrl+clic de fijar origen no abre ningún gesto
            return
        super().release(ctx, x, y, mods)

    def _paint(self, ctx, p0, p1, first):
        size, hardness, aa = self._params(ctx)
        dirty = raster.stamp_segment(self.cov, p0, p1, size, hardness, aa, include_start=first)
        if raster.is_empty(dirty):
            return
        snap = self.handle.snapshot
        x0, y0, x1, y1 = dirty
        dx, dy = self.offset
        src = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)      # fuera de la capa: transparente
        h, w = snap.shape[:2]
        sx0, sy0, sx1, sy1 = max(0, x0 + dx), max(0, y0 + dy), min(w, x1 + dx), min(h, y1 + dy)
        if sx1 > sx0 and sy1 > sy0:
            src[sy0 - y0 - dy:sy1 - y0 - dy, sx0 - x0 - dx:sx1 - x0 - dx] = snap[sy0:sy1, sx0:sx1]
        cov = _region_view(self.cov, dirty) * ctx.options.opacity
        self.handle.write(dirty, raster.blend_pixels(_region_view(snap, dirty), src, cov))


class RecolorTool(StrokeTool):
    """Cambio de color: sustituye por el primario los píxeles parecidos al secundario bajo el pincel."""

    key, label, undo_label = "recolor", tr('Recolor'), tr('Recolor')

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.old = self.colors(ctx, button)[1]      # color que se sustituye (antes del primer toque)
        super().press(ctx, x, y, button, mods)

    def _paint(self, ctx, p0, p1, first):
        size, hardness, aa = self._params(ctx)
        dirty = raster.stamp_segment(self.cov, p0, p1, size, hardness, aa, include_start=first)
        if raster.is_empty(dirty):
            return
        old = self.old
        block = raster.recolor_block(_region_view(self.handle.snapshot, dirty), old, self.color,
                                     ctx.options.tolerance, _region_view(self.cov, dirty), ctx.options.opacity)
        self.handle.write(dirty, block)
