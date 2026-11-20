import numpy as np

from paintmint.core.selection import Selection, shift_array


def test_rect_selection_exact():
    s = Selection(20, 20)
    s.select_rect(2, 3, 6, 8)
    assert s.mask.sum() // 255 == 20
    assert s.bbox() == (2, 3, 6, 8)
    assert s.contains(2, 3) and not s.contains(6, 8)


def test_combine_modes():
    s = Selection(20, 20)
    s.select_rect(0, 0, 10, 10)
    s.select_rect(5, 5, 15, 15, "add")
    assert s.mask.sum() // 255 == 100 + 100 - 25
    s.select_rect(0, 0, 7, 7, "intersect")
    assert s.bbox() == (0, 0, 7, 7)
    s.select_rect(0, 0, 5, 5, "subtract")
    assert s.mask[4, 4] == 0 and s.mask[6, 6] == 255
    s.select_rect(0, 0, 20, 20, "xor")
    assert s.mask[4, 4] == 255 and s.mask[6, 6] == 0


def test_empty_result_clears_selection():
    s = Selection(10, 10)
    s.select_rect(0, 0, 5, 5)
    s.select_rect(0, 0, 5, 5, "subtract")
    assert not s.active


def test_invert_and_noop_without_selection():
    s = Selection(10, 10)
    s.invert()
    assert not s.active
    s.select_rect(0, 0, 5, 10)
    s.invert()
    assert s.bbox() == (5, 0, 10, 10)


def test_ellipse_area_close_to_pi_r2():
    s = Selection(60, 60)
    s.select_ellipse(5, 5, 55, 55)
    area = s.mask.sum() / 255
    assert abs(area - np.pi * 25 ** 2) / (np.pi * 25 ** 2) < 0.02
    assert s.mask[30, 30] == 255 and s.mask[0, 0] == 0


def test_lasso_polygon():
    s = Selection(40, 40)
    s.select_polygon([(5, 5), (35, 5), (5, 35)])  # triángulo
    assert s.mask[10, 10] == 255 and s.mask[30, 30] == 0
    area = s.mask.sum() / 255
    assert 0.9 * 450 < area < 1.1 * 450


def test_degenerate_polygon_is_empty():
    s = Selection(10, 10)
    s.select_polygon([(1, 1), (5, 5)])
    assert not s.active


def test_shift_array_has_no_wraparound():
    a = np.arange(16, dtype=np.uint8).reshape(4, 4)
    out = shift_array(a, 1, 1)
    assert out[0].sum() == 0 and out[:, 0].sum() == 0 and out[1, 1] == a[0, 0]


def test_selection_is_undoable_via_session(session):
    session.select_rect(0, 0, 10, 10)
    session.select_rect(20, 20, 30, 30, "add")
    assert session.doc.selection.bbox() == (0, 0, 30, 30)
    session.undo()
    assert session.doc.selection.bbox() == (0, 0, 10, 10)
    session.undo()
    assert not session.doc.selection.active
    session.redo()
    assert session.doc.selection.active


def test_magic_wand_selects_contiguous_region(session):
    session.active_layer.pixels[10:20, 10:20] = (255, 0, 0, 255)
    session.active_layer.pixels[10:20, 50:60] = (255, 0, 0, 255)
    session.select_wand(12, 12, tolerance=0)
    assert session.doc.selection.bbox() == (10, 10, 20, 20)
    session.select_wand(12, 12, tolerance=0, contiguous=False)
    assert session.doc.selection.bbox() == (10, 10, 60, 20)
