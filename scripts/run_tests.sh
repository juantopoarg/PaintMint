#!/usr/bin/env bash
# Ejecuta la suite completa sin necesidad de pantalla (Qt en modo offscreen).
cd "$(dirname "$0")/.." || exit 1
export QT_QPA_PLATFORM=offscreen
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
exec "$PY" -m pytest "$@"
