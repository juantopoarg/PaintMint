"""Sesión de edición: une documento + historial y expone todas las operaciones de alto nivel.

Es la única puerta de escritura al documento para herramientas e interfaz, de
modo que toda modificación queda registrada en el historial.
"""

from __future__ import annotations

from ..i18n import tr

from typing import Callable, List, Optional, Tuple

import numpy as np
from PIL import Image

from ..render import raster
from ..render.text import render_text_layer
from . import commands as C
from . import memory
from .blend import composite
from .document import DocSnapshot, Document
from .errors import InvalidOperationError, OutOfMemoryAppError, PaintMintError
from .history import History
from .layer import Layer, TextSpec

_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
_BICUBIC = getattr(Image, "Resampling", Image).BICUBIC
_NEAREST = getattr(Image, "Resampling", Image).NEAREST
_BILINEAR = getattr(Image, "Resampling", Image).BILINEAR
RESAMPLE = {"lanczos": _LANCZOS, "bicubic": _BICUBIC, "bilinear": _BILINEAR, "nearest": _NEAREST}

ANCHORS = ("tl", "t", "tr", "l", "c", "r", "bl", "b", "br")
# fracción (horizontal, vertical) del espacio nuevo que queda antes de la imagen original
_ANCHOR_FRACTIONS = {
    "tl": (0.0, 0.0), "t": (0.5, 0.0), "tr": (1.0, 0.0),
    "l": (0.0, 0.5), "c": (0.5, 0.5), "r": (1.0, 0.5),
    "bl": (0.0, 1.0), "b": (0.5, 1.0), "br": (1.0, 1.0),
}


class EditHandle:
    """Edición transitoria de una capa (trazo, vista previa de efecto, arrastre de forma...).

    Mantiene una copia ``snapshot`` de la capa al empezar; todo lo que se escribe
    se recorta con la selección activa, y ``commit`` registra un único comando
    de historial con el rectángulo realmente modificado.
    """

    def __init__(self, session: "EditSession", layer: Layer):
        self.session, self.layer = session, layer
        self.doc = session.doc
        self.snapshot = memory.copy_pixels(layer.pixels, tr('edit the layer'))
        self.text_before = layer.text.copy() if layer.text else None
        layer.text = None                 # editar píxeles rasteriza el texto
        self.sel_mask = self.doc.selection.mask
        self.dirty: Optional[raster.Rect] = None
        self.closed = False

    # -- escritura ---------------------------------------------------------
    def write(self, rect: raster.Rect, block: np.ndarray, clip: bool = True) -> None:
        """Sustituye ``rect`` por ``block`` (recortado por la selección si ``clip``)."""
        h, w = self.layer.pixels.shape[:2]
        x0, y0, x1, y1 = rect
        cx0, cy0, cx1, cy1 = raster.clip_rect(rect, w, h)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        block = block[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
        snap = self.snapshot[cy0:cy1, cx0:cx1]
        if clip and self.sel_mask is not None:
            sel = self.sel_mask[cy0:cy1, cx0:cx1]
            if not sel.any():
                block = snap
            elif not (sel == 255).all():
                block = raster.lerp_premult(snap, block, sel.astype(np.float32) / 255.0)
        self.layer.pixels[cy0:cy1, cx0:cx1] = block
        self.dirty = raster.union_rect(self.dirty, (cx0, cy0, cx1, cy1))
        self.doc.emit("pixels", (cx0, cy0, cx1, cy1))

    def write_full(self, pixels: np.ndarray) -> None:
        """Escribe una capa completa (efectos); solo se procesa la caja de la selección."""
        h, w = pixels.shape[:2]
        if self.sel_mask is not None:
            x0, y0, x1, y1 = self.doc.selection.bbox()
        else:
            x0, y0, x1, y1 = 0, 0, w, h
        self.write((x0, y0, x1, y1), pixels[y0:y1, x0:x1])

    def reset(self) -> None:
        """Vuelve al estado inicial de la capa sin cerrar la edición."""
        if self.dirty is not None:
            x0, y0, x1, y1 = self.dirty
            self.layer.pixels[y0:y1, x0:x1] = self.snapshot[y0:y1, x0:x1]
            self.doc.emit("pixels", self.dirty)
            self.dirty = None

    # -- cierre ------------------------------------------------------------
    def cancel(self) -> None:
        if self.closed:
            return
        self.reset()
        self.layer.text = self.text_before
        self.closed = True

    def commit(self, label: str, extra: Optional[List[C.Command]] = None) -> bool:
        """Registra el cambio. Devuelve ``False`` (y no crea comando) si nada cambió."""
        if self.closed:
            return False
        self.closed = True
        cmds: List[C.Command] = []
        changed = False
        if self.dirty is not None:
            x0, y0, x1, y1 = self.dirty
            diff = (self.layer.pixels[y0:y1, x0:x1] != self.snapshot[y0:y1, x0:x1]).any(axis=2)
            rows, cols = np.flatnonzero(diff.any(axis=1)), np.flatnonzero(diff.any(axis=0))
            if rows.size:
                rect = (x0 + int(cols[0]), y0 + int(rows[0]), x0 + int(cols[-1]) + 1, y0 + int(rows[-1]) + 1)
                rx0, ry0, rx1, ry1 = rect
                cmds.append(C.PatchCommand(
                    self.layer.id, rect,
                    self.snapshot[ry0:ry1, rx0:rx1], self.layer.pixels[ry0:ry1, rx0:rx1].copy(),
                    label, text_before=self.text_before, text_after=None))
                changed = True
        if not changed:
            self.layer.text = self.text_before  # nada cambió: el texto sigue siendo editable
        if extra:
            cmds.extend(extra)
        if not cmds:
            return False
        self.session.history.push(cmds[0] if len(cmds) == 1 else C.CompoundCommand(label, cmds))
        return True


class EditSession:
    def __init__(self, doc: Document, history_max_bytes: Optional[int] = None):
        self.doc = doc
        self.history = History(doc, history_max_bytes)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def modified(self) -> bool:
        return self.history.modified

    @property
    def active_layer(self) -> Layer:
        return self.doc.active_layer

    def mark_saved(self, path: Optional[str] = None) -> None:
        if path:
            self.doc.path = path
        self.history.mark_clean()

    def undo(self) -> bool:
        return self.history.undo()

    def redo(self) -> bool:
        return self.history.redo()

    # ------------------------------------------------------------------
    # Edición de píxeles
    # ------------------------------------------------------------------
    def begin_edit(self, layer: Optional[Layer] = None) -> EditHandle:
        return EditHandle(self, layer or self.doc.active_layer)

    def apply_effect(self, effect, params: dict, layer: Optional[Layer] = None) -> bool:
        """Aplica un efecto/ajuste a la capa (limitado a la selección). Devuelve si cambió algo."""
        handle = self.begin_edit(layer)
        try:
            result = effect.apply(handle.snapshot, **effect.resolve(params))
            handle.write_full(result)
        except MemoryError as exc:
            handle.cancel()
            raise OutOfMemoryAppError(tr('Not enough memory to apply the effect.')) from exc
        except Exception:
            handle.cancel()
            raise
        return handle.commit(effect.label)

    def fill_selection(self, color: Tuple[int, int, int, int]) -> bool:
        handle = self.begin_edit()
        x0, y0, x1, y1 = self.doc.selection.bbox()
        block = np.empty((y1 - y0, x1 - x0, 4), dtype=np.uint8)
        block[...] = color
        handle.write((x0, y0, x1, y1), block)
        return handle.commit(tr('Fill selection'))

    def delete_selection(self) -> bool:
        handle = self.begin_edit()
        x0, y0, x1, y1 = self.doc.selection.bbox()
        handle.write((x0, y0, x1, y1), np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8))
        return handle.commit(tr('Delete selection'))

    def flip_layer(self, horizontal: bool = True) -> bool:
        handle = self.begin_edit()
        flipped = handle.snapshot[:, ::-1] if horizontal else handle.snapshot[::-1]
        handle.write((0, 0, self.doc.width, self.doc.height), np.ascontiguousarray(flipped), clip=False)
        return handle.commit(tr('Flip layer horizontally') if horizontal else tr('Flip layer vertically'))

    # ------------------------------------------------------------------
    # Capas
    # ------------------------------------------------------------------
    def add_layer(self, name: Optional[str] = None, fill=(0, 0, 0, 0)) -> Layer:
        pixels = memory.alloc_pixels(self.doc.width, self.doc.height, fill, tr('add a layer'))
        layer = Layer(pixels, name=name or tr("Layer {n}").format(n=len(self.doc.layers) + 1))
        self.history.execute(C.AddLayerCommand(layer, self.doc.active_index + 1))
        return layer

    def duplicate_layer(self) -> Layer:
        src = self.doc.active_layer
        memory.ensure_memory(src.pixels.nbytes * 2, tr('duplicate the layer'))
        layer = src.clone(new_id=True)
        layer.name = src.name + tr(' copy')
        self.history.execute(C.AddLayerCommand(layer, self.doc.active_index + 1, tr('Duplicate layer')))
        return layer

    def delete_layer(self, index: Optional[int] = None) -> None:
        if len(self.doc.layers) <= 1:
            raise InvalidOperationError(tr('The only layer in the document cannot be deleted.'))
        idx = self.doc.active_index if index is None else index
        self.history.execute(C.RemoveLayerCommand(idx))

    def move_layer(self, delta: int, index: Optional[int] = None) -> bool:
        src = self.doc.active_index if index is None else index
        dst = src + delta
        if not (0 <= dst < len(self.doc.layers)) or dst == src:
            return False
        self.history.execute(C.MoveLayerCommand(src, dst))
        return True

    def set_layer_props(self, layer: Layer, merge: bool = False, **props) -> bool:
        before = {k: getattr(layer, k) for k in props}
        if before == props:
            return False
        # validar antes de aplicar (los setters lanzan PaintMintError con valores inválidos)
        probe = Layer(np.zeros((1, 1, 4), np.uint8))
        probe.apply_props(props)
        key = ("props", layer.id, tuple(sorted(props))) if merge else None
        label = tr('Layer properties')
        if set(props) == {"visible"}:
            label = tr('Show layer') if props["visible"] else tr('Hide layer')
        elif set(props) == {"opacity"}:
            label = tr('Layer opacity')
        elif set(props) == {"name"}:
            label = tr('Rename layer')
        self.history.execute(C.LayerPropsCommand(layer.id, before, props, label, key))
        return True

    def merge_down(self) -> None:
        idx = self.doc.active_index
        if idx == 0:
            raise InvalidOperationError(tr('There is no layer below to merge with.'))
        top, below = self.doc.layers[idx], self.doc.layers[idx - 1]
        base = Layer(below.pixels, opacity=1.0, blend_mode="normal")
        merged = composite([base, top], self.doc.width, self.doc.height)
        rect = (0, 0, self.doc.width, self.doc.height)
        patch = C.PatchCommand(below.id, rect, below.pixels.copy(), merged, tr('Merge layer down'),
                               text_before=below.text, text_after=None)
        self.history.execute(C.CompoundCommand(tr('Merge layer down'),
                                               [patch, C.RemoveLayerCommand(idx)]))

    def flatten(self) -> None:
        if len(self.doc.layers) <= 1:
            raise InvalidOperationError(tr('The image already has a single layer.'))
        merged = self.doc.composite()
        layer = Layer(merged, name=tr('Background'))
        self._replace_all(tr('Flatten image'), self.doc.width, self.doc.height, [layer])

    # ------------------------------------------------------------------
    # Texto editable
    # ------------------------------------------------------------------
    def create_text_layer(self, spec: TextSpec) -> Layer:
        pixels = render_text_layer(spec, self.doc.width, self.doc.height)
        layer = Layer(pixels, name=tr('Text: ') + (spec.text.splitlines() or [""])[0][:20], text=spec.copy())
        self.history.execute(C.AddLayerCommand(layer, self.doc.active_index + 1, tr('Add text')))
        return layer

    def update_text_layer(self, layer: Layer, spec: TextSpec, merge: bool = True) -> None:
        if layer.text is None:
            raise InvalidOperationError(tr('The layer is not an editable text layer.'))
        new_px = render_text_layer(spec, self.doc.width, self.doc.height)
        cmd = C.TextCommand(layer.id, layer.text, spec, layer.pixels, new_px,
                            merge_key=("text", layer.id) if merge else None)
        self.history.execute(cmd)

    def rasterize_layer(self, layer: Optional[Layer] = None) -> bool:
        layer = layer or self.doc.active_layer
        if layer.text is None:
            return False
        rect = (0, 0, self.doc.width, self.doc.height)
        px = layer.pixels.copy()
        self.history.execute(C.PatchCommand(layer.id, rect, px, px.copy(), tr('Rasterize text'),
                                            text_before=layer.text, text_after=None))
        return True

    # ------------------------------------------------------------------
    # Selección
    # ------------------------------------------------------------------
    def _change_selection(self, fn: Callable, label: str) -> bool:
        sel = self.doc.selection
        before = None if sel.mask is None else sel.mask.copy()
        fn(sel)
        after = sel.mask
        if before is None and after is None:
            return False
        if before is not None and after is not None and np.array_equal(before, after):
            return False
        self.doc.emit("selection")
        self.history.push(C.SelectionCommand(before, None if after is None else after.copy(), label))
        return True

    def select_all(self) -> bool:
        return self._change_selection(lambda s: s.select_all(), tr('Select all'))

    def deselect(self) -> bool:
        return self._change_selection(lambda s: s.clear(), tr('Deselect'))

    def invert_selection(self) -> bool:
        return self._change_selection(lambda s: s.invert(), tr('Invert selection'))

    def select_rect(self, x0, y0, x1, y1, mode="replace") -> bool:
        return self._change_selection(lambda s: s.select_rect(x0, y0, x1, y1, mode), tr('Rectangle select'))

    def select_ellipse(self, x0, y0, x1, y1, mode="replace") -> bool:
        return self._change_selection(lambda s: s.select_ellipse(x0, y0, x1, y1, mode), tr('Ellipse select'))

    def resize_selection(self, new_box) -> bool:
        """Lleva la selección actual a la caja ``new_box`` (x0, y0, x1, y1) en un solo paso de historial.

        Un rectángulo se recalcula exacto; el resto (elipse, lazo, varita) se reescala con su forma.
        """
        sel = self.doc.selection
        if not sel.active:
            return False
        x0, y0, x1, y1 = sel.bbox()
        nx0, ny0, nx1, ny1 = (int(round(v)) for v in new_box)
        nx1, ny1 = max(nx1, nx0 + 1), max(ny1, ny0 + 1)
        if (nx0, ny0, nx1, ny1) == (x0, y0, x1, y1) or x1 <= x0 or y1 <= y0:
            return False
        crop = sel.mask[y0:y1, x0:x1]
        if (crop == 255).all():
            return self._change_selection(lambda s: s.select_rect(nx0, ny0, nx1, ny1, "replace"), tr('Resize selection'))
        from PIL import Image
        scaled = np.asarray(Image.fromarray(np.ascontiguousarray(crop)).resize((nx1 - nx0, ny1 - ny0), Image.BILINEAR))

        def apply(s):
            m = np.zeros_like(s.mask)
            cx0, cy0, cx1, cy1 = max(nx0, 0), max(ny0, 0), min(nx1, s.width), min(ny1, s.height)
            if cx1 > cx0 and cy1 > cy0:
                m[cy0:cy1, cx0:cx1] = scaled[cy0 - ny0:cy1 - ny0, cx0 - nx0:cx1 - nx0]
            s.mask = m if m.any() else None
        return self._change_selection(apply, tr('Resize selection'))

    def scale_selection_content(self, new_box) -> bool:
        """Escala los píxeles seleccionados de la capa activa hasta ``new_box`` (x0, y0, x1, y1).

        La selección se ajusta a la caja nueva. Un solo paso de historial (píxeles + selección).
        """
        doc = self.doc
        sel = doc.selection
        if not sel.active:
            raise InvalidOperationError(tr('Make a selection first to create a layer from it.'))
        layer = doc.active_layer
        if not layer.visible:
            raise InvalidOperationError(tr('The active layer is hidden. Make it visible to draw on it.'))
        x0, y0, x1, y1 = sel.bbox()
        nx0, ny0, nx1, ny1 = (int(round(v)) for v in new_box)
        nx1, ny1 = max(nx1, nx0 + 1), max(ny1, ny0 + 1)
        if (nx0, ny0, nx1, ny1) == (x0, y0, x1, y1) or x1 <= x0 or y1 <= y0:
            return False
        from PIL import Image
        H, W = layer.pixels.shape[:2]
        before = sel.mask.copy()
        handle = self.begin_edit()
        try:
            snap = handle.snapshot
            src = snap[y0:y1, x0:x1].copy()
            src[..., 3] = (src[..., 3].astype(np.uint16) * before[y0:y1, x0:x1] // 255).astype(np.uint8)
            size = (nx1 - nx0, ny1 - ny0)
            scaled = np.asarray(Image.fromarray(np.ascontiguousarray(src), "RGBA").convert("RGBa")
                                .resize(size, Image.BILINEAR).convert("RGBA"))
            smask = np.asarray(Image.fromarray(np.ascontiguousarray(before[y0:y1, x0:x1])).resize(size, Image.BILINEAR))
            union = raster.union_rect((x0, y0, x1, y1), raster.clip_rect((nx0, ny0, nx1, ny1), W, H))
            ux0, uy0, ux1, uy1 = union
            block = snap[uy0:uy1, ux0:ux1].copy()
            block = raster.lerp_premult(block, np.zeros_like(block), before[uy0:uy1, ux0:ux1].astype(np.float32) / 255.0)
            cx0, cy0, cx1, cy1 = max(nx0, 0), max(ny0, 0), min(nx1, W), min(ny1, H)
            new_mask = np.zeros_like(before)
            if cx1 > cx0 and cy1 > cy0:
                part = scaled[cy0 - ny0:cy1 - ny0, cx0 - nx0:cx1 - nx0]
                reg = block[cy0 - uy0:cy1 - uy0, cx0 - ux0:cx1 - ux0]
                block[cy0 - uy0:cy1 - uy0, cx0 - ux0:cx1 - ux0] = raster.over(
                    reg, part[..., :3], part[..., 3].astype(np.float32) / 255.0)
                new_mask[cy0:cy1, cx0:cx1] = smask[cy0 - ny0:cy1 - ny0, cx0 - nx0:cx1 - nx0]
            handle.write(union, block, clip=False)
            sel.mask = new_mask if new_mask.any() else None
            doc.emit("selection")
            changed = handle.commit(tr('Scale selection'),
                                    extra=[C.SelectionCommand(before, None if sel.mask is None else sel.mask.copy())])
        except MemoryError as exc:
            handle.cancel()
            sel.mask = before
            doc.emit("selection")
            raise OutOfMemoryAppError(tr('Not enough memory to complete the operation.')) from exc
        except Exception:
            handle.cancel()
            sel.mask = before
            doc.emit("selection")
            raise
        if not changed:
            sel.mask = before
            doc.emit("selection")
        return changed

    def select_polygon(self, points, mode="replace") -> bool:
        return self._change_selection(lambda s: s.select_polygon(points, mode), tr('Lasso select'))

    def select_wand(self, x: int, y: int, tolerance: float = 30.0, contiguous: bool = True,
                    mode: str = "replace", sample_image: bool = False) -> bool:
        src = self.doc.composite() if sample_image else self.doc.active_layer.pixels
        region = raster.flood_mask(src, int(x), int(y), tolerance, contiguous)
        return self._change_selection(lambda s: s.select_bool(region, mode), tr('Magic wand'))

    def layer_via_selection(self, cut: bool = False) -> Layer:
        """Crea una capa nueva con los píxeles seleccionados de la capa activa (copiados o cortados).

        Un único paso de historial; la selección se conserva.
        """
        doc = self.doc
        if not doc.selection.active:
            raise InvalidOperationError(tr('Make a selection first to create a layer from it.'))
        x0, y0, x1, y1 = doc.selection.bbox()
        src = doc.active_layer
        pixels = memory.alloc_pixels(doc.width, doc.height, (0, 0, 0, 0), tr('create the layer from the selection'))
        part = src.pixels[y0:y1, x0:x1].copy()
        m = doc.selection.mask[y0:y1, x0:x1].astype(np.uint16)
        part[..., 3] = (part[..., 3].astype(np.uint16) * m // 255).astype(np.uint8)
        pixels[y0:y1, x0:x1] = part
        label = tr('Layer via cut') if cut else tr('Layer via copy')
        layer = Layer(pixels, name=f"{src.name} ({tr('cut') if cut else tr('copy')})")
        index = doc.active_index + 1
        if not cut:
            self.history.execute(C.AddLayerCommand(layer, index, label))
            return layer
        handle = self.begin_edit(src)
        try:
            handle.write((x0, y0, x1, y1), np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8))
            add = C.AddLayerCommand(layer, index, label)
            add.do(doc)           # ya aplicado: commit lo registra junto con el parche
        except Exception:
            handle.cancel()
            raise
        handle.commit(label, extra=[add])
        return layer

    # ------------------------------------------------------------------
    # Portapapeles (la interfaz convierte a/desde QImage)
    # ------------------------------------------------------------------
    def copy_pixels(self, merged: bool = False):
        """Devuelve ``(rgba, (x, y))`` de la región seleccionada de la capa activa (o de la imagen)."""
        x0, y0, x1, y1 = self.doc.selection.bbox()
        if x1 <= x0 or y1 <= y0:
            return None
        src = self.doc.composite((x0, y0, x1, y1)) if merged else self.doc.active_layer.pixels[y0:y1, x0:x1].copy()
        if self.doc.selection.mask is not None:
            m = self.doc.selection.mask[y0:y1, x0:x1].astype(np.uint16)
            src[..., 3] = (src[..., 3].astype(np.uint16) * m // 255).astype(np.uint8)
        return src, (x0, y0)

    def cut_pixels(self):
        data = self.copy_pixels()
        if data is not None:
            self.delete_selection()
        return data

    def paste_pixels(self, rgba: np.ndarray, at: Optional[Tuple[int, int]] = None) -> Layer:
        """Pega ``rgba`` como capa nueva y selecciona el área pegada."""
        h, w = rgba.shape[:2]
        x, y = at if at is not None else (0, 0)
        pixels = memory.alloc_pixels(self.doc.width, self.doc.height, (0, 0, 0, 0), "pegar")
        sx0, sy0 = max(0, -x), max(0, -y)
        dx0, dy0 = max(0, x), max(0, y)
        cw, ch = min(w - sx0, self.doc.width - dx0), min(h - sy0, self.doc.height - dy0)
        if cw <= 0 or ch <= 0:
            raise InvalidOperationError(tr('The pasted content falls outside the canvas.'))
        pixels[dy0:dy0 + ch, dx0:dx0 + cw] = rgba[sy0:sy0 + ch, sx0:sx0 + cw]
        layer = Layer(pixels, name=tr('Pasted'))
        sel = self.doc.selection
        before = None if sel.mask is None else sel.mask.copy()
        new_mask = raster.rect_mask(self.doc.height, self.doc.width, dx0, dy0, dx0 + cw, dy0 + ch)
        self.history.execute(C.CompoundCommand(tr('Paste'), [
            C.AddLayerCommand(layer, self.doc.active_index + 1),
            C.SelectionCommand(before, new_mask),
        ]))
        return layer

    # ------------------------------------------------------------------
    # Operaciones sobre toda la imagen
    # ------------------------------------------------------------------
    def _replace_all(self, label: str, width: int, height: int, layers: List[Layer]) -> None:
        before = DocSnapshot(self.doc)
        doc = self.doc
        old = (doc.width, doc.height, doc.layers, doc.active_index, doc.selection.mask)
        try:
            doc.width, doc.height, doc.layers = width, height, layers
            doc.active_index = min(max(0, old[3]), len(layers) - 1)
            doc.selection.resize_canvas(width, height)
            after = DocSnapshot(doc)
        except Exception:
            doc.width, doc.height, doc.layers, doc.active_index = old[:4]
            doc.selection.width, doc.selection.height, doc.selection.mask = old[0], old[1], old[4]
            raise
        doc.emit("size")
        doc.emit("structure")
        doc.emit("selection")
        doc.emit("pixels", None)
        self.history.push(C.SnapshotCommand(before, after, label))

    def _transform_layers(self, fn: Callable[[np.ndarray], np.ndarray]) -> List[Layer]:
        out = []
        for l in self.doc.layers:
            new = l.clone(copy_pixels=False)
            new.pixels = np.ascontiguousarray(fn(l.pixels))
            new.text = None  # transformar rasteriza el texto
            out.append(new)
        return out

    def flip_image(self, horizontal: bool = True) -> None:
        layers = self._transform_layers(lambda p: p[:, ::-1] if horizontal else p[::-1])
        self._replace_all(tr('Flip image horizontally') if horizontal else tr('Flip image vertically'),
                          self.doc.width, self.doc.height, layers)

    def rotate_image(self, degrees: int) -> None:
        """Rota 90, 180 o 270 grados en sentido horario."""
        k = {90: -1, 180: 2, 270: 1}.get(degrees % 360)
        if k is None:
            raise InvalidOperationError(tr('Only rotations of 90, 180 or 270 degrees are supported.'))
        layers = self._transform_layers(lambda p: np.rot90(p, k))
        h, w = layers[0].pixels.shape[:2]
        self._replace_all(tr("Rotate image {deg}°").format(deg=degrees % 360), w, h, layers)

    def resize_image(self, width: int, height: int, resample: str = "lanczos") -> None:
        memory.check_canvas_size(width, height)
        memory.ensure_memory(width * height * 4 * (len(self.doc.layers) + 2), tr('resize the image'))
        method = RESAMPLE.get(resample, _LANCZOS)
        layers = self._transform_layers(
            lambda p: np.asarray(Image.fromarray(np.ascontiguousarray(p)).resize((width, height), method)))
        self._replace_all(tr('Resize image'), width, height, layers)

    def resize_canvas(self, width: int, height: int, anchor: str = "c") -> None:
        if anchor not in ANCHORS:
            raise InvalidOperationError(f"Unknown anchor: {anchor}")
        memory.check_canvas_size(width, height)
        memory.ensure_memory(width * height * 4 * (len(self.doc.layers) + 2), tr('change the canvas size'))
        ow, oh = self.doc.width, self.doc.height
        ax, ay = _ANCHOR_FRACTIONS[anchor]
        offx, offy = int(round((width - ow) * ax)), int(round((height - oh) * ay))

        def fn(p):
            out = memory.alloc_pixels(width, height, (0, 0, 0, 0), tr('change the canvas size'))
            sx0, sy0 = max(0, -offx), max(0, -offy)
            dx0, dy0 = max(0, offx), max(0, offy)
            cw, ch = min(ow - sx0, width - dx0), min(oh - sy0, height - dy0)
            if cw > 0 and ch > 0:
                out[dy0:dy0 + ch, dx0:dx0 + cw] = p[sy0:sy0 + ch, sx0:sx0 + cw]
            return out

        layers = self._transform_layers(fn)
        self._replace_all(tr('Canvas size'), width, height, layers)

    def crop_to_selection(self) -> None:
        if not self.doc.selection.active:
            raise InvalidOperationError(tr('There is no selection to crop to.'))
        x0, y0, x1, y1 = self.doc.selection.bbox()
        layers = self._transform_layers(lambda p: p[y0:y1, x0:x1])
        self._replace_all(tr('Crop to selection'), x1 - x0, y1 - y0, layers)
