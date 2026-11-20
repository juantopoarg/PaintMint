"""Control de límites de tamaño y de memoria.

En Linux el *overcommit* hace que ``np.zeros`` casi nunca lance ``MemoryError``:
el proceso es terminado por el OOM-killer más tarde, sin aviso. Por eso, antes
de reservar buffers grandes se compara con ``MemAvailable`` de ``/proc/meminfo``
y se lanza un error recuperable si no cabe.
"""

from __future__ import annotations

from ..i18n import tr

import numpy as np

from .errors import ImageTooLargeError, OutOfMemoryAppError

# Límites configurables (las pruebas los modifican).
MAX_PIXELS = 100_000_000        # 100 megapíxeles por capa
MAX_DIMENSION = 32_768          # lado máximo
MEMORY_SAFETY_FACTOR = 0.80     # fracción de MemAvailable que se permite usar


def available_bytes():
    """Memoria disponible en bytes, o ``None`` si no se puede determinar."""
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def check_canvas_size(width: int, height: int) -> None:
    """Valida dimensiones de lienzo; lanza ``ImageTooLargeError`` si no son válidas."""
    if int(width) < 1 or int(height) < 1:
        raise ImageTooLargeError(tr('The image dimensions must be at least 1×1 pixel.'))
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ImageTooLargeError(
            tr("An image of {w}×{h} px exceeds the maximum side length ({max} px).").format(w=width, h=height, max=MAX_DIMENSION)
        )
    if width * height > MAX_PIXELS:
        raise ImageTooLargeError(
            tr("An image of {w}×{h} px ({mp:.1f} MP) exceeds the maximum allowed ({maxmp:.0f} MP).").format(w=width, h=height, mp=width * height / 1e6, maxmp=MAX_PIXELS / 1e6)
        )


def ensure_memory(nbytes: int, what: str = tr('the operation')) -> None:
    """Lanza ``OutOfMemoryAppError`` si ``nbytes`` no caben en la memoria disponible."""
    avail = available_bytes()
    if avail is not None and nbytes > avail * MEMORY_SAFETY_FACTOR:
        raise OutOfMemoryAppError(
            tr("Not enough memory to {what} (about {need:.0f} MB needed, {avail:.0f} MB free). Close other images or reduce the size.").format(what=what, need=nbytes / 2**20, avail=avail / 2**20)
        )


def alloc_pixels(width: int, height: int, fill=(0, 0, 0, 0), what: str = tr('create the layer')) -> np.ndarray:
    """Reserva un búfer RGBA uint8 (alto, ancho, 4) con comprobaciones de límites."""
    check_canvas_size(width, height)
    ensure_memory(width * height * 4 * 2, what)  # ×2: margen para copias de trabajo
    try:
        arr = np.empty((height, width, 4), dtype=np.uint8)
        arr[...] = fill
    except MemoryError as exc:
        raise OutOfMemoryAppError(tr("Not enough memory to {what}.").format(what=what)) from exc
    return arr


def copy_pixels(arr: np.ndarray, what: str = tr('copy the layer')) -> np.ndarray:
    """Copia segura de un búfer (comprueba memoria primero)."""
    ensure_memory(arr.nbytes * 2, what)
    try:
        return arr.copy()
    except MemoryError as exc:
        raise OutOfMemoryAppError(tr("Not enough memory to {what}.").format(what=what)) from exc
