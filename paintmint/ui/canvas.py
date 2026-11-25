"""Lienzo con zoom, desplazamiento, cuadrícula de transparencia, hormigas de selección y sobreposiciones."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QAbstractScrollArea, QApplication

from ..core.errors import PaintMintError
from ..core.session import EditSession
from ..tools import ToolContext
from ..tools.select import RESIZE_TOOLS, cursor_name, handle_points, hit_handle, resized_box
from .icons import tool_cursor
from .qtutil import qimage_from_rgba

MIN_ZOOM, MAX_ZOOM = 0.02, 64.0
MARGIN = 24
HANDLE_PX = 7          # radio de captura de los tiradores de la selección (píxeles de pantalla)
PAINTING_TOOLS = ("brush", "pencil", "eraser", "clone", "recolor")


class CanvasView(QAbstractScrollArea):
    cursor_moved = pyqtSignal(float, float)
    zoom_changed = pyqtSignal(float)
    message = pyqtSignal(str)           # avisos no modales (barra de estado)
    error = pyqtSignal(object)          # excepciones inesperadas -> diálogo
    tool_finished = pyqtSignal()        # un gesto de herramienta terminó
    selection_changed = pyqtSignal()

    def __init__(self, session: EditSession, tools: dict, options, parent=None):
        super().__init__(parent)
        self.session, self.tools, self.options = session, tools, options
        self.tool_key = "brush"
        self.zoom = 1.0
        self._comp: Optional[np.ndarray] = None
        self._qimg = None
        self._pan_last = None
        self._space = False
        self._active_tool = None
        self._mouse_img = None
        self._phase = 0
        self._cursor_cache = {}
        self._sel_box = None            # caja de la selección en caché (se invalida con el evento «selection»)
        self._resize = None             # gesto de redimensionado: {'handle', 'box', 'new'}
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.StrongFocus)
        session.doc.add_listener(self._on_doc_event)
        self._ants = QTimer(self)
        self._ants.timeout.connect(self._tick)
        self._ants.start(180)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.viewport().update())
        self.verticalScrollBar().valueChanged.connect(lambda _: self.viewport().update())
        self._update_scrollbars()

    # ------------------------------------------------------------------
    # Caché de composición
    # ------------------------------------------------------------------
    def _ensure_cache(self):
        doc = self.session.doc
        if self._comp is None or self._comp.shape[:2] != (doc.height, doc.width):
            self._comp = doc.composite()
            self._qimg = qimage_from_rgba(self._comp, copy=False)

    def _on_doc_event(self, kind, payload):
        if kind in ("selection", "size", "structure"):
            self._sel_box = None
        doc = self.session.doc
        if kind == "size":
            self._comp = None
            self._update_scrollbars()
            self.viewport().update()
        elif kind == "pixels":
            if self._comp is None or self._comp.shape[:2] != (doc.height, doc.width):
                self._comp = None
                self.viewport().update()
                return
            rect = payload if payload is not None else (0, 0, doc.width, doc.height)
            part = doc.composite(rect)
            if part.size:
                x0, y0 = rect[0], rect[1]
                self._comp[y0:y0 + part.shape[0], x0:x0 + part.shape[1]] = part
                self._update_rect(rect)
        elif kind == "selection":
            self.viewport().update()
            self.selection_changed.emit()

    def _update_rect(self, rect):
        ox, oy = self._origin()
        z = self.zoom
        self.viewport().update(int(ox + rect[0] * z) - 2, int(oy + rect[1] * z) - 2,
                               int((rect[2] - rect[0]) * z) + 5, int((rect[3] - rect[1]) * z) + 5)

    # ------------------------------------------------------------------
    # Geometría y zoom
    # ------------------------------------------------------------------
    def _content_size(self):
        d = self.session.doc
        return d.width * self.zoom + 2 * MARGIN, d.height * self.zoom + 2 * MARGIN

    def _update_scrollbars(self):
        cw, ch = self._content_size()
        vw, vh = self.viewport().width(), self.viewport().height()
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        hb.setRange(0, max(0, int(cw - vw)))
        vb.setRange(0, max(0, int(ch - vh)))
        hb.setPageStep(vw)
        vb.setPageStep(vh)

    def _origin(self):
        cw, ch = self._content_size()
        vw, vh = self.viewport().width(), self.viewport().height()
        ox = (vw - cw) / 2 + MARGIN if cw <= vw else MARGIN - self.horizontalScrollBar().value()
        oy = (vh - ch) / 2 + MARGIN if ch <= vh else MARGIN - self.verticalScrollBar().value()
        return ox, oy

    def to_image(self, pos):
        ox, oy = self._origin()
        return (pos.x() - ox) / self.zoom, (pos.y() - oy) / self.zoom

    def set_zoom(self, zoom: float, anchor=None):
        zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
        vp = self.viewport()
        if anchor is None:
            anchor = QPointF(vp.width() / 2, vp.height() / 2)
        ix, iy = self.to_image(anchor)
        self.zoom = zoom
        self._update_scrollbars()
        ox, oy = self._origin()
        # mantener bajo el ancla el mismo punto de la imagen
        self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() + (ox + ix * zoom - anchor.x())))
        self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() + (oy + iy * zoom - anchor.y())))
        self.viewport().update()
        self.zoom_changed.emit(self.zoom)

    def zoom_in(self):
        self.set_zoom(self.zoom * 1.25)

    def zoom_out(self):
        self.set_zoom(self.zoom / 1.25)

    def actual_size(self):
        self.set_zoom(1.0)

    def fit(self):
        d, vp = self.session.doc, self.viewport()
        z = min((vp.width() - 2 * MARGIN) / d.width, (vp.height() - 2 * MARGIN) / d.height)
        self.set_zoom(max(MIN_ZOOM, min(z, 32.0)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_scrollbars()

    # ------------------------------------------------------------------
    # Herramienta activa
    # ------------------------------------------------------------------
    def set_tool(self, key: str):
        self.finish_pending()          # polígono/curva en edición: se confirman al cambiar de herramienta
        self.cancel_gesture()
        self.tool_key = key
        self._apply_cursor()
        self.viewport().update()

    def _apply_cursor(self):
        """Cursor según la herramienta activa (la barra espaciadora fuerza la mano)."""
        key = "pan" if self._space else self.tool_key
        if key not in self._cursor_cache:
            self._cursor_cache[key] = tool_cursor(key)
        self.viewport().setCursor(self._cursor_cache[key])

    # -- tiradores de la selección ---------------------------------------------
    def _selection_box(self):
        sel = self.session.doc.selection
        if not sel.active:
            return None
        if self._sel_box is None:
            self._sel_box = sel.bbox()
        x0, y0, x1, y1 = self._sel_box
        return self._sel_box if x1 > x0 and y1 > y0 else None

    def _handle_at(self, pos):
        """Tirador bajo ``pos`` (pantalla) si la herramienta actual muestra tiradores."""
        if self.tool_key not in RESIZE_TOOLS or self._space or self._active_tool is not None:
            return None
        box = self._selection_box()
        if box is None:
            return None
        x, y = self.to_image(pos)
        return hit_handle(box, x, y, HANDLE_PX / self.zoom)

    def _update_hover_cursor(self, pos):
        h = self._handle_at(pos) if self._resize is None else self._resize["handle"]
        if h is None:
            self._apply_cursor()
            return
        shape = {"fdiag": Qt.SizeFDiagCursor, "bdiag": Qt.SizeBDiagCursor, "ver": Qt.SizeVerCursor,
                 "hor": Qt.SizeHorCursor}[cursor_name(h)]
        self.viewport().setCursor(shape)

    def _cancel_resize(self):
        if self._resize is not None:
            self._resize = None
            self._apply_cursor()
            self.viewport().update()

    def _ctx(self):
        return ToolContext(self.session, self.options)

    @staticmethod
    def _mods():
        m = QApplication.keyboardModifiers()
        out = set()
        if m & Qt.ShiftModifier:
            out.add("shift")
        if m & Qt.ControlModifier:
            out.add("ctrl")
        if m & Qt.AltModifier:
            out.add("alt")
        return frozenset(out)

    def finish_pending(self):
        """Confirma las ediciones pendientes (polígono, curva) de las herramientas."""
        for tool in self.tools.values():
            if tool.pending:
                self._run(tool.finish)
                self.viewport().update()
                self.tool_finished.emit()

    def _cancel_pending(self) -> bool:
        cancelled = False
        for tool in self.tools.values():
            if tool.pending:
                tool.cancel(self._ctx())
                cancelled = True
        if cancelled:
            self.viewport().update()
        return cancelled

    def handle_escape(self):
        """Esc: cancela el gesto o la edición pendiente; si no hay ninguno, anula la selección (como Ctrl+D)."""
        if self._resize is not None:
            self._cancel_resize()
        elif self._active_tool is not None:
            self.cancel_gesture()
        elif self._cancel_pending():
            pass
        elif self.session.doc.selection.active:
            try:
                self.session.deselect()
            except Exception as exc:  # noqa: BLE001
                self.error.emit(exc)

    def cancel_gesture(self):
        if self._active_tool is not None:
            try:
                self._active_tool.cancel(self._ctx())
            finally:
                self._active_tool = None
            self.viewport().update()

    def _run(self, fn, *args):
        """Ejecuta un evento de herramienta; los errores esperables van a la barra de estado."""
        try:
            fn(self._ctx(), *args)
        except PaintMintError as exc:
            self._abort_gesture()
            self.message.emit(str(exc))
        except (Exception, MemoryError) as exc:  # noqa: BLE001
            self._abort_gesture()
            self.error.emit(exc)

    def _abort_gesture(self):
        tool, self._active_tool = self._active_tool, None
        if tool is not None:
            try:
                tool.cancel(self._ctx())
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Ratón y teclado
    # ------------------------------------------------------------------
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MiddleButton or self._space or self.tool_key == "pan":
            self._pan_last = e.pos()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if self.tool_key == "zoom":
            self.set_zoom(self.zoom * (1.5 if e.button() == Qt.LeftButton else 1 / 1.5), QPointF(e.pos()))
            return
        if e.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        if e.button() == Qt.LeftButton:
            h = self._handle_at(e.pos())
            if h is not None:                       # arrastrar un tirador redimensiona la selección
                self._resize = {"handle": h, "box": self._selection_box(), "new": self._selection_box()}
                self._update_hover_cursor(e.pos())
                return
        tool = self.tools.get(self.tool_key)
        if tool is None:
            return
        x, y = self.to_image(e.pos())
        self._active_tool = tool
        self._run(tool.press, x, y, "primary" if e.button() == Qt.LeftButton else "secondary", self._mods())
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and any(t.pending for t in self.tools.values()):
            self.finish_pending()
        else:
            super().mouseDoubleClickEvent(e)

    def hideEvent(self, e):
        self.finish_pending()          # al cambiar de pestaña no queda nada pendiente en este documento
        super().hideEvent(e)

    def mouseMoveEvent(self, e):
        x, y = self.to_image(e.pos())
        self._mouse_img = (x, y)
        self.cursor_moved.emit(x, y)
        if self._pan_last is not None:
            d = e.pos() - self._pan_last
            self._pan_last = e.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            return
        if self._resize is not None:
            r = self._resize
            r["new"] = resized_box(r["box"], r["handle"], x, y, "shift" in self._mods())
            self.viewport().update()
            return
        if self._active_tool is not None:
            self._run(self._active_tool.move, x, y, self._mods())
        elif not e.buttons():
            self._update_hover_cursor(e.pos())
        if self._active_tool is not None or self.tool_key in PAINTING_TOOLS:
            self.viewport().update()

    def mouseReleaseEvent(self, e):
        if self._pan_last is not None:
            self._pan_last = None
            self._apply_cursor()
            return
        if self._resize is not None:
            new, self._resize = self._resize["new"], None
            try:
                self.session.resize_selection(new)
            except PaintMintError as exc:
                self.message.emit(str(exc))
            except (Exception, MemoryError) as exc:  # noqa: BLE001
                self.error.emit(exc)
            self._apply_cursor()
            self.viewport().update()
            self.tool_finished.emit()
            return
        tool, self._active_tool = self._active_tool, None
        if tool is not None:
            x, y = self.to_image(e.pos())
            try:
                tool.release(self._ctx(), x, y, self._mods())
            except PaintMintError as exc:
                self.message.emit(str(exc))
            except (Exception, MemoryError) as exc:  # noqa: BLE001
                self.error.emit(exc)
            self.viewport().update()
            self.tool_finished.emit()

    def leaveEvent(self, e):
        self._mouse_img = None
        self.viewport().update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15), QPointF(e.pos()))
            e.accept()
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self._apply_cursor()
        elif e.key() == Qt.Key_Escape:
            self.handle_escape()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and any(t.pending for t in self.tools.values()):
            self.finish_pending()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self._apply_cursor()
        else:
            super().keyReleaseEvent(e)

    # ------------------------------------------------------------------
    # Pintado
    # ------------------------------------------------------------------
    def _tick(self):
        if self.session.doc.selection.active and self.isVisible():
            self._phase = (self._phase + 1) % 8
            self.viewport().update()

    def paintEvent(self, ev):
        self._ensure_cache()
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor(58, 58, 62))
        doc, z = self.session.doc, self.zoom
        ox, oy = self._origin()
        target = QRectF(ox, oy, doc.width * z, doc.height * z)
        # cuadrícula de transparencia
        p.save()
        p.setClipRect(target.toAlignedRect().intersected(ev.rect()))
        p.fillRect(target, QColor(255, 255, 255))
        tile = 8
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(204, 204, 204))
        vis = target.intersected(QRectF(ev.rect()))
        x0 = int((vis.left() - target.left()) // (tile * 2)) * tile * 2
        y0 = int((vis.top() - target.top()) // tile) * tile
        yy = y0
        while target.top() + yy < vis.bottom():
            xx = x0 + (tile if (yy // tile) % 2 else 0)
            while target.left() + xx < vis.right():
                p.drawRect(QRectF(target.left() + xx, target.top() + yy, tile, tile))
                xx += tile * 2
            yy += tile
        p.restore()
        # imagen
        p.setRenderHint(QPainter.SmoothPixmapTransform, z < 1.0)
        p.drawImage(target, self._qimg, QRectF(0, 0, doc.width, doc.height))
        self._paint_selection(p, target)
        self._paint_overlay(p)
        self._paint_handles(p)
        p.end()

    def _paint_selection(self, p, target):
        mask = self.session.doc.selection.mask
        if mask is None:
            return
        vp = self.viewport().rect()
        vis = target.toAlignedRect().intersected(vp)
        if vis.width() < 1 or vis.height() < 1:
            return
        z = self.zoom
        sx = np.arange(vis.left(), vis.left() + vis.width())
        sy = np.arange(vis.top(), vis.top() + vis.height())
        ix = np.clip(((sx + 0.5 - target.left()) / z).astype(np.int64), 0, mask.shape[1] - 1)
        iy = np.clip(((sy + 0.5 - target.top()) / z).astype(np.int64), 0, mask.shape[0] - 1)
        inside = mask[iy[:, None], ix[None, :]] > 127
        pad = np.pad(inside, 1)
        edge = inside & ~(pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:])
        if not edge.any():
            return
        xs, ys = np.meshgrid(sx, sy)
        dark = (((xs + ys + self._phase) // 4) % 2) == 0
        rgba = np.zeros(edge.shape + (4,), dtype=np.uint8)
        rgba[edge & dark] = (0, 0, 0, 255)
        rgba[edge & ~dark] = (255, 255, 255, 255)
        img = qimage_from_rgba(rgba)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawImage(vis.topLeft(), img)

    def _paint_handles(self, p):
        if self.tool_key not in RESIZE_TOOLS or self._active_tool is not None:
            return
        box = self._resize["new"] if self._resize is not None else self._selection_box()
        if box is None:
            return
        p.setRenderHint(QPainter.Antialiasing, False)
        if self._resize is not None:                       # vista previa del nuevo contorno
            a, b = self._to_screen(box[0], box[1]), self._to_screen(box[2], box[3])
            for color, off in ((QColor(255, 255, 255), 0), (QColor(0, 0, 0), 4)):
                pen = QPen(color, 1, Qt.CustomDashLine)
                pen.setDashPattern([4, 4])
                pen.setDashOffset(off)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(a, b))
        for hx, hy in handle_points(box).values():
            c = self._to_screen(hx, hy)
            p.setBrush(QColor(255, 255, 255))
            p.setPen(QPen(QColor(0, 0, 0), 1))
            p.drawRect(QRectF(round(c.x()) - 3.5, round(c.y()) - 3.5, 7, 7))

    def _to_screen(self, x, y):
        ox, oy = self._origin()
        return QPointF(ox + x * self.zoom, oy + y * self.zoom)

    def _paint_overlay(self, p):
        tool = self.tools.get(self.tool_key)
        ov = getattr(tool, "overlay", None) if tool is not None else None
        p.setRenderHint(QPainter.Antialiasing, True)

        def dashed(draw):
            for color, offset in ((QColor(255, 255, 255), 0), (QColor(0, 0, 0), 4)):
                pen = QPen(color, 1, Qt.CustomDashLine)
                pen.setDashPattern([4, 4])
                pen.setDashOffset(offset)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                draw()

        if ov:
            if ov["type"] in ("rect", "ellipse"):
                x0, y0, x1, y1 = ov["box"]
                a, b = self._to_screen(min(x0, x1), min(y0, y1)), self._to_screen(max(x0, x1), max(y0, y1))
                r = QRectF(a, b)
                dashed(lambda: p.drawRect(r) if ov["type"] == "rect" else p.drawEllipse(r))
            elif ov["type"] == "polygon":
                poly = QPolygonF([self._to_screen(*pt) for pt in ov["points"]])
                dashed(lambda: p.drawPolyline(poly))
            elif ov["type"] == "line":
                a, b = self._to_screen(*ov["p0"]), self._to_screen(*ov["p1"])
                dashed(lambda: p.drawLine(a, b))
            elif ov["type"] == "nodes":          # nodos de polígono/curva: cuadritos agarrables
                for pt in ov["points"]:
                    c = self._to_screen(*pt)
                    p.setBrush(QColor(255, 255, 255))
                    p.setPen(QPen(QColor(0, 0, 0), 1))
                    p.drawRect(QRectF(c.x() - 4, c.y() - 4, 8, 8))
            elif ov["type"] == "cross":          # origen del tampón de clonar
                c = self._to_screen(*ov["p"])
                for color, wd in ((QColor(255, 255, 255), 3), (QColor(0, 0, 0), 1)):
                    p.setPen(QPen(color, wd))
                    p.drawLine(QPointF(c.x() - 8, c.y()), QPointF(c.x() + 8, c.y()))
                    p.drawLine(QPointF(c.x(), c.y() - 8), QPointF(c.x(), c.y() + 8))
        if self.tool_key in PAINTING_TOOLS and self._mouse_img is not None and self._pan_last is None:
            c = self._to_screen(*self._mouse_img)
            r = max(1.5, self.options.size * self.zoom / 2)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.drawEllipse(c, r + 1, r + 1)
            p.setPen(QPen(QColor(0, 0, 0), 1))
            p.drawEllipse(c, r, r)
