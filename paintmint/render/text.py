"""Renderizado de texto con Pillow (independiente de Qt).

La búsqueda de fuentes usa ``fc-match`` si está disponible (Linux Mint lo
incluye con fontconfig) y recurre a Pillow por defecto si no se encuentra.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..core.layer import TextSpec


@functools.lru_cache(maxsize=256)
def find_font_path(family: str, bold: bool, italic: bool) -> Optional[str]:
    """Ruta del archivo de fuente que fontconfig asocia a la familia pedida."""
    if shutil.which("fc-match") is None:
        return None
    style = []
    if bold:
        style.append("bold")
    if italic:
        style.append("italic")
    pattern = family + (":" + ":".join(style) if style else "")
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", pattern],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


@functools.lru_cache(maxsize=128)
def load_font(family: str, size: int, bold: bool, italic: bool):
    path = find_font_path(family, bold, italic)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, ValueError):
            pass  # variable/otf corrupto: se cae a la fuente por defecto
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def render_text_mask(spec: TextSpec) -> np.ndarray:
    """Máscara de cobertura (alto, ancho) uint8 del texto, recortada al contenido."""
    font = load_font(spec.family, max(1, int(spec.size)), spec.bold, spec.italic)
    text = spec.text if spec.text else ""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = probe.multiline_textbbox((0, 0), text, font=font, align=spec.align)
    w, h = max(1, int(r - l) + 2), max(1, int(b - t) + 2)
    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).multiline_text((-l + 1, -t + 1), text, font=font, fill=255, align=spec.align)
    return np.asarray(img, dtype=np.uint8)


def render_text_layer(spec: TextSpec, width: int, height: int) -> np.ndarray:
    """Píxeles RGBA (alto, ancho, 4) del lienzo con el texto colocado en (x, y)."""
    out = np.zeros((height, width, 4), dtype=np.uint8)
    if not spec.text:
        return out
    mask = render_text_mask(spec)
    mh, mw = mask.shape
    x0, y0 = int(round(spec.x)), int(round(spec.y))
    # recorte contra los bordes del lienzo
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    cw = min(mw - sx0, width - dx0)
    ch = min(mh - sy0, height - dy0)
    if cw <= 0 or ch <= 0:
        return out
    cov = mask[sy0:sy0 + ch, sx0:sx0 + cw].astype(np.uint16)
    r, g, b, a = spec.color
    region = out[dy0:dy0 + ch, dx0:dx0 + cw]
    region[..., 0], region[..., 1], region[..., 2] = r, g, b
    region[..., 3] = (cov * a // 255).astype(np.uint8)
    return out


def text_bounds(spec: TextSpec):
    """Rectángulo (x0, y0, x1, y1) que ocupa el texto, para detectar clics."""
    mh, mw = render_text_mask(spec).shape
    x0, y0 = int(round(spec.x)), int(round(spec.y))
    return x0, y0, x0 + mw, y0 + mh
