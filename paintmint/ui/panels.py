"""Paneles acoplables: capas, historial, colores y texto; y barra de opciones de herramienta."""

from __future__ import annotations

from ..i18n import tr

from PyQt5.QtCore import QRegExp, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPixmap, QRegExpValidator
from PyQt5.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFontComboBox, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                             QSlider, QSpinBox, QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import config
from ..core.blend import BLEND_MODES
from ..core.errors import PaintMintError
from ..core.layer import TextSpec
from ..render.raster import GRADIENT_KINDS, HATCH_STYLES, LINE_STYLES, SHAPE_KINDS
from .colorwidgets import ColorWheel, fit_spin, GradientSlider, PaletteGrid, SliderSpin, SwatchPair, hsv_to_rgb, rgb_to_hsv
from .icons import option_icon
from .qtutil import color_tuple, guarded, pixmap_from_rgba, qcolor, show_error


def _rebind(panel, session):
    """Cambia la sesión observada por ``panel`` sin acumular oyentes en documentos anteriores."""
    old = panel.session
    if old is not None and panel._on_event in old.doc.listeners:
        old.doc.listeners.remove(panel._on_event)
    panel.session = session
    if session is not None:
        session.doc.add_listener(panel._on_event)


# ----------------------------------------------------------------------------
# Capas
# ----------------------------------------------------------------------------
class LayersPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = None
        self._busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 48))
        self.list.setSpacing(1)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.blend = QComboBox()
        for key, label in BLEND_MODES.items():
            self.blend.addItem(label, key)
        self.blend.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)   # no impone un ancho mínimo grande
        self.blend.setMinimumContentsLength(8)
        row.addWidget(self.blend, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('Opacity:')))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity_label = QLabel("100%")
        row.addWidget(self.opacity, 1)
        row.addWidget(self.opacity_label)
        lay.addLayout(row)
        self.buttons = {}
        btns = QHBoxLayout()
        for key, text, tip in (("add", "＋", tr('New layer')), ("dup", "⧉", tr('Duplicate layer')),
                               ("del", "🗑", tr('Delete layer')), ("up", "▲", tr('Move layer up')),
                               ("down", "▼", tr('Move layer down')), ("merge", "⤓", tr('Merge layer down')),
                               ("props", "⚙", tr('Layer properties'))):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setFixedWidth(28)
            self.buttons[key] = b
            btns.addWidget(b)
        btns.setSpacing(2)
        lay.addLayout(btns)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(250)
        self._thumb_timer.timeout.connect(self.refresh)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemChanged.connect(self._item_changed)
        self.blend.activated.connect(self._blend_changed)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.opacity.sliderReleased.connect(lambda: self.session and self.session.history.break_merge())

    def bind(self, session):
        _rebind(self, session)
        self.refresh()

    def _on_event(self, kind, payload):
        if kind == "pixels":
            self._thumb_timer.start()
        elif kind in ("structure", "size"):
            self.refresh()

    def refresh(self):
        s = self.session
        self._busy = True
        try:
            self.list.clear()
            if s is None:
                return
            doc = s.doc
            for i in range(len(doc.layers) - 1, -1, -1):
                layer = doc.layers[i]
                item = QListWidgetItem(layer.name + ("  [T]" if layer.is_text else ""))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
                item.setData(Qt.UserRole, layer.id)
                step = max(1, max(layer.height, layer.width) // 96)
                item.setIcon(QIcon(pixmap_from_rgba(layer.pixels[::step, ::step], 48)))
                self.list.addItem(item)
            self.list.setCurrentRow(len(doc.layers) - 1 - doc.active_index)
            active = doc.active_layer
            self.blend.setCurrentIndex(self.blend.findData(active.blend_mode))
            self.opacity.setValue(round(active.opacity * 100))
            self.opacity_label.setText(f"{round(active.opacity * 100)}%")
        finally:
            self._busy = False

    def _layer_at(self, row):
        doc = self.session.doc
        return doc.layers[len(doc.layers) - 1 - row]

    def _row_changed(self, row):
        if self._busy or self.session is None or row < 0:
            return
        self.session.doc.set_active(len(self.session.doc.layers) - 1 - row)

    @guarded
    def _item_changed(self, item):
        if self._busy or self.session is None:
            return
        layer = self.session.doc.layer_by_id(item.data(Qt.UserRole))
        self.session.set_layer_props(layer, visible=item.checkState() == Qt.Checked)

    @guarded
    def _blend_changed(self, _):
        if self._busy or self.session is None:
            return
        self.session.set_layer_props(self.session.active_layer, blend_mode=self.blend.currentData())

    @guarded
    def _opacity_changed(self, value):
        self.opacity_label.setText(f"{value}%")
        if self._busy or self.session is None:
            return
        self.session.set_layer_props(self.session.active_layer, merge=True, opacity=value / 100.0)


# ----------------------------------------------------------------------------
# Historial
# ----------------------------------------------------------------------------
class HistoryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = None
        self._busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = QListWidget()
        lay.addWidget(self.list)
        self.list.currentRowChanged.connect(self._row)

    def bind(self, session):
        if self.session is not None:
            try:
                self.session.history.listeners.remove(self.refresh)
            except ValueError:
                pass
        self.session = session
        if session is not None:
            session.history.listeners.append(self.refresh)
        self.refresh()

    def refresh(self):
        self._busy = True
        self.list.clear()
        if self.session is not None:
            h = self.session.history
            self.list.addItem(tr('Original image'))
            for label in h.labels:
                self.list.addItem(label)
            self.list.setCurrentRow(h.position)
        self._busy = False

    @guarded
    def _row(self, row):
        if not self._busy and self.session is not None and row >= 0:
            self.session.history.goto(row)


# ----------------------------------------------------------------------------
# Colores
# ----------------------------------------------------------------------------
class ColorsPanel(QWidget):
    """Ventana «Colores» al estilo de Paint.NET: destino primario/secundario, rueda, deslizadores
    RGB/HSV/alfa, hexadecimal y paleta grande. «Menos/Más» oculta o muestra la parte avanzada."""

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options = options
        self._busy = False
        self.target = "primary"
        self._h, self._s, self._v = 0, 0, 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self.target_combo = QComboBox()
        self.target_combo.addItem(tr('Primary'), "primary")
        self.target_combo.addItem(tr('Secondary'), "secondary")
        self.more_btn = QPushButton()
        self.more_btn.setCheckable(True)
        self.more_btn.setChecked(bool(config.get("colors_more")))     # por defecto: versión simplificada
        top.addWidget(self.target_combo, 1)
        top.addWidget(self.more_btn)
        lay.addLayout(top)

        pair_row = QHBoxLayout()
        self.pair = SwatchPair()
        self.swap = QToolButton()
        self.swap.setText("⇄")
        self.swap.setToolTip(tr('Swap colors (X)'))
        self.reset = QToolButton()
        self.reset.setText("◼◻")
        self.reset.setToolTip(tr('Reset to black and white'))
        self.add_btn = QToolButton()
        self.add_btn.setText("＋")
        self.add_btn.setToolTip(tr('Add to palette'))
        pair_row.addWidget(self.pair)
        side = QVBoxLayout()
        side.addWidget(self.swap)
        side.addWidget(self.reset)
        pair_row.addLayout(side)
        pair_row.addStretch(1)
        pair_row.addWidget(self.add_btn, 0, Qt.AlignBottom)
        lay.addLayout(pair_row)

        # --- parte avanzada: rueda + deslizadores
        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(3)
        self.wheel = ColorWheel()
        dl.addWidget(self.wheel, 0, Qt.AlignHCenter)
        self.sliders = {}
        self.spins = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        rows = [("r", "R", 255), ("g", "G", 255), ("b", "B", 255), ("hex", tr('Hex'), 0),
                ("h", "H", 359), ("s", "S", 100), ("v", "V", 100), ("a", tr('Transparency - Alpha'), 255)]
        r = 0
        for key, label, mx in rows:
            if key == "a":
                grid.addWidget(QLabel(label), r, 0, 1, 3)
                r += 1
                grid.addWidget(QLabel(""), r, 0)
            elif key == "hex":
                grid.addWidget(QLabel(label), r, 0)
                self.hex = QLineEdit()
                self.hex.setMaxLength(6)
                self.hex.setValidator(QRegExpValidator(QRegExp("[0-9A-Fa-f]{0,6}")))
                self.hex.setFixedWidth(70)
                grid.addWidget(self.hex, r, 1, 1, 2, Qt.AlignLeft)
                r += 1
                continue
            else:
                grid.addWidget(QLabel(label), r, 0)
            sl, sp = GradientSlider(mx), QSpinBox()
            sp.setRange(0, mx)
            self.sliders[key], self.spins[key] = sl, sp
            grid.addWidget(sl, r, 1)
            grid.addWidget(sp, r, 2)
            sl.valueChanged.connect(lambda v, k=key: self._edited(k, v))
            sp.valueChanged.connect(lambda v, k=key: self._edited(k, v))
            r += 1
        grid.setColumnStretch(1, 1)
        dl.addLayout(grid)
        lay.addWidget(self.details)

        self.palette = PaletteGrid(config.get("custom_colors"))
        lay.addWidget(self.palette, 0, Qt.AlignHCenter)
        lay.addStretch(1)

        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.pair.selected.connect(self.set_target)
        self.more_btn.toggled.connect(self._toggle_details)
        self.wheel.picked.connect(self._wheel_picked)
        self.hex.editingFinished.connect(self._hex_edited)
        self.palette.picked.connect(self._palette_picked)
        self.add_btn.clicked.connect(self._add_custom)
        self.swap.clicked.connect(options.swap_colors)
        self.reset.clicked.connect(self._reset)
        options.listeners.append(self.sync)
        self._toggle_details(self.more_btn.isChecked())
        self.sync()

    # -- estado ------------------------------------------------------------------
    def current(self):
        return tuple(getattr(self.options, self.target))

    def set_target(self, which):
        self.target = which
        self.target_combo.blockSignals(True)
        self.target_combo.setCurrentIndex(self.target_combo.findData(which))
        self.target_combo.blockSignals(False)
        self.sync()

    def _target_changed(self, _i):
        self.set_target(self.target_combo.currentData())

    def _toggle_details(self, more):
        config.set_value("colors_more", bool(more))
        self.details.setVisible(more)
        self.more_btn.setText(tr('<< Less') if more else tr('More >>'))

    def _commit(self, rgba):
        if self._busy:
            return
        setattr(self.options, self.target, tuple(int(c) for c in rgba))
        self.options.notify()

    # -- edición desde los controles -----------------------------------------------------
    def _edited(self, key, value):
        if self._busy:
            return
        r, g, b, a = self.current()
        if key in ("r", "g", "b", "a"):
            vals = {"r": r, "g": g, "b": b, "a": a}
            vals[key] = int(value)
            self._h, self._s, self._v = rgb_to_hsv(vals["r"], vals["g"], vals["b"]) if (
                vals["r"], vals["g"], vals["b"]) != (r, g, b) else (self._h, self._s, self._v)
            self._commit((vals["r"], vals["g"], vals["b"], vals["a"]))
        else:   # h, s, v
            hs = {"h": self._h, "s": self._s, "v": self._v}
            hs[key] = int(value)
            self._h, self._s, self._v = hs["h"], hs["s"], hs["v"]
            self._commit(hsv_to_rgb(self._h, self._s, self._v) + (a,))

    def _wheel_picked(self, h, s, button):
        """Clic izquierdo en la rueda -> color primario; derecho -> secundario (se arrastra igual)."""
        which = "primary" if button == "left" else "secondary"
        if which != self.target:
            self.set_target(which)          # los controles pasan a mostrar el color elegido
        if self._v == 0:                    # con valor 0 todo tono sería negro: se usa el brillo máximo
            self._v = 100
        self._h, self._s = h, s
        self._commit(hsv_to_rgb(h, s, self._v) + (self.current()[3],))

    def _hex_edited(self):
        text = self.hex.text().strip()
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) != 6:
            self.sync()
            return
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        self._h, self._s, self._v = rgb_to_hsv(r, g, b)
        self._commit((r, g, b, self.current()[3]))

    def _palette_picked(self, button, rgba):
        other = "secondary" if self.target == "primary" else "primary"
        which = self.target if button == "left" else other
        setattr(self.options, which, tuple(rgba))
        if which == self.target:
            self._h, self._s, self._v = rgb_to_hsv(*rgba[:3])
        self.options.notify()

    def _add_custom(self):
        self.palette.add_custom(self.current())
        config.set_value("custom_colors", self.palette.custom_list())

    def _reset(self):
        self.options.primary, self.options.secondary = (0, 0, 0, 255), (255, 255, 255, 255)
        self.options.notify()

    # -- sincronización con las opciones ----------------------------------------------------
    def sync(self):
        self._busy = True
        try:
            r, g, b, a = self.current()
            h, s, v = rgb_to_hsv(r, g, b)
            # conserva el tono/saturación de la rueda cuando el color es gris o negro (no están definidos)
            if hsv_to_rgb(self._h, self._s, self._v) != (r, g, b):
                if v == 0:
                    h, s = self._h, self._s
                elif s == 0:
                    h = self._h
                self._h, self._s, self._v = h, s, v
            h, s, v = self._h, self._s, self._v
            self.pair.set_colors(self.options.primary, self.options.secondary, self.target)
            self.wheel.set_hsv(h, s, v)
            vals = {"r": r, "g": g, "b": b, "h": h, "s": s, "v": v, "a": a}
            for k, val in vals.items():
                self.sliders[k].setValue(val)
                self.spins[k].setValue(val)
            if not self.hex.hasFocus():
                self.hex.setText("%02X%02X%02X" % (r, g, b))
            self._update_gradients(r, g, b, h, s, v)
        finally:
            self._busy = False

    def _update_gradients(self, r, g, b, h, s, v):
        c = QColor
        self.sliders["r"].set_stops([(0, c(0, g, b)), (1, c(255, g, b))])
        self.sliders["g"].set_stops([(0, c(r, 0, b)), (1, c(r, 255, b))])
        self.sliders["b"].set_stops([(0, c(r, g, 0)), (1, c(r, g, 255))])
        self.sliders["h"].set_stops([(i / 6.0, c(*hsv_to_rgb(i * 60, s, v))) for i in range(7)])
        self.sliders["s"].set_stops([(0, c(*hsv_to_rgb(h, 0, v))), (1, c(*hsv_to_rgb(h, 100, v)))])
        self.sliders["v"].set_stops([(0, c(*hsv_to_rgb(h, s, 0))), (1, c(*hsv_to_rgb(h, s, 100)))])
        self.sliders["a"].set_stops([(0, QColor(r, g, b, 0)), (1, QColor(r, g, b, 255))])


# ----------------------------------------------------------------------------
# Texto
# ----------------------------------------------------------------------------
class TextPanel(QWidget):
    """Edita la capa de texto activa; si no hay ninguna, fija los valores del próximo texto."""

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options, self.session, self._busy = options, None, False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(tr('Select the Text tool and click on the image…'))
        self.edit.setMaximumHeight(110)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        self.font = QFontComboBox()
        self.size = QSpinBox()
        self.size.setRange(4, 1000)
        self.size.setSuffix(" px")
        row.addWidget(self.font, 1)
        row.addWidget(self.size)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.bold = QToolButton()
        self.bold.setText("N")
        self.bold.setCheckable(True)
        self.bold.setToolTip(tr('Bold'))
        self.italic = QToolButton()
        self.italic.setText("K")
        self.italic.setCheckable(True)
        self.italic.setToolTip(tr('Italic'))
        self.align = QComboBox()
        for key, label in (("left", tr('Left')), ("center", tr('Center')), ("right", tr('Right'))):
            self.align.addItem(label, key)
        self.color = QPushButton("Color")
        for w in (self.bold, self.italic, self.align, self.color):
            row.addWidget(w)
        lay.addLayout(row)
        lay.addStretch(1)
        self.edit.textChanged.connect(self._changed)
        self.font.currentFontChanged.connect(self._changed)
        self.size.valueChanged.connect(self._changed)
        self.bold.toggled.connect(self._changed)
        self.italic.toggled.connect(self._changed)
        self.align.currentIndexChanged.connect(self._changed)
        self.color.clicked.connect(self._pick_color)
        self._load_defaults()

    def _load_defaults(self):
        o = self.options
        self._busy = True
        self.font.setCurrentFont(QFontDatabase().font(o.font_family, "", 12))
        self.size.setValue(o.font_size)
        self.bold.setChecked(o.font_bold)
        self.italic.setChecked(o.font_italic)
        self.align.setCurrentIndex(self.align.findData(o.text_align))
        self._busy = False

    def bind(self, session):
        _rebind(self, session)
        self.sync()

    def _on_event(self, kind, payload):
        if kind == "structure":
            self.sync()

    def sync(self):
        """Carga en los controles la especificación de la capa de texto activa."""
        self._busy = True
        try:
            layer = self.session.active_layer if self.session is not None else None
            spec = layer.text if layer is not None else None
            self.edit.setEnabled(spec is not None)
            if spec is None:
                if self.edit.toPlainText():
                    self.edit.setPlainText("")
                return
            if self.edit.toPlainText() != spec.text:
                self.edit.setPlainText(spec.text)
            self.font.setCurrentFont(QFontDatabase().font(spec.family, "", 12))
            self.size.setValue(spec.size)
            self.bold.setChecked(spec.bold)
            self.italic.setChecked(spec.italic)
            self.align.setCurrentIndex(self.align.findData(spec.align))
        finally:
            self._busy = False

    def focus_editor(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def _spec_from_controls(self, base: TextSpec) -> TextSpec:
        spec = base.copy()
        spec.text = self.edit.toPlainText()
        spec.family = self.font.currentFont().family()
        spec.size = self.size.value()
        spec.bold, spec.italic = self.bold.isChecked(), self.italic.isChecked()
        spec.align = self.align.currentData()
        return spec

    @guarded
    def _changed(self, *_):
        if self._busy:
            return
        o = self.options
        o.font_family, o.font_size = self.font.currentFont().family(), self.size.value()
        o.font_bold, o.font_italic, o.text_align = self.bold.isChecked(), self.italic.isChecked(), self.align.currentData()
        layer = self.session.active_layer if self.session is not None else None
        if layer is not None and layer.text is not None:
            spec = self._spec_from_controls(layer.text)
            if spec != layer.text:
                self.session.update_text_layer(layer, spec, merge=True)

    @guarded
    def _pick_color(self, *_):
        layer = self.session.active_layer if self.session is not None else None
        if layer is None or layer.text is None:
            return
        c = QColorDialog.getColor(qcolor(layer.text.color), self, tr('Text color'), QColorDialog.ShowAlphaChannel)
        if c.isValid():
            spec = layer.text.copy()
            spec.color = color_tuple(c)
            self.session.history.break_merge()
            self.session.update_text_layer(layer, spec, merge=False)


# ----------------------------------------------------------------------------
# Opciones de herramienta
# ----------------------------------------------------------------------------
# qué controles muestra cada herramienta
TOOL_OPTIONS = {
    "select_rect": {"select_mode"}, "select_ellipse": {"select_mode"}, "select_lasso": {"select_mode"},
    "select_wand": {"select_mode", "tolerance", "contiguous", "sample"},
    "move": set(),
    "brush": {"size", "hardness", "opacity", "aa", "blend"},
    "pencil": {"size", "opacity", "blend"},
    "eraser": {"size", "hardness", "opacity", "aa"},
    "fill": {"fill_style", "tolerance", "contiguous", "sample", "opacity", "blend"},
    "clone": {"hint", "size", "hardness", "opacity", "aa"},
    "recolor": {"size", "hardness", "tolerance", "opacity", "aa"},
    "gradient": {"gradient", "opacity"},
    "shape": {"shape", "shape_mode", "size", "fill_style", "line_style", "aa", "blend", "opacity", "radius"},
    "move_selection": set(),
    "line": {"size", "line_style", "aa", "blend", "opacity"},
    "curve": {"hint", "size", "line_style", "aa", "blend", "opacity"},
    "rectangle": {"size", "shape_mode", "fill_style", "line_style", "aa", "blend", "opacity"},
    "rounded_rectangle": {"size", "shape_mode", "fill_style", "line_style", "aa", "blend", "opacity", "radius"},
    "ellipse": {"size", "shape_mode", "fill_style", "line_style", "aa", "blend", "opacity"},
    "freeform": {"size", "shape_mode", "fill_style", "line_style", "aa", "blend", "opacity"},
    "polygon": {"hint", "size", "shape_mode", "fill_style", "line_style", "aa", "blend", "opacity"},
    "text": set(), "picker": {"sample"}, "zoom": set(), "pan": set(),
}


TOOL_HINTS = {
    "clone": tr('Hold Ctrl and click to set the area to clone from, then drag to paint the copy.'),
    "polygon": tr('Click to add points (drag to move them). Enter or double-click finishes; Esc cancels.'),
    "curve": tr('Drag to draw a line, then drag the line or its nodes to bend it. Enter or double-click finishes.'),
}

# versiones cortas para la barra de opciones (la barra de estado muestra el texto completo)
TOOL_BAR_HINTS = {
    "clone": tr('Ctrl+click: set source'),
    "polygon": tr('Click to add points; Enter finishes'),
    "curve": tr('Drag, then bend; Enter finishes'),
}


class ToolOptionsBar(QToolBar):
    def __init__(self, options, parent=None):
        super().__init__(tr('Tool options'), parent)
        self.options = options
        self.setMovable(False)
        self.widgets = {}
        self._busy = False

        TOOL_HINT_WIDGET = QLabel()
        TOOL_HINT_WIDGET.setStyleSheet("color: palette(link); font-style: italic;")
        self.hint = TOOL_HINT_WIDGET

        def add(key, label, widget):
            lab = QLabel(" " + label + " ")
            a1, a2 = self.addWidget(lab), self.addWidget(widget)
            self.widgets[key] = (a1, a2, widget)
            return widget

        self.size = SliderSpin(1, 1000, " px")
        self.hardness = SliderSpin(0, 100, " %")
        self.opacity = SliderSpin(0, 100, " %")
        self.tolerance = SliderSpin(0, 100, " %")
        self.radius = QSpinBox(); self.radius.setRange(0, 500); self.radius.setSuffix(" px"); fit_spin(self.radius)
        self.aa = QCheckBox(tr('Antialiasing'))
        self.contiguous = QCheckBox(tr('Contiguous'))
        self.sample = QCheckBox(tr('Sample image'))
        self.shape = QComboBox()
        for k, label in zip(SHAPE_KINDS, (tr('Line'), tr('Rectangle'), tr('Rounded rect.'), tr('Ellipse'))):
            self.shape.addItem(label, k)
        self.shape_mode = QComboBox()
        for k, label in (("outline", tr('Outline')), ("fill", tr('Fill')), ("both", tr('Outline and fill'))):
            self._icon_item(self.shape_mode, "shape_mode", k, label)
        self.fill_style = QComboBox()
        for k, label in zip(HATCH_STYLES, (tr('Solid color'), tr('Horizontal hatch'), tr('Vertical hatch'),
                                           tr('Diagonal hatch \\'), tr('Diagonal hatch /'), tr('Cross hatch'),
                                           tr('Diagonal cross hatch'), tr('Dots'), tr('Small checkerboard'),
                                           tr('Large checkerboard'))):
            self._icon_item(self.fill_style, "fill_style", k, label)
        self.line_style = QComboBox()
        for k, label in zip(LINE_STYLES, (tr('Solid line'), tr('Dashed'), tr('Dotted'), tr('Dash-dot'), tr('Dash-dot-dot'))):
            self._icon_item(self.line_style, "line_style", k, label)
        self.blend = QComboBox()
        self._icon_item(self.blend, "blend", "normal", tr('Normal blending'))
        self._icon_item(self.blend, "blend", "overwrite", tr('Overwrite'))
        self.gradient = QComboBox()
        for k, label in zip(GRADIENT_KINDS, (tr('Linear'), tr('Reflected'), tr('Diamond'), "Radial", tr('Conical'))):
            self.gradient.addItem(label, k)
        self.select_mode = QComboBox()
        for k, label in (("replace", tr('Replace')), ("add", tr('Add (union)')), ("subtract", tr('Subtract')),
                         ("intersect", tr('Intersect')), ("xor", tr('Exclusive (XOR)'))):
            self.select_mode.addItem(label, k)
        add("select_mode", tr('Mode:'), self.select_mode)
        add("size", tr('Brush width:'), self.size)
        add("hardness", tr('Hardness:'), self.hardness)
        add("opacity", tr('Opacity:'), self.opacity)
        add("shape", tr('Shape:'), self.shape)
        add("shape_mode", tr('Style:'), self.shape_mode)
        add("fill_style", tr('Fill:'), self.fill_style)
        add("line_style", tr('Line style:'), self.line_style)
        add("blend", tr('Blending:'), self.blend)
        add("radius", tr('Corners:'), self.radius)
        add("gradient", tr('Type:'), self.gradient)
        add("tolerance", tr('Tolerance:'), self.tolerance)
        for key, w in (("aa", self.aa), ("contiguous", self.contiguous), ("sample", self.sample)):
            act = self.addWidget(w)
            self.widgets[key] = (act, act, w)
        add("hint", "", self.hint)          # al final: es largo y no debe empujar los demás controles

        for w, sig in ((self.size, self.size.valueChanged), (self.hardness, self.hardness.valueChanged),
                       (self.opacity, self.opacity.valueChanged), (self.tolerance, self.tolerance.valueChanged),
                       (self.radius, self.radius.valueChanged), (self.aa, self.aa.toggled),
                       (self.contiguous, self.contiguous.toggled), (self.sample, self.sample.toggled),
                       (self.shape, self.shape.currentIndexChanged), (self.shape_mode, self.shape_mode.currentIndexChanged),
                       (self.gradient, self.gradient.currentIndexChanged),
                       (self.fill_style, self.fill_style.currentIndexChanged),
                       (self.line_style, self.line_style.currentIndexChanged),
                       (self.blend, self.blend.currentIndexChanged),
                       (self.select_mode, self.select_mode.currentIndexChanged)):
            sig.connect(self._push)
        self.load()
        self.show_for("brush")

    @staticmethod
    def _icon_item(combo, group, value, tip):
        """Elemento gráfico (solo icono; el texto va como ayuda emergente), como en Paint.NET."""
        combo.setIconSize(QSize(46, 20))
        combo.addItem(option_icon(group, value), "", value)
        combo.setItemData(combo.count() - 1, tip, Qt.ToolTipRole)
        combo.setToolTip(tip)

    def load(self):
        o = self.options
        self._busy = True
        self.size.setValue(int(o.size)); self.hardness.setValue(round(o.hardness * 100))
        self.opacity.setValue(round(o.opacity * 100)); self.tolerance.setValue(round(o.tolerance))
        self.radius.setValue(int(o.corner_radius)); self.aa.setChecked(o.antialias)
        self.contiguous.setChecked(o.contiguous); self.sample.setChecked(o.sample_image)
        self.shape.setCurrentIndex(self.shape.findData(o.shape))
        self.shape_mode.setCurrentIndex(self.shape_mode.findData(o.shape_mode))
        self.gradient.setCurrentIndex(self.gradient.findData(o.gradient))
        self.fill_style.setCurrentIndex(self.fill_style.findData(o.fill_style))
        self.line_style.setCurrentIndex(self.line_style.findData(o.line_style))
        self.blend.setCurrentIndex(self.blend.findData(o.blend))
        self.select_mode.setCurrentIndex(self.select_mode.findData(o.select_mode))
        self._busy = False

    def _push(self, *_):
        if self._busy:
            return
        o = self.options
        o.size, o.hardness = float(self.size.value()), self.hardness.value() / 100.0
        o.opacity, o.tolerance = self.opacity.value() / 100.0, float(self.tolerance.value())
        o.corner_radius, o.antialias = float(self.radius.value()), self.aa.isChecked()
        o.contiguous, o.sample_image = self.contiguous.isChecked(), self.sample.isChecked()
        o.shape, o.shape_mode = self.shape.currentData(), self.shape_mode.currentData()
        o.gradient, o.select_mode = self.gradient.currentData(), self.select_mode.currentData()
        o.fill_style, o.line_style = self.fill_style.currentData(), self.line_style.currentData()
        o.blend = self.blend.currentData()

    def show_for(self, tool_key):
        wanted = TOOL_OPTIONS.get(tool_key, set())
        self.hint.setText(TOOL_BAR_HINTS.get(tool_key, ""))
        for key, (a1, a2, _) in self.widgets.items():
            a1.setVisible(key in wanted)
            a2.setVisible(key in wanted)
