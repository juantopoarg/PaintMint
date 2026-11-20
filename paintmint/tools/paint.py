"""Herramientas de dibujo: pincel, lápiz, borrador, relleno, degradado, formas y cuentagotas."""

from __future__ import annotations

from ..i18n import tr

import math

import numpy as np

from ..render import raster
from .base import NO_MODS, Tool, ToolContext


def _region_view(arr, rect):
    x0, y0, x1, y1 = rect
    return arr[y0:y1, x0:x1]


class StrokeTool(Tool):
    """Trazo a mano alzada. La opacidad no se acumula dentro de un mismo trazo (como en Paint.NET)."""

    modifies_pixels = True
    erase = False
    force_aliased = False
    undo_label = tr('Brush')

    def __init__(self):
        super().__init__()
        self.handle = None
        self.cov = None
        self.last = None
        self.color = (0, 0, 0, 255)

    def _params(self, ctx):
        o = ctx.options
        if self.force_aliased:
            return o.size, 1.0, False
        return o.size, o.hardness, o.antialias

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.require_drawable(ctx)
        self.handle = ctx.session.begin_edit()
        h, w = self.handle.snapshot.shape[:2]
        self.cov = np.zeros((h, w), dtype=np.float32)
        self.color = self.colors(ctx, button)[0]
        self.last = (x, y)
        self._paint(ctx, (x, y), (x, y), True)

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        self._paint(ctx, self.last, (x, y), False)
        self.last = (x, y)

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        self.move(ctx, x, y, mods)
        self.handle.commit(self.undo_label)
        self.handle = self.cov = None

    def cancel(self, ctx):
        if self.handle is not None:
            self.handle.cancel()
        self.handle = self.cov = None

    def _paint(self, ctx, p0, p1, first):
        size, hardness, aa = self._params(ctx)
        dirty = raster.stamp_segment(self.cov, p0, p1, size, hardness, aa, include_start=first)
        if raster.is_empty(dirty):
            return
        alpha = _region_view(self.cov, dirty) * (ctx.options.opacity * self.color[3] / 255.0)
        snap = _region_view(self.handle.snapshot, dirty)
        block = raster.erase_alpha(snap, alpha) if self.erase else raster.over(snap, self.color[:3], alpha)
        self.handle.write(dirty, block)


class BrushTool(StrokeTool):
    key, label, undo_label = "brush", tr('Brush'), tr('Brush')


class PencilTool(StrokeTool):
    key, label, undo_label = "pencil", tr('Pencil'), tr('Pencil')
    force_aliased = True


class EraserTool(StrokeTool):
    key, label, undo_label = "eraser", tr('Eraser'), tr('Eraser')
    erase = True


class FillTool(Tool):
    key, label = "fill", tr('Paint bucket')
    modifies_pixels = True

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.require_drawable(ctx)
        o = ctx.options
        color = self.colors(ctx, button)[0]
        handle = ctx.session.begin_edit()
        try:
            src = ctx.session.doc.composite() if o.sample_image else handle.snapshot
            region = raster.flood_mask(src, int(math.floor(x)), int(math.floor(y)), o.tolerance, o.contiguous)
            rows, cols = np.flatnonzero(region.any(axis=1)), np.flatnonzero(region.any(axis=0))
            if rows.size == 0:
                handle.cancel()
                return
            rect = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
            alpha = _region_view(region, rect).astype(np.float32) * (o.opacity * color[3] / 255.0)
            handle.write(rect, raster.over(_region_view(handle.snapshot, rect), color[:3], alpha))
        except Exception:
            handle.cancel()
            raise
        handle.commit(tr('Fill'))


class GradientTool(Tool):
    key, label = "gradient", tr('Gradient')
    modifies_pixels = True

    def __init__(self):
        super().__init__()
        self.handle = None
        self.start = None
        self.colors_ = None

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.require_drawable(ctx)
        self.handle = ctx.session.begin_edit()
        self.start = (x, y)
        self.colors_ = self.colors(ctx, button)
        self.overlay = {"type": "line", "p0": self.start, "p1": self.start}

    def _render(self, ctx, end):
        h = self.handle
        h.reset()
        sel = ctx.session.doc.selection
        rect = sel.bbox() if sel.active else (0, 0, h.snapshot.shape[1], h.snapshot.shape[0])
        c0, c1 = self.colors_
        grad = raster.gradient_rgba(rect, ctx.options.gradient, self.start, end, c0, c1)
        alpha = grad[..., 3].astype(np.float32) / 255.0 * ctx.options.opacity
        h.write(rect, raster.over(_region_view(h.snapshot, rect), grad[..., :3], alpha))

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        self.overlay = {"type": "line", "p0": self.start, "p1": (x, y)}
        self._render(ctx, (x, y))

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        if math.hypot(x - self.start[0], y - self.start[1]) < 1.0:
            self.handle.cancel()
        else:
            self._render(ctx, (x, y))
            self.handle.commit(tr('Gradient'))
        self.handle = None
        self.overlay = None

    def cancel(self, ctx):
        if self.handle is not None:
            self.handle.cancel()
        self.handle = None
        self.overlay = None


class ShapeTool(Tool):
    """Forma genérica (el tipo viene de ``options.shape``); las subclases fijan ``kind``."""

    key, label = "shape", tr('Shapes')
    modifies_pixels = True
    kind = None

    def __init__(self):
        super().__init__()
        self.handle = None
        self.start = None
        self.colors_ = None

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.require_drawable(ctx)
        self.handle = ctx.session.begin_edit()
        self.start = (x, y)
        self.colors_ = self.colors(ctx, button)

    @staticmethod
    def _constrain(p0, p1, kind):
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        if kind == "line":  # múltiplos de 45°
            ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
            d = math.hypot(dx, dy)
            return p0[0] + d * math.cos(ang), p0[1] + d * math.sin(ang)
        side = max(abs(dx), abs(dy))  # cuadrado / círculo
        return p0[0] + math.copysign(side, dx or 1), p0[1] + math.copysign(side, dy or 1)

    def _render(self, ctx, end):
        o, h = ctx.options, self.handle
        h.reset()
        height, width = h.snapshot.shape[:2]
        kind = self.kind or o.shape
        mode = "outline" if kind == "line" else o.shape_mode
        rect, outline, fill = raster.shape_coverage(
            height, width, kind, self.start, end, o.size,
            want_outline=mode in ("outline", "both"), want_fill=mode in ("fill", "both"),
            radius=o.corner_radius)
        if rect is None:
            return
        primary, secondary = self.colors_
        block = _region_view(h.snapshot, rect)
        if fill is not None:
            fc = secondary if mode == "both" else primary
            block = raster.over(block, fc[:3], fill * (o.opacity * fc[3] / 255.0))
        if outline is not None:
            block = raster.over(block, primary[:3], outline * (o.opacity * primary[3] / 255.0))
        h.write(rect, block)

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        end = self._constrain(self.start, (x, y), self.kind or ctx.options.shape) if "shift" in mods else (x, y)
        self._render(ctx, end)

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        self.move(ctx, x, y, mods)
        self.handle.commit(tr('Shape'))
        self.handle = None

    def cancel(self, ctx):
        if self.handle is not None:
            self.handle.cancel()
        self.handle = None


class LineTool(ShapeTool):
    key, label, kind = "line", tr('Line'), "line"


class RectangleTool(ShapeTool):
    key, label, kind = "rectangle", tr('Rectangle'), "rectangle"


class RoundedRectangleTool(ShapeTool):
    key, label, kind = "rounded_rectangle", tr('Rounded rectangle'), "rounded_rectangle"


class EllipseTool(ShapeTool):
    key, label, kind = "ellipse", tr('Ellipse'), "ellipse"


class ColorPickerTool(Tool):
    key, label = "picker", tr('Color picker')

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        doc, o = ctx.session.doc, ctx.options
        px, py = int(math.floor(x)), int(math.floor(y))
        if not (0 <= px < doc.width and 0 <= py < doc.height):
            return
        src = doc.composite((px, py, px + 1, py + 1))[0, 0] if o.sample_image else doc.active_layer.pixels[py, px]
        color = tuple(int(v) for v in src)
        if button == "primary":
            o.primary = color
        else:
            o.secondary = color
        o.notify()
