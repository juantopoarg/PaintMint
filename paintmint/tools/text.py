"""Herramienta de texto: crea capas de texto editables y permite arrastrarlas."""

from __future__ import annotations

from ..i18n import tr

import math

from ..core.layer import TextSpec
from ..render.text import text_bounds
from .base import NO_MODS, Tool


class TextTool(Tool):
    key, label = "text", tr('Text')

    def __init__(self):
        super().__init__()
        self.layer = None
        self.grab = None
        self.moved = False
        self.origin = None

    def default_spec(self, ctx, x, y) -> TextSpec:
        o = ctx.options
        return TextSpec(text=tr('Text'), family=o.font_family, size=o.font_size, bold=o.font_bold,
                        italic=o.font_italic, color=tuple(o.primary), x=round(x), y=round(y), align=o.text_align)

    @staticmethod
    def hit_layer(doc, x, y):
        """Capa de texto más alta cuyo recuadro contiene (x, y)."""
        for layer in reversed(doc.layers):
            if layer.text is not None and layer.visible:
                x0, y0, x1, y1 = text_bounds(layer.text)
                if x0 <= x < x1 and y0 <= y < y1:
                    return layer
        return None

    def press(self, ctx, x, y, button="primary", mods=NO_MODS):
        doc = ctx.session.doc
        layer = self.hit_layer(doc, x, y)
        if layer is None:
            layer = ctx.session.create_text_layer(self.default_spec(ctx, x, y))
        else:
            doc.set_active(doc.index_of(layer))
        self.layer = layer
        self.origin = (x, y)
        self.grab = (layer.text.x, layer.text.y)
        self.moved = False
        ctx.session.history.break_merge()

    def move(self, ctx, x, y, mods=NO_MODS):
        if self.layer is None or self.layer.text is None:
            return
        dx, dy = x - self.origin[0], y - self.origin[1]
        if not self.moved and math.hypot(dx, dy) < 3:
            return  # un clic simple no debe desplazar el texto
        self.moved = True
        spec = self.layer.text.copy()
        spec.x, spec.y = round(self.grab[0] + dx), round(self.grab[1] + dy)
        if (spec.x, spec.y) != (self.layer.text.x, self.layer.text.y):
            ctx.session.update_text_layer(self.layer, spec, merge=True)

    def release(self, ctx, x, y, mods=NO_MODS):
        self.move(ctx, x, y, mods)
        ctx.session.history.break_merge()
        self.layer = None

    def cancel(self, ctx):
        self.layer = None
