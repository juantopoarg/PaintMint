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


# ---------------------------------------------------------------- v1.3.2: más herramientas y opciones
CTRL = frozenset({"ctrl"})


def test_polygon_pending_until_finish_then_one_undo_step(session, ctx, tools):
    t = tools["polygon"]
    ctx.options.primary, ctx.options.shape_mode = (255, 0, 0, 255), "fill"
    for p in ((10, 10), (60, 12), (35, 50)):
        t.press(ctx, *p); t.release(ctx, *p)
    assert t.pending and px(session, 35, 25) == (255, 0, 0, 255)       # vista previa ya visible
    assert len(session.history.labels) == 0
    t.finish(ctx)
    assert not t.pending and len(session.history.labels) == 1
    session.undo()
    assert px(session, 35, 25) == (255, 255, 255, 255)


def test_polygon_vertices_can_be_dragged_and_esc_cancels(session, ctx, tools):
    t = tools["polygon"]
    ctx.options.shape_mode = "fill"
    for p in ((10, 10), (60, 10), (35, 50)):
        t.press(ctx, *p); t.release(ctx, *p)
    t.press(ctx, 35, 50); t.move(ctx, 80, 70); t.release(ctx, 80, 70)   # arrastra el tercer vértice
    assert t.pts[2] == (80, 70)
    t.cancel(ctx)
    assert not t.pending and px(session, 35, 25) == (255, 255, 255, 255) and not session.history.labels


def test_polygon_with_too_few_vertices_commits_nothing(session, ctx, tools):
    t = tools["polygon"]
    t.press(ctx, 10, 10); t.release(ctx, 10, 10)
    t.press(ctx, 50, 50); t.release(ctx, 50, 50)
    t.finish(ctx)
    assert not session.history.labels


def test_freeform_shape_closes_on_release(session, ctx, tools):
    ctx.options.primary, ctx.options.shape_mode = (0, 0, 255, 255), "fill"
    pts = [(10, 10), (40, 8), (60, 30), (50, 60), (15, 50), (10, 10)]
    stroke(tools["freeform"], ctx, pts)
    assert px(session, 35, 30) == (0, 0, 255, 255)
    assert len(session.history.labels) == 1 and not tools["freeform"].pending


def test_curve_line_then_bend_adds_node(session, ctx, tools):
    t = tools["curve"]
    ctx.options.primary, ctx.options.size = (0, 0, 0, 255), 3
    t.press(ctx, 10, 40); t.move(ctx, 90, 40); t.release(ctx, 90, 40)
    assert t.pending and len(t.pts) == 2 and px(session, 50, 40) == (0, 0, 0, 255)
    t.press(ctx, 50, 40); t.move(ctx, 50, 10); t.release(ctx, 50, 10)      # se agarra la línea y se curva
    assert len(t.pts) == 3 and t.pts[1] == (50, 10)
    assert px(session, 50, 40) == (255, 255, 255, 255) and px(session, 50, 10)[:3] == (0, 0, 0)
    t.finish(ctx)
    assert len(session.history.labels) == 1


def test_curve_click_far_from_line_starts_new_curve(session, ctx, tools):
    t = tools["curve"]
    t.press(ctx, 10, 10); t.move(ctx, 90, 10); t.release(ctx, 90, 10)
    t.press(ctx, 10, 70); t.move(ctx, 90, 70); t.release(ctx, 90, 70)
    t.finish(ctx)
    assert len(session.history.labels) == 2


def test_clone_stamp_needs_source_and_copies_offset(session, ctx, tools):
    t = tools["clone"]
    ctx.options.primary, ctx.options.size = (255, 0, 0, 255), 8
    stroke(tools["brush"], ctx, [(20, 20), (24, 20)])                       # marca roja de origen
    with pytest.raises(InvalidOperationError):
        t.press(ctx, 60, 60)
    t.press(ctx, 22, 20, "primary", CTRL); t.release(ctx, 22, 20, CTRL)     # fija el origen
    assert not session.history.labels[1:]                                   # fijar origen no es una edición
    ctx.options.hardness, ctx.options.opacity = 1.0, 1.0
    stroke(t, ctx, [(62, 50), (64, 50)])                                    # copia con desplazamiento (-40, -30)
    assert px(session, 63, 50)[:3] == (255, 0, 0)
    assert px(session, 63, 70) == (255, 255, 255, 255)


def test_recolor_replaces_only_matching_color(session, ctx, tools):
    ctx.options.primary, ctx.options.size, ctx.options.hardness = (255, 255, 0, 255), 6, 1.0
    session.fill_selection((200, 0, 0, 255))
    stroke(tools["brush"], ctx, [(50, 40), (50, 40)])                       # un punto amarillo no debe afectarse
    ctx.options.primary, ctx.options.secondary, ctx.options.tolerance = (0, 255, 0, 255), (200, 0, 0, 255), 10
    stroke(tools["recolor"], ctx, [(10, 10), (30, 10)])
    assert px(session, 20, 10)[:3] == (0, 255, 0)
    assert px(session, 50, 40)[:3] == (255, 255, 0) and px(session, 20, 60)[:3] == (200, 0, 0)


def test_hatch_fill_uses_both_colors_and_is_anchored_to_image(session, ctx, tools):
    o = ctx.options
    o.primary, o.secondary, o.shape_mode, o.fill_style = (255, 0, 0, 255), (0, 0, 255, 255), "fill", "horizontal"
    stroke(tools["rectangle"], ctx, [(10, 10), (60, 50)])
    colors = {px(session, 30, y)[:3] for y in range(12, 48)}
    assert colors == {(255, 0, 0), (0, 0, 255)}
    rows_red = [y for y in range(12, 48) if px(session, 30, y)[:3] == (255, 0, 0)]
    assert all((y % 6) < 2 for y in rows_red)


def test_bucket_hatch_and_dashed_outline_and_overwrite(session, ctx, tools):
    o = ctx.options
    o.primary, o.secondary, o.fill_style = (0, 128, 0, 255), (255, 255, 0, 255), "checker_large"
    tools["fill"].press(ctx, 5, 5)
    assert {px(session, x, 5)[:3] for x in range(0, 40)} == {(0, 128, 0), (255, 255, 0)}
    session.undo()
    o.fill_style, o.line_style, o.size, o.shape_mode = "solid", "dash", 3, "outline"
    stroke(tools["line"], ctx, [(5, 40), (95, 40)])
    row = [px(session, x, 40)[:3] == (0, 128, 0) for x in range(5, 95)]
    assert any(row) and not all(row)                                         # trazos con huecos
    session.undo()
    o.line_style, o.blend, o.opacity, o.primary = "solid", "overwrite", 1.0, (10, 20, 30, 128)
    stroke(tools["line"], ctx, [(5, 40), (95, 40)])
    assert px(session, 50, 40) == (10, 20, 30, 128)                         # sobrescribe también el alfa


def test_aliased_option_gives_hard_edges(session, ctx, tools):
    o = ctx.options
    o.antialias, o.shape_mode, o.primary = False, "fill", (0, 0, 0, 255)
    stroke(tools["ellipse"], ctx, [(10, 10), (60, 50)])
    alphas = {px(session, x, y)[0] for x in range(8, 64) for y in range(8, 54)}
    assert alphas <= {0, 255}
