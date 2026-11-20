import numpy as np
import pytest

from paintmint.core.errors import InvalidOperationError
from paintmint.core.layer import TextSpec
from conftest import px


def stroke(tool, ctx, pts, button="primary", mods=frozenset()):
    tool.press(ctx, *pts[0], button, mods)
    for p in pts[1:]:
        tool.move(ctx, *p, mods)
    tool.release(ctx, *pts[-1], mods)


def test_brush_paints_primary_and_is_one_undo_step(session, ctx, tools):
    ctx.options.primary = (255, 0, 0, 255)
    ctx.options.size = 6
    stroke(tools["brush"], ctx, [(10, 10), (40, 10), (40, 40)])
    assert px(session, 25, 10) == (255, 0, 0, 255)
    assert len(session.history.labels) == 1
    session.undo()
    assert px(session, 25, 10) == (255, 255, 255, 255)


def test_right_button_uses_secondary_color(session, ctx, tools):
    ctx.options.primary, ctx.options.secondary = (255, 0, 0, 255), (0, 0, 255, 255)
    stroke(tools["brush"], ctx, [(20, 20), (30, 20)], button="secondary")
    assert px(session, 25, 20)[:3] == (0, 0, 255)


def test_brush_opacity_does_not_accumulate_within_stroke(session, ctx, tools):
    ctx.options.primary, ctx.options.opacity, ctx.options.size = (0, 0, 0, 255), 0.5, 8
    stroke(tools["brush"], ctx, [(10, 10), (60, 10), (10, 10), (60, 10)])  # pasa varias veces
    assert abs(px(session, 30, 10)[0] - 128) <= 1


def test_brush_size_and_hardness(session, ctx, tools):
    ctx.options.size, ctx.options.hardness, ctx.options.primary = 20, 1.0, (0, 0, 0, 255)
    stroke(tools["brush"], ctx, [(50, 40), (50, 40)])
    assert px(session, 50, 40)[0] == 0 and px(session, 50, 33)[0] == 0
    assert px(session, 50, 25)[0] == 255                      # fuera del radio 10
    ctx.options.size = 30
    ctx.options.hardness = 0.0
    stroke(tools["brush"], ctx, [(20, 20), (20, 20)])
    edge = px(session, 20 + 12, 20)[0]
    assert 0 < edge < 255                                     # borde suave


def test_pencil_is_aliased(session, ctx, tools):
    ctx.options.size, ctx.options.primary = 1, (0, 0, 0, 255)
    stroke(tools["pencil"], ctx, [(10.3, 10.3), (30.7, 10.3)])
    vals = set(session.active_layer.pixels[10, 10:31, 0].tolist())
    assert vals == {0}
    assert set(np.unique(session.active_layer.pixels[..., 0])) == {0, 255}


def test_eraser_makes_pixels_transparent(session, ctx, tools):
    ctx.options.size, ctx.options.hardness = 10, 1.0
    stroke(tools["eraser"], ctx, [(30, 30), (60, 30)])
    assert px(session, 45, 30)[3] == 0
    assert px(session, 45, 60)[3] == 255


def test_painting_respects_selection(session, ctx, tools):
    session.select_rect(0, 0, 50, 80)
    ctx.options.size, ctx.options.primary = 10, (0, 0, 0, 255)
    stroke(tools["brush"], ctx, [(10, 40), (90, 40)])
    assert px(session, 40, 40)[0] == 0
    assert px(session, 70, 40)[0] == 255


def test_painting_on_hidden_layer_is_refused(session, ctx, tools):
    session.active_layer.visible = False
    with pytest.raises(InvalidOperationError):
        tools["brush"].press(ctx, 5, 5)
    assert session.history.labels == []


def test_fill_contiguous_vs_global_and_tolerance(session, ctx, tools):
    session.active_layer.pixels[:, 50] = (0, 0, 0, 255)           # muro vertical
    ctx.options.primary, ctx.options.tolerance = (255, 0, 0, 255), 0
    tools["fill"].press(ctx, 10, 10)
    assert px(session, 20, 20) == (255, 0, 0, 255) and px(session, 80, 20) == (255, 255, 255, 255)
    session.undo()
    ctx.options.contiguous = False
    tools["fill"].press(ctx, 10, 10)
    assert px(session, 80, 20) == (255, 0, 0, 255) and px(session, 50, 20) == (0, 0, 0, 255)


def test_fill_tolerance_includes_similar_colors(session, ctx, tools):
    session.active_layer.pixels[:40] = (250, 250, 250, 255)
    ctx.options.primary, ctx.options.tolerance = (0, 255, 0, 255), 10
    tools["fill"].press(ctx, 5, 5)
    assert px(session, 5, 5) == (0, 255, 0, 255) and px(session, 5, 60) == (0, 255, 0, 255)


def test_gradient_linear_endpoints(session, ctx, tools):
    ctx.options.primary, ctx.options.secondary = (0, 0, 0, 255), (255, 255, 255, 255)
    stroke(tools["gradient"], ctx, [(0, 40), (99, 40)])
    row = session.active_layer.pixels[40, :, 0].astype(int)
    assert row[0] < 10 and row[-1] > 245 and (np.diff(row) >= 0).all()


@pytest.mark.parametrize("kind", ["rectangle", "rounded_rectangle", "ellipse", "line"])
def test_shapes_draw_and_undo(session, ctx, tools, kind):
    ctx.options.shape, ctx.options.shape_mode, ctx.options.size = kind, "both", 3
    ctx.options.primary, ctx.options.secondary = (255, 0, 0, 255), (0, 0, 255, 255)
    stroke(tools["shape"], ctx, [(20, 20), (70, 60)])
    assert (session.active_layer.pixels != 255).any()
    session.undo()
    assert (session.active_layer.pixels == 255).all()


def test_shape_fill_and_outline_colors(session, ctx, tools):
    ctx.options.shape, ctx.options.shape_mode, ctx.options.size = "rectangle", "both", 4
    ctx.options.primary, ctx.options.secondary = (255, 0, 0, 255), (0, 0, 255, 255)
    stroke(tools["shape"], ctx, [(20, 20), (80, 60)])
    assert px(session, 50, 40) == (0, 0, 255, 255)         # relleno = secundario
    assert px(session, 20, 40)[:3] == (255, 0, 0)          # contorno = primario


def test_shift_constrains_shape_to_square(session, ctx, tools):
    ctx.options.shape, ctx.options.shape_mode = "rectangle", "fill"
    ctx.options.primary = (0, 0, 0, 255)
    stroke(tools["shape"], ctx, [(10, 10), (60, 30)], mods=frozenset({"shift"}))
    ys, xs = np.nonzero(session.active_layer.pixels[..., 0] == 0)
    assert abs((xs.max() - xs.min()) - (ys.max() - ys.min())) <= 1


def test_color_picker_sets_colors(session, ctx, tools):
    session.active_layer.pixels[5, 5] = (1, 2, 3, 255)
    notified = []
    ctx.options.listeners.append(lambda: notified.append(1))
    tools["picker"].press(ctx, 5.5, 5.5)
    assert ctx.options.primary == (1, 2, 3, 255) and notified
    tools["picker"].press(ctx, 5.5, 5.5, "secondary")
    assert ctx.options.secondary == (1, 2, 3, 255)


def test_rect_select_tool_modes_and_click_to_deselect(session, ctx, tools):
    t = tools["select_rect"]
    stroke(t, ctx, [(10, 10), (30, 30)])
    assert session.doc.selection.bbox() == (10, 10, 30, 30)
    stroke(t, ctx, [(50, 50), (60, 60)], mods=frozenset({"ctrl"}))
    assert session.doc.selection.bbox() == (10, 10, 60, 60)
    stroke(t, ctx, [(5, 5), (5, 5)])
    assert not session.doc.selection.active


def test_lasso_tool(session, ctx, tools):
    stroke(tools["select_lasso"], ctx, [(10, 10), (50, 10), (50, 50), (10, 50)])
    assert session.doc.selection.active and session.doc.selection.contains(30, 30)


def test_move_selected_pixels(session, ctx, tools):
    session.active_layer.pixels[10:20, 10:20] = (255, 0, 0, 255)
    session.select_rect(10, 10, 20, 20)
    stroke(tools["move"], ctx, [(15, 15), (25, 20), (35, 25)])
    assert session.doc.selection.bbox() == (30, 20, 40, 30)
    assert px(session, 35, 25) == (255, 0, 0, 255)
    assert px(session, 15, 15)[3] == 0                     # origen vaciado
    n = session.history.position
    session.undo()
    assert px(session, 15, 15) == (255, 0, 0, 255)
    assert session.doc.selection.bbox() == (10, 10, 20, 20)
    assert session.history.position == n - 1 and n == 2   # un único paso para píxeles + selección


def test_move_whole_layer_without_selection(session, ctx, tools):
    session.add_layer("x")
    session.active_layer.pixels[0:5, 0:5] = (0, 255, 0, 255)
    stroke(tools["move"], ctx, [(0, 0), (10, 10)])
    assert px(session, 12, 12) == (0, 255, 0, 255) and px(session, 2, 2)[3] == 0


def test_text_tool_creates_editable_layer_and_edits_are_undoable(session, ctx, tools):
    ctx.options.primary = (10, 20, 30, 255)
    tools["text"].press(ctx, 10, 10)
    tools["text"].release(ctx, 10, 10)
    layer = session.active_layer
    assert layer.is_text and layer.text.text == "Text" and layer.pixels[..., 3].any()
    spec = layer.text.copy()
    spec.text = "Hola mundo"
    spec.size = 20
    session.update_text_layer(layer, spec)
    assert layer.text.text == "Hola mundo"
    session.undo()
    assert layer.text.text == "Text"
    session.redo()
    assert layer.text.text == "Hola mundo"


def test_text_edits_coalesce_but_tool_click_breaks_coalescing(session, ctx, tools):
    layer = session.create_text_layer(TextSpec(text="a", x=5, y=5))
    n = len(session.history.labels)
    for t in ("ab", "abc", "abcd"):
        spec = layer.text.copy(); spec.text = t
        session.update_text_layer(layer, spec)
    assert len(session.history.labels) == n + 1


def test_text_tool_drag_moves_existing_text(session, ctx, tools):
    layer = session.create_text_layer(TextSpec(text="Mover", size=30, x=10, y=10))
    t = tools["text"]
    t.press(ctx, 15, 15); t.move(ctx, 35, 35); t.release(ctx, 35, 35)
    assert (layer.text.x, layer.text.y) == (30, 30)
    assert len(session.doc.layers) == 2                    # no creó otra capa


def test_painting_on_text_layer_rasterizes_it_and_undo_restores(session, ctx, tools):
    layer = session.create_text_layer(TextSpec(text="Hola", size=30, x=5, y=5))
    ctx.options.size = 4
    stroke(tools["brush"], ctx, [(60, 60), (70, 60)])
    assert layer.text is None
    session.undo()
    assert layer.text is not None and layer.text.text == "Hola"


def test_rasterize_text_layer(session):
    layer = session.create_text_layer(TextSpec(text="x", x=1, y=1))
    assert session.rasterize_layer(layer)
    assert layer.text is None
    session.undo()
    assert layer.text is not None


def test_fill_and_delete_selection(session):
    session.select_rect(10, 10, 20, 20)
    session.fill_selection((1, 2, 3, 255))
    assert px(session, 15, 15) == (1, 2, 3, 255) and px(session, 5, 5) == (255, 255, 255, 255)
    session.delete_selection()
    assert px(session, 15, 15)[3] == 0


# -- capa vía selección, mover selección y formas por separado ------------------------
def test_layer_via_copy_keeps_source_and_is_one_undo_step(session):
    session.active_layer.pixels[10:20, 10:20] = (255, 0, 0, 255)
    session.select_rect(10, 10, 20, 20)
    n = session.history.position
    layer = session.layer_via_selection(cut=False)
    assert session.active_layer is layer and len(session.doc.layers) == 2
    assert px(session, 15, 15, layer) == (255, 0, 0, 255) and px(session, 5, 5, layer)[3] == 0
    assert px(session, 15, 15, session.doc.layers[0]) == (255, 0, 0, 255)      # el origen no cambia
    assert session.history.position == n + 1
    session.undo()
    assert len(session.doc.layers) == 1


def test_layer_via_cut_moves_pixels_and_undoes_atomically(session):
    session.active_layer.pixels[10:20, 10:20] = (255, 0, 0, 255)
    session.select_rect(10, 10, 20, 20)
    n = session.history.position
    layer = session.layer_via_selection(cut=True)
    assert px(session, 15, 15, layer) == (255, 0, 0, 255)
    assert px(session, 15, 15, session.doc.layers[0])[3] == 0                  # vaciado en el origen
    assert session.history.position == n + 1 and session.doc.selection.active
    session.undo()
    assert len(session.doc.layers) == 1 and px(session, 15, 15) == (255, 0, 0, 255)
    session.redo()
    assert len(session.doc.layers) == 2 and px(session, 15, 15, session.doc.layers[0])[3] == 0


def test_layer_via_selection_respects_soft_selection_and_requires_selection(session):
    with pytest.raises(InvalidOperationError):
        session.layer_via_selection()
    session.select_ellipse(10, 10, 50, 50)
    layer = session.layer_via_selection()
    alpha = layer.pixels[..., 3]
    assert alpha[30, 30] == 255 and alpha[5, 5] == 0 and 0 < alpha[30, 10] <= 255


def test_move_selection_tool_moves_outline_only(session, ctx, tools):
    session.active_layer.pixels[10:20, 10:20] = (255, 0, 0, 255)
    session.select_rect(10, 10, 20, 20)
    before = session.active_layer.pixels.copy()
    stroke(tools["move_selection"], ctx, [(15, 15), (25, 25), (45, 35)])
    assert session.doc.selection.bbox() == (40, 30, 50, 40)
    assert np.array_equal(session.active_layer.pixels, before)                # píxeles intactos
    session.undo()
    assert session.doc.selection.bbox() == (10, 10, 20, 20)


@pytest.mark.parametrize("key", ["line", "rectangle", "rounded_rectangle", "ellipse"])
def test_separate_shape_tools_ignore_generic_shape_option(session, ctx, tools, key):
    ctx.options.shape = "line"          # no debe influir en las herramientas dedicadas
    ctx.options.shape_mode, ctx.options.size = "fill", 3
    ctx.options.primary = (0, 0, 0, 255)
    stroke(tools[key], ctx, [(20, 20), (70, 60)])
    filled = int((session.active_layer.pixels[..., 0] == 0).sum())
    if key == "line":
        assert 0 < filled < 400
    else:
        assert filled > 800
