"""Herramientas de trazado: forma libre, polígono y línea/curva (con edición pendiente hasta confirmar)."""

from __future__ import annotations

import math

import numpy as np

from ..i18n import tr
from ..render import raster
from .base import NO_MODS, Tool

NODE_RADIUS = 7.0   # distancia (px de imagen) para agarrar un nodo existente


def _region(arr, rect):
    x0, y0, x1, y1 = rect
    return arr[y0:y1, x0:x1]


def _aliased(cov, antialias):
    return cov if antialias or cov is None else (cov >= 0.5).astype(np.float32)


def paint_coverages(block, rect, outline, fill, mode, colors, o):
    """Pinta relleno (primario, o secundario si hay contorno) y contorno sobre ``block``."""
    primary, secondary = colors
    ow = o.blend == "overwrite"
    if fill is not None:
        fg, bg = (secondary, primary) if mode == "both" else (primary, secondary)
        block = raster.styled_fill(block, rect, _aliased(fill, o.antialias), fg, bg, o.fill_style, o.opacity, ow)
    if outline is not None:
        block = raster.paint_block(block, primary, _aliased(outline, o.antialias), o.opacity, ow)
    return block


class PathTool(Tool):
    """Base: una lista de nodos que se previsualiza en la capa y se confirma con ``finish``."""

    modifies_pixels = True
    closed = False
    fillable = False
    min_nodes = 2
    undo_label = tr('Shape')

    def __init__(self):
        super().__init__()
        self.handle = None
        self.pts = []
        self.drag = None
        self.colors_ = None

    # -- estado ----------------------------------------------------------------
    @property
    def pending(self) -> bool:
        return self.handle is not None

    def _begin(self, ctx, button):
        self.require_drawable(ctx)
        self.handle = ctx.session.begin_edit()
        self.colors_ = self.colors(ctx, button)
        self.pts = []
        self.drag = None

    def _reset(self):
        self.handle, self.pts, self.drag, self.overlay = None, [], None, None

    def _nearest_node(self, x, y):
        best, bd = None, NODE_RADIUS
        for i, (px, py) in enumerate(self.pts):
            d = math.hypot(px - x, py - y)
            if d <= bd:
                best, bd = i, d
        return best

    def _geometry(self):
        return list(self.pts)

    # -- dibujo ------------------------------------------------------------------
    def _render(self, ctx):
        h, o = self.handle, ctx.options
        h.reset()
        pts = self._geometry()
        mode = o.shape_mode if self.fillable else "outline"
        height, width = h.snapshot.shape[:2]
        rect, outline, fill = raster.path_coverage(height, width, pts, self.closed, o.size,
                                                   mode in ("outline", "both"), mode in ("fill", "both"), o.line_style)
        if rect is not None:
            h.write(rect, paint_coverages(_region(h.snapshot, rect), rect, outline, fill, mode, self.colors_, o))
        self.overlay = {"type": "nodes", "points": list(self.pts)}

    # -- eventos -----------------------------------------------------------------
    def move(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None or self.drag is None:
            return
        self.pts[self.drag] = (x, y)
        self._render(ctx)

    def release(self, ctx, x, y, mods=NO_MODS):
        self.drag = None

    def finish(self, ctx):
        handle = self.handle
        if handle is None:
            return
        try:
            if len(self.pts) >= self.min_nodes:
                self._render(ctx)
                handle.commit(self.undo_label)
            else:
                handle.cancel()
        finally:
            self._reset()

    def cancel(self, ctx):
        if self.handle is not None:
            self.handle.cancel()
        self._reset()


class PolygonTool(PathTool):
    """Polígono: un clic por vértice (se pueden arrastrar); Intro, doble clic o cambiar de herramienta lo cierra."""

    key, label = "polygon", tr('Polygon')
    closed, fillable, min_nodes = True, True, 3
    undo_label = tr('Polygon')

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        if self.handle is None:
            self._begin(ctx, button)
        idx = self._nearest_node(x, y)
        if idx is None:
            self.pts.append((x, y))
            idx = len(self.pts) - 1
        self.drag = idx
        self._render(ctx)


class FreeformShapeTool(PathTool):
    """Forma libre: se dibuja arrastrando; al soltar se cierra y se confirma."""

    key, label = "freeform", tr('Freeform shape')
    closed, fillable, min_nodes = True, True, 3
    undo_label = tr('Freeform shape')

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.finish(ctx)
        self._begin(ctx, button)
        self.pts = [(x, y)]
        self._render(ctx)

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        lx, ly = self.pts[-1]
        if math.hypot(x - lx, y - ly) >= 1.5:
            self.pts.append((x, y))
            self._render(ctx)

    def release(self, ctx, x, y, mods=NO_MODS):
        self.finish(ctx)


class CurveTool(PathTool):
    """Línea/curva: se arrastra una recta; luego se arrastran sus nodos o se agarra la línea para curvarla
    (cada agarre añade un nodo). Intro, doble clic o cambiar de herramienta la confirma."""

    key, label = "curve", tr('Curve')
    min_nodes = 2
    undo_label = tr('Curve')
    PER_SEGMENT = 24

    def _geometry(self):
        return raster.spline_points(self.pts, self.PER_SEGMENT)

    def _segment_at(self, x, y):
        """Índice del tramo entre nodos más cercano a (x, y) si está sobre la línea, si no ``None``."""
        dense = self._geometry()
        per = self.PER_SEGMENT if len(self.pts) >= 3 else len(dense)
        best, bd = None, NODE_RADIUS
        for i, (a, b) in enumerate(zip(dense, dense[1:])):
            ax, ay, bx, by = a[0], a[1], b[0], b[1]
            L2 = (bx - ax) ** 2 + (by - ay) ** 2
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
            d = math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay)))
            if d <= bd:
                best, bd = i // per if len(self.pts) >= 3 else 0, d
        return best

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        if self.handle is None:
            self._begin(ctx, button)
            self.pts = [(x, y), (x, y)]
            self.drag = 1
        else:
            idx = self._nearest_node(x, y)
            if idx is None:
                seg = self._segment_at(x, y)
                if seg is None:                      # lejos de la curva: se confirma y empieza otra
                    self.finish(ctx)
                    self._begin(ctx, button)
                    self.pts = [(x, y), (x, y)]
                    self.drag = 1
                else:
                    self.pts.insert(seg + 1, (x, y))
                    idx = seg + 1
            if idx is not None:
                self.drag = idx
        self._render(ctx)
