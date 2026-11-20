"""Utilidades Qt: conversión NumPy<->QImage, colores y manejo de errores de interfaz."""

from __future__ import annotations

import functools
import logging
import os
import sys
import traceback

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QMessageBox

from ..core.errors import OutOfMemoryAppError, PaintMintError

log = logging.getLogger("paintmint")


def qimage_from_rgba(arr: np.ndarray, copy: bool = True) -> QImage:
    """QImage RGBA8888 (alfa recto) a partir de un arreglo (h, w, 4) contiguo uint8."""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888)
    return img.copy() if copy else img


def rgba_from_qimage(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    ptr = img.constBits()
    ptr.setsize(h * bpl)
    return np.frombuffer(ptr, dtype=np.uint8).reshape(h, bpl // 4, 4)[:, :w].copy()


def pixmap_from_rgba(arr: np.ndarray, size: int) -> QPixmap:
    return QPixmap.fromImage(qimage_from_rgba(arr)).scaled(
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def qcolor(c) -> QColor:
    return QColor(int(c[0]), int(c[1]), int(c[2]), int(c[3]))


def color_tuple(qc: QColor):
    return (qc.red(), qc.green(), qc.blue(), qc.alpha())


def show_error(parent, exc: BaseException, title: str = "PaintMint") -> None:
    """Muestra un error al usuario sin cerrar la aplicación."""
    if isinstance(exc, OutOfMemoryAppError) or isinstance(exc, MemoryError):
        box = QMessageBox(QMessageBox.Warning, tr('Out of memory'), str(exc) or
                          tr('Not enough memory to complete the operation.'), QMessageBox.Ok, parent)
    elif isinstance(exc, PaintMintError):
        box = QMessageBox(QMessageBox.Warning, title, str(exc), QMessageBox.Ok, parent)
    else:
        log.error(tr('Unexpected error'), exc_info=exc)
        box = QMessageBox(QMessageBox.Critical, tr('Unexpected error'),
                          tr('An unexpected error occurred, but the application is still running.\nYour images have not been lost; consider saving your work.'), QMessageBox.Ok, parent)
        box.setDetailedText("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    box.exec_()


def guarded(fn):
    """Decorador para slots de la interfaz: captura y muestra cualquier excepción."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except (Exception, MemoryError) as exc:  # noqa: BLE001 - la UI nunca debe morir por un slot
            show_error(self if hasattr(self, "isVisible") else None, exc)
            return None

    return wrapper


def log_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    folder = os.path.join(base, "paintmint")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return os.devnull
    return os.path.join(folder, "error.log")


def install_excepthook() -> None:
    """Evita que una excepción no capturada en un slot de Qt termine el proceso."""
    logging.basicConfig(filename=log_path(), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    def hook(etype, value, tb):
        log.error('Uncaught exception', exc_info=(etype, value, tb))
        if QApplication.instance() is not None:
            try:
                show_error(QApplication.activeWindow(), value)
            except Exception:  # pragma: no cover
                traceback.print_exception(etype, value, tb)
        else:  # pragma: no cover
            traceback.print_exception(etype, value, tb)

    sys.excepthook = hook
