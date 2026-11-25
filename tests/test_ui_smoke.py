"""Pruebas de humo de la interfaz (Qt en modo offscreen)."""

import numpy as np
import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QTest

from paintmint.core import io as pmio
from paintmint.core.document import Document
from paintmint.effects import REGISTRY


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app, monkeypatch, tmp_path):
    from paintmint.ui import main_window
    from PyQt5.QtCore import QSettings
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path))
    errors = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, exc, title="": errors.append(exc))
    w = main_window.MainWindow()
    w.settings.clear()
    w.errors = errors
    w.show()
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).session.mark_saved()
    w.close()


def screen_pos(view, x, y):
    ox, oy = view._origin()
    return QPoint(int(ox + x * view.zoom), int(oy + y * view.zoom))


def drag(view, pts, button=Qt.LeftButton):
    vp = view.viewport()
    QTest.mousePress(vp, button, Qt.NoModifier, screen_pos(view, *pts[0]))
    for p in pts[1:]:
        QTest.mouseMove(vp, screen_pos(view, *p))
        # QTest.mouseMove no entrega botones; se invoca el evento a mano
        from PyQt5.QtGui import QMouseEvent
        from PyQt5.QtCore import QEvent, QPointF
        ev = QMouseEvent(QEvent.MouseMove, QPointF(screen_pos(view, *p)), button, button, Qt.NoModifier)
        view.mouseMoveEvent(ev)
    QTest.mouseRelease(vp, button, Qt.NoModifier, screen_pos(view, *pts[-1]))


def test_window_starts_without_documents_and_actions_disabled(win):
    assert win.tabs.count() == 0
    assert not win.a_save.isEnabled() and not win.a_undo.isEnabled()


def test_new_document_enables_actions(win):
    win.add_document(Document(200, 150))
    assert win.a_save.isEnabled() and win.tabs.count() == 1
    assert win.layers_panel.list.count() == 1


def test_brush_stroke_with_mouse_then_undo_redo_via_actions(win):
    view = win.add_document(Document(200, 150))
    view.set_zoom(1.0)
    win.options.size, win.options.primary = 8, (255, 0, 0, 255)
    win.select_tool("brush")
    drag(view, [(20, 20), (100, 20), (100, 80)])
    layer = view.session.active_layer
    assert tuple(layer.pixels[20, 60]) == (255, 0, 0, 255)
    assert win.a_undo.isEnabled() and "Brush" in win.a_undo.toolTip()
    assert "*" in win.tabs.tabText(0)
    win.a_undo.trigger()
    assert tuple(layer.pixels[20, 60]) == (255, 255, 255, 255)
    win.a_redo.trigger()
    assert tuple(layer.pixels[20, 60]) == (255, 0, 0, 255)
    assert win.history_panel.list.count() == 2        # original + 1 acción


def test_selection_tool_and_status(win):
    view = win.add_document(Document(200, 150))
    view.set_zoom(1.0)
    win.select_tool("select_rect")
    drag(view, [(10, 10), (60, 50)])
    assert view.session.doc.selection.bbox() == (10, 10, 60, 50)
    assert "50 × 40" in win.sel_label.text()
    view.grab()                                           # pinta hormigas sin fallar


def test_layers_panel_buttons_and_visibility_checkbox(win):
    win.add_document(Document(50, 50))
    win.layers_panel.buttons["add"].click()
    win.layers_panel.buttons["add"].click()
    assert win.layers_panel.list.count() == 3
    item = win.layers_panel.list.item(0)
    item.setCheckState(Qt.Unchecked)
    assert win.current_session().doc.layers[-1].visible is False
    win.layers_panel.opacity.setValue(40)
    assert win.current_session().active_layer.opacity == pytest.approx(0.4)
    win.layers_panel.buttons["del"].click()
    assert win.layers_panel.list.count() == 2


def test_painting_on_hidden_layer_reports_in_status_bar_without_dialog(win):
    view = win.add_document(Document(100, 100))
    view.session.active_layer.visible = False
    win.select_tool("brush")
    drag(view, [(10, 10), (20, 20)])
    assert win.errors == []
    assert "hidden" in win.statusBar().currentMessage()


def test_opening_corrupt_file_shows_error_and_app_survives(win, tmp_path):
    bad = tmp_path / "roto.png"
    bad.write_bytes(b"basura")
    win.open_path(str(bad))
    assert len(win.errors) == 1 and "damaged" in str(win.errors[0])
    assert win.tabs.count() == 0
    win.add_document(Document(10, 10))
    assert win.tabs.count() == 1


def test_open_save_roundtrip_through_window(win, tmp_path):
    d = Document(30, 20, (5, 6, 7, 255))
    path = str(tmp_path / "a.png")
    pmio.save_document(d, path)
    win.open_path(path)
    win.open_path(path)                                   # reabrir solo activa la pestaña
    assert win.tabs.count() == 1
    view = win.current_view()
    view.session.fill_selection((1, 1, 1, 255))
    assert view.session.modified
    out = str(tmp_path / "b.png")
    assert win._save_to(view, out)
    assert not view.session.modified and view.session.doc.path == out
    assert tuple(pmio.open_document(out).layers[0].pixels[0, 0]) == (1, 1, 1, 255)


def test_save_failure_is_reported_not_raised(win, tmp_path):
    view = win.add_document(Document(10, 10))
    assert win._save_to(view, str(tmp_path / "sin_extension_valida.xyz")) is False
    assert win._save_to(view, str(tmp_path / "no" / "existe" / "a.png")) is False
    assert len(win.errors) == 2
    assert view.session.history.labels == []              # el documento sigue intacto


def test_effect_dialog_preview_accept_and_cancel(win, app):
    from paintmint.ui.dialogs import EffectDialog
    view = win.add_document(Document(40, 40, (100, 100, 100, 255)))
    s = view.session
    dlg = EffectDialog(REGISTRY["brightness_contrast"], s)
    assert "brightness" in dlg.controls
    spin = dlg.findChildren(QtWidgets.QSpinBox)[0]
    spin.setValue(50)
    dlg._preview()
    assert s.active_layer.pixels[0, 0, 0] > 100               # vista previa en vivo
    assert s.history.labels == []                              # aún sin historial
    dlg.reject()
    assert (s.active_layer.pixels[..., 0] == 100).all()
    dlg = EffectDialog(REGISTRY["brightness_contrast"], s)
    dlg.findChildren(QtWidgets.QSpinBox)[0].setValue(50)
    dlg.accept()
    assert s.active_layer.pixels[0, 0, 0] > 100 and s.history.labels == ["Brightness and contrast"]


def test_every_effect_dialog_builds_and_previews(win):
    from paintmint.ui.dialogs import EffectDialog
    view = win.add_document(Document(30, 30))
    for eff in REGISTRY.values():
        if eff.params:
            dlg = EffectDialog(eff, view.session)
            assert dlg.status.text() == "", eff.key
            dlg.reject()


def test_parameterless_effect_runs_directly(win):
    view = win.add_document(Document(10, 10, (0, 0, 0, 255)))
    win.act_effect(REGISTRY["invert"])
    assert tuple(view.session.active_layer.pixels[0, 0]) == (255, 255, 255, 255)


def test_zoom_actions_and_fit(win):
    view = win.add_document(Document(400, 300))
    view.set_zoom(2.0)
    assert view.zoom == 2.0
    win.a_zoom_out.trigger(); assert view.zoom < 2.0
    win.a_actual.trigger(); assert view.zoom == 1.0
    win.a_fit.trigger(); assert view.zoom > 0
    view.set_zoom(1000)
    assert view.zoom == 64.0


def test_text_tool_syncs_panel(win):
    view = win.add_document(Document(200, 100))
    view.set_zoom(1.0)
    win.select_tool("text")
    drag(view, [(20, 20), (20, 20)])
    assert view.session.active_layer.is_text
    assert win.text_panel.edit.toPlainText() == "Text"
    win.text_panel.edit.setPlainText("Cambiado")
    assert view.session.active_layer.text.text == "Cambiado"


def test_tabs_rebind_docks_to_current_document(win):
    a = win.add_document(Document(20, 20))
    a.session.add_layer(); a.session.add_layer()
    win.add_document(Document(20, 20))
    assert win.layers_panel.list.count() == 1
    win.tabs.setCurrentIndex(0)
    assert win.layers_panel.list.count() == 3


def test_unexpected_exception_in_action_does_not_crash(win):
    win._safe(lambda: 1 / 0)
    assert isinstance(win.errors[-1], ZeroDivisionError)


def test_clipboard_copy_paste(win, app):
    view = win.add_document(Document(60, 60, (9, 9, 9, 255)))
    view.session.select_rect(10, 10, 30, 30)
    win.a_copy.trigger()
    win.a_paste.trigger()
    assert len(view.session.doc.layers) == 2
    assert tuple(view.session.active_layer.pixels[5, 5]) == (9, 9, 9, 255)


# -- Esc, cursores, caja de herramientas, icono ---------------------------------------
def press_key(view, key):
    QTest.keyClick(view, key)


def test_escape_deselects_like_ctrl_d(win):
    view = win.add_document(Document(100, 100))
    s = view.session
    s.select_rect(10, 10, 50, 50)
    assert s.doc.selection.active
    win.a_escape.trigger()
    assert not s.doc.selection.active
    s.undo()                                      # igual que Ctrl+D: queda en el historial
    assert s.doc.selection.active
    win.a_escape.trigger()
    win.a_escape.trigger()                        # sin selección: no hace nada ni falla
    assert win.errors == []


def test_escape_key_press_on_canvas_deselects_and_cancels_gesture_first(win):
    view = win.add_document(Document(100, 100))
    view.set_zoom(1.0)
    view.session.select_rect(10, 10, 50, 50)
    press_key(view, Qt.Key_Escape)
    assert not view.session.doc.selection.active
    # con un gesto en curso, Esc cancela el gesto y conserva la selección
    view.session.select_rect(10, 10, 50, 50)
    win.select_tool("brush")
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, screen_pos(view, 70, 70))
    assert view._active_tool is not None
    press_key(view, Qt.Key_Escape)
    assert view._active_tool is None and view.session.doc.selection.active


def test_escape_shortcut_is_bound_to_escape_key(win):
    assert win.a_escape.shortcut().toString() == "Esc"


def test_cursor_changes_with_selected_tool(win):
    view = win.add_document(Document(50, 50))
    seen = {}
    for key in win.tool_actions:
        win.select_tool(key)
        c = view.viewport().cursor()
        seen[key] = (c.shape(), c.pixmap().cacheKey() if c.shape() == Qt.BitmapCursor else 0)
    assert seen["text"][0] == Qt.IBeamCursor
    assert seen["move"][0] == Qt.SizeAllCursor and seen["move_selection"][0] == Qt.SizeAllCursor
    assert seen["pan"][0] == Qt.OpenHandCursor
    assert seen["brush"][0] == Qt.CrossCursor
    for key in ("fill", "gradient", "picker", "zoom", "select_wand", "select_rect", "line", "ellipse"):
        assert seen[key][0] == Qt.BitmapCursor, key           # cursor propio con insignia de la herramienta
    custom = [seen[k][1] for k in ("fill", "gradient", "picker", "zoom", "select_wand", "select_rect", "line", "ellipse")]
    assert len(set(custom)) == len(custom)                    # cada herramienta, un cursor distinto


def test_space_bar_switches_to_hand_cursor_and_restores_tool_cursor(win):
    view = win.add_document(Document(50, 50))
    win.select_tool("fill")
    tool_cursor_key = view.viewport().cursor().pixmap().cacheKey()
    QTest.keyPress(view, Qt.Key_Space)
    assert view.viewport().cursor().shape() == Qt.OpenHandCursor
    QTest.keyRelease(view, Qt.Key_Space)
    assert view.viewport().cursor().pixmap().cacheKey() == tool_cursor_key


def test_toolbox_is_icon_only_grid_with_paintnet_tools(win):
    from paintmint.ui.main_window import TOOLBOX_LAYOUT
    assert all(isinstance(k, str) for k in TOOLBOX_LAYOUT)   # lista plana en orden de lectura
    keys = [k for k in TOOLBOX_LAYOUT]
    assert len(keys) == len(set(keys)) and set(keys) <= set(win.tool_actions)
    buttons = win.toolbox_dock.widget().findChildren(QtWidgets.QToolButton)
    assert len(buttons) == len(keys)
    assert all(b.toolButtonStyle() == Qt.ToolButtonIconOnly for b in buttons)


def test_layer_via_selection_actions_in_menu(win):
    view = win.add_document(Document(60, 60, (9, 9, 9, 255)))
    assert win.a_via_copy.isEnabled()
    win.a_via_copy.trigger()                                   # sin selección: aviso de error, no cierra
    assert len(win.errors) == 1
    view.session.select_rect(10, 10, 30, 30)
    win.a_via_copy.trigger()
    assert len(view.session.doc.layers) == 2
    win.a_via_cut.trigger()
    assert len(view.session.doc.layers) == 3
    assert win.a_via_copy.shortcut().toString() == "Ctrl+J"


def test_app_icon_exists_in_all_sizes(win):
    import os
    from paintmint.ui.main_window import ICON_DIR, app_icon
    for size in (16, 32, 48, 64, 128, 256):
        assert os.path.exists(os.path.join(ICON_DIR, f"paintmint-{size}.png"))
    assert os.path.exists(os.path.join(ICON_DIR, "paintmint.svg"))
    assert not app_icon().isNull() and not win.windowIcon().isNull()
    assert 256 in [s.width() for s in app_icon().availableSizes()]


# ---------------------------------------------------------------- v1.2: colores, sliders, idioma, about
def test_toolbox_has_two_columns_so_all_tools_fit(win):
    from paintmint.ui.main_window import TOOLBOX_ROWS
    box = win.toolbox_dock.widget().widget()
    buttons = box.findChildren(QtWidgets.QToolButton)
    xs = {b.mapTo(box, b.rect().topLeft()).x() for b in buttons}
    assert len(xs) == 2 and all(len(r) == 2 for r in TOOLBOX_ROWS) and len(buttons) == 2 * len(TOOLBOX_ROWS)


def test_colors_panel_sliders_hex_and_alpha_update_options(win):
    cp = win.colors_panel
    cp.sliders["r"].valueChanged.emit(200)
    assert win.options.primary[0] == 200
    cp.spins["g"].setValue(100)
    assert win.options.primary[:3] == (200, 100, 0)
    cp.hex.setText("12ab34")
    cp.hex.editingFinished.emit()
    assert win.options.primary[:3] == (0x12, 0xAB, 0x34)
    cp.spins["a"].setValue(128)
    assert win.options.primary[3] == 128
    assert cp.spins["r"].value() == 0x12 and cp.hex.text() == "12AB34"


def test_colors_panel_hsv_wheel_target_and_palette(win):
    cp = win.colors_panel
    cp.spins["h"].setValue(120); cp.spins["s"].setValue(100); cp.spins["v"].setValue(100)
    assert win.options.primary[:3] == (0, 255, 0)
    cp.wheel.picked.emit(0, 100, "right")                  # clic derecho en la rueda: rojo puro al secundario
    assert win.options.secondary[:3] == (255, 0, 0) and win.options.primary[:3] == (0, 255, 0)
    cp.set_target("secondary")
    cp.palette.picked.emit("left", (1, 2, 3, 4))           # clic izquierdo -> destino (secundario)
    assert win.options.secondary == (1, 2, 3, 4)
    cp.palette.picked.emit("right", (9, 8, 7, 255))        # derecho -> el otro (primario)
    assert win.options.primary == (9, 8, 7, 255)
    cp.swap.click()
    assert win.options.primary == (1, 2, 3, 4)
    cp.reset.click()
    assert win.options.primary == (0, 0, 0, 255) and win.options.secondary == (255, 255, 255, 255)


def test_gray_keeps_hue_when_value_goes_to_zero(win):
    cp = win.colors_panel
    cp.spins["h"].setValue(200); cp.spins["s"].setValue(80); cp.spins["v"].setValue(0)
    assert win.options.primary[:3] == (0, 0, 0) and cp.spins["h"].value() == 200 and cp.spins["s"].value() == 80


def test_palette_is_large_and_has_semitransparent_rows():
    from paintmint.ui.colorwidgets import build_palette
    pal = build_palette()
    flat = [c for row in pal for c in row]
    assert len(flat) >= 120 and len({c for c in flat}) == len(flat)
    assert any(c[3] < 255 for c in flat) and all(len(r) == 14 for r in pal)


def test_custom_palette_colors_persist(win):
    from paintmint import config
    win.options.primary = (10, 20, 30, 255)
    win.colors_panel.add_btn.click()
    assert [10, 20, 30, 255] in config.get("custom_colors")


def test_tool_options_use_sliders_and_stay_in_sync(win):
    bar = win.options_bar
    for name in ("opacity", "tolerance", "hardness", "size"):
        w = getattr(bar, name)
        assert w.slider is not None and w.spin is not None
    win.select_tool("select_wand")
    assert bar.widgets["tolerance"][1].isVisible()           # la varita muestra el control de tolerancia
    bar.tolerance.slider.setValue(37)
    assert bar.tolerance.spin.value() == 37 and win.options.tolerance == 37.0
    bar.tolerance.spin.setValue(12)
    assert bar.tolerance.slider.value() == 12 and win.options.tolerance == 12.0
    bar.opacity.slider.setValue(40)
    assert abs(win.options.opacity - 0.40) < 1e-9


def test_about_dialog_has_repo_and_donation(win):
    from paintmint.ui.about import AboutDialog, DONATE_URL, DONATE_TEXT, REPO_URL
    d = AboutDialog(win)
    assert REPO_URL in d.repo_label.text()
    assert DONATE_TEXT.strip() in d.donation_label.text()
    assert DONATE_URL == "https://www.paypal.com/donate/?hosted_button_id=Q9VZZG5U83NC8"
    assert d.donate_button.toolTip() == DONATE_URL


def test_language_menu_saves_choice(win, monkeypatch):
    from paintmint import config
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: shown.append(a))
    assert set(win.lang_actions) == {"en", "es", "fr", "pt", "zh", "hi", "de", "ru"}
    for code in ("es", "fr", "pt", "zh", "hi", "de", "ru"):
        win.act_set_language(code)
        assert config.get("language") == code
    assert shown
    win.act_set_language("en")
    assert config.get("language") == "en"


# ---------------------------------------------------------------- v1.3: ventana, paneles, lienzo inicial, pegado
def test_window_has_min_max_buttons_and_can_maximize(win):
    from PyQt5.QtCore import Qt as _Qt
    assert win.windowFlags() & _Qt.WindowMaximizeButtonHint and win.windowFlags() & _Qt.WindowMinimizeButtonHint
    # la altura mínima debe caber en una pantalla modesta; si no, el gestor de ventanas oculta «Maximizar»
    assert win.minimumSizeHint().height() <= 700
    assert win.maximumSize().width() >= 16777215
    win.a_maximize.setChecked(True)
    win.a_maximize.setChecked(False)


def test_right_column_panels_collapse_and_expand(win):
    from paintmint.ui.docks import is_collapsed, set_collapsed
    for dock in (win.colors_dock, win.history_dock, win.layers_dock):
        assert not is_collapsed(dock)
        full = dock.maximumHeight()
        set_collapsed(dock, True)
        assert is_collapsed(dock) and dock.widget().maximumHeight() == 0 and dock.maximumHeight() < 60
        set_collapsed(dock, False)
        assert not is_collapsed(dock) and dock.maximumHeight() >= full


def test_text_panel_is_floating_and_only_visible_with_text_tool(win):
    win.show()
    QtWidgets.QApplication.processEvents()
    d = win.text_dock
    assert d.isFloating() and not d.isVisible() and d not in win._panel_docks()
    win.select_tool("text")
    assert d.isFloating() and d.isVisible()
    win.select_tool("brush")
    assert not d.isVisible()
    win.select_tool("text")
    assert d.isVisible()


def test_title_bar_buttons_float_and_close(win):
    bar = win.layers_dock.titleBarWidget()
    bar.collapse_btn.click()
    from paintmint.ui.docks import is_collapsed
    assert is_collapsed(win.layers_dock)
    bar.float_btn.click()
    assert win.layers_dock.isFloating()
    bar.float_btn.click()
    assert not win.layers_dock.isFloating()


def test_paintnet_floating_layout_and_reset(win):
    win.a_float_panels.setChecked(True)
    assert all(d.isFloating() for d in win._panel_docks())
    win.a_float_panels.setChecked(False)
    assert not any(d.isFloating() for d in win._panel_docks())
    win.a_float_panels.setChecked(True)
    win.a_reset_panels.trigger()
    assert not any(d.isFloating() for d in win._panel_docks()) and not win.a_float_panels.isChecked()


def test_startup_opens_blank_canvas_with_last_size(app, monkeypatch, tmp_path):
    from paintmint import config
    from paintmint.ui import main_window
    from PyQt5.QtCore import QSettings
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path))
    config.set_value("last_canvas", [321, 123])
    w = main_window.MainWindow(open_blank=True)
    try:
        assert w.tabs.count() == 1
        doc = w.current_session().doc
        assert (doc.width, doc.height) == (321, 123) and not w.current_session().history.modified
        assert doc.layers[0].pixels[0, 0].tolist() == [255, 255, 255, 255]
    finally:
        w.close()
    w2 = main_window.MainWindow(files=[], open_blank=False)
    assert w2.tabs.count() == 0
    w2.close()


def test_last_canvas_size_is_remembered_and_validated(win, tmp_path):
    from paintmint import config
    win.add_document(Document(50, 40))
    win._remember_canvas(77, 66)
    assert config.get("last_canvas") == [77, 66]
    config.set_value("last_canvas", [0, "x"])           # configuración dañada -> valor por defecto
    assert config.get("last_canvas") == [800, 600]


def test_new_image_dialog_locks_aspect_ratio():
    from paintmint.ui.dialogs import NewImageDialog
    d = NewImageDialog(None, (800, 600))
    assert d.keep_ratio.isChecked()
    d.w.setValue(1600)
    assert d.h.value() == 1200
    d.h.setValue(300)
    assert d.w.value() == 400
    d.keep_ratio.setChecked(False)
    d.w.setValue(1000)
    assert d.h.value() == 300                            # sin bloqueo se mueven por separado
    d.keep_ratio.setChecked(True)                        # se bloquea la proporción actual (1000:300)
    d.w.setValue(500)
    assert d.h.value() == 150
    d.preset.setCurrentIndex(3)                          # 1280×720 y la proporción pasa a 16:9
    assert (d.w.value(), d.h.value()) == (1280, 720)
    d.w.setValue(640)
    assert d.h.value() == 360


def _clipboard_image(w, h, color=(10, 200, 30, 255)):
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtWidgets import QApplication
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(*color))
    QApplication.clipboard().setImage(img)


def test_paste_larger_than_canvas_expand(win, monkeypatch):
    view = win.add_document(Document(100, 80))
    s = view.session
    _clipboard_image(150, 60)
    asked = []
    monkeypatch.setattr(win, "_ask_paste_oversize", lambda *a: asked.append(a) or "expand")
    win.act_paste()
    assert asked == [(150, 60, 100, 80)]
    assert (s.doc.width, s.doc.height) == (150, 80)
    assert s.active_layer.pixels[0, 149, 1] == 200 and s.active_layer.pixels[59, 0, 1] == 200
    assert not win.errors


def test_paste_larger_than_canvas_keep_size_crops(win, monkeypatch):
    view = win.add_document(Document(100, 80))
    s = view.session
    _clipboard_image(150, 120)
    monkeypatch.setattr(win, "_ask_paste_oversize", lambda *a: "keep")
    win.act_paste()
    assert (s.doc.width, s.doc.height) == (100, 80)
    assert s.active_layer.pixels[79, 99, 1] == 200


def test_paste_larger_than_canvas_cancel_changes_nothing(win, monkeypatch):
    view = win.add_document(Document(100, 80))
    s = view.session
    n = len(s.doc.layers)
    pos = s.history.position
    _clipboard_image(150, 120)
    monkeypatch.setattr(win, "_ask_paste_oversize", lambda *a: None)
    win.act_paste()
    assert (s.doc.width, s.doc.height) == (100, 80) and len(s.doc.layers) == n and s.history.position == pos


def test_paste_that_fits_does_not_ask(win, monkeypatch):
    view = win.add_document(Document(100, 80))
    _clipboard_image(50, 40)
    monkeypatch.setattr(win, "_ask_paste_oversize", lambda *a: pytest.fail("no debe preguntar"))
    win.act_paste()
    assert len(view.session.doc.layers) == 2


def test_stale_saved_layout_with_tabbed_docks_is_discarded(app, tmp_path):
    from paintmint.ui import main_window
    from PyQt5.QtCore import QSettings
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path))
    old = main_window.MainWindow()
    old.setDockOptions(old.dockOptions() | QtWidgets.QMainWindow.AllowTabbedDocks)
    old.tabifyDockWidget(old.history_dock, old.layers_dock)            # disposición antigua: pestañas
    assert old.tabifiedDockWidgets(old.history_dock)
    old.settings.setValue("state", old.saveState())                  # sin «layout_version», como las versiones previas
    old.settings.remove("layout_version")
    old.settings.sync()
    new = main_window.MainWindow()
    try:
        assert new.tabifiedDockWidgets(new.history_dock) == [] and new.tabifiedDockWidgets(new.layers_dock) == []
        assert not new.dockOptions() & QtWidgets.QMainWindow.AllowTabbedDocks
    finally:
        new.close()
        old.close()


def test_right_column_can_be_resized_and_shows_all_content(win):
    win.resize(1280, 800)
    win.show()
    QtWidgets.QApplication.processEvents()
    assert win.colors_dock.minimumSizeHint().width() <= 260           # no impone un ancho enorme
    docks = [win.colors_dock, win.history_dock, win.layers_dock]
    for wide in (420, 240, 420):
        win.resizeDocks(docks, [wide] * 3, Qt.Horizontal)
        QtWidgets.QApplication.processEvents()
        assert all(abs(d.width() - wide) <= 12 for d in docks)
    # si la columna es estrecha, el contenido se desplaza en vez de recortarse
    sa = win.colors_dock.widget()
    assert sa.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded


def test_wheel_left_sets_primary_right_sets_secondary_even_from_black(win):
    from PyQt5.QtCore import QPoint
    cp = win.colors_panel
    assert win.options.primary == (0, 0, 0, 255)            # valor 0: antes la rueda no tenía efecto
    cp.wheel.picked.emit(120, 100, "left")
    assert win.options.primary[:3] == (0, 255, 0)
    cp.wheel.picked.emit(240, 100, "right")
    assert win.options.secondary[:3] == (0, 0, 255) and win.options.primary[:3] == (0, 255, 0)
    # con el ratón real: clic izquierdo y derecho sobre la rueda
    from PyQt5.QtTest import QTest
    win.options.primary = (0, 0, 0, 255); win.options.notify()
    cp.set_target("primary")
    wheel = cp.wheel
    wheel.resize(150, 150)
    pt = QPoint(wheel.width() // 2 + 40, wheel.height() // 2)            # hacia la derecha del centro: tono 0 (rojo)
    QTest.mouseClick(wheel, Qt.LeftButton, Qt.NoModifier, pt)
    assert win.options.primary[0] > 150 and win.options.primary[3] == 255
    QTest.mouseClick(wheel, Qt.RightButton, Qt.NoModifier, QPoint(wheel.width() // 2 - 40, wheel.height() // 2))
    assert win.options.secondary != (255, 255, 255, 255) and cp.target == "secondary"


def test_new_tools_are_registered_with_icons_and_options(app):
    from paintmint.tools import create_tools
    from paintmint.ui.icons import tool_cursor, tool_icon
    from paintmint.ui.main_window import TOOLBOX_LAYOUT, TOOL_KEYS
    from paintmint.ui.panels import TOOL_OPTIONS
    for key in ("curve", "freeform", "polygon", "clone", "recolor"):
        assert key in create_tools() and key in TOOLBOX_LAYOUT and key in TOOL_KEYS and key in TOOL_OPTIONS
        assert not tool_icon(key).isNull() and tool_cursor(key) is not None
    assert len(set(TOOL_KEYS.values())) == len(TOOL_KEYS)                    # sin atajos repetidos


def test_polygon_in_canvas_enter_confirms_esc_cancels_and_tool_switch_confirms(win):
    from PyQt5.QtTest import QTest
    view = win.add_document(Document(120, 90))
    win.select_tool("polygon")
    win.options.shape_mode = "fill"
    win.options.primary = (255, 0, 0, 255)
    vp = view.viewport()

    def click(ix, iy):
        pt = view._to_screen(ix, iy).toPoint()
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pt)

    for p in ((20, 20), (90, 25), (50, 70)):
        click(*p)
    assert win.tools["polygon"].pending
    QTest.keyClick(view, Qt.Key_Escape)                       # Esc descarta la edición pendiente
    assert not win.tools["polygon"].pending and view.session.history.position == 0
    for p in ((20, 20), (90, 25), (50, 70)):
        click(*p)
    QTest.keyClick(view, Qt.Key_Return)                       # Intro confirma
    assert view.session.history.position == 1 and not win.tools["polygon"].pending
    for p in ((20, 20), (90, 25), (50, 70)):
        click(*p)
    win.select_tool("brush")                                  # cambiar de herramienta confirma
    assert view.session.history.position == 2
    assert view.session.doc.layers[0].pixels[40, 55, 0] == 255
    assert not win.errors


def test_options_bar_shows_hatch_line_style_and_blend_for_shapes(win):
    win.select_tool("rectangle")
    bar = win.options_bar
    for key in ("size", "shape_mode", "fill_style", "line_style", "aa", "blend"):
        assert bar.widgets[key][1].isVisible(), key
    bar.fill_style.setCurrentIndex(bar.fill_style.findData("cross"))
    bar.line_style.setCurrentIndex(bar.line_style.findData("dot"))
    bar.blend.setCurrentIndex(bar.blend.findData("overwrite"))
    assert (win.options.fill_style, win.options.line_style, win.options.blend) == ("cross", "dot", "overwrite")
    win.select_tool("brush")
    assert not bar.widgets["fill_style"][1].isVisible()


def test_colors_window_defaults_to_simplified_version(win):
    from paintmint import config
    cp = win.colors_panel
    assert not cp.more_btn.isChecked() and cp.details.isHidden()
    cp.more_btn.setChecked(True)                      # lo que el usuario elige se recuerda
    assert config.get("colors_more") is True and not cp.details.isHidden()
    cp.more_btn.setChecked(False)
    assert config.get("colors_more") is False


def test_number_boxes_fit_their_content(win):
    bar = win.options_bar
    for w in (bar.size, bar.opacity, bar.tolerance, bar.hardness):
        assert w.spin.width() <= 110       # antes ocupaban todo el ancho disponible
    assert bar.size.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Fixed


def test_option_lists_are_graphical_not_text(win):
    bar = win.options_bar
    for combo in (bar.shape_mode, bar.fill_style, bar.line_style, bar.blend):
        assert combo.count() >= 2
        for i in range(combo.count()):
            assert combo.itemText(i) == "" and not combo.itemIcon(i).isNull()
            assert combo.itemData(i, Qt.ToolTipRole)              # el nombre queda como ayuda emergente
    # los iconos son distintos entre sí
    keys = [bar.fill_style.itemIcon(i).pixmap(46, 20).toImage().bits().asstring(46 * 20 * 4)
            for i in range(bar.fill_style.count())]
    assert len(set(keys)) == len(keys)


def test_clone_tool_explains_ctrl_in_bar_and_status(win):
    win.resize(1280, 800)
    win.show()
    win.select_tool("clone")
    QtWidgets.QApplication.processEvents()
    assert win.options_bar.hint.isVisible() and "Ctrl" in win.options_bar.hint.text()
    assert "Ctrl" in win.statusBar().currentMessage()
    win.select_tool("brush")
    QtWidgets.QApplication.processEvents()
    assert not win.options_bar.hint.isVisible()


def test_effects_menu_has_the_nine_submenus(win):
    from paintmint.effects import GROUPS
    from tests.test_effects_catalog import PDN_EFFECTS, PDN_ADJUSTMENTS
    if True:
        assert list(win.effect_menus) == list(GROUPS)
        for g, menu in win.effect_menus.items():
            assert len(menu.actions()) == len(PDN_EFFECTS[g])
        adj = [a for a in win.menuBar().actions() if a.menu() and "djust" in a.text()][0].menu()
        assert len(adj.actions()) == len(PDN_ADJUSTMENTS)


# ---------------------------------------------------------------- v1.3.8: tiradores de la selección
def test_pure_handle_logic():
    from paintmint.tools.select import hit_handle, resized_box
    box = (10, 10, 60, 50)
    assert hit_handle(box, 11, 9, 4) == "nw" and hit_handle(box, 60, 50, 4) == "se"
    assert hit_handle(box, 35, 10, 4) == "n" and hit_handle(box, 35, 30, 4) is None
    assert resized_box(box, "se", 80, 70) == (10, 10, 80, 70)
    assert resized_box(box, "w", 0, 99) == (0, 10, 60, 50)
    assert resized_box(box, "se", 0, 0) == (0, 0, 10, 10)             # cruzar el opuesto voltea la caja
    x0, y0, x1, y1 = resized_box(box, "se", 110, 60, keep_aspect=True)  # Mayús conserva la proporción 5:4
    assert abs((x1 - x0) / (y1 - y0) - 50 / 40) < 1e-6 and (x0, y0) == (10, 10)


def test_dragging_a_corner_resizes_a_rectangular_selection(win):
    view = win.add_document(Document(200, 150))
    view.set_zoom(1.0)
    win.select_tool("select_rect")
    drag(view, [(10, 10), (60, 50)])
    drag(view, [(60, 50), (90, 80)])                       # esquina inferior derecha
    sel = view.session.doc.selection
    assert sel.bbox() == (10, 10, 90, 80) and (sel.mask[10:80, 10:90] == 255).all()
    drag(view, [(10, 10), (0, 0)])                         # esquina superior izquierda hacia afuera
    assert sel.bbox() == (0, 0, 90, 80)
    view.session.undo()
    assert view.session.doc.selection.bbox() == (10, 10, 90, 80)


def test_dragging_a_side_handle_and_cursor_feedback(win):
    view = win.add_document(Document(200, 150))
    view.set_zoom(1.0)
    win.select_tool("select_rect")
    drag(view, [(10, 10), (60, 50)])
    vp = view.viewport()
    QTest.mouseMove(vp, screen_pos(view, 60, 30))
    assert vp.cursor().shape() == Qt.SizeHorCursor
    QTest.mouseMove(vp, screen_pos(view, 60, 50))
    assert vp.cursor().shape() == Qt.SizeFDiagCursor
    QTest.mouseMove(vp, screen_pos(view, 30, 30))
    assert vp.cursor().shape() != Qt.SizeFDiagCursor
    drag(view, [(60, 30), (100, 30)])
    assert view.session.doc.selection.bbox() == (10, 10, 100, 50)
    view.grab()                                            # pinta tiradores sin fallar


def test_resizing_an_ellipse_selection_keeps_its_shape_and_esc_cancels(win):
    view = win.add_document(Document(200, 150))
    view.set_zoom(1.0)
    win.select_tool("select_ellipse")
    drag(view, [(20, 20), (80, 60)])
    sel = view.session.doc.selection
    ox, oy = sel.bbox()[:2]                                # el borde suave de la elipse puede ocupar 1 px más
    drag(view, [(80, 60), (140, 100)])
    assert sel.bbox() == (ox, oy, 140, 100)
    assert sel.mask[60, 80] > 127 and sel.mask[21, 21] < 128        # centro dentro, esquina fuera
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, screen_pos(view, 140, 100))
    view.handle_escape()
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, screen_pos(view, 150, 110))
    assert view.session.doc.selection.bbox() == (ox, oy, 140, 100)


def test_handles_do_not_appear_for_other_tools(win):
    view = win.add_document(Document(200, 150))
    view.set_zoom(1.0)
    win.select_tool("select_rect")
    drag(view, [(10, 10), (60, 50)])
    win.select_tool("brush")
    assert view._handle_at(screen_pos(view, 60, 50)) is None
