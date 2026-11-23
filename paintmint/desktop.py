"""Registro automático del lanzador en el menú de aplicaciones (categoría Gráficos)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "ui" / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)

ENTRY = """[Desktop Entry]
Type=Application
Name=PaintMint
Comment=Layered image editor
Comment[es]=Editor de imágenes por capas
Exec=bash "{exec}" %F
Icon=paintmint
Terminal=false
StartupWMClass=paintmint
Categories=Graphics;RasterGraphics;2DGraphics;
MimeType=image/png;image/jpeg;image/bmp;image/gif;image/tiff;image/openraster;
"""


def ensure_launcher(data_home: str | None = None) -> bool:
    """Crea o corrige ``paintmint.desktop`` y los iconos. Devuelve True si cambió algo. Nunca lanza."""
    if not sys.platform.startswith("linux") or os.environ.get("PAINTMINT_NO_DESKTOP"):
        return False
    try:
        data = Path(data_home or os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        launcher = ROOT / "paintmint.sh"
        if not launcher.exists():
            return False
        text = ENTRY.format(exec=launcher)
        target = data / "applications" / "paintmint.desktop"
        if target.exists() and target.read_text(encoding="utf-8") == text:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        for size in SIZES:
            src = ASSETS / f"paintmint-{size}.png"
            if src.exists():
                dst = data / "icons" / "hicolor" / f"{size}x{size}" / "apps"
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst / "paintmint.png")
        svg = ASSETS / "paintmint.svg"
        if svg.exists():
            dst = data / "icons" / "hicolor" / "scalable" / "apps"
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(svg, dst / "paintmint.svg")
        target.write_text(text, encoding="utf-8")
        for cmd in (["update-desktop-database", str(target.parent)],
                    ["gtk-update-icon-cache", "-f", "-t", str(data / "icons" / "hicolor")]):
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
        return True
    except OSError:
        return False
