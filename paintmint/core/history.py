"""Historial de deshacer/rehacer basado en comandos.

Es ilimitado por defecto: los comandos de píxeles guardan solo el rectángulo
modificado (antes/después) y comprimido con zlib, de modo que el coste de
memoria es proporcional al área editada. ``max_bytes`` permite acotarlo.
"""

from __future__ import annotations

from ..i18n import tr

from typing import Callable, List, Optional


class Command:
    """Operación reversible sobre un ``Document``."""

    label = tr('Operation')
    merge_key = None  # comandos consecutivos con la misma clave se fusionan en uno

    def do(self, doc) -> None:
        raise NotImplementedError

    def undo(self, doc) -> None:
        raise NotImplementedError

    def merge(self, other: "Command") -> bool:
        """Absorbe ``other`` (ya aplicado) si es posible; devuelve True si lo hizo."""
        return False

    @property
    def nbytes(self) -> int:
        return 256


class History:
    def __init__(self, doc, max_bytes: Optional[int] = None):
        self.doc = doc
        self.max_bytes = max_bytes
        self._undo: List[Command] = []
        self._redo: List[Command] = []
        self._clean_pos: Optional[int] = 0   # posición de la pila en el último guardado
        self._barrier = False                # impide fusionar con el comando anterior
        self.listeners: List[Callable[[], None]] = []

    # -- consulta ----------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> Optional[str]:
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> Optional[str]:
        return self._redo[-1].label if self._redo else None

    @property
    def position(self) -> int:
        return len(self._undo)

    @property
    def labels(self) -> List[str]:
        """Etiquetas de toda la línea de tiempo (deshechos y rehacibles, en orden)."""
        return [c.label for c in self._undo] + [c.label for c in reversed(self._redo)]

    @property
    def modified(self) -> bool:
        return self._clean_pos is None or self._clean_pos != len(self._undo)

    @property
    def total_bytes(self) -> int:
        return sum(c.nbytes for c in self._undo) + sum(c.nbytes for c in self._redo)

    # -- mutación ----------------------------------------------------------
    def _notify(self) -> None:
        for fn in list(self.listeners):
            fn()

    def execute(self, cmd: Command) -> None:
        """Aplica ``cmd`` y lo registra."""
        cmd.do(self.doc)
        self.push(cmd)

    def push(self, cmd: Command) -> None:
        """Registra un comando ya aplicado (p. ej. un trazo de pincel)."""
        if self._clean_pos is not None and self._clean_pos > len(self._undo):
            self._clean_pos = None  # el estado guardado estaba en la rama rehacer descartada
        self._redo.clear()
        top = self._undo[-1] if self._undo else None
        if (top is not None and not self._barrier and cmd.merge_key is not None
                and top.merge_key == cmd.merge_key and top.merge(cmd)):
            pass
        else:
            self._undo.append(cmd)
        self._barrier = False
        self._trim()
        self._notify()

    def break_merge(self) -> None:
        """La próxima operación no se fusionará con la anterior (p. ej. al cambiar de foco)."""
        self._barrier = True

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        cmd.undo(self.doc)
        self._redo.append(cmd)
        self._barrier = True
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        cmd.do(self.doc)
        self._undo.append(cmd)
        self._barrier = True
        self._notify()
        return True

    def goto(self, position: int) -> None:
        """Salta a ``position`` comandos aplicados (0 = estado original)."""
        total = len(self._undo) + len(self._redo)
        position = max(0, min(total, position))
        while len(self._undo) > position:
            self.undo()
        while len(self._undo) < position:
            self.redo()

    def mark_clean(self) -> None:
        self._clean_pos = len(self._undo)
        self._notify()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._clean_pos = 0
        self._barrier = False
        self._notify()

    def _trim(self) -> None:
        if self.max_bytes is None:
            return
        total = self.total_bytes
        while total > self.max_bytes and len(self._undo) > 1:
            dropped = self._undo.pop(0)
            total -= dropped.nbytes
            if self._clean_pos is not None:
                self._clean_pos -= 1
                if self._clean_pos < 0:
                    self._clean_pos = None
