"""Documento: lienzo, pila de capas (índice 0 = fondo) y selección."""

from __future__ import annotations

from ..i18n import tr

import zlib
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import numpy as np

from . import memory
from .blend import composite
from .errors import InvalidOperationError
from .layer import Layer
from .selection import Selection

Listener = Callable[[str, object], None]


class Packed:
    """Arreglo numpy guardado (opcionalmente comprimido) para el historial."""

    __slots__ = ("shape", "dtype", "data", "compressed")

    def __init__(self, arr: np.ndarray):
        raw = np.ascontiguousarray(arr)
        self.shape, self.dtype = raw.shape, raw.dtype
        if raw.nbytes >= 64 * 1024:
            self.data, self.compressed = zlib.compress(raw.tobytes(), 1), True
        else:
            self.data, self.compressed = raw.tobytes(), False

    def unpack(self) -> np.ndarray:
        raw = zlib.decompress(self.data) if self.compressed else self.data
        return np.frombuffer(raw, dtype=self.dtype).reshape(self.shape).copy()

    @property
    def nbytes(self) -> int:
        return len(self.data)


@dataclass
class _LayerState:
    pixels: Packed
    props: dict
    text: object
    layer_id: int


class DocSnapshot:
    """Instantánea completa (tamaño, capas, selección) para operaciones globales."""

    def __init__(self, doc: "Document"):
        self.width, self.height = doc.width, doc.height
        self.active = doc.active_index
        self.layers: List[_LayerState] = [
            _LayerState(Packed(l.pixels), l.props(), l.text.copy() if l.text else None, l.id)
            for l in doc.layers
        ]
        self.mask = Packed(doc.selection.mask) if doc.selection.mask is not None else None

    @property
    def nbytes(self) -> int:
        return sum(s.pixels.nbytes for s in self.layers) + (self.mask.nbytes if self.mask else 0)

    def layers_restored(self) -> List[Layer]:
        out = []
        for st in self.layers:
            layer = Layer(st.pixels.unpack(), text=st.text.copy() if st.text else None, layer_id=st.layer_id)
            layer.apply_props(st.props)
            out.append(layer)
        return out


class Document:
    """Modelo de un documento abierto. No conoce la interfaz: emite eventos a ``listeners``.

    Eventos: ``("pixels", rect|None)``, ``("structure", None)``,
    ``("selection", None)``, ``("size", None)``.
    """

    def __init__(self, width: int, height: int, fill=(255, 255, 255, 255), name: str = tr('Background')):
        pixels = memory.alloc_pixels(width, height, fill, tr('create the image'))
        self.width, self.height = width, height
        self.layers: List[Layer] = [Layer(pixels, name=name)]
        self.active_index = 0
        self.selection = Selection(width, height)
        self.listeners: List[Listener] = []
        self.path: Optional[str] = None

    # -- construcción alternativa ------------------------------------------
    @classmethod
    def from_pixels(cls, pixels: np.ndarray, name: str = tr('Background')) -> "Document":
        h, w = pixels.shape[:2]
        memory.check_canvas_size(w, h)
        doc = cls.__new__(cls)
        doc.width, doc.height = w, h
        doc.layers = [Layer(pixels, name=name)]
        doc.active_index = 0
        doc.selection = Selection(w, h)
        doc.listeners = []
        doc.path = None
        return doc

    @classmethod
    def from_layers(cls, width: int, height: int, layers: List[Layer]) -> "Document":
        if not layers:
            raise InvalidOperationError(tr('A document needs at least one layer.'))
        memory.check_canvas_size(width, height)
        doc = cls.__new__(cls)
        doc.width, doc.height = width, height
        doc.layers = list(layers)
        doc.active_index = len(layers) - 1
        doc.selection = Selection(width, height)
        doc.listeners = []
        doc.path = None
        return doc

    # -- eventos -----------------------------------------------------------
    def add_listener(self, fn: Listener) -> None:
        self.listeners.append(fn)

    def emit(self, kind: str, payload=None) -> None:
        for fn in list(self.listeners):
            fn(kind, payload)

    # -- acceso --------------------------------------------------------------
    @property
    def active_layer(self) -> Layer:
        return self.layers[self.active_index]

    def layer_by_id(self, layer_id: int) -> Layer:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        raise KeyError(f"Layer {layer_id} does not exist")

    def index_of(self, layer: Layer) -> int:
        for i, l in enumerate(self.layers):
            if l is layer:
                return i
        raise KeyError('The layer does not belong to the document')

    def set_active(self, index: int) -> None:
        self.active_index = max(0, min(len(self.layers) - 1, index))
        self.emit("structure")

    # -- mutaciones de bajo nivel (las usan los comandos del historial) ------
    def insert_layer(self, layer: Layer, index: Optional[int] = None) -> int:
        index = len(self.layers) if index is None else max(0, min(len(self.layers), index))
        self.layers.insert(index, layer)
        self.active_index = index
        self.emit("structure")
        self.emit("pixels", None)
        return index

    def pop_layer(self, index: int) -> Layer:
        if len(self.layers) <= 1:
            raise InvalidOperationError(tr('The only layer in the document cannot be deleted.'))
        layer = self.layers.pop(index)
        self.active_index = max(0, min(len(self.layers) - 1, self.active_index))
        self.emit("structure")
        self.emit("pixels", None)
        return layer

    def move_layer(self, src: int, dst: int) -> None:
        layer = self.layers.pop(src)
        self.layers.insert(dst, layer)
        self.active_index = dst
        self.emit("structure")
        self.emit("pixels", None)

    def restore(self, snap: DocSnapshot) -> None:
        self.width, self.height = snap.width, snap.height
        self.layers = snap.layers_restored()
        self.active_index = max(0, min(len(self.layers) - 1, snap.active))
        self.selection = Selection(self.width, self.height, snap.mask.unpack() if snap.mask else None)
        self.emit("size")
        self.emit("structure")
        self.emit("selection")
        self.emit("pixels", None)

    # -- composición ---------------------------------------------------------
    def composite(self, region: Optional[Tuple[int, int, int, int]] = None,
                  background: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
        return composite(self.layers, self.width, self.height, region, background)
