"""Configuración persistente del usuario (JSON en ~/.config/paintmint/config.json).

Se usa para el idioma y las opciones de actualización; funciona sin Qt para que el
idioma pueda fijarse antes de importar la interfaz.
"""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULTS = {
    "language": "en",            # "en" | "es"
    "check_updates": True,       # comprobar actualizaciones al iniciar
    "last_update_check": 0.0,    # marca de tiempo UNIX de la última comprobación
    "last_canvas": [800, 600],   # último tamaño de lienzo usado (ancho, alto)
    "custom_colors": [],         # colores añadidos a la paleta por el usuario: [[r,g,b,a], ...]
}


def config_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "paintmint", "config.json")


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass  # sin archivo o dañado: se usan los valores por defecto
    lc = data.get("last_canvas")
    if not (isinstance(lc, (list, tuple)) and len(lc) == 2 and all(isinstance(v, int) and not isinstance(v, bool)
                                                                       and 1 <= v <= 32768 for v in lc)):
        data["last_canvas"] = list(DEFAULTS["last_canvas"])
    return data


def save(data: dict) -> bool:
    """Guarda la configuración; devuelve False si no se pudo escribir (no es un error grave)."""
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({k: data.get(k, v) for k, v in DEFAULTS.items()}, fh, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def get(key: str) -> Any:
    return load()[key]


def set_value(key: str, value: Any) -> bool:
    data = load()
    data[key] = value
    return save(data)
