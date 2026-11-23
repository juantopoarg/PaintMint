#!/usr/bin/env bash
# Crea el lanzador en el menú de aplicaciones e instala el icono (brocha con hoja de menta).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS="$DATA/applications"
ASSETS="$ROOT/paintmint/ui/assets"
mkdir -p "$APPS"

for size in 16 24 32 48 64 128 256; do
    dir="$DATA/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$dir"
    cp "$ASSETS/paintmint-$size.png" "$dir/paintmint.png"
done
mkdir -p "$DATA/icons/hicolor/scalable/apps"
cp "$ASSETS/paintmint.svg" "$DATA/icons/hicolor/scalable/apps/paintmint.svg"

cat > "$APPS/paintmint.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=PaintMint
Comment=Layered image editor
Comment[es]=Editor de imágenes por capas
Exec=bash "$ROOT/paintmint.sh" %F
Icon=paintmint
Terminal=false
StartupWMClass=paintmint
Categories=Graphics;RasterGraphics;2DGraphics;
MimeType=image/png;image/jpeg;image/bmp;image/gif;image/tiff;image/openraster;
DESK
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$DATA/icons/hicolor" 2>/dev/null || true
echo "Installed: $APPS/paintmint.desktop (icon: paintmint)"
