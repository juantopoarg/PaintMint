import numpy as np
import pytest

from paintmint.core.document import Document
from paintmint.core.errors import ImageTooLargeError, InvalidOperationError, PaintMintError
from paintmint.core.session import EditSession
from conftest import px


def test_new_document_has_white_background_layer(session):
    assert len(session.doc.layers) == 1
    assert px(session, 5, 5) == (255, 255, 255, 255)


def test_add_select_reorder_delete_layers(session):
    a = session.add_layer("A")
    b = session.add_layer("B")
    assert [l.name for l in session.doc.layers] == ["Background", "A", "B"]
    assert session.doc.active_layer is b
    assert session.move_layer(-1)                       # B baja
    assert [l.name for l in session.doc.layers] == ["Background", "B", "A"]
    assert not session.move_layer(-5)                   # fuera de rango: sin efecto
    session.doc.set_active(0)
    assert session.active_layer.name == "Background"
    session.delete_layer(1)
    assert [l.name for l in session.doc.layers] == ["Background", "A"]
    session.undo()
    assert [l.name for l in session.doc.layers] == ["Background", "B", "A"]


def test_cannot_delete_last_layer(session):
    with pytest.raises(InvalidOperationError):
        session.delete_layer()


def test_visibility_opacity_blend_are_undoable(session):
    layer = session.add_layer("X")
    session.set_layer_props(layer, visible=False)
    session.set_layer_props(layer, opacity=0.25)
    session.set_layer_props(layer, blend_mode="multiply")
    assert (layer.visible, layer.opacity, layer.blend_mode) == (False, 0.25, "multiply")
    session.undo(); session.undo(); session.undo()
    assert (layer.visible, layer.opacity, layer.blend_mode) == (True, 1.0, "normal")


def test_invalid_blend_mode_rejected_without_changing_layer(session):
    with pytest.raises(PaintMintError):
        session.set_layer_props(session.active_layer, blend_mode="inexistente")
    assert session.active_layer.blend_mode == "normal"


def test_opacity_changes_merge_into_single_history_entry(session):
    layer = session.add_layer("X")
    n = len(session.history.labels)
    for v in (0.9, 0.7, 0.5, 0.3):
        session.set_layer_props(layer, merge=True, opacity=v)
    assert len(session.history.labels) == n + 1
    session.undo()
    assert layer.opacity == 1.0


def test_duplicate_layer_is_independent_copy(session):
    session.active_layer.pixels[0, 0] = (1, 2, 3, 255)
    dup = session.duplicate_layer()
    dup.pixels[0, 0] = (9, 9, 9, 255)
    assert tuple(session.doc.layers[0].pixels[0, 0]) == (1, 2, 3, 255)
    assert dup.id != session.doc.layers[0].id


def test_composite_respects_visibility_and_opacity():
    s = EditSession(Document(4, 4, (0, 0, 0, 255)))
    top = s.add_layer("rojo", fill=(255, 0, 0, 255))
    top.opacity = 0.5
    out = s.doc.composite()
    assert tuple(out[0, 0]) == (128, 0, 0, 255)
    top.visible = False
    assert tuple(s.doc.composite()[0, 0]) == (0, 0, 0, 255)


def test_merge_down_applies_top_over_lower():
    s = EditSession(Document(4, 4, (0, 0, 255, 255)))
    s.add_layer("rojo", fill=(255, 0, 0, 255)).opacity = 0.5
    s.merge_down()
    assert len(s.doc.layers) == 1
    assert tuple(s.doc.layers[0].pixels[0, 0]) == (128, 0, 128, 255)
    s.undo()
    assert len(s.doc.layers) == 2
    assert tuple(s.doc.layers[0].pixels[0, 0]) == (0, 0, 255, 255)


def test_merge_down_on_bottom_layer_errors(session):
    with pytest.raises(InvalidOperationError):
        session.merge_down()


def test_flatten_drops_hidden_layers_and_is_undoable():
    s = EditSession(Document(4, 4, (10, 10, 10, 255)))
    s.add_layer("a", fill=(200, 0, 0, 255))
    hidden = s.add_layer("b", fill=(0, 200, 0, 255))
    hidden.visible = False
    s.flatten()
    assert len(s.doc.layers) == 1
    assert tuple(s.doc.layers[0].pixels[0, 0]) == (200, 0, 0, 255)
    s.undo()
    assert len(s.doc.layers) == 3 and not s.doc.layers[2].visible


def test_image_too_large_is_rejected():
    with pytest.raises(ImageTooLargeError):
        Document(40000, 10)
    with pytest.raises(ImageTooLargeError):
        Document(0, 10)


def test_resize_canvas_anchor_and_undo(session):
    session.doc.layers[0].pixels[0, 0] = (1, 2, 3, 255)
    session.resize_canvas(120, 100, "br")
    assert (session.doc.width, session.doc.height) == (120, 100)
    assert tuple(session.doc.layers[0].pixels[20, 20]) == (1, 2, 3, 255)  # esquina original desplazada
    assert session.doc.layers[0].pixels[0, 0, 3] == 0                   # zona nueva transparente
    session.undo()
    assert (session.doc.width, session.doc.height) == (100, 80)


def test_resize_image_flip_rotate_crop(session):
    session.resize_image(50, 40)
    assert session.doc.layers[0].pixels.shape == (40, 50, 4)
    session.rotate_image(90)
    assert (session.doc.width, session.doc.height) == (40, 50)
    session.flip_image(True)
    session.select_rect(5, 5, 15, 25)
    session.crop_to_selection()
    assert (session.doc.width, session.doc.height) == (10, 20)
    assert not session.doc.selection.active
    for _ in range(5):  # recorte, selección, voltear, rotar, redimensionar
        session.undo()
    assert (session.doc.width, session.doc.height) == (100, 80)


def test_crop_without_selection_errors(session):
    with pytest.raises(InvalidOperationError):
        session.crop_to_selection()


def test_flip_layer_only_affects_active_layer(session):
    session.active_layer.pixels[0, 0] = (5, 5, 5, 255)
    session.flip_layer(True)
    assert tuple(session.active_layer.pixels[0, -1]) == (5, 5, 5, 255)
    session.undo()
    assert tuple(session.active_layer.pixels[0, 0]) == (5, 5, 5, 255)
