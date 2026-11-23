#!/usr/bin/env bash
# Instala las dependencias de PaintMint en Linux Mint / Ubuntu / Debian.
#   ./scripts/install_deps.sh          -> paquetes del sistema (apt), recomendado
#   ./scripts/install_deps.sh --venv   -> entorno virtual .venv con pip (usa los PyQt5 del sistema)
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v apt-get >/dev/null 2>&1; then
    echo "This script requires apt (Linux Mint, Ubuntu or Debian)." >&2
    exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

echo ">> Installing system packages…"
$SUDO apt-get update
$SUDO apt-get install -y \
    python3 python3-pip python3-venv \
    python3-pyqt5 python3-numpy python3-pil python3-scipy \
    python3-pytest fontconfig fonts-dejavu-core

if [ "${1:-}" = "--venv" ]; then
    echo ">> Creating the .venv virtual environment (with access to the system PyQt5)…"
    python3 -m venv --system-site-packages .venv
    # shellcheck disable=SC1091
    . .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    echo ">> Activate it with:   source .venv/bin/activate"
fi

echo ">> Checking imports…"
python3 - <<'PY'
import sys
missing = []
for mod in ("PyQt5.QtWidgets", "numpy", "PIL", "scipy"):
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)
if missing:
    sys.exit("Missing modules: " + ", ".join(missing))
print("All good.")
PY

echo ">> Adding PaintMint to the applications menu (Graphics)…"
"$(dirname "$0")/install_desktop_entry.sh" || true

echo ">> Done. Run:   ./paintmint.sh   (o: python3 -m paintmint)"
