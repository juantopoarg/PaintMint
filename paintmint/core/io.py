"""Apertura y guardado de imágenes (PNG, JPG, BMP, GIF, TIFF) y del formato por capas OpenRaster (.ora).

Todos los fallos esperables (archivo inexistente, corrupto, sin permisos, disco
lleno, memoria insuficiente) se convierten en ``PaintMintError`` con un mensaje
apto para el usuario; nunca se propagan excepciones de Pillow/OSError sin traducir.
"""

from __future__ import annotations

from ..i18n import tr

import dataclasses
import errno
import io as _io
import json
import os
import struct
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from . import memory
from .blend import BLEND_MODES
from .document import Document
from .errors import (ImageLoadError, ImageSaveError, ImageTooLargeError, OutOfMemoryAppError,
                     PaintMintError, UnsupportedFormatError)
from .layer import Layer, TextSpec

# Los límites de tamaño los controla ``memory.check_canvas_size`` (antes de decodificar),
# por eso se desactiva la protección interna de Pillow, que solo avisa.
Image.MAX_IMAGE_PIXELS = None

SAVE_FORMATS = {
    ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".jpe": "JPEG", ".bmp": "BMP",
    ".gif": "GIF", ".tif": "TIFF", ".tiff": "TIFF", ".ora": "ORA",
}
SUPPORTED_PIL_FORMATS = {"PNG", "JPEG", "MPO", "BMP", "GIF", "TIFF"}

FILE_FILTERS = {
    "open": tr('Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.ora);;All files (*)'),
    "png": "PNG (*.png)", "jpg": "JPEG (*.jpg *.jpeg)", "bmp": "BMP (*.bmp)",
    "gif": "GIF (*.gif)", "tiff": "TIFF (*.tif *.tiff)", "ora": tr('OpenRaster with layers (*.ora)'),
}

_ORA_OPS = {
    "normal": "svg:src-over", "multiply": "svg:multiply", "screen": "svg:screen",
    "overlay": "svg:overlay", "darken": "svg:darken", "lighten": "svg:lighten",
    "color_dodge": "svg:color-dodge", "color_burn": "svg:color-burn",
    "difference": "svg:difference", "additive": "svg:plus",
}
_ORA_OPS_REV = {v: k for k, v in _ORA_OPS.items()}


# ----------------------------------------------------------------------------
# Apertura
# ----------------------------------------------------------------------------
def _to_rgba_array(im: Image.Image) -> np.ndarray:
    """Convierte cualquier modo de Pillow a un arreglo RGBA uint8 (incluye 16 bits y flotantes)."""
    if im.mode in ("I;16", "I;16L", "I;16B", "I;16N", "I", "F"):
        arr = np.asarray(im).astype(np.float64)
        top = arr.max() if arr.size else 1.0
        scale = 65535.0 if im.mode.startswith("I;16") else (255.0 if top <= 255 else max(top, 1.0))
        gray = np.clip(arr / scale * 255.0, 0, 255).astype(np.uint8)
        return np.dstack([gray, gray, gray, np.full_like(gray, 255)])
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return np.array(im, dtype=np.uint8)


def open_document(path: str) -> Document:
    """Abre un archivo de imagen o ``.ora`` y devuelve un ``Document``."""
    path = os.fspath(path)
    if not os.path.exists(path):
        raise ImageLoadError(tr("The file does not exist:\n{path}").format(path=path))
    if os.path.isdir(path):
        raise ImageLoadError(tr('"{path}" is a folder, not an image file.').format(path=path))
    if not os.access(path, os.R_OK):
        raise ImageLoadError(tr("You do not have read permission for the file:\n{path}").format(path=path))
    try:
        if path.lower().endswith(".ora"):
            doc = _open_ora(path)
        else:
            doc = _open_raster(path)
    except PaintMintError:
        raise
    except MemoryError as exc:
        raise OutOfMemoryAppError(tr('Not enough memory to open this image.')) from exc
    except UnidentifiedImageError as exc:
        raise ImageLoadError(
            tr('"{name}" is not a valid image or is damaged.').format(name=os.path.basename(path))) from exc
    except PermissionError as exc:
        raise ImageLoadError(tr("You do not have read permission for the file:\n{path}").format(path=path)) from exc
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(tr('The image is too large to open safely.')) from exc
    except (OSError, SyntaxError, ValueError, EOFError, struct.error, zipfile.BadZipFile, ET.ParseError,
            KeyError) as exc:
        raise ImageLoadError(
            tr('Could not read "{name}": the file is damaged or incomplete ({error}).').format(name=os.path.basename(path), error=exc)) from exc
    doc.path = path
    return doc


def _open_raster(path: str) -> Document:
    with Image.open(path) as im:
        if im.format not in SUPPORTED_PIL_FORMATS:
            raise UnsupportedFormatError(
                tr("Unsupported format ({fmt}). Use PNG, JPG, BMP, GIF, TIFF or ORA.").format(fmt=im.format))
        w, h = im.size
        memory.check_canvas_size(w, h)
        memory.ensure_memory(w * h * 4 * 3, tr('open the image'))
        im.seek(0)  # GIF/TIFF multi-cuadro: solo se abre el primero
        im.load()
        try:
            im = ImageOps.exif_transpose(im)  # respeta la orientación EXIF
        except Exception:
            pass  # EXIF ilegible: se conserva la orientación tal cual
        rgba = _to_rgba_array(im)
    return Document.from_pixels(rgba, name=tr('Background'))


def _open_ora(path: str) -> Document:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("stack.xml"))
        image = root if root.tag == "image" else root.find("image")
        if image is None:
            raise ImageLoadError(tr('The ORA file does not contain a valid image.'))
        w, h = int(image.get("w")), int(image.get("h"))
        memory.check_canvas_size(w, h)
        nodes = [n for n in image.iter("layer")]
        if not nodes:
            raise ImageLoadError(tr('The ORA file contains no layers.'))
        layers = []
        for node in reversed(nodes):  # en ORA la primera capa es la superior
            with Image.open(_io.BytesIO(zf.read(node.get("src")))) as limg:
                limg.load()
                arr = _to_rgba_array(limg)
            canvas = memory.alloc_pixels(w, h, (0, 0, 0, 0), tr('open the layers'))
            x, y = int(float(node.get("x", 0))), int(float(node.get("y", 0)))
            lh, lw = arr.shape[:2]
            sx0, sy0, dx0, dy0 = max(0, -x), max(0, -y), max(0, x), max(0, y)
            cw, ch = min(lw - sx0, w - dx0), min(lh - sy0, h - dy0)
            if cw > 0 and ch > 0:
                canvas[dy0:dy0 + ch, dx0:dx0 + cw] = arr[sy0:sy0 + ch, sx0:sx0 + cw]
            op = node.get("composite-op", "svg:src-over")
            mode = node.get("paintmint-blend") or _ORA_OPS_REV.get(op, "normal")
            layer = Layer(canvas, name=node.get("name", tr('Layer')),
                          visible=node.get("visibility", "visible") != "hidden",
                          opacity=float(node.get("opacity", 1.0)),
                          blend_mode=mode if mode in BLEND_MODES else "normal")
            spec = node.get("paintmint-text")
            if spec:
                try:
                    data = json.loads(spec)
                    data["color"] = tuple(data.get("color", (0, 0, 0, 255)))
                    layer.text = TextSpec(**data)
                except (TypeError, ValueError):
                    layer.text = None  # texto no restaurable: queda como píxeles
            layers.append(layer)
    return Document.from_layers(w, h, layers)


# ----------------------------------------------------------------------------
# Guardado
# ----------------------------------------------------------------------------
def format_for_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    fmt = SAVE_FORMATS.get(ext)
    if fmt is None:
        raise UnsupportedFormatError(
            tr('Extension "{ext}" is not supported. Use .png, .jpg, .bmp, .gif, .tif or .ora.').format(ext=ext or tr("(none)")))
    return fmt


def _gif_image(flat: np.ndarray):
    rgb = Image.fromarray(np.ascontiguousarray(flat[..., :3]))
    transparent = flat[..., 3] < 128
    if not transparent.any():
        return rgb.quantize(colors=256), None
    pal_img = rgb.quantize(colors=255)
    palette = (pal_img.getpalette() or [])[:765]
    palette += [0] * (768 - len(palette))
    idx = np.array(pal_img, dtype=np.uint8)
    idx[transparent] = 255
    out = Image.frombytes("P", (idx.shape[1], idx.shape[0]), np.ascontiguousarray(idx).tobytes())
    out.putpalette(palette)
    return out, 255


def _encode(doc: Document, fmt: str, quality: int) -> bytes:
    buf = _io.BytesIO()
    if fmt == "ORA":
        _write_ora(doc, buf)
        return buf.getvalue()
    if fmt == "JPEG":
        flat = doc.composite(background=(255, 255, 255, 255))  # JPEG no tiene alfa
        Image.fromarray(np.ascontiguousarray(flat[..., :3])).save(buf, "JPEG", quality=int(quality), optimize=True)
    elif fmt == "GIF":
        img, transp = _gif_image(doc.composite())
        kw = {"transparency": transp} if transp is not None else {}
        img.save(buf, "GIF", **kw)
    elif fmt == "TIFF":
        img = Image.fromarray(np.ascontiguousarray(doc.composite()))
        try:
            img.save(buf, "TIFF", compression="tiff_lzw")
        except (OSError, ValueError, KeyError):
            buf = _io.BytesIO()
            img.save(buf, "TIFF")  # sin libtiff: sin compresión
    elif fmt == "BMP":
        # el alfa de BMP no es interoperable (Pillow ni siquiera lo relee): se aplana sobre blanco
        flat = doc.composite(background=(255, 255, 255, 255))
        Image.fromarray(np.ascontiguousarray(flat[..., :3])).save(buf, "BMP")
    elif fmt == "PNG":
        Image.fromarray(np.ascontiguousarray(doc.composite())).save(buf, "PNG")
    else:  # pragma: no cover
        raise UnsupportedFormatError(f"Unsupported format: {fmt}")
    return buf.getvalue()


def _write_ora(doc: Document, fileobj) -> None:
    def png_bytes(arr):
        b = _io.BytesIO()
        Image.fromarray(np.ascontiguousarray(arr)).save(b, "PNG")
        return b.getvalue()

    image = ET.Element("image", w=str(doc.width), h=str(doc.height), version="0.0.3")
    stack = ET.SubElement(image, "stack")
    with zipfile.ZipFile(fileobj, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "image/openraster", compress_type=zipfile.ZIP_STORED)
        for i, layer in reversed(list(enumerate(doc.layers))):  # superior primero
            name = f"data/layer{i}.png"
            zf.writestr(name, png_bytes(layer.pixels))
            attrs = {
                "name": layer.name, "src": name, "x": "0", "y": "0",
                "opacity": f"{layer.opacity:.4f}",
                "visibility": "visible" if layer.visible else "hidden",
                "composite-op": _ORA_OPS.get(layer.blend_mode, "svg:src-over"),
                "paintmint-blend": layer.blend_mode,
            }
            if layer.text is not None:
                attrs["paintmint-text"] = json.dumps(dataclasses.asdict(layer.text))
            ET.SubElement(stack, "layer", attrs)
        zf.writestr("stack.xml", ET.tostring(image, encoding="utf-8", xml_declaration=True))
        zf.writestr("mergedimage.png", png_bytes(doc.composite()))


def save_document(doc: Document, path: str, quality: int = 92) -> str:
    """Guarda ``doc`` en ``path`` (formato según extensión). Devuelve el formato usado.

    Se escribe primero en un temporal y se renombra, de modo que un fallo a mitad
    de camino (disco lleno, permisos) nunca destruye el archivo existente.
    """
    path = os.fspath(path)
    fmt = format_for_path(path)
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        raise ImageSaveError(tr("The destination folder does not exist:\n{folder}").format(folder=folder))
    if not os.access(folder, os.W_OK):
        raise ImageSaveError(tr("You do not have write permission for the folder:\n{folder}").format(folder=folder))
    if os.path.exists(path) and not os.access(path, os.W_OK):
        raise ImageSaveError(tr("The file is read-only:\n{path}").format(path=path))
    try:
        memory.ensure_memory(doc.width * doc.height * 4 * 3, tr('save the image'))
        data = _encode(doc, fmt, quality)
    except PaintMintError:
        raise
    except MemoryError as exc:
        raise OutOfMemoryAppError(tr('Not enough memory to save the image.')) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise ImageSaveError(tr("Could not encode the image as {fmt}: {error}").format(fmt=fmt, error=exc)) from exc

    tmp = os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except PermissionError as exc:
        raise ImageSaveError(tr("You do not have permission to save to:\n{path}").format(path=path)) from exc
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise ImageSaveError(tr('There is not enough disk space to save the file.')) from exc
        if exc.errno == errno.EROFS:
            raise ImageSaveError(tr('The destination is on a read-only file system.')) from exc
        raise ImageSaveError(tr("Could not save the file: {error}").format(error=exc.strerror or exc)) from exc
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return fmt
