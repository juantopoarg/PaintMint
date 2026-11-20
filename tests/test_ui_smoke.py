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


def test_toolbox_is_single_column_icon_strip_with_paintnet_tools(win):
    from paintmint.ui.main_window import TOOLBOX_LAYOUT
    assert all(isinstance(k, str) for k in TOOLBOX_LAYOUT)   # una sola columna
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
def test_toolbox_buttons_share_one_column(win):
    buttons = win.toolbox_dock.widget().findChildren(QtWidgets.QToolButton)
    xs = {b.mapTo(win.toolbox_dock.widget(), b.rect().topLeft()).x() for b in buttons}
    assert len(xs) == 1


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
    cp.set_target("secondary")
    cp.wheel.changed.emit(0, 100)                          # rojo puro
    assert win.options.secondary[:3] == (255, 0, 0) and win.options.primary[:3] == (0, 255, 0)
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
    assert set(win.lang_actions) == {"en", "es"}
    win.act_set_language("es")
    assert config.get("language") == "es" and shown
    win.act_set_language("en")
    assert config.get("language") == "en"
