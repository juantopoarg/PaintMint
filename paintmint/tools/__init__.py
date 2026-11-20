"""Herramientas de edición (independientes de Qt). ``create_tools()`` devuelve una instancia por herramienta."""

from .base import Tool, ToolContext, ToolOptions  # noqa: F401
from .paint import (BrushTool, ColorPickerTool, EllipseTool, EraserTool, FillTool, GradientTool,  # noqa: F401
                    LineTool, PencilTool, RectangleTool, RoundedRectangleTool, ShapeTool)
from .path import CurveTool, FreeformShapeTool, PolygonTool  # noqa: F401
from .retouch import CloneStampTool, RecolorTool  # noqa: F401
from .select import (EllipseSelectTool, LassoSelectTool, MoveSelectedTool, MoveSelectionTool,  # noqa: F401
                     RectSelectTool, WandSelectTool)
from .text import TextTool  # noqa: F401

TOOL_CLASSES = [
    RectSelectTool, EllipseSelectTool, LassoSelectTool, WandSelectTool, MoveSelectedTool, MoveSelectionTool,
    BrushTool, PencilTool, EraserTool, FillTool, GradientTool, ShapeTool, LineTool, RectangleTool,
    RoundedRectangleTool, EllipseTool, TextTool, ColorPickerTool, CloneStampTool, RecolorTool, CurveTool,
    FreeformShapeTool, PolygonTool,
]


def create_tools():
    """Diccionario ``clave -> instancia`` en el orden de la barra de herramientas."""
    return {cls.key: cls() for cls in TOOL_CLASSES}
