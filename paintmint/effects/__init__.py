"""Efectos y ajustes de imagen. ``REGISTRY`` mapea clave -> instancia de ``Effect``."""

from .base import Effect, Param  # noqa: F401
from .adjustments import ADJUSTMENTS as _ADJ  # noqa: F401
from .adjustments2 import ADJUSTMENTS2
from .filters import FILTERS  # noqa: F401
from .fx_blurs import BLUR_FX, OTHER_FX
from .fx_distort import ARTISTIC_FX, DISTORT_FX
from .fx_render import RENDER_FX, STYLIZE_FX

ADJUSTMENTS = [*_ADJ, *ADJUSTMENTS2]
EFFECTS = [*FILTERS, *BLUR_FX, *OTHER_FX, *DISTORT_FX, *ARTISTIC_FX, *RENDER_FX, *STYLIZE_FX]
REGISTRY = {e.key: e for e in (*ADJUSTMENTS, *EFFECTS)}

# submenús de Efectos en el orden de Paint.NET
GROUPS = ("artistic", "blurs", "color", "distort", "noise", "object", "photo", "render", "stylize")
