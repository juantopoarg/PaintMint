"""Ventana principal: pestañas de documentos, barras, paneles y todas las acciones de menú."""

from __future__ import annotations

from ..i18n import tr

import os
from typing import Optional

from PyQt5.QtCore import QTimer, QSettings, QSize, Qt
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QDockWidget, QFileDialog, QGridLayout, QInputDialog,
                             QFrame, QLabel, QScrollArea, QVBoxLayout, QMainWindow, QMessageBox, QTabWidget, QToolBar, QToolButton, QWidget)

from .. import APP_NAME, __version__, config, i18n, updater
from ..core import io as pmio
from ..core.document import Document
from ..core.errors import InvalidOperationError, PaintMintError
from ..core.session import EditSession
from ..effects import REGISTRY
from ..tools import ToolOptions, create_tools
from .canvas import CanvasView
from .dialogs import CanvasSizeDialog, EffectDialog, LayerPropertiesDialog, NewImageDialog, ResizeDialog
from .icons import tool_icon
from .about import AboutDialog
from .docks import QWIDGETSIZE_MAX,  is_collapsed, set_collapsed, setup_dock, wrap_scroll
from .update_ui import UpdateController
from .panels import ColorsPanel, HistoryPanel, LayersPanel, TextPanel, ToolOptionsBar
from .qtutil import guarded, qimage_from_rgba, rgba_from_qimage, show_error

SHORTCUTS = {"levels": "Ctrl+L", "curves": "Ctrl+Shift+M", "hue_saturation": "Ctrl+Shift+U",
             "invert": "Ctrl+Shift+I", "grayscale": "Ctrl+Shift+G", "sepia": "Ctrl+Shift+E"}
TOOL_KEYS = {"select_rect": "S", "select_ellipse": "Shift+S", "select_lasso": "L", "select_wand": "W",
             "move": "M", "move_selection": "Shift+M", "brush": "B", "pencil": "P", "eraser": "E", "fill": "F",
             "gradient": "G", "line": "I", "rectangle": "O", "rounded_rectangle": "Shift+O", "ellipse": "J",
             "text": "T", "picker": "K", "zoom": "Z", "pan": "H"}
# filas de dos botones; None = hueco
TOOLBOX_LAYOUT = [   # una sola columna, en el orden de Paint.NET
    "select_rect", "move", "zoom", "move_selection", "select_lasso", "pan", "select_ellipse",
    "select_wand", "fill", "gradient", "brush", "eraser", "pencil", "picker", "text", "line",
    "rectangle", "rounded_rectangle", "ellipse",
]
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
MAX_RECENT = 10


def app_icon() -> QIcon:
    """Icono de la aplicación (brocha con hoja de menta) en varios tamaños."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        path = os.path.join(ICON_DIR, f"paintmint-{size}.png")
        if os.path.exists(path):
            icon.addFile(path)
    return icon


LAYOUT_VERSION = "3"   # súbase al cambiar la disposición de los paneles (invalida el estado guardado)


class MainWindow(QMainWindow):
    def __init__(self, files=(), open_blank=False):
        super().__init__()
        self.settings = QSettings("PaintMint", "PaintMint")
        self.options = ToolOptions()
        self.updates = UpdateController(self)
        self.tools = create_tools()
        self.tool_key = "brush"
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        # los paneles se apilan en columnas; no se permiten pestañas (Texto e Historial no deben quedar juntos)
        self.setDockOptions(QMainWindow.AnimatedDocks)
        # botones de minimizar y maximizar siempre disponibles
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._tab_close_requested)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        self._build_docks()
        self._build_actions()
        self._build_toolbox()
        self._build_menus()
        self._build_toolbars()
        self._build_statusbar()
        self.options.listeners.append(self._options_changed)
        self.select_tool("brush")
        self._update_actions()
        for path in files:
            self.open_path(path)
        if not files:
            self.settings_restore()
        if open_blank and not files:
            self.open_blank_canvas()
        QTimer.singleShot(4000, self._auto_check_updates)   # en segundo plano, sin bloquear el arranque

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        self.addDockWidget(area, d)
        setup_dock(d)
        return d

    def _build_docks(self):
        self.colors_panel = ColorsPanel(self.options)
        self.layers_panel = LayersPanel()
        self.history_panel = HistoryPanel()
        self.text_panel = TextPanel(self.options)
        # una columna a la derecha con los cuatro paneles; cada uno se puede colapsar, flotar o cerrar
        self.colors_dock = self._dock(tr('Colors'), wrap_scroll(self.colors_panel), Qt.RightDockWidgetArea, "colors")
        self.history_dock = self._dock(tr('History'), self.history_panel, Qt.RightDockWidgetArea, "history")
        self.layers_dock = self._dock(tr('Layers'), self.layers_panel, Qt.RightDockWidgetArea, "layers")
        self.text_dock = self._dock(tr('Text'), wrap_scroll(self.text_panel), Qt.RightDockWidgetArea, "text")
        set_collapsed(self.text_dock, True)          # se despliega al elegir la herramienta Texto
        self.resizeDocks([self.colors_dock, self.history_dock, self.layers_dock], [360, 110, 220], Qt.Vertical)
        self.resizeDocks([self.colors_dock], [300], Qt.Horizontal)       # ancho inicial de la columna derecha
        lp = self.layers_panel.buttons
        lp["add"].clicked.connect(lambda: self.act_add_layer())
        lp["dup"].clicked.connect(lambda: self.act_duplicate_layer())
        lp["del"].clicked.connect(lambda: self.act_delete_layer())
        lp["up"].clicked.connect(lambda: self.act_move_layer(1))
        lp["down"].clicked.connect(lambda: self.act_move_layer(-1))
        lp["merge"].clicked.connect(lambda: self.act_merge_down())
        lp["props"].clicked.connect(lambda: self.act_layer_properties())
        self.layers_panel.list.itemDoubleClicked.connect(lambda _: self.act_layer_properties())

    def _act(self, text, slot, shortcut=None, icon=None, checkable=False, tip=None) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(QIcon.fromTheme(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        if tip:
            a.setStatusTip(tip)
        # los slots se envuelven para que ninguna excepción cierre la aplicación
        a.triggered.connect(lambda checked=False, f=slot: self._safe(f))
        return a

    def _safe(self, fn):
        try:
            fn()
        except (Exception, MemoryError) as exc:  # noqa: BLE001
            show_error(self, exc)

    def _build_actions(self):
        A = self._act
        self.a_new = A(tr('&New…'), self.act_new, "Ctrl+N", "document-new")
        self.a_open = A(tr('&Open…'), self.act_open, "Ctrl+O", "document-open")
        self.a_save = A(tr('&Save'), self.act_save, "Ctrl+S", "document-save")
        self.a_save_as = A(tr('Save &as…'), self.act_save_as, "Ctrl+Shift+S", "document-save-as")
        self.a_close = A(tr('&Close'), lambda: self._tab_close_requested(self.tabs.currentIndex()), "Ctrl+W")
        self.a_quit = A(tr('&Quit'), self.close, "Ctrl+Q", "application-exit")
        self.a_undo = A(tr('&Undo'), self.act_undo, "Ctrl+Z", "edit-undo")
        self.a_redo = A(tr('&Redo'), self.act_redo, "Ctrl+Y", "edit-redo")
        self.a_redo2 = A(tr('Redo'), self.act_redo, "Ctrl+Shift+Z")
        self.addAction(self.a_redo2)
        self.a_cut = A(tr('Cu&t'), self.act_cut, "Ctrl+X", "edit-cut")
        self.a_copy = A(tr('&Copy'), self.act_copy, "Ctrl+C", "edit-copy")
        self.a_copy_merged = A(tr('Copy merged'), self.act_copy_merged, "Ctrl+Shift+C")
        self.a_paste = A(tr('&Paste into new layer'), self.act_paste, "Ctrl+V", "edit-paste")
        self.a_paste_img = A(tr('Paste into new image'), self.act_paste_new_image, "Ctrl+Alt+V")
        self.a_delete = A(tr('&Delete selection'), lambda: self.session_do(lambda s: s.delete_selection()), "Delete")
        self.a_fill = A(tr('&Fill selection'), self.act_fill_selection, "Backspace")
        self.a_all = A(tr('Select &all'), lambda: self.session_do(lambda s: s.select_all()), "Ctrl+A")
        self.a_none = A(tr('&Deselect'), lambda: self.session_do(lambda s: s.deselect()), "Ctrl+D")
        self.a_invert = A(tr('&Invert selection'), lambda: self.session_do(lambda s: s.invert_selection()), "Ctrl+I")
        self.a_zoom_in = A(tr('Zoom in'), lambda: self.view_do(lambda v: v.zoom_in()), "Ctrl++")
        self.a_zoom_in2 = A(tr('Zoom in'), lambda: self.view_do(lambda v: v.zoom_in()), "Ctrl+=")
        self.addAction(self.a_zoom_in2)
        self.a_zoom_out = A(tr('Zoom out'), lambda: self.view_do(lambda v: v.zoom_out()), "Ctrl+-")
        self.a_actual = A(tr('Actual size (100%)'), lambda: self.view_do(lambda v: v.actual_size()), "Ctrl+0")
        self.a_fit = A(tr('Fit to window'), lambda: self.view_do(lambda v: v.fit()), "Ctrl+B")
        self.a_crop = A(tr('Crop to selection'), lambda: self.session_do(lambda s: s.crop_to_selection()), "Ctrl+Shift+X")
        self.a_resize = A(tr('&Resize…'), self.act_resize, "Ctrl+R")
        self.a_canvas = A(tr('Canvas si&ze…'), self.act_canvas_size, "Ctrl+Shift+R")
        self.a_flip_h = A(tr('Flip image horizontally'), lambda: self.session_do(lambda s: s.flip_image(True)))
        self.a_flip_v = A(tr('Flip image vertically'), lambda: self.session_do(lambda s: s.flip_image(False)))
        self.a_rot_cw = A(tr('Rotate 90° clockwise'), lambda: self.session_do(lambda s: s.rotate_image(90)))
        self.a_rot_ccw = A(tr('Rotate 90° counterclockwise'), lambda: self.session_do(lambda s: s.rotate_image(270)))
        self.a_rot_180 = A(tr('Rotate 180°'), lambda: self.session_do(lambda s: s.rotate_image(180)))
        self.a_flatten = A(tr('&Flatten'), lambda: self.session_do(lambda s: s.flatten()), "Ctrl+Shift+F")
        self.a_l_add = A(tr('&New layer'), self.act_add_layer, "Ctrl+Shift+N")
        self.a_l_del = A(tr('&Delete layer'), self.act_delete_layer)
        self.a_l_dup = A(tr('D&uplicate layer'), self.act_duplicate_layer, "Ctrl+Shift+D")
        self.a_l_merge = A(tr('Merge layer &down'), self.act_merge_down, "Ctrl+M")
        self.a_l_up = A(tr('Move layer up'), lambda: self.act_move_layer(1))
        self.a_l_down = A(tr('Move layer down'), lambda: self.act_move_layer(-1))
        self.a_l_fh = A(tr('Flip layer horizontally'), lambda: self.session_do(lambda s: s.flip_layer(True)))
        self.a_l_fv = A(tr('Flip layer vertically'), lambda: self.session_do(lambda s: s.flip_layer(False)))
        self.a_l_raster = A(tr('Rasterize text'), lambda: self.session_do(lambda s: s.rasterize_layer()))
        self.a_l_props = A(tr('Layer &properties…'), self.act_layer_properties, "F4")
        self.a_via_copy = A(tr('New layer via copy'), lambda: self.session_do(lambda s: s.layer_via_selection(False)),
                            "Ctrl+J", tip=tr('Creates a new layer with the selected pixels'))
        self.a_via_cut = A(tr('New layer via cut'), lambda: self.session_do(lambda s: s.layer_via_selection(True)),
                           "Ctrl+Shift+J", tip=tr('Moves the selected pixels to a new layer'))
        self.a_escape = A(tr('Clear selection'), self.act_escape, "Escape")
        self.addAction(self.a_escape)
        self.a_about = A(tr('&About PaintMint'), self.act_about)
        self.a_swap = A(tr('Swap colors'), self.options.swap_colors, "X")
        self.addAction(self.a_swap)

        self.effect_actions = {}
        for key, eff in REGISTRY.items():
            label = eff.label + ("…" if eff.params else "")
            act = A(label, lambda e=eff: self.act_effect(e), SHORTCUTS.get(key))
            self.effect_actions[key] = act

        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        labels = {k: t.label for k, t in self.tools.items()}
        labels.update({"zoom": "Zoom", "pan": tr('Pan')})
        for key in TOOLBOX_LAYOUT:
            a = QAction(tool_icon(key), labels[key], self)
            a.setCheckable(True)
            a.setToolTip(f"{labels[key]} ({TOOL_KEYS[key]})")
            a.setShortcut(QKeySequence(TOOL_KEYS[key]))
            a.triggered.connect(lambda checked=False, k=key: self.select_tool(k))
            self.tool_group.addAction(a)
            self.tool_actions[key] = a

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(tr('&File'))
        m.addActions([self.a_new, self.a_open])
        self.recent_menu = m.addMenu(tr('&Recent files'))
        m.addSeparator()
        m.addActions([self.a_save, self.a_save_as, self.a_close])
        m.addSeparator()
        m.addAction(self.a_quit)
        m = mb.addMenu(tr('&Edit'))
        m.addActions([self.a_undo, self.a_redo])
        m.addSeparator()
        m.addActions([self.a_cut, self.a_copy, self.a_copy_merged, self.a_paste, self.a_paste_img])
        m.addSeparator()
        m.addActions([self.a_delete, self.a_fill])
        m.addSeparator()
        m.addActions([self.a_all, self.a_none, self.a_invert])
        m = mb.addMenu(tr('&View'))
        m.addActions([self.a_zoom_in, self.a_zoom_out, self.a_actual, self.a_fit])
        m.addSeparator()
        for d in (self.toolbox_dock, self.colors_dock, self.text_dock, self.layers_dock, self.history_dock):
            m.addAction(d.toggleViewAction())
        m.addSeparator()
        self.a_float_panels = QAction(tr('&Floating panels (Paint.NET layout)'), self, checkable=True)
        self.a_float_panels.toggled.connect(lambda on: self._safe(lambda: self.set_floating_panels(on)))
        self.a_reset_panels = QAction(tr('&Reset panel layout'), self, triggered=lambda: self._safe(self.reset_panels))
        self.a_maximize = QAction(tr('&Maximize window'), self, checkable=True, shortcut=QKeySequence("F11"))
        self.a_maximize.toggled.connect(lambda on: self.showMaximized() if on else self.showNormal())
        m.addActions([self.a_float_panels, self.a_reset_panels, self.a_maximize])
        m = mb.addMenu(tr('&Image'))
        m.addActions([self.a_crop, self.a_resize, self.a_canvas])
        m.addSeparator()
        m.addActions([self.a_flip_h, self.a_flip_v, self.a_rot_cw, self.a_rot_ccw, self.a_rot_180])
        m.addSeparator()
        m.addAction(self.a_flatten)
        m = mb.addMenu(tr('&Layers'))
        m.addActions([self.a_l_add, self.a_l_dup, self.a_l_del, self.a_l_merge])
        m.addSeparator()
        m.addActions([self.a_via_copy, self.a_via_cut])
        m.addSeparator()
        m.addActions([self.a_l_up, self.a_l_down, self.a_l_fh, self.a_l_fv, self.a_l_raster])
        m.addSeparator()
        m.addAction(self.a_l_props)
        madj = mb.addMenu(tr('&Adjustments'))
        mfx = mb.addMenu(tr('E&ffects'))
        for key, eff in REGISTRY.items():
            (madj if eff.category == "adjust" else mfx).addAction(self.effect_actions[key])
        m = mb.addMenu(tr('&Help'))
        lang_menu = m.addMenu(tr('&Language'))
        self.lang_actions = {}
        group = QActionGroup(self)
        for code, name in i18n.LANGUAGES.items():
            act = QAction(name, self, checkable=True)
            act.setChecked(code == i18n.current_language())
            act.triggered.connect(lambda checked=False, c=code: self.act_set_language(c))
            group.addAction(act)
            lang_menu.addAction(act)
            self.lang_actions[code] = act
        self.a_check_updates = QAction(tr('Check for &updates…'), self, triggered=self.act_check_updates)
        self.a_auto_updates = QAction(tr('Check for updates at &startup'), self, checkable=True)
        self.a_auto_updates.setChecked(bool(config.get("check_updates")))
        self.a_auto_updates.toggled.connect(self.act_toggle_auto_updates)
        m.addActions([self.a_check_updates, self.a_auto_updates])
        m.addSeparator()
        m.addAction(self.a_about)
        self._refresh_recent_menu()

    def _build_toolbars(self):
        tb = QToolBar(tr('File'), self)
        tb.setObjectName("tb_file")
        tb.addActions([self.a_new, self.a_open, self.a_save])
        tb.addSeparator()
        tb.addActions([self.a_undo, self.a_redo])
        tb.addSeparator()
        tb.addActions([self.a_cut, self.a_copy, self.a_paste])
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.options_bar = ToolOptionsBar(self.options, self)
        self.options_bar.setObjectName("tb_options")
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.options_bar)

    def _build_toolbox(self):
        """Caja de herramientas de una sola columna, solo con iconos (estilo Paint.NET)."""
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(4, 4, 4, 4)
        col.setSpacing(2)
        for key in TOOLBOX_LAYOUT:
            btn = QToolButton()
            btn.setDefaultAction(self.tool_actions[key])
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setAutoRaise(True)
            btn.setIconSize(QSize(26, 26))
            btn.setFixedSize(36, 36)
            col.addWidget(btn)
        col.addStretch(1)
        scroll = QScrollArea()          # por si la ventana es más baja que la columna de herramientas
        scroll.setWidget(box)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(60)
        dock = self._dock(tr('Tools'), scroll, Qt.LeftDockWidgetArea, "toolbox")
        self.toolbox_dock = dock

    def _build_statusbar(self):
        sb = self.statusBar()
        self.pos_label = QLabel("")
        self.sel_label = QLabel("")
        self.size_label = QLabel("")
        self.zoom_label = QLabel("")
        for w in (self.pos_label, self.sel_label, self.size_label, self.zoom_label):
            w.setMinimumWidth(110)
            sb.addPermanentWidget(w)

    # ------------------------------------------------------------------
    # Documentos y pestañas
    # ------------------------------------------------------------------
    def current_view(self) -> Optional[CanvasView]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, CanvasView) else None

    def current_session(self) -> Optional[EditSession]:
        v = self.current_view()
        return v.session if v else None

    def session_do(self, fn):
        s = self.current_session()
        if s is None:
            return None
        return fn(s)

    def view_do(self, fn):
        v = self.current_view()
        if v is not None:
            fn(v)

    def add_document(self, doc: Document, title: Optional[str] = None) -> CanvasView:
        session = EditSession(doc)
        view = CanvasView(session, self.tools, self.options)
        view.set_tool(self.tool_key)
        view.cursor_moved.connect(self._on_cursor)
        view.zoom_changed.connect(lambda z: self._update_status())
        view.message.connect(lambda m: self.statusBar().showMessage(m, 6000))
        view.error.connect(lambda exc: show_error(self, exc))
        view.tool_finished.connect(self._tool_finished)
        view.selection_changed.connect(self._update_status)
        session.history.listeners.append(self._update_actions)
        session.history.listeners.append(self._update_titles)
        name = title or (os.path.basename(doc.path) if doc.path else tr('Untitled'))
        idx = self.tabs.addTab(view, name)
        self.tabs.setCurrentIndex(idx)
        view.fit() if doc.width * doc.height > 1_000_000 else None
        self._update_titles()
        return view

    def _tab_changed(self, index):
        v = self.current_view()
        s = v.session if v else None
        self.layers_panel.bind(s)
        self.history_panel.bind(s)
        self.text_panel.bind(s)
        self._update_actions()
        self._update_status()
        self._update_titles()

    def _tool_finished(self):
        self._update_status()
        s = self.current_session()
        if self.tool_key == "text" and s is not None and s.active_layer.is_text:
            self.text_panel.sync()
            self.text_dock.raise_()
            self.text_panel.focus_editor()

    def _options_changed(self):
        pass  # los paneles se sincronizan solos mediante sus propios oyentes

    def _update_titles(self):
        for i in range(self.tabs.count()):
            v = self.tabs.widget(i)
            if isinstance(v, CanvasView):
                name = os.path.basename(v.session.doc.path) if v.session.doc.path else tr('Untitled')
                self.tabs.setTabText(i, name + (" *" if v.session.modified else ""))
                self.tabs.setTabToolTip(i, v.session.doc.path or name)
        v = self.current_view()
        if v is None:
            self.setWindowTitle(APP_NAME)
        else:
            name = os.path.basename(v.session.doc.path) if v.session.doc.path else tr('Untitled')
            self.setWindowTitle(f"{name}{' *' if v.session.modified else ''} — {APP_NAME}")

    def _update_actions(self):
        s = self.current_session()
        has = s is not None
        self.a_undo.setEnabled(has and s.history.can_undo)
        self.a_redo.setEnabled(has and s.history.can_redo)
        self.a_undo.setStatusTip(tr('Undo: ') + (s.history.undo_label or "") if has and s.history.can_undo else "")
        self.a_redo.setStatusTip(tr('Redo: ') + (s.history.redo_label or "") if has and s.history.can_redo else "")
        self.a_undo.setToolTip(tr('Undo ') + (s.history.undo_label or "") if has and s.history.can_undo else tr('Undo'))
        self.a_redo.setToolTip(tr('Redo ') + (s.history.redo_label or "") if has and s.history.can_redo else tr('Redo'))
        for a in (self.a_save, self.a_save_as, self.a_close, self.a_cut, self.a_copy, self.a_copy_merged,
                  self.a_paste, self.a_delete, self.a_fill, self.a_all, self.a_none, self.a_invert,
                  self.a_zoom_in, self.a_zoom_out, self.a_actual, self.a_fit, self.a_crop, self.a_resize,
                  self.a_canvas, self.a_flip_h, self.a_flip_v, self.a_rot_cw, self.a_rot_ccw, self.a_rot_180,
                  self.a_flatten, self.a_l_add, self.a_l_del, self.a_l_dup, self.a_l_merge, self.a_l_up,
                  self.a_l_down, self.a_l_fh, self.a_l_fv, self.a_l_raster, self.a_l_props, self.a_via_copy, self.a_via_cut,
                  *self.effect_actions.values()):
            a.setEnabled(has)

    def _on_cursor(self, x, y):
        self.pos_label.setText(f"{int(x)}, {int(y)} px")

    def _update_status(self):
        v = self.current_view()
        if v is None:
            self.size_label.setText("")
            self.zoom_label.setText("")
            self.sel_label.setText("")
            return
        d = v.session.doc
        self.size_label.setText(f"{d.width} × {d.height} px")
        self.zoom_label.setText(f"{v.zoom * 100:.0f} %")
        if d.selection.active:
            x0, y0, x1, y1 = d.selection.bbox()
            self.sel_label.setText(tr("Selection: {w} × {h}").format(w=x1 - x0, h=y1 - y0))
        else:
            self.sel_label.setText("")

    def select_tool(self, key):
        self.tool_key = key
        self.tool_actions[key].setChecked(True)
        self.options_bar.show_for(key)
        if key == "text" and is_collapsed(self.text_dock):
            set_collapsed(self.text_dock, False)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CanvasView):
                w.set_tool(key)

    # ------------------------------------------------------------------
    # Archivo
    # ------------------------------------------------------------------
    def act_new(self):
        dlg = NewImageDialog(self, tuple(config.get("last_canvas")))
        if dlg.exec_() != dlg.Accepted:
            return
        w, h, bg = dlg.values()
        fill = [(255, 255, 255, 255), (0, 0, 0, 0), self.options.primary, self.options.secondary][bg]
        self.add_document(Document(w, h, fill))
        self._remember_canvas(w, h)

    def _remember_canvas(self, w, h):
        config.set_value("last_canvas", [int(w), int(h)])

    def open_blank_canvas(self):
        """Documento en blanco con el último tamaño de lienzo usado (por defecto 800×600)."""
        w, h = config.get("last_canvas")
        try:
            self.add_document(Document(w, h))
        except (Exception, MemoryError):   # si el tamaño guardado ya no cabe, se usa el estándar
            self.add_document(Document(800, 600))

    def act_open(self):
        start = self.settings.value("last_dir", os.path.expanduser("~"))
        paths, _ = QFileDialog.getOpenFileNames(self, tr('Open image'), start, pmio.FILE_FILTERS["open"])
        for p in paths:
            self.open_path(p)

    def open_path(self, path: str):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            existing = self._find_open_tab(path)
            if existing is not None:
                self.tabs.setCurrentIndex(existing)
                QApplication.restoreOverrideCursor()
                return
            doc = pmio.open_document(path)
        except (Exception, MemoryError) as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            show_error(self, exc, tr('Could not open the file'))
            return
        QApplication.restoreOverrideCursor()
        self.add_document(doc)
        self.settings.setValue("last_dir", os.path.dirname(os.path.abspath(path)))
        self._add_recent(path)

    def _find_open_tab(self, path):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CanvasView) and w.session.doc.path:
                try:
                    if os.path.samefile(w.session.doc.path, path):
                        return i
                except OSError:
                    pass
        return None

    def act_save(self):
        v = self.current_view()
        if v is None:
            return
        if v.session.doc.path:
            self._save_to(v, v.session.doc.path)
        else:
            self.act_save_as()

    def act_save_as(self):
        v = self.current_view()
        if v is None:
            return
        start = v.session.doc.path or os.path.join(self.settings.value("last_dir", os.path.expanduser("~")), "image.png")
        filters = ";;".join(pmio.FILE_FILTERS[k] for k in ("png", "jpg", "bmp", "gif", "tiff", "ora"))
        path, chosen = QFileDialog.getSaveFileName(self, tr('Save as'), start, filters)
        if not path:
            return
        if not os.path.splitext(path)[1]:  # añadir extensión según el filtro elegido
            ext = {"PNG": ".png", "JPEG": ".jpg", "JPG": ".jpg", "BMP": ".bmp", "GIF": ".gif", "TIFF": ".tif",
                   "OpenRaster": ".ora"}
            path += next((e for k, e in ext.items() if chosen.startswith(k)), ".png")
        self._save_to(v, path)

    def _save_to(self, view: CanvasView, path: str) -> bool:
        doc = view.session.doc
        try:
            fmt = pmio.format_for_path(path)
        except PaintMintError as exc:
            show_error(self, exc, tr('Could not save'))
            return False
        if fmt != "ORA" and len(doc.layers) > 1:
            r = QMessageBox.question(
                self, tr('Save image'),
                tr("The image has {n} layers and the {fmt} format does not keep them.\nA flattened copy will be saved (the open document keeps its layers).\nUse the .ora format to keep the layers.\n\nContinue?").format(n=len(doc.layers), fmt=fmt),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r != QMessageBox.Yes:
                return False
        quality = int(self.settings.value("jpeg_quality", 92))
        if fmt == "JPEG":
            q, ok = QInputDialog.getInt(self, tr('JPEG quality'), tr('Quality (1-100):'), quality, 1, 100)
            if not ok:
                return False
            quality = q
            self.settings.setValue("jpeg_quality", q)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pmio.save_document(doc, path, quality=quality)
        except (Exception, MemoryError) as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            show_error(self, exc, tr('Could not save'))
            return False
        QApplication.restoreOverrideCursor()
        view.session.mark_saved(path)
        self._update_titles()
        self._add_recent(path)
        self.statusBar().showMessage(tr("Saved: {path}").format(path=path), 5000)
        return True

    def _tab_close_requested(self, index) -> bool:
        w = self.tabs.widget(index)
        if not isinstance(w, CanvasView):
            return True
        if w.session.modified:
            name = os.path.basename(w.session.doc.path) if w.session.doc.path else tr('Untitled')
            self.tabs.setCurrentIndex(index)
            r = QMessageBox.question(self, tr('Unsaved changes'), tr('"{name}" has unsaved changes.').format(name=name),
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                if w.session.doc.path:
                    if not self._save_to(w, w.session.doc.path):
                        return False
                else:
                    self.act_save_as()
                    if w.session.modified:
                        return False
        w.cancel_gesture()
        self.tabs.removeTab(index)
        w.deleteLater()
        return True

    def changeEvent(self, e):
        if e.type() == e.WindowStateChange and hasattr(self, "a_maximize"):
            self.a_maximize.blockSignals(True)
            self.a_maximize.setChecked(self.isMaximized())
            self.a_maximize.blockSignals(False)
        super().changeEvent(e)

    # -- disposición de los paneles -------------------------------------------------
    def _fit_to_screen(self):
        """Si la geometría guardada deja la ventana (y sus paneles) fuera de la pantalla, la ajusta."""
        scr = QApplication.desktop().availableGeometry(self)
        fg = self.frameGeometry()
        w, h = min(fg.width(), scr.width()), min(fg.height(), scr.height())
        if (w, h) != (fg.width(), fg.height()):
            self.resize(max(self.minimumSizeHint().width(), w - (fg.width() - self.width())),
                        max(self.minimumSizeHint().height(), h - (fg.height() - self.height())))
        fg = self.frameGeometry()
        x = min(max(scr.left(), fg.left()), scr.right() - fg.width() + 1)
        y = min(max(scr.top(), fg.top()), scr.bottom() - fg.height() + 1)
        self.move(x, y)

    def _panel_docks(self):
        return [self.toolbox_dock, self.colors_dock, self.history_dock, self.layers_dock, self.text_dock]

    def set_floating_panels(self, on: bool):
        """Activa la disposición de Paint.NET (paneles flotando sobre el lienzo) o los acopla de nuevo."""
        if not on:
            self.reset_panels(keep_flag=True)
            return
        area = self.centralWidget()
        tl = area.mapToGlobal(area.rect().topLeft())
        w, h = area.width(), area.height()
        # (dock, ancho, alto, esquina)
        spec = [(self.toolbox_dock, 76, min(h - 16, 560), "tl"), (self.history_dock, 220, 180, "tr"),
                (self.colors_dock, 260, 250, "bl"), (self.layers_dock, 240, 220, "br"),
                (self.text_dock, 260, 40, "tr2")]
        self.colors_panel.more_btn.setChecked(False)          # como Paint.NET: «Menos» al flotar
        for dock, dw, dh, corner in spec:
            dock.show()
            dock.setFloating(True)
            dock.resize(dw, dh)
            x = tl.x() + (8 if corner in ("tl", "bl") else w - dw - 8)
            y = tl.y() + (8 if corner in ("tl", "tr") else h - dh - 8 if corner in ("bl", "br") else 240)
            dock.move(x, y)

    def reset_panels(self, keep_flag=False):
        for d in self._panel_docks():
            d.setFloating(False)
            d.show()
            set_collapsed(d, d is self.text_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.toolbox_dock)
        for d in (self.colors_dock, self.history_dock, self.layers_dock, self.text_dock):
            self.addDockWidget(Qt.RightDockWidgetArea, d)
        self.colors_panel.more_btn.setChecked(True)
        if not keep_flag:
            self.a_float_panels.blockSignals(True)
            self.a_float_panels.setChecked(False)
            self.a_float_panels.blockSignals(False)

    def closeEvent(self, e):
        while self.tabs.count():
            if not self._tab_close_requested(self.tabs.count() - 1):
                e.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        self.settings.setValue("layout_version", LAYOUT_VERSION)
        self.settings.setValue("collapsed", [d.objectName() for d in self._panel_docks() if is_collapsed(d)])
        e.accept()

    def settings_restore(self):
        g, s = self.settings.value("geometry"), self.settings.value("state")
        if g is not None:
            self.restoreGeometry(g)
        self._fit_to_screen()
        # un estado guardado por una versión con otra disposición de paneles (p. ej. Texto e Historial
        # en pestañas) se descarta: se usa la disposición por defecto
        if str(self.settings.value("layout_version", "")) != LAYOUT_VERSION:
            return
        if s is not None:
            self.restoreState(s)
        collapsed = self.settings.value("collapsed")
        if collapsed is not None:
            collapsed = [collapsed] if isinstance(collapsed, str) else list(collapsed)
            for d in self._panel_docks():
                set_collapsed(d, d.objectName() in collapsed)

    # -- recientes -------------------------------------------------------
    def _recent(self):
        r = self.settings.value("recent", [])
        return [r] if isinstance(r, str) else list(r or [])

    def _add_recent(self, path):
        path = os.path.abspath(path)
        r = [p for p in self._recent() if p != path]
        self.settings.setValue("recent", ([path] + r)[:MAX_RECENT])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        recent = self._recent()
        for p in recent:
            a = QAction(os.path.basename(p), self)
            a.setStatusTip(p)
            a.triggered.connect(lambda checked=False, path=p: self.open_path(path))
            self.recent_menu.addAction(a)
        self.recent_menu.setEnabled(bool(recent))

    # -- arrastrar y soltar ------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())

    # ------------------------------------------------------------------
    # Edición
    # ------------------------------------------------------------------
    def act_undo(self):
        self.session_do(lambda s: s.undo())

    def act_redo(self):
        self.session_do(lambda s: s.redo())

    def _copy_to_clipboard(self, data):
        if data is None:
            return False
        QApplication.clipboard().setImage(qimage_from_rgba(data[0]))
        return True

    def act_copy(self):
        self.session_do(lambda s: self._copy_to_clipboard(s.copy_pixels()))

    def act_copy_merged(self):
        self.session_do(lambda s: self._copy_to_clipboard(s.copy_pixels(merged=True)))

    def act_cut(self):
        self.session_do(lambda s: self._copy_to_clipboard(s.cut_pixels()))

    def act_paste(self):
        s, v = self.current_session(), self.current_view()
        if s is None:
            return
        img = QApplication.clipboard().image()
        if img.isNull():
            self.statusBar().showMessage(tr('The clipboard does not contain an image.'), 4000)
            return
        ox, oy = v._origin()
        x = max(0, int((0 - ox) / v.zoom)) if ox < 0 else 0
        y = max(0, int((0 - oy) / v.zoom)) if oy < 0 else 0
        rgba = rgba_from_qimage(img)
        ph, pw = rgba.shape[:2]
        if pw > s.doc.width or ph > s.doc.height:
            choice = self._ask_paste_oversize(pw, ph, s.doc.width, s.doc.height)
            if choice is None:
                return                                   # cancelado: no se hace nada
            if choice == "expand":
                s.resize_canvas(max(pw, s.doc.width), max(ph, s.doc.height), "tl")
                self._remember_canvas(s.doc.width, s.doc.height)
                x = y = 0
        s.paste_pixels(rgba, (x, y))
        self.select_tool("move")

    def _ask_paste_oversize(self, pw, ph, cw, ch):
        """Como Paint.NET: «expandir el lienzo» o «mantener el tamaño». Devuelve 'expand', 'keep' o None."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(tr('Paste'))
        box.setText(tr('The image you are pasting ({pw} × {ph}) is larger than the canvas ({cw} × {ch}).\n'
                       'What would you like to do?').format(pw=pw, ph=ph, cw=cw, ch=ch))
        expand = box.addButton(tr('Expand canvas'), QMessageBox.AcceptRole)
        keep = box.addButton(tr('Keep canvas size'), QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        return "expand" if clicked is expand else "keep" if clicked is keep else None

    def act_paste_new_image(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.statusBar().showMessage(tr('The clipboard does not contain an image.'), 4000)
            return
        self.add_document(Document.from_pixels(rgba_from_qimage(img)))

    def act_escape(self):
        """Esc: cancela el gesto en curso o, si no hay ninguno, anula la selección."""
        self.view_do(lambda v: v.handle_escape())

    def act_fill_selection(self):
        self.session_do(lambda s: s.fill_selection(self.options.primary))

    # ------------------------------------------------------------------
    # Imagen, capas y efectos
    # ------------------------------------------------------------------
    def act_resize(self):
        s = self.current_session()
        if s is None:
            return
        dlg = ResizeDialog(s.doc.width, s.doc.height, self)
        if dlg.exec_() == dlg.Accepted:
            w, h, m = dlg.values()
            self._busy(lambda: s.resize_image(w, h, m))
            self._remember_canvas(s.doc.width, s.doc.height)

    def act_canvas_size(self):
        s = self.current_session()
        if s is None:
            return
        dlg = CanvasSizeDialog(s.doc.width, s.doc.height, self)
        if dlg.exec_() == dlg.Accepted:
            w, h, a = dlg.values()
            self._busy(lambda: s.resize_canvas(w, h, a))
            self._remember_canvas(s.doc.width, s.doc.height)

    def _busy(self, fn):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            fn()
        finally:
            QApplication.restoreOverrideCursor()

    def act_add_layer(self):
        self.session_do(lambda s: s.add_layer())

    def act_duplicate_layer(self):
        self.session_do(lambda s: s.duplicate_layer())

    @guarded
    def act_delete_layer(self):
        self.session_do(lambda s: s.delete_layer())

    def act_move_layer(self, delta):
        self.session_do(lambda s: s.move_layer(delta))

    def act_merge_down(self):
        self.session_do(lambda s: s.merge_down())

    def act_layer_properties(self):
        s = self.current_session()
        if s is None:
            return
        layer = s.active_layer
        dlg = LayerPropertiesDialog(layer, self)
        if dlg.exec_() == dlg.Accepted:
            s.set_layer_props(layer, **dlg.values())

    def act_effect(self, effect):
        s = self.current_session()
        if s is None:
            return
        if not s.active_layer.visible:
            raise InvalidOperationError(tr('The active layer is hidden. Make it visible to apply the effect.'))
        if not effect.params:
            self._busy(lambda: s.apply_effect(effect, {}))
            return
        EffectDialog(effect, s, self).exec_()

    def act_about(self):
        AboutDialog(self, os.path.join(ICON_DIR, "paintmint-64.png")).exec_()

    def act_check_updates(self):
        self.updates.check(manual=True)

    def act_toggle_auto_updates(self, checked):
        config.set_value("check_updates", bool(checked))

    def act_set_language(self, code):
        if code == i18n.current_language() and config.get("language") == code:
            return
        config.set_value("language", code)
        QMessageBox.information(self, tr("Language"), tr("The language will change the next time you start PaintMint."))
        for c, act in self.lang_actions.items():
            act.setChecked(c == code)

    def _auto_check_updates(self):
        if os.environ.get("PAINTMINT_NO_UPDATE_CHECK"):
            return
        if config.get("check_updates") and updater.due_for_auto_check(config.get("last_update_check")):
            self.updates.check(manual=False)
