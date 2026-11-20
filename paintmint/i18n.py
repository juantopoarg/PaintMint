"""Internacionalización mínima: inglés (predeterminado) y español.

Los textos del código fuente están en inglés y ``tr()`` los traduce con el catálogo
``translations_es``. El idioma se resuelve al importar el módulo, en este orden:

1. variable de entorno ``PAINTMINT_LANG`` (``en`` / ``es``),
2. ``language`` en ``~/.config/paintmint/config.json``,
3. inglés.

Cambiar de idioma desde la aplicación guarda la preferencia y se aplica al reiniciar
(los textos se evalúan al construir la interfaz).
"""

from __future__ import annotations

import os

from . import config

LANGUAGES = {"en": "English", "es": "Español"}
DEFAULT_LANGUAGE = "en"

_lang = DEFAULT_LANGUAGE
_catalog: dict = {}


def _load_catalog(code: str) -> dict:
    if code == "es":
        from .translations_es import ES
        return ES
    return {}


def set_language(code: str) -> None:
    """Fija el idioma activo en este proceso (no guarda la preferencia)."""
    global _lang, _catalog
    if code not in LANGUAGES:
        code = DEFAULT_LANGUAGE
    _lang, _catalog = code, _load_catalog(code)


def current_language() -> str:
    return _lang


def tr(text: str) -> str:
    """Traduce ``text`` (en inglés) al idioma activo; si falta la entrada devuelve el original."""
    return _catalog.get(text, text)


def _initial_language() -> str:
    env = os.environ.get("PAINTMINT_LANG", "").strip().lower()[:2]
    if env in LANGUAGES:
        return env
    try:
        stored = str(config.get("language"))
    except Exception:  # noqa: BLE001 - nunca impedir el arranque por la configuración
        stored = DEFAULT_LANGUAGE
    return stored if stored in LANGUAGES else DEFAULT_LANGUAGE


set_language(_initial_language())
