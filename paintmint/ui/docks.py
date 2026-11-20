"""Paneles acoplables al estilo de Paint.NET: barra de título con colapsar, flotar y cerrar."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDockWidget, QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton, QWidget

from ..i18n import tr

QWIDGETSIZE_MAX = 16777215


class DockTitleBar(QWidget):
    """Título + botones: ▾/▸ colapsar dentro de la columna, ⧉ flotar/acoplar, ✕ cerrar."""

    def __init__(self, dock: QDockWidget):
        super().__init__(dock)
        self.dock = dock
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 2, 2)
        lay.setSpacing(2)
        self.collapse_btn = self._button("▾", tr('Collapse / expand'))
        self.label = QLabel(dock.windowTitle())
        self.label.setStyleSheet("font-weight: bold;")
        self.float_btn = self._button("⧉", tr('Float / dock'))
        self.close_btn = self._button("✕", tr('Close'))
        lay.addWidget(self.collapse_btn)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.float_btn)
        lay.addWidget(self.close_btn)
        self.collapse_btn.clicked.connect(lambda: set_collapsed(dock, not is_collapsed(dock)))
        self.float_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        self.close_btn.clicked.connect(dock.close)
        dock.windowTitleChanged.connect(self.label.setText)

    @staticmethod
    def _button(text, tip):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def mouseDoubleClickEvent(self, e):   # doble clic en el título: colapsar/expandir
        if e.button() == Qt.LeftButton:
            set_collapsed(self.dock, not is_collapsed(self.dock))


def wrap_scroll(widget: QWidget) -> QScrollArea:
    """Envuelve un panel en un área con desplazamiento para que no imponga su altura mínima a la ventana."""
    sa = QScrollArea()
    sa.setWidget(widget)
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setMinimumHeight(60)
    return sa


def setup_dock(dock: QDockWidget) -> DockTitleBar:
    dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
    bar = DockTitleBar(dock)
    dock.setTitleBarWidget(bar)
    dock.setProperty("collapsed", False)
    return bar


def is_collapsed(dock: QDockWidget) -> bool:
    return bool(dock.property("collapsed"))


def set_collapsed(dock: QDockWidget, collapsed: bool) -> None:
    """Oculta el contenido y deja solo la barra de título; la columna reparte el espacio sobrante."""
    bar = dock.titleBarWidget()
    inner = dock.widget()
    dock.setProperty("collapsed", bool(collapsed))
    if inner is not None:
        inner.setVisible(not collapsed)
    if isinstance(bar, DockTitleBar):
        bar.collapse_btn.setText("▸" if collapsed else "▾")
    if collapsed:
        dock.setMaximumHeight(bar.sizeHint().height() + 2)
    else:
        dock.setMaximumHeight(QWIDGETSIZE_MAX)
    dock.updateGeometry()
