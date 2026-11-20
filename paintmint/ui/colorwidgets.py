"""Widgets de color al estilo de la ventana «Colores» de Paint.NET.

Contiene: ``SliderSpin`` (deslizador + cuadro numérico), ``GradientSlider`` (barra con degradado),
``ColorWheel`` (rueda tono/saturación), ``SwatchPair`` (primario/secundario) y ``PaletteGrid``
(paleta grande con grises, tonos, tintes y filas semitransparentes).
"""

from __future__ import annotations

import colorsys
from typing import List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QConicalGradient, QImage, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QHBoxLayout, QSlider, QSpinBox, QWidget

from ..i18n import tr

RGBA = Tuple[int, int, int, int]


# -- utilidades ----------------------------------------------------------------
def rgb_to_hsv(r: int, g: int, b: int) -> Tuple[int, int, int]:
    """RGB 0-255 -> (H 0-359, S 0-100, V 0-100)."""
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return int(round(h * 360)) % 360, int(round(s * 100)), int(round(v * 100))


def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    """(H 0-360, S 0-100, V 0-100) -> RGB 0-255."""
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, max(0, min(100, s)) / 100.0, max(0, min(100, v)) / 100.0)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def checker_brush(cell: int = 6) -> QBrush:
    img = QImage(cell * 2, cell * 2, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.fillRect(0, 0, cell, cell, QColor(200, 200, 200))
    p.fillRect(cell, cell, cell, cell, QColor(200, 200, 200))
    p.end()
    return QBrush(img)


_CHECKER = None


def paint_color(p: QPainter, rect, rgba: RGBA) -> None:
    """Pinta ``rgba`` sobre un tablero de ajedrez, para ver la transparencia."""
    global _CHECKER
    if _CHECKER is None:
        _CHECKER = checker_brush()
    p.fillRect(rect, _CHECKER)
    p.fillRect(rect, QColor(*rgba))


# -- deslizador + cuadro numérico ------------------------------------------------------
class SliderSpin(QWidget):
    """Deslizador con un cuadro numérico sincronizado (como la opacidad en Paint.NET).

    Expone la misma interfaz mínima que ``QSpinBox`` (``value``/``setValue``/``valueChanged``).
    """

    valueChanged = pyqtSignal(int)

    def __init__(self, minimum=0, maximum=100, suffix="", slider_width=90, parent=None):
        super().__init__(parent)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setFixedWidth(slider_width)
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        if suffix:
            self.spin.setSuffix(suffix)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.slider)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v):
        if self.spin.value() != v:
            self.spin.setValue(v)       # emite valueChanged vía _from_spin

    def _from_spin(self, v):
        if self.slider.value() != v:
            self.slider.setValue(v)
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, v: int) -> None:
        self.spin.setValue(int(v))

    def setSuffix(self, s: str) -> None:
        self.spin.setSuffix(s)

    def setRange(self, lo: int, hi: int) -> None:
        self.slider.setRange(lo, hi)
        self.spin.setRange(lo, hi)


# -- barra con degradado ---------------------------------------------------------------------
class GradientSlider(QWidget):
    """Barra horizontal con degradado y control deslizante (R, G, B, H, S, V y alfa)."""

    valueChanged = pyqtSignal(int)

    def __init__(self, maximum: int, parent=None):
        super().__init__(parent)
        self._max = maximum
        self._value = 0
        self._stops: List[Tuple[float, QColor]] = [(0.0, QColor(0, 0, 0)), (1.0, QColor(255, 255, 255))]
        self.setFixedHeight(20)
        self.setMinimumWidth(80)
        self.setCursor(Qt.PointingHandCursor)

    def maximum(self) -> int:
        return self._max

    def value(self) -> int:
        return self._value

    def setValue(self, v: int) -> None:
        v = max(0, min(self._max, int(v)))
        if v != self._value:
            self._value = v
            self.update()

    def set_stops(self, stops: List[Tuple[float, QColor]]) -> None:
        self._stops = stops
        self.update()

    def _bar(self) -> QRectF:
        return QRectF(6, 4, self.width() - 12, self.height() - 8)

    def paintEvent(self, _e):
        p = QPainter(self)
        bar = self._bar()
        p.fillRect(bar, checker_brush(4))
        g = QLinearGradient(bar.left(), 0, bar.right(), 0)
        for pos, col in self._stops:
            g.setColorAt(pos, col)
        p.fillRect(bar, QBrush(g))
        p.setPen(QPen(QColor(60, 60, 60)))
        p.drawRect(bar)
        x = bar.left() + bar.width() * (self._value / float(self._max))
        tri = [QPointF(x - 4, 0), QPointF(x + 4, 0), QPointF(x, 5)]
        tri2 = [QPointF(x - 4, self.height()), QPointF(x + 4, self.height()), QPointF(x, self.height() - 5)]
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(30, 30, 30))
        p.setPen(QPen(QColor(240, 240, 240)))
        p.drawPolygon(*tri)
        p.drawPolygon(*tri2)

    def _set_from_x(self, x: float) -> None:
        bar = self._bar()
        frac = (x - bar.left()) / max(1.0, bar.width())
        v = int(round(max(0.0, min(1.0, frac)) * self._max))
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._set_from_x(e.x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_from_x(e.x())

    def wheelEvent(self, e):
        step = 1 if e.angleDelta().y() > 0 else -1
        v = max(0, min(self._max, self._value + step))
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)


# -- rueda de color ------------------------------------------------------------------------------
class ColorWheel(QWidget):
    """Rueda de tono (ángulo) y saturación (radio), con valor 100 %."""

    picked = pyqtSignal(int, int, str)   # (tono 0-359, saturación 0-100, botón: "left" | "right")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h, self._s, self._v = 0, 0, 100
        self._cache: Optional[QImage] = None
        self._cache_key = None
        self.setMinimumSize(120, 120)
        self.setCursor(Qt.CrossCursor)

    def sizeHint(self):
        return QSize(150, 150)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    def set_hsv(self, h: int, s: int, v: int) -> None:
        if (h, s, v) != (self._h, self._s, self._v):
            self._h, self._s, self._v = h, s, v
            self.update()

    def _geometry(self):
        side = min(self.width(), self.height()) - 8
        cx, cy = self.width() / 2.0, self.height() / 2.0
        return cx, cy, side / 2.0

    def _wheel_image(self, d: int) -> QImage:
        key = d
        if self._cache is None or self._cache_key != key:
            img = QImage(d, d, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            cg = QConicalGradient(d / 2.0, d / 2.0, 0)
            for i in range(0, 361, 30):
                r, g, b = hsv_to_rgb(i, 100, 100)
                cg.setColorAt(min(1.0, i / 360.0), QColor(r, g, b))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(cg))
            p.drawEllipse(QRectF(0, 0, d, d))
            rg = QRadialGradient(d / 2.0, d / 2.0, d / 2.0)
            gray = 255
            rg.setColorAt(0.0, QColor(gray, gray, gray, 255))
            rg.setColorAt(1.0, QColor(gray, gray, gray, 0))
            p.setBrush(QBrush(rg))
            p.drawEllipse(QRectF(0, 0, d, d))
            p.end()
            self._cache, self._cache_key = img, key
        return self._cache

    def paintEvent(self, _e):
        cx, cy, r = self._geometry()
        d = max(8, int(2 * r))
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(int(cx - d / 2.0), int(cy - d / 2.0), self._wheel_image(d))
        p.setPen(QPen(QColor(70, 70, 70)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        import math
        ang = math.radians(self._h)
        rad = r * self._s / 100.0
        mx, my = cx + rad * math.cos(ang), cy - rad * math.sin(ang)
        p.setPen(QPen(QColor(0, 0, 0), 2))
        p.drawEllipse(QPointF(mx, my), 5, 5)
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawEllipse(QPointF(mx, my), 6.5, 6.5)

    def _pick(self, pos, button: str) -> None:
        import math
        cx, cy, r = self._geometry()
        dx, dy = pos.x() - cx, cy - pos.y()
        dist = min(math.hypot(dx, dy), r)
        h = int(round(math.degrees(math.atan2(dy, dx)))) % 360
        s = int(round(100.0 * dist / max(1.0, r)))
        self._h, self._s = h, s
        self.update()
        self.picked.emit(h, s, button)

    def mousePressEvent(self, e):
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            self._pick(e.pos(), "left" if e.button() == Qt.LeftButton else "right")

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._pick(e.pos(), "left")
        elif e.buttons() & Qt.RightButton:
            self._pick(e.pos(), "right")

    def contextMenuEvent(self, e):      # el clic derecho elige el secundario, no abre menús
        e.accept()


# -- par primario / secundario --------------------------------------------------------------------
class SwatchPair(QWidget):
    """Dos cuadros superpuestos (primario arriba-izquierda, secundario abajo-derecha)."""

    selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.primary: RGBA = (0, 0, 0, 255)
        self.secondary: RGBA = (255, 255, 255, 255)
        self.target = "primary"
        self.setFixedSize(54, 54)

    def set_colors(self, primary: RGBA, secondary: RGBA, target: str) -> None:
        self.primary, self.secondary, self.target = tuple(primary), tuple(secondary), target
        self.update()

    def _rects(self):
        return QRect(2, 2, 32, 32), QRect(20, 20, 32, 32)

    def paintEvent(self, _e):
        p = QPainter(self)
        r1, r2 = self._rects()
        paint_color(p, r2, self.secondary)
        p.setPen(QPen(QColor(30, 30, 30), 2 if self.target == "secondary" else 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r2)
        paint_color(p, r1, self.primary)
        p.setPen(QPen(QColor(30, 30, 30), 2 if self.target == "primary" else 1))
        p.drawRect(r1)

    def mousePressEvent(self, e):
        r1, _ = self._rects()
        self.selected.emit("primary" if r1.contains(e.pos()) else "secondary")


# -- paleta ----------------------------------------------------------------------------------------
def build_palette() -> List[List[RGBA]]:
    """Paleta de 14 columnas × 9 filas: 2 columnas de grises, 12 de tonos (tintes → sombras)
    y dos filas semitransparentes al final."""
    cols = 14
    grays_a = [255, 224, 192, 160, 128, 96, 64]
    grays_b = [240, 208, 176, 144, 112, 80, 0]
    sv = [(0.30, 1.0), (0.55, 1.0), (0.80, 1.0), (1.0, 1.0), (1.0, 0.75), (1.0, 0.50), (1.0, 0.28)]
    rows: List[List[RGBA]] = []
    for i in range(7):
        row: List[RGBA] = [(grays_a[i],) * 3 + (255,), (grays_b[i],) * 3 + (255,)]
        for k in range(12):
            r, g, b = hsv_to_rgb(k * 30, sv[i][0] * 100, sv[i][1] * 100)
            row.append((r, g, b, 255))
        rows.append(row)
    for alpha in (160, 80):
        row = [(0, 0, 0, alpha), (255, 255, 255, alpha)]
        for k in range(12):
            r, g, b = hsv_to_rgb(k * 30, 100, 100)
            row.append((r, g, b, alpha))
        rows.append(row)
    assert all(len(r) == cols for r in rows)
    return rows


class PaletteGrid(QWidget):
    """Cuadrícula de colores. Clic izquierdo: color de destino; derecho: el otro color."""

    picked = pyqtSignal(str, tuple)   # ("left" | "right", rgba)
    CELL = 17

    def __init__(self, custom: Optional[List[RGBA]] = None, parent=None):
        super().__init__(parent)
        self.rows = build_palette()
        self.custom_slots = 14
        self.custom: List[Optional[RGBA]] = [None] * self.custom_slots
        for i, c in enumerate((custom or [])[: self.custom_slots]):
            self.custom[i] = tuple(c)
        self.setMouseTracking(True)
        self.setFixedSize(self.CELL * 14 + 1, self.CELL * (len(self.rows) + 1) + 7)

    def sizeHint(self):
        return self.size()

    def add_custom(self, rgba: RGBA) -> None:
        rgba = tuple(rgba)
        if rgba in self.custom:
            return
        try:
            idx = self.custom.index(None)
        except ValueError:
            self.custom = self.custom[1:] + [None]
            idx = self.custom_slots - 1
        self.custom[idx] = rgba
        self.update()

    def custom_list(self) -> List[List[int]]:
        return [list(c) for c in self.custom if c is not None]

    def _cell_at(self, pos) -> Optional[RGBA]:
        c = pos.x() // self.CELL
        if not (0 <= c < 14):
            return None
        y = pos.y()
        if y < self.CELL * len(self.rows):
            r = y // self.CELL
            return self.rows[r][c]
        y -= self.CELL * len(self.rows) + 6
        if 0 <= y < self.CELL:
            return self.custom[c]
        return None

    def paintEvent(self, _e):
        p = QPainter(self)
        cs = self.CELL
        for r, row in enumerate(self.rows):
            for c, rgba in enumerate(row):
                rect = QRect(c * cs, r * cs, cs, cs)
                paint_color(p, rect.adjusted(0, 0, -1, -1), rgba)
        y0 = cs * len(self.rows) + 6
        p.setPen(QPen(QColor(128, 128, 128)))
        p.drawLine(0, y0 - 3, cs * 14, y0 - 3)
        for c, rgba in enumerate(self.custom):
            rect = QRect(c * cs, y0, cs - 1, cs - 1)
            if rgba is None:
                p.setPen(QPen(QColor(150, 150, 150)))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect)
            else:
                paint_color(p, rect, rgba)

    def mouseMoveEvent(self, e):
        rgba = self._cell_at(e.pos())
        if rgba is None:
            self.setToolTip("")
        else:
            self.setToolTip("#%02X%02X%02X · α %d" % (rgba[0], rgba[1], rgba[2], rgba[3]))

    def mousePressEvent(self, e):
        rgba = self._cell_at(e.pos())
        if rgba is None:
            return
        if e.button() == Qt.LeftButton:
            self.picked.emit("left", tuple(rgba))
        elif e.button() == Qt.RightButton:
            self.picked.emit("right", tuple(rgba))
