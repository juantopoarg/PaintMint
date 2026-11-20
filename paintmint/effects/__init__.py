"""Efectos y ajustes de imagen. ``REGISTRY`` mapea clave -> instancia de ``Effect``."""

from .base import Effect, Param  # noqa: F401
from .adjustments import ADJUSTMENTS  # noqa: F401
from .filters import FILTERS  # noqa: F401

REGISTRY = {e.key: e for e in (*ADJUSTMENTS, *FILTERS)}
