"""Diálogos: nueva imagen, redimensionar, lienzo, propiedades de capa y efectos con vista previa."""

from __future__ import annotations

from ..i18n import tr

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QSlider, QSpinBox,
                             QVBoxLayout, QWidget, QApplication)

from ..core import memory
from ..core.blend import BLEND_MODES
from ..effects.adjustments import curve_lut
from ..effects.base import normalize_curve
from .qtutil import show_error


def _buttons(dialog) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class NewImageDialog(QDialog):
    PRESETS = [(tr('Custom'), None), ("640 × 480", (640, 480)), ("800 × 600", (800, 600)),
               ("1280 × 720 (HD)", (1280, 720)), ("1920 × 1080 (Full HD)", (1920, 1080)),
               ("3840 × 2160 (4K)", (3840, 2160))]

    def __init__(self, parent=None, size=(800, 600)):
        super().__init__(parent)
        self.setWindowTitle(tr('New image'))
        form = QFormLayout(self)
        self.preset = QComboBox()
        for label, _ in self.PRESETS:
            self.preset.addItem(label)
        self.w = QSpinBox()
        self.h = QSpinBox()
        for s, v in ((self.w, size[0]), (self.h, size[1])):
            s.setRange(1, memory.MAX_DIMENSION)
            s.setValue(v)
        self.bg = QComboBox()
        self.bg.addItems([tr('White'), tr('Transparent'), tr('Primary color'), tr('Secondary color')])
        form.addRow(tr('Preset size:'), self.preset)
        form.addRow(tr('Width (px):'), self.w)
        form.addRow(tr('Height (px):'), self.h)
        self.keep_ratio = QCheckBox(tr('Maintain aspect ratio'))
        self.keep_ratio.setChecked(True)
        form.addRow("", self.keep_ratio)
        form.addRow(tr('Background:'), self.bg)
        form.addRow(_buttons(self))
        self._ratio = size[0] / float(size[1])
        self._busy = False
        self.preset.currentIndexChanged.connect(self._preset)
        self.w.valueChanged.connect(lambda v: self._linked(self.w, self.h, 1.0 / self._ratio))
        self.h.valueChanged.connect(lambda v: self._linked(self.h, self.w, self._ratio))
        self.keep_ratio.toggled.connect(self._lock_toggled)

    def _lock_toggled(self, on):
        if on and self.h.value():
            self._ratio = self.w.value() / float(self.h.value())   # se bloquea la proporción actual

    def _linked(self, src, dst, factor):
        """Con la proporción bloqueada, al cambiar un lado el otro se ajusta (se respeta el máximo)."""
        if self._busy:
            return
        if self.keep_ratio.isChecked():
            self._busy = True
            dst.setValue(max(1, int(round(src.value() * factor))))
            self._busy = False
        elif self.h.value():
            self._ratio = self.w.value() / float(self.h.value())

    def _preset(self, i):
        size = self.PRESETS[i][1]
        if size:
            self._busy = True
            self.w.setValue(size[0])
            self.h.setValue(size[1])
            self._busy = False
            self._ratio = size[0] / float(size[1])

    def values(self):
        return self.w.value(), self.h.value(), self.bg.currentIndex()


class ResizeDialog(QDialog):
    def __init__(self, width, height, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Resize image'))
        self.ow, self.oh = width, height
        form = QFormLayout(self)
        self.pct = QDoubleSpinBox()
        self.pct.setRange(0.1, 1000)
        self.pct.setValue(100)
        self.pct.setSuffix(" %")
        self.w, self.h = QSpinBox(), QSpinBox()
        for s, v in ((self.w, width), (self.h, height)):
            s.setRange(1, memory.MAX_DIMENSION)
            s.setValue(v)
        self.keep = QCheckBox(tr('Keep aspect ratio'))
        self.keep.setChecked(True)
        self.method = QComboBox()
        for key, label in (("lanczos", tr('Lanczos (best quality)')), ("bicubic", tr('Bicubic')),
                           ("bilinear", tr('Bilinear')), ("nearest", tr('Nearest neighbor'))):
            self.method.addItem(label, key)
        form.addRow(tr('Percentage:'), self.pct)
        form.addRow(tr('Width (px):'), self.w)
        form.addRow(tr('Height (px):'), self.h)
        form.addRow(self.keep)
        form.addRow(tr('Resampling:'), self.method)
        form.addRow(_buttons(self))
        self._busy = False
        self.pct.valueChanged.connect(self._from_pct)
        self.w.valueChanged.connect(lambda v: self._from_dim(True))
        self.h.valueChanged.connect(lambda v: self._from_dim(False))

    def _from_pct(self, v):
        if self._busy:
            return
        self._busy = True
        self.w.setValue(max(1, round(self.ow * v / 100)))
        self.h.setValue(max(1, round(self.oh * v / 100)))
        self._busy = False

    def _from_dim(self, width_changed):
        if self._busy:
            return
        self._busy = True
        if self.keep.isChecked():
            if width_changed:
                self.h.setValue(max(1, round(self.w.value() * self.oh / self.ow)))
            else:
                self.w.setValue(max(1, round(self.h.value() * self.ow / self.oh)))
        self.pct.setValue(self.w.value() * 100.0 / self.ow)
        self._busy = False

    def values(self):
        return self.w.value(), self.h.value(), self.method.currentData()


class CanvasSizeDialog(QDialog):
    ANCHORS = [["tl", "t", "tr"], ["l", "c", "r"], ["bl", "b", "br"]]

    def __init__(self, width, height, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Canvas size'))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.w, self.h = QSpinBox(), QSpinBox()
        for s, v in ((self.w, width), (self.h, height)):
            s.setRange(1, memory.MAX_DIMENSION)
            s.setValue(v)
        form.addRow(tr('Width (px):'), self.w)
        form.addRow(tr('Height (px):'), self.h)
        lay.addLayout(form)
        lay.addWidget(QLabel(tr('Anchor:')))
        grid = QGridLayout()
        self.radios = {}
        for r, row in enumerate(self.ANCHORS):
            for c, key in enumerate(row):
                rb = QRadioButton()
                self.radios[key] = rb
                grid.addWidget(rb, r, c)
        self.radios["c"].setChecked(True)
        lay.addLayout(grid)
        lay.addWidget(_buttons(self))

    def values(self):
        anchor = next(k for k, rb in self.radios.items() if rb.isChecked())
        return self.w.value(), self.h.value(), anchor


class LayerPropertiesDialog(QDialog):
    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Layer properties'))
        form = QFormLayout(self)
        self.name = QLineEdit(layer.name)
        self.visible = QCheckBox("Visible")
        self.visible.setChecked(layer.visible)
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(round(layer.opacity * 100))
        self.blend = QComboBox()
        for key, label in BLEND_MODES.items():
            self.blend.addItem(label, key)
        self.blend.setCurrentIndex(self.blend.findData(layer.blend_mode))
        form.addRow(tr('Name:'), self.name)
        form.addRow(self.visible)
        form.addRow(tr('Opacity:'), self.opacity)
        form.addRow(tr('Blend mode:'), self.blend)
        form.addRow(_buttons(self))

    def values(self):
        return {"name": self.name.text() or tr('Layer'), "visible": self.visible.isChecked(),
                "opacity": self.opacity.value() / 100.0, "blend_mode": self.blend.currentData()}


class CurvesWidget(QWidget):
    """Editor de curva tonal: clic añade/arrastra puntos, clic derecho los elimina."""

    changed = pyqtSignal()
    SIZE = 256

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = [(0, 0), (255, 255)]
        self.setFixedSize(self.SIZE + 16, self.SIZE + 16)
        self._drag = None

    def set_points(self, pts):
        self.points = normalize_curve(pts)
        self.update()

    def _to_screen(self, x, y):
        return QPointF(8 + x, 8 + (255 - y))

    def _from_screen(self, pos):
        return max(0, min(255, int(pos.x() - 8))), max(0, min(255, int(255 - (pos.y() - 8))))

    def _hit(self, pos):
        for i, (x, y) in enumerate(self.points):
            s = self._to_screen(x, y)
            if abs(s.x() - pos.x()) <= 7 and abs(s.y() - pos.y()) <= 7:
                return i
        return None

    def mousePressEvent(self, e):
        i = self._hit(e.pos())
        if e.button() == Qt.RightButton:
            if i is not None and 0 < i < len(self.points) - 1:
                del self.points[i]
                self.changed.emit()
                self.update()
            return
        if i is None:
            x, y = self._from_screen(e.pos())
            if any(px == x for px, _ in self.points):
                return
            self.points = sorted(self.points + [(x, y)])
            i = self.points.index((x, y))
            self.changed.emit()
        self._drag = i
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        x, y = self._from_screen(e.pos())
        i = self._drag
        lo = self.points[i - 1][0] + 1 if i > 0 else 0
        hi = self.points[i + 1][0] - 1 if i < len(self.points) - 1 else 255
        if i == 0:
            x = 0
        elif i == len(self.points) - 1:
            x = 255
        else:
            x = max(lo, min(hi, x))
        self.points[i] = (x, y)
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(40, 40, 44))
        p.setPen(QPen(QColor(80, 80, 86), 1))
        for k in range(0, 257, 64):
            p.drawLine(8 + k, 8, 8 + k, 8 + 255)
            p.drawLine(8, 8 + k, 8 + 255, 8 + k)
        p.setPen(QPen(QColor(120, 120, 126), 1, Qt.DashLine))
        p.drawLine(self._to_screen(0, 0), self._to_screen(255, 255))
        lut = curve_lut(self.points)
        p.setPen(QPen(QColor(120, 220, 160), 2))
        prev = self._to_screen(0, int(lut[0]))
        for x in range(1, 256):
            cur = self._to_screen(x, int(lut[x]))
            p.drawLine(prev, cur)
            prev = cur
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(0, 0, 0), 1))
        for x, y in self.points:
            p.drawEllipse(self._to_screen(x, y), 4, 4)


class EffectDialog(QDialog):
    """Diálogo generado a partir de ``effect.params`` con vista previa en vivo sobre el lienzo."""

    def __init__(self, effect, session, parent=None):
        super().__init__(parent)
        self.effect, self.session = effect, session
        self.setWindowTitle(effect.label)
        self.controls = {}
        form = QFormLayout(self)
        for prm in effect.params:
            form.addRow(prm.label + ":", self._make_control(prm))
        self.status = QLabel("")
        self.status.setStyleSheet("color: #c0392b;")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        form.addRow(_buttons(self))
        self.handle = session.begin_edit()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._preview)
        self._preview()

    # -- controles -----------------------------------------------------------
    def _make_control(self, prm):
        if prm.kind in ("int", "float"):
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            if prm.kind == "int":
                spin = QSpinBox()
                spin.setRange(int(prm.min), int(prm.max))
                spin.setValue(int(prm.default))
                slider = QSlider(Qt.Horizontal)
                slider.setRange(int(prm.min), int(prm.max))
                slider.setValue(int(prm.default))
                slider.valueChanged.connect(spin.setValue)
                spin.valueChanged.connect(slider.setValue)
            else:
                spin = QDoubleSpinBox()
                spin.setDecimals(2)
                spin.setSingleStep(0.1)
                spin.setRange(prm.min, prm.max)
                spin.setValue(prm.default)
                slider = QSlider(Qt.Horizontal)
                slider.setRange(0, 1000)
                span = prm.max - prm.min
                slider.setValue(int((prm.default - prm.min) / span * 1000))
                slider.valueChanged.connect(lambda v, s=spin, p=prm: s.setValue(p.min + v / 1000.0 * (p.max - p.min)))
                spin.valueChanged.connect(lambda v, sl=slider, p=prm: (
                    sl.blockSignals(True), sl.setValue(int((v - p.min) / (p.max - p.min) * 1000)),
                    sl.blockSignals(False)))
            spin.valueChanged.connect(self._schedule)
            lay.addWidget(slider, 1)
            lay.addWidget(spin)
            self.controls[prm.key] = spin.value
            return w
        if prm.kind == "bool":
            cb = QCheckBox()
            cb.setChecked(prm.default)
            cb.toggled.connect(self._schedule)
            self.controls[prm.key] = cb.isChecked
            return cb
        if prm.kind == "choice":
            combo = QComboBox()
            for value, label in prm.choices:
                combo.addItem(label, value)
            combo.currentIndexChanged.connect(self._schedule)
            self.controls[prm.key] = combo.currentData
            return combo
        if prm.kind == "curve":
            cw = CurvesWidget()
            cw.set_points(prm.default)
            cw.changed.connect(self._schedule)
            self.controls[prm.key] = lambda c=cw: list(c.points)
            return cw
        raise ValueError(prm.kind)

    def values(self):
        return {k: getter() for k, getter in self.controls.items()}

    # -- vista previa ----------------------------------------------------------
    def _schedule(self, *_):
        self.timer.start()

    def _preview(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.handle.reset()
            result = self.effect.apply(self.handle.snapshot, **self.effect.resolve(self.values()))
            self.handle.write_full(result)
            self.status.setText("")
        except (Exception, MemoryError) as exc:  # noqa: BLE001
            self.handle.reset()
            self.status.setText(str(exc) or tr('Could not generate the preview.'))
        finally:
            QApplication.restoreOverrideCursor()

    def accept(self):
        self.timer.stop()
        self._preview()
        if self.status.text():
            return  # no se cierra con un error pendiente
        self.handle.commit(self.effect.label)
        super().accept()

    def reject(self):
        self.timer.stop()
        self.handle.cancel()
        super().reject()
