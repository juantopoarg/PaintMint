"""Excepciones propias de la aplicación.

Todas heredan de ``PaintMintError`` y su mensaje (``str(exc)``) está pensado
para mostrarse tal cual al usuario. La interfaz las captura y las presenta en
un diálogo; nunca deben cerrar la aplicación.
"""


class PaintMintError(Exception):
    """Base de los errores recuperables de la aplicación."""


class ImageLoadError(PaintMintError):
    """El archivo no existe, está dañado o no se puede leer."""


class ImageSaveError(PaintMintError):
    """No se pudo escribir el archivo (permisos, disco lleno, etc.)."""


class UnsupportedFormatError(PaintMintError):
    """Extensión o formato de archivo no soportado."""


class ImageTooLargeError(PaintMintError):
    """Las dimensiones solicitadas superan los límites configurados."""


class OutOfMemoryAppError(PaintMintError):
    """No hay memoria suficiente para completar la operación."""


class InvalidOperationError(PaintMintError):
    """Operación no válida en el estado actual (p. ej. borrar la última capa)."""
