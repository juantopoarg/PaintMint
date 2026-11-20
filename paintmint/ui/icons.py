"""Iconos de herramientas dibujados con QPainter (no dependen de temas ni de archivos externos)."""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import QApplication


def tool_icon(key: str, size: int = 32, ink: QColor = None) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 32.0
    p.scale(s, s)
    if ink is None:  # color del texto del tema actual, para que se vea en temas claros y oscuros
        ink = QApplication.palette().color(QPalette.ButtonText)
    accent = QColor(80, 190, 140)
    pen = QPen(ink, 2)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    dash = QPen(ink, 2, Qt.DashLine)

    if key == "select_rect":
        p.setPen(dash); p.drawRect(QRectF(6, 8, 20, 16))
    elif key == "select_ellipse":
        p.setPen(dash); p.drawEllipse(QRectF(5, 7, 22, 18))
    elif key == "select_lasso":
        p.setPen(dash); p.drawEllipse(QRectF(6, 6, 20, 14)); p.setPen(pen); p.drawLine(16, 20, 12, 27)
    elif key == "select_wand":
        p.drawLine(8, 26, 20, 14); p.setPen(QPen(accent, 2))
        for dx, dy in ((22, 10), (26, 14), (18, 8), (24, 6)):
            p.drawPoint(QPointF(dx, dy))
        p.drawLine(22, 6, 22, 12); p.drawLine(19, 9, 25, 9)
    elif key == "move":
        p.drawLine(16, 5, 16, 27); p.drawLine(5, 16, 27, 16)
        for a, b, c, d in ((16, 5, 12, 9), (16, 5, 20, 9), (16, 27, 12, 23), (16, 27, 20, 23),
                           (5, 16, 9, 12), (5, 16, 9, 20), (27, 16, 23, 12), (27, 16, 23, 20)):
            p.drawLine(a, b, c, d)
    elif key == "brush":
        p.setPen(QPen(ink, 3, Qt.SolidLine, Qt.RoundCap)); p.drawLine(24, 6, 14, 18)
        p.setPen(Qt.NoPen); p.setBrush(accent); p.drawEllipse(QRectF(6, 16, 10, 10))
    elif key == "pencil":
        p.drawLine(24, 6, 8, 22); p.drawLine(8, 22, 7, 26); p.drawLine(7, 26, 11, 25)
        p.setPen(QPen(accent, 2)); p.drawLine(20, 10, 22, 12)
    elif key == "eraser":
        p.setBrush(accent); p.drawPolygon(QPolygonF([QPointF(6, 20), QPointF(16, 8), QPointF(26, 14), QPointF(16, 26)]))
        p.setPen(pen); p.drawLine(6, 27, 26, 27)
    elif key == "fill":
        p.drawPolygon(QPolygonF([QPointF(7, 16), QPointF(15, 6), QPointF(23, 14), QPointF(14, 24)]))
        p.setPen(Qt.NoPen); p.setBrush(accent); p.drawEllipse(QRectF(22, 19, 6, 8))
    elif key == "gradient":
        for i in range(8):
            c = QColor(accent); c.setAlpha(int(255 * (i + 1) / 8))
            p.fillRect(QRectF(5 + i * 2.75, 8, 2.75, 16), c)
        p.drawRect(QRectF(5, 8, 22, 16))
    elif key == "shape":
        p.drawRect(QRectF(5, 12, 14, 14)); p.setPen(QPen(accent, 2)); p.drawEllipse(QRectF(13, 5, 14, 14))
    elif key == "line":
        p.setPen(QPen(ink, 3, Qt.SolidLine, Qt.RoundCap)); p.drawLine(7, 25, 25, 7)
    elif key == "curve":
        from PyQt5.QtGui import QPainterPath
        path = QPainterPath(QPointF(6, 25)); path.cubicTo(8, 4, 22, 28, 26, 7)
        p.setPen(QPen(ink, 2.5, Qt.SolidLine, Qt.RoundCap)); p.drawPath(path)
        p.setPen(QPen(accent, 1)); p.setBrush(accent); p.drawRect(QRectF(4, 23, 4, 4)); p.drawRect(QRectF(24, 5, 4, 4))
    elif key == "freeform":
        from PyQt5.QtGui import QPainterPath
        path = QPainterPath(QPointF(6, 22)); path.cubicTo(2, 8, 14, 4, 18, 12); path.cubicTo(22, 18, 30, 8, 27, 22)
        path.closeSubpath(); p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 120)); p.drawPath(path)
    elif key == "polygon":
        p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 120))
        p.drawPolygon(QPolygonF([QPointF(16, 5), QPointF(27, 13), QPointF(23, 26), QPointF(9, 26), QPointF(5, 13)]))
    elif key == "clone":
        p.drawRoundedRect(QRectF(8, 20, 16, 6), 2, 2); p.drawRect(QRectF(13, 12, 6, 8)); p.setBrush(accent)
        p.drawEllipse(QRectF(11, 4, 10, 9))
    elif key == "recolor":
        p.setBrush(accent); p.drawEllipse(QRectF(5, 5, 12, 12)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(15, 15, 12, 12)); p.drawLine(14, 18, 18, 14)
    elif key == "rectangle":
        p.drawRect(QRectF(6, 9, 20, 14))
    elif key == "rounded_rectangle":
        p.drawRoundedRect(QRectF(6, 9, 20, 14), 6, 6)
    elif key == "ellipse":
        p.drawEllipse(QRectF(5, 8, 22, 16))
    elif key == "move_selection":
        p.setPen(dash); p.drawRect(QRectF(5, 5, 14, 14)); p.setPen(pen)
        p.drawLine(14, 14, 26, 26); p.drawLine(26, 26, 20, 26); p.drawLine(26, 26, 26, 20)
    elif key == "text":
        f = p.font(); f.setBold(True); f.setPixelSize(24); p.setFont(f)
        p.drawText(QRectF(0, 0, 32, 32), Qt.AlignCenter, "T")
    elif key == "picker":
        p.drawLine(23, 9, 10, 22); p.setPen(QPen(accent, 3)); p.drawLine(10, 22, 7, 26)
        p.setPen(pen); p.drawEllipse(QRectF(20, 4, 8, 8))
    elif key == "zoom":
        p.drawEllipse(QRectF(5, 5, 16, 16)); p.drawLine(18, 18, 27, 27)
        p.drawLine(9, 13, 17, 13); p.drawLine(13, 9, 13, 17)
    elif key == "pan":
        p.drawRoundedRect(QRectF(9, 13, 14, 12), 4, 4)
        for x in (11, 14.5, 18, 21):
            p.drawLine(QPointF(x, 13), QPointF(x, 6))
    p.end()
    return QIcon(pm)


# Cursores por herramienta: (punto activo, tipo). «None» usa el cursor estándar de Qt.
_STANDARD_CURSORS = {
    "text": Qt.IBeamCursor,
    "move": Qt.SizeAllCursor,
    "move_selection": Qt.SizeAllCursor,
    "pan": Qt.OpenHandCursor,
    # los pinceles dibujan su propio círculo de tamaño sobre el lienzo; basta una cruz fina
    "brush": Qt.CrossCursor,
    "eraser": Qt.CrossCursor,
    "pencil": Qt.CrossCursor,
}


def tool_cursor(key: str):
    """Cursor para ``key``: estándar de Qt o una cruz con la insignia de la herramienta."""
    from PyQt5.QtGui import QCursor

    std = _STANDARD_CURSORS.get(key)
    if std is not None:
        return QCursor(std)
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # cruz con el punto activo en (9, 9); doble trazo (blanco+negro) para verse sobre cualquier fondo
    for color, width in ((QColor(255, 255, 255), 3), (QColor(0, 0, 0), 1)):
        p.setPen(QPen(color, width))
        p.drawLine(1, 9, 17, 9)
        p.drawLine(9, 1, 9, 17)
    # insignia de la herramienta (icono oscuro con halo blanco) abajo a la derecha
    badge_size = 20
    dark = tool_icon(key, badge_size, QColor(0, 0, 0)).pixmap(badge_size, badge_size)
    halo = tool_icon(key, badge_size, QColor(255, 255, 255)).pixmap(badge_size, badge_size)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        p.drawPixmap(12 + dx, 12 + dy, halo)
    p.drawPixmap(12, 12, dark)
    p.end()
    return QCursor(pm, 9, 9)
