#!/usr/bin/env bash
# Lanzador: ./paintmint.sh [imagen ...]
cd "$(dirname "$(readlink -f "$0")")" || exit 1
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m paintmint "$@"
fi
exec python3 -m paintmint "$@"
