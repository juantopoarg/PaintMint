"""Comandos concretos del historial."""

from __future__ import annotations

from ..i18n import tr

from typing import Dict, List, Optional

import numpy as np

from .document import DocSnapshot, Document, Packed
from .history import Command
from .layer import Layer, TextSpec


class PatchCommand(Command):
    """Cambio de píxeles en un rectángulo de una capa (y, opcionalmente, de su texto)."""

    def __init__(self, layer_id: int, rect, before: np.ndarray, after: np.ndarray, label: str,
                 text_before: Optional[TextSpec] = None, text_after: Optional[TextSpec] = None):
        self.layer_id, self.rect, self.label = layer_id, rect, label
        self._before, self._after = Packed(before), Packed(after)
        self.text_before, self.text_after = text_before, text_after

    def _apply(self, doc: Document, packed: Packed, text) -> None:
        layer = doc.layer_by_id(self.layer_id)
        x0, y0, x1, y1 = self.rect
        layer.pixels[y0:y1, x0:x1] = packed.unpack()
        layer.text = text.copy() if text else None
        doc.emit("pixels", self.rect)

    def do(self, doc):
        self._apply(doc, self._after, self.text_after)

    def undo(self, doc):
        self._apply(doc, self._before, self.text_before)

    @property
    def nbytes(self):
        return self._before.nbytes + self._after.nbytes + 128


class TextCommand(Command):
    """Cambio de la especificación de texto (se guardan también los píxeles resultantes)."""

    def __init__(self, layer_id: int, before_spec: TextSpec, after_spec: TextSpec,
                 before_px: np.ndarray, after_px: np.ndarray, label: str = tr('Edit text'),
                 merge_key=None):
        self.layer_id, self.label, self.merge_key = layer_id, label, merge_key
        self.before_spec, self.after_spec = before_spec.copy(), after_spec.copy()
        self._before, self._after = Packed(before_px), Packed(after_px)

    def _apply(self, doc, spec, packed):
        layer = doc.layer_by_id(self.layer_id)
        layer.text = spec.copy()
        layer.pixels[...] = packed.unpack()
        doc.emit("pixels", None)
        doc.emit("structure")

    def do(self, doc):
        self._apply(doc, self.after_spec, self._after)

    def undo(self, doc):
        self._apply(doc, self.before_spec, self._before)

    def merge(self, other):
        if isinstance(other, TextCommand) and other.layer_id == self.layer_id:
            self.after_spec, self._after = other.after_spec, other._after
            return True
        return False

    @property
    def nbytes(self):
        return self._before.nbytes + self._after.nbytes + 256


class LayerPropsCommand(Command):
    def __init__(self, layer_id: int, before: Dict, after: Dict, label=tr('Layer properties'), merge_key=None):
        self.layer_id, self.before, self.after = layer_id, dict(before), dict(after)
        self.label, self.merge_key = label, merge_key

    def do(self, doc):
        doc.layer_by_id(self.layer_id).apply_props(self.after)
        doc.emit("structure")
        doc.emit("pixels", None)

    def undo(self, doc):
        doc.layer_by_id(self.layer_id).apply_props(self.before)
        doc.emit("structure")
        doc.emit("pixels", None)

    def merge(self, other):
        if isinstance(other, LayerPropsCommand) and other.layer_id == self.layer_id:
            self.after = other.after
            return True
        return False


class AddLayerCommand(Command):
    def __init__(self, layer: Layer, index: int, label=tr('Add layer')):
        self.layer, self.index, self.label = layer, index, label
        self._active_before: Optional[int] = None

    def do(self, doc):
        self._active_before = doc.active_index
        doc.insert_layer(self.layer, self.index)

    def undo(self, doc):
        doc.pop_layer(doc.index_of(self.layer))
        doc.active_index = max(0, min(len(doc.layers) - 1, self._active_before or 0))
        doc.emit("structure")

    @property
    def nbytes(self):
        return self.layer.pixels.nbytes


class RemoveLayerCommand(Command):
    def __init__(self, index: int, label=tr('Delete layer')):
        self.index, self.label = index, label
        self.layer: Optional[Layer] = None
        self._active_before = 0

    def do(self, doc):
        self._active_before = doc.active_index
        self.layer = doc.pop_layer(self.index)

    def undo(self, doc):
        doc.insert_layer(self.layer, self.index)
        doc.active_index = self._active_before
        doc.emit("structure")

    @property
    def nbytes(self):
        return self.layer.pixels.nbytes if self.layer is not None else 256


class MoveLayerCommand(Command):
    def __init__(self, src: int, dst: int, label=tr('Move layer')):
        self.src, self.dst, self.label = src, dst, label

    def do(self, doc):
        doc.move_layer(self.src, self.dst)

    def undo(self, doc):
        doc.move_layer(self.dst, self.src)


class SelectionCommand(Command):
    def __init__(self, before: Optional[np.ndarray], after: Optional[np.ndarray], label=tr('Selection')):
        self.label = label
        self._before = Packed(before) if before is not None else None
        self._after = Packed(after) if after is not None else None

    @staticmethod
    def _set(doc, packed):
        doc.selection.mask = packed.unpack() if packed is not None else None
        doc.emit("selection")

    def do(self, doc):
        self._set(doc, self._after)

    def undo(self, doc):
        self._set(doc, self._before)

    @property
    def nbytes(self):
        return (self._before.nbytes if self._before else 0) + (self._after.nbytes if self._after else 0) + 128


class SnapshotCommand(Command):
    """Cambios globales (redimensionar, recortar, aplanar, rotar...) mediante instantáneas."""

    def __init__(self, before: DocSnapshot, after: DocSnapshot, label: str):
        self.before, self.after, self.label = before, after, label

    def do(self, doc):
        doc.restore(self.after)

    def undo(self, doc):
        doc.restore(self.before)

    @property
    def nbytes(self):
        return self.before.nbytes + self.after.nbytes


class CompoundCommand(Command):
    def __init__(self, label: str, commands: List[Command]):
        self.label, self.commands = label, commands

    def do(self, doc):
        for c in self.commands:
            c.do(doc)

    def undo(self, doc):
        for c in reversed(self.commands):
            c.undo(doc)

    @property
    def nbytes(self):
        return sum(c.nbytes for c in self.commands)
