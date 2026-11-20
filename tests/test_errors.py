"""Manejo de errores: archivos corruptos/no soportados, permisos, memoria y límites."""

import os
import stat

import numpy as np
import pytest
from PIL import Image

from paintmint.core import io as pmio
from paintmint.core import memory
from paintmint.core.document import Document
from paintmint.core.errors import (ImageLoadError, ImageSaveError, ImageTooLargeError, OutOfMemoryAppError,
                                   PaintMintError, UnsupportedFormatError)
from paintmint.core.session import EditSession

running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0


def test_open_missing_file(tmp_path):
    with pytest.raises(ImageLoadError, match="does not exist"):
        pmio.open_document(str(tmp_path / "nada.png"))


def test_open_directory(tmp_path):
    with pytest.raises(ImageLoadError):
        pmio.open_document(str(tmp_path))


@pytest.mark.parametrize("name", ["a.png", "a.jpg", "a.bmp", "a.gif", "a.tif", "a.ora"])
def test_open_garbage_is_reported_not_raised_raw(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"esto no es una imagen" * 10)
    with pytest.raises(ImageLoadError):
        pmio.open_document(str(p))


def test_open_empty_file(tmp_path):
    p = tmp_path / "vacio.png"
    p.write_bytes(b"")
    with pytest.raises(ImageLoadError):
        pmio.open_document(str(p))


def test_open_truncated_png(tmp_path):
    good = tmp_path / "ok.png"
    Image.fromarray(np.random.default_rng(0).integers(0, 255, (64, 64, 3), dtype=np.uint8)).save(good)
    data = good.read_bytes()
    bad = tmp_path / "trunc.png"
    bad.write_bytes(data[: len(data) // 2])
    with pytest.raises(ImageLoadError):
        pmio.open_document(str(bad))


def test_open_corrupt_ora(tmp_path):
    import zipfile
    p = tmp_path / "c.ora"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("stack.xml", "<image w='4' h='4'><stack><layer src='falta.png'/></stack></image>")
    with pytest.raises(ImageLoadError):
        pmio.open_document(str(p))


def test_open_unsupported_image_format(tmp_path):
    p = tmp_path / "x.webp"
    try:
        Image.new("RGB", (4, 4)).save(p, "WEBP")
    except Exception:
        pytest.skip("Pillow sin soporte WEBP")
    with pytest.raises(UnsupportedFormatError):
        pmio.open_document(str(p))


@pytest.mark.skipif(running_as_root, reason="root ignora los permisos de archivo")
def test_open_without_read_permission(tmp_path):
    p = tmp_path / "p.png"
    Image.new("RGB", (4, 4)).save(p)
    os.chmod(p, 0)
    try:
        with pytest.raises(ImageLoadError, match="permission"):
            pmio.open_document(str(p))
    finally:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def test_save_unsupported_extension(tmp_path):
    with pytest.raises(UnsupportedFormatError):
        pmio.save_document(Document(4, 4), str(tmp_path / "a.xyz"))
    with pytest.raises(UnsupportedFormatError):
        pmio.save_document(Document(4, 4), str(tmp_path / "sinextension"))


def test_save_to_missing_folder(tmp_path):
    with pytest.raises(ImageSaveError, match="folder"):
        pmio.save_document(Document(4, 4), str(tmp_path / "no" / "existe" / "a.png"))


@pytest.mark.skipif(running_as_root, reason="root ignora los permisos de archivo")
def test_save_without_write_permission(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(ImageSaveError, match="permission"):
            pmio.save_document(Document(4, 4), str(ro / "a.png"))
    finally:
        os.chmod(ro, stat.S_IRWXU)


@pytest.mark.skipif(running_as_root, reason="root ignora los permisos de archivo")
def test_save_over_readonly_file(tmp_path):
    p = tmp_path / "r.png"
    Image.new("RGB", (4, 4)).save(p)
    os.chmod(p, stat.S_IRUSR)
    try:
        with pytest.raises(ImageSaveError, match="read-only"):
            pmio.save_document(Document(4, 4), str(p))
    finally:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def test_permission_error_during_write_is_translated(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("denegado")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(ImageSaveError, match="permission"):
        pmio.save_document(Document(4, 4), str(tmp_path / "a.png"))
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]   # sin temporales huérfanos


def test_disk_full_is_translated(tmp_path, monkeypatch):
    import builtins
    real_open = builtins.open

    class Full:
        def __init__(self, f): self.f = f
        def __enter__(self): return self
        def __exit__(self, *a): self.f.close()
        def write(self, d): raise OSError(28, "No space left on device")
        def __getattr__(self, n): return getattr(self.f, n)

    def fake_open(path, mode="r", *a, **k):
        f = real_open(path, mode, *a, **k)
        return Full(f) if "w" in mode and str(path).endswith(".tmp") else f

    monkeypatch.setattr(builtins, "open", fake_open)
    with pytest.raises(ImageSaveError, match="disk space"):
        pmio.save_document(Document(4, 4), str(tmp_path / "a.png"))


def test_failed_save_keeps_existing_file_intact(tmp_path, monkeypatch):
    p = tmp_path / "keep.png"
    pmio.save_document(Document(4, 4, (1, 2, 3, 255)), str(p))
    original = p.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError(5, "io")))
    with pytest.raises(ImageSaveError):
        pmio.save_document(Document(4, 4, (9, 9, 9, 255)), str(p))
    assert p.read_bytes() == original


# -- memoria y tamaño ------------------------------------------------------------
def test_canvas_size_limits(monkeypatch):
    monkeypatch.setattr(memory, "MAX_PIXELS", 1000)
    with pytest.raises(ImageTooLargeError):
        Document(100, 100)
    Document(10, 10)


def test_open_huge_image_header_rejected_before_decoding(tmp_path, monkeypatch):
    p = tmp_path / "big.png"
    Image.new("L", (400, 400)).save(p)
    monkeypatch.setattr(memory, "MAX_PIXELS", 10_000)
    with pytest.raises(ImageTooLargeError):
        pmio.open_document(str(p))


def test_insufficient_memory_is_reported(monkeypatch):
    monkeypatch.setattr(memory, "available_bytes", lambda: 1000)
    with pytest.raises(OutOfMemoryAppError, match="memory"):
        Document(200, 200)


def test_insufficient_memory_on_add_layer_and_open_keeps_document_usable(tmp_path, monkeypatch):
    s = EditSession(Document(100, 100))
    p = tmp_path / "ok.png"
    Image.new("RGB", (300, 300)).save(p)
    monkeypatch.setattr(memory, "available_bytes", lambda: 50_000)
    with pytest.raises(OutOfMemoryAppError):
        s.add_layer()
    with pytest.raises(OutOfMemoryAppError):
        pmio.open_document(str(p))
    with pytest.raises(OutOfMemoryAppError):
        s.resize_image(2000, 2000)
    assert len(s.doc.layers) == 1 and (s.doc.width, s.doc.height) == (100, 100)
    monkeypatch.undo()
    s.add_layer()                                              # y se puede seguir trabajando
    assert len(s.doc.layers) == 2


def test_numpy_memoryerror_is_translated(monkeypatch):
    real = np.empty
    def boom(*a, **k):
        raise MemoryError()
    monkeypatch.setattr(memory.np, "empty", boom)
    with pytest.raises(OutOfMemoryAppError):
        memory.alloc_pixels(10, 10)


def test_memoryerror_during_decode_is_translated(tmp_path, monkeypatch):
    p = tmp_path / "a.png"
    Image.new("RGB", (4, 4)).save(p)
    monkeypatch.setattr(pmio, "_open_raster", lambda path: (_ for _ in ()).throw(MemoryError()))
    with pytest.raises(OutOfMemoryAppError):
        pmio.open_document(str(p))


def test_all_app_errors_share_base_and_have_messages():
    for cls in (ImageLoadError, ImageSaveError, UnsupportedFormatError, ImageTooLargeError, OutOfMemoryAppError):
        assert issubclass(cls, PaintMintError)


def test_available_bytes_reads_proc_meminfo():
    v = memory.available_bytes()
    assert v is None or v > 0


def test_unreadable_proc_meminfo_does_not_block(monkeypatch):
    import builtins
    real = builtins.open
    monkeypatch.setattr(builtins, "open", lambda p, *a, **k: (_ for _ in ()).throw(OSError()) if p == "/proc/meminfo" else real(p, *a, **k))
    assert memory.available_bytes() is None
    memory.ensure_memory(10 ** 15)       # sin dato no se bloquea (se confía en MemoryError)
