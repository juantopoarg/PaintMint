"""Herramientas de selección y movimiento de píxeles seleccionados."""

from __future__ import annotations

from ..i18n import tr

import math

import numpy as np

from ..core import commands as C
from ..core.selection import shift_array
from ..render import raster
from .base import NO_MODS, Tool


def mode_from(ctx, mods) -> str:
    """Ctrl = unir, Alt = restar, Ctrl+Alt = intersecar; si no, el modo de las opciones."""
    if "ctrl" in mods and "alt" in mods:
        return "intersect"
    if "ctrl" in mods:
        return "add"
    if "alt" in mods:
        return "subtract"
    return ctx.options.select_mode


class _BoxSelect(Tool):
    shape = "rect"

    def __init__(self):
        super().__init__()
        self.start = None

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.start = (x, y)
        self.overlay = {"type": self.shape, "box": (x, y, x, y)}

    def _box(self, x, y, mods):
        x0, y0 = self.start
        if "shift" in mods:
            side = max(abs(x - x0), abs(y - y0))
            x, y = x0 + math.copysign(side, x - x0 or 1), y0 + math.copysign(side, y - y0 or 1)
        return x0, y0, x, y

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.start is not None:
            self.overlay = {"type": self.shape, "box": self._box(x, y, mods)}

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.start is None:
            return
        x0, y0, x1, y1 = self._box(x, y, mods)
        self.start = self.overlay = None
        if abs(x1 - x0) < 1 and abs(y1 - y0) < 1:   # clic sin arrastrar: quitar selección
            ctx.session.deselect()
            return
        mode = mode_from(ctx, mods)
        if self.shape == "rect":
            ctx.session.select_rect(x0, y0, x1, y1, mode)
        else:
            ctx.session.select_ellipse(x0, y0, x1, y1, mode)

    def cancel(self, ctx):
        self.start = self.overlay = None


class RectSelectTool(_BoxSelect):
    key, label, shape = "select_rect", tr('Rectangle select'), "rect"


class EllipseSelectTool(_BoxSelect):
    key, label, shape = "select_ellipse", tr('Ellipse select'), "ellipse"


class LassoSelectTool(Tool):
    key, label = "select_lasso", tr('Lasso select')

    def __init__(self):
        super().__init__()
        self.points = None

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.points = [(x, y)]
        self.overlay = {"type": "polygon", "points": list(self.points)}

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.points is not None:
            lx, ly = self.points[-1]
            if math.hypot(x - lx, y - ly) >= 1.0:  # descarta puntos casi idénticos
                self.points.append((x, y))
                self.overlay = {"type": "polygon", "points": list(self.points)}

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.points is None:
            return
        self.points.append((x, y))
        pts, self.points, self.overlay = self.points, None, None
        if len(pts) < 3:
            ctx.session.deselect()
            return
        ctx.session.select_polygon(pts, mode_from(ctx, mods))

    def cancel(self, ctx):
        self.points = self.overlay = None


class WandSelectTool(Tool):
    key, label = "select_wand", tr('Magic wand')

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        o = ctx.options
        ctx.session.select_wand(math.floor(x), math.floor(y), o.tolerance, o.contiguous,
                                mode_from(ctx, mods), o.sample_image)


class MoveSelectedTool(Tool):
    """Mueve los píxeles seleccionados de la capa activa (o la capa entera si no hay selección)."""

    key, label = "move", tr('Move selected pixels')
    modifies_pixels = True

    def __init__(self):
        super().__init__()
        self.handle = None
        self.start = None
        self.orig_mask = None
        self.last_delta = (0, 0)

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        self.require_drawable(ctx)
        self.handle = ctx.session.begin_edit()
        sel = ctx.session.doc.selection
        self.orig_mask = None if sel.mask is None else sel.mask.copy()
        self.start, self.last_delta = (x, y), (0, 0)

    def _render(self, ctx, dx, dy):
        h, doc = self.handle, ctx.session.doc
        H, W = h.snapshot.shape[:2]
        sx0, sy0, sx1, sy1 = doc.selection.bbox() if self.orig_mask is not None else (0, 0, W, H)
        # el selector ya se desplazó; la caja original sale de la máscara original
        if self.orig_mask is not None:
            tmp = np.flatnonzero(self.orig_mask.any(axis=1)), np.flatnonzero(self.orig_mask.any(axis=0))
            sx0, sx1, sy0, sy1 = int(tmp[1][0]), int(tmp[1][-1]) + 1, int(tmp[0][0]), int(tmp[0][-1]) + 1
        dest = raster.clip_rect((sx0 + dx, sy0 + dy, sx1 + dx, sy1 + dy), W, H)
        union = raster.union_rect((sx0, sy0, sx1, sy1), dest)
        ux0, uy0, ux1, uy1 = union
        block = h.snapshot[uy0:uy1, ux0:ux1].copy()
        # 1) borrar la zona original
        if self.orig_mask is None:
            block[...] = 0
            mask_full = None
        else:
            m = self.orig_mask[uy0:uy1, ux0:ux1].astype(np.float32) / 255.0
            block = raster.lerp_premult(block, np.zeros_like(block), m)
        # 2) pegar el contenido desplazado
        src = h.snapshot[sy0:sy1, sx0:sx1].copy()
        if self.orig_mask is not None:
            src[..., 3] = (src[..., 3].astype(np.uint16) * self.orig_mask[sy0:sy1, sx0:sx1] // 255).astype(np.uint8)
        cx0, cy0 = max(sx0 + dx, 0), max(sy0 + dy, 0)
        cx1, cy1 = min(sx1 + dx, W), min(sy1 + dy, H)
        if cx1 > cx0 and cy1 > cy0:
            part = src[cy0 - (sy0 + dy):cy1 - (sy0 + dy), cx0 - (sx0 + dx):cx1 - (sx0 + dx)]
            reg = block[cy0 - uy0:cy1 - uy0, cx0 - ux0:cx1 - ux0]
            block[cy0 - uy0:cy1 - uy0, cx0 - ux0:cx1 - ux0] = raster.over(
                reg, part[..., :3], part[..., 3].astype(np.float32) / 255.0)
        h.reset()
        h.write(union, block, clip=False)
        if self.orig_mask is not None:
            doc.selection.mask = shift_array(self.orig_mask, dx, dy)
            doc.emit("selection")

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        dx, dy = int(round(x - self.start[0])), int(round(y - self.start[1]))
        if (dx, dy) != self.last_delta:
            self.last_delta = (dx, dy)
            self._render(ctx, dx, dy)

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.handle is None:
            return
        self.move(ctx, x, y, mods)
        doc = ctx.session.doc
        extra = None
        if self.orig_mask is not None and self.last_delta != (0, 0):
            now = doc.selection.mask
            extra = [C.SelectionCommand(self.orig_mask, None if now is None else now.copy())]
        if not self.handle.commit(tr('Move selection'), extra=extra) and self.orig_mask is not None:
            doc.selection.mask = self.orig_mask   # no hubo cambio real de píxeles
            doc.emit("selection")
        self.handle = None

    def cancel(self, ctx):
        if self.handle is not None:
            self.handle.cancel()
            if self.orig_mask is not None:
                ctx.session.doc.selection.mask = self.orig_mask
                ctx.session.doc.emit("selection")
        self.handle = None


class MoveSelectionTool(Tool):
    """Mueve solo el contorno de la selección, sin tocar los píxeles."""

    key, label = "move_selection", tr('Move selection')

    def __init__(self):
        super().__init__()
        self.start = None
        self.orig = None

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        sel = ctx.session.doc.selection
        if not sel.active:
            return
        self.orig, self.start = sel.mask.copy(), (x, y)

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.orig is None:
            return
        doc = ctx.session.doc
        doc.selection.mask = shift_array(self.orig, int(round(x - self.start[0])), int(round(y - self.start[1])))
        doc.emit("selection")

    def release(self, ctx, x, y, mods=NO_MODS):
        if self.orig is None:
            return
        self.move(ctx, x, y, mods)
        doc, orig, self.orig = ctx.session.doc, self.orig, None
        now = doc.selection.mask
        if now is not None and np.array_equal(now, orig):
            return
        ctx.session.history.push(C.SelectionCommand(orig, None if now is None else now.copy(), tr('Move selection')))

    def cancel(self, ctx):
        if self.orig is not None:
            ctx.session.doc.selection.mask = self.orig
            ctx.session.doc.emit("selection")
        self.orig = None


# ---------------------------------------------------------------------------
# Tiradores de redimensionado de la selección (esquinas y lados de su caja)
# ---------------------------------------------------------------------------
HANDLES = {"nw": (0.0, 0.0), "n": (0.5, 0.0), "ne": (1.0, 0.0), "e": (1.0, 0.5),
           "se": (1.0, 1.0), "s": (0.5, 1.0), "sw": (0.0, 1.0), "w": (0.0, 0.5)}
RESIZE_TOOLS = ("select_rect", "select_ellipse", "select_lasso", "select_wand", "move")   # «move» escala los píxeles


def handle_points(box):
    x0, y0, x1, y1 = box
    return {k: (x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy) for k, (fx, fy) in HANDLES.items()}


def hit_handle(box, x, y, tol):
    """Tirador de la caja más cercano a (x, y) dentro de ``tol`` (unidades de imagen), o None.

    Las esquinas tienen prioridad sobre los lados.
    """
    best, best_d = None, tol
    for k, (hx, hy) in handle_points(box).items():
        d = max(abs(hx - x), abs(hy - y))
        if d < best_d or (d == best_d and best is not None and len(k) == 2 and len(best) == 1):
            best, best_d = k, d
    return best


def resized_box(box, handle, x, y, keep_aspect=False):
    """Caja resultante de arrastrar ``handle`` hasta (x, y); admite cruzar el lado opuesto (voltea)."""
    x0, y0, x1, y1 = box
    fx, fy = HANDLES[handle]
    nx0, ny0, nx1, ny1 = x0, y0, x1, y1
    if fx == 0.0:
        nx0 = x
    elif fx == 1.0:
        nx1 = x
    if fy == 0.0:
        ny0 = y
    elif fy == 1.0:
        ny1 = y
    if keep_aspect and len(handle) == 2 and (x1 - x0) > 0 and (y1 - y0) > 0:
        ratio = (x1 - x0) / (y1 - y0)
        ax, ay = (x1 if fx == 0.0 else x0), (y1 if fy == 0.0 else y0)     # esquina opuesta (fija)
        w, h = abs((nx1 if fx == 1.0 else nx0) - ax), abs((ny1 if fy == 1.0 else ny0) - ay)
        if w / ratio > h:
            h = w / ratio
        else:
            w = h * ratio
        sx = 1 if x >= ax else -1
        sy = 1 if y >= ay else -1
        nx0, nx1 = sorted((ax, ax + sx * w))
        ny0, ny1 = sorted((ay, ay + sy * h))
    return min(nx0, nx1), min(ny0, ny1), max(nx0, nx1), max(ny0, ny1)


def cursor_name(handle):
    return {"nw": "fdiag", "se": "fdiag", "ne": "bdiag", "sw": "bdiag", "n": "ver", "s": "ver",
            "e": "hor", "w": "hor"}[handle]
