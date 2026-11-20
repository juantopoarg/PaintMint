import numpy as np

from paintmint.core.document import Document
from paintmint.core.session import EditSession


def paint_dot(session, x, y, color=(255, 0, 0, 255)):
    h = session.begin_edit()
    block = np.empty((1, 1, 4), np.uint8)
    block[...] = color
    h.write((x, y, x + 1, y + 1), block)
    return h.commit("punto")


def test_undo_redo_restores_exact_pixels(session):
    before = session.active_layer.pixels.copy()
    paint_dot(session, 3, 4)
    after = session.active_layer.pixels.copy()
    assert not np.array_equal(before, after)
    session.undo()
    assert np.array_equal(session.active_layer.pixels, before)
    session.redo()
    assert np.array_equal(session.active_layer.pixels, after)


def test_no_op_edit_creates_no_history(session):
    h = session.begin_edit()
    assert h.commit("nada") is False
    paint_dot(session, 1, 1, (255, 255, 255, 255))  # mismo color que el fondo
    assert session.history.labels == []


def test_new_action_discards_redo_branch(session):
    paint_dot(session, 1, 1)
    paint_dot(session, 2, 2)
    session.undo()
    assert session.history.can_redo
    paint_dot(session, 3, 3)
    assert not session.history.can_redo
    assert len(session.history.labels) == 2


def test_history_is_unlimited_by_default(session):
    for i in range(300):
        paint_dot(session, i % 100, i % 80, (i % 255, 0, 0, 255))
    assert len(session.history.labels) >= 290
    for _ in range(300):
        session.undo()
    assert not session.history.can_undo
    assert (session.active_layer.pixels == 255).all()


def test_history_patches_store_only_changed_rect(session):
    paint_dot(session, 10, 10)
    cmd = session.history._undo[-1]
    assert cmd.rect == (10, 10, 11, 11)
    assert cmd.nbytes < 1000


def test_max_bytes_trims_oldest_commands():
    s = EditSession(Document(200, 200), history_max_bytes=3000)
    for i in range(50):
        h = s.begin_edit()
        h.write((0, 0, 20, 20), np.full((20, 20, 4), i + 1, np.uint8))
        h.commit("bloque")
    assert len(s.history.labels) < 50
    assert s.history.can_undo


def test_goto_jumps_through_timeline(session):
    for i in range(5):
        paint_dot(session, i, 0)
    session.history.goto(2)
    assert session.active_layer.pixels[0, 1, 1] == 0 and session.active_layer.pixels[0, 2, 1] == 255
    session.history.goto(5)
    assert session.active_layer.pixels[0, 4, 1] == 0
    session.history.goto(0)
    assert (session.active_layer.pixels == 255).all()


def test_modified_flag_tracks_saved_state(session):
    assert not session.modified
    paint_dot(session, 1, 1)
    assert session.modified
    session.mark_saved()
    assert not session.modified
    session.undo()
    assert session.modified
    session.redo()
    assert not session.modified


def test_saved_state_lost_when_redo_branch_discarded(session):
    paint_dot(session, 1, 1)
    session.mark_saved()
    session.undo()
    paint_dot(session, 2, 2)  # descarta el estado guardado
    session.undo()
    session.redo()
    assert session.modified


def test_selection_clips_edits_and_undo_is_exact(session):
    session.select_rect(10, 10, 20, 20)
    h = session.begin_edit()
    h.write((0, 0, 100, 80), np.zeros((80, 100, 4), np.uint8))
    h.commit("borrar")
    px = session.active_layer.pixels
    assert px[15, 15, 3] == 0 and px[5, 5, 3] == 255 and px[25, 25, 3] == 255
    session.undo()
    assert (px == 255).all()


def test_compound_operations_undo_as_one(session):
    session.select_rect(0, 0, 10, 10)
    session.history.break_merge()
    data = session.copy_pixels()
    assert data is not None
    session.paste_pixels(data[0], (30, 30))
    assert len(session.doc.layers) == 2 and session.doc.selection.bbox() == (30, 30, 40, 40)
    session.undo()
    assert len(session.doc.layers) == 1 and session.doc.selection.bbox() == (0, 0, 10, 10)


def test_history_listeners_notified(session):
    calls = []
    session.history.listeners.append(lambda: calls.append(1))
    paint_dot(session, 1, 1)
    session.undo()
    session.redo()
    assert len(calls) == 3
