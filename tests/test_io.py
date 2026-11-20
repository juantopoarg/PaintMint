import os
import zipfile

import numpy as np
import pytest
from PIL import Image

from paintmint.core import io as pmio
from paintmint.core.document import Document
from paintmint.core.layer import TextSpec
from paintmint.core.session import EditSession


def make_doc():
    d = Document(40, 30, (10, 200, 30, 255))
    d.layers[0].pixels[:10, :10] = (250, 0, 0, 255)
    return d


@pytest.mark.parametrize("ext", ["png", "tif", "tiff", "ora"])
def test_lossless_roundtrip_is_pixel_exact(tmp_path, ext):
    d = make_doc()
    d.layers[0].pixels[20:25, 20:25] = (1, 2, 3, 128)       # con transparencia parcial
    path = str(tmp_path / f"a.{ext}")
    pmio.save_document(d, path)
    back = pmio.open_document(path)
    assert (back.width, back.height) == (40, 30)
    assert np.array_equal(back.composite(), d.composite())
    assert back.path == path


def test_bmp_roundtrip_opaque_exact_and_alpha_flattened_on_white(tmp_path):
    d = make_doc()
    pmio.save_document(d, str(tmp_path / "a.bmp"))
    assert np.array_equal(pmio.open_document(str(tmp_path / "a.bmp")).composite(), d.composite())
    t = Document(8, 8, (0, 0, 0, 0))
    pmio.save_document(t, str(tmp_path / "t.bmp"))
    assert tuple(pmio.open_document(str(tmp_path / "t.bmp")).layers[0].pixels[0, 0]) == (255, 255, 255, 255)


def test_jpeg_roundtrip_is_close_and_flattens_alpha_on_white(tmp_path):
    d = Document(32, 32, (0, 0, 0, 0))
    path = str(tmp_path / "a.jpg")
    pmio.save_document(d, path, quality=95)
    back = pmio.open_document(path)
    assert back.layers[0].pixels[..., :3].min() >= 250        # transparente -> blanco
    d2 = make_doc()
    pmio.save_document(d2, str(tmp_path / "b.jpeg"), quality=95)
    b2 = pmio.open_document(str(tmp_path / "b.jpeg"))
    diff = np.abs(b2.composite().astype(int) - d2.composite().astype(int))
    assert diff[..., :3].mean() < 6


def test_jpeg_quality_changes_file_size(tmp_path):
    rng = np.random.default_rng(0)
    d = Document.from_pixels(np.dstack([rng.integers(0, 256, (64, 64, 3), dtype=np.uint8),
                                        np.full((64, 64), 255, np.uint8)]))
    pmio.save_document(d, str(tmp_path / "lo.jpg"), quality=10)
    pmio.save_document(d, str(tmp_path / "hi.jpg"), quality=95)
    assert os.path.getsize(tmp_path / "lo.jpg") < os.path.getsize(tmp_path / "hi.jpg")


def test_gif_roundtrip_with_transparency(tmp_path):
    d = Document(20, 20, (0, 0, 255, 255))
    d.layers[0].pixels[:5, :5] = (0, 0, 0, 0)
    path = str(tmp_path / "a.gif")
    pmio.save_document(d, path)
    back = pmio.open_document(path)
    assert back.layers[0].pixels[0, 0, 3] == 0
    assert tuple(back.layers[0].pixels[10, 10]) == (0, 0, 255, 255)


def test_multilayer_is_flattened_for_flat_formats_and_preserved_in_ora(tmp_path):
    s = EditSession(Document(10, 10, (0, 0, 255, 255)))
    top = s.add_layer("Rojo", fill=(255, 0, 0, 255))
    top.opacity, top.blend_mode = 0.5, "multiply"
    s.set_layer_props(top, name="Red layer")
    pmio.save_document(s.doc, str(tmp_path / "f.png"))
    assert len(pmio.open_document(str(tmp_path / "f.png")).layers) == 1
    pmio.save_document(s.doc, str(tmp_path / "f.ora"))
    back = pmio.open_document(str(tmp_path / "f.ora"))
    assert [l.name for l in back.layers] == ["Background", "Red layer"]
    assert back.layers[1].opacity == pytest.approx(0.5, abs=1e-3) and back.layers[1].blend_mode == "multiply"
    assert np.array_equal(back.composite(), s.doc.composite())


def test_ora_preserves_hidden_flag_and_editable_text(tmp_path):
    s = EditSession(Document(60, 40))
    t = s.create_text_layer(TextSpec(text="Hola", size=20, x=2, y=2, color=(9, 8, 7, 255), bold=True))
    s.add_layer("hidden").visible = False
    path = str(tmp_path / "t.ora")
    pmio.save_document(s.doc, path)
    back = pmio.open_document(path)
    assert back.layers[2].visible is False
    assert back.layers[1].text is not None and back.layers[1].text.text == "Hola"
    assert back.layers[1].text.color == (9, 8, 7, 255) and back.layers[1].text.bold


def test_ora_is_valid_openraster_zip(tmp_path):
    path = str(tmp_path / "v.ora")
    pmio.save_document(make_doc(), path)
    with zipfile.ZipFile(path) as z:
        assert z.namelist()[0] == "mimetype" and z.read("mimetype") == b"image/openraster"
        assert {"stack.xml", "mergedimage.png"} <= set(z.namelist())


def test_open_exif_orientation_and_16bit_grayscale(tmp_path):
    im = Image.new("RGB", (20, 10), (255, 0, 0))
    exif = Image.Exif(); exif[0x0112] = 6                      # rotar 90°
    im.save(tmp_path / "rot.jpg", exif=exif)
    assert (pmio.open_document(str(tmp_path / "rot.jpg")).width,
            pmio.open_document(str(tmp_path / "rot.jpg")).height) == (10, 20)
    g16 = Image.fromarray((np.arange(16, dtype=np.uint16).reshape(4, 4) * 4096))
    g16.save(tmp_path / "g.tif")
    d = pmio.open_document(str(tmp_path / "g.tif"))
    assert d.layers[0].pixels[3, 3, 0] > d.layers[0].pixels[0, 0, 0] + 100


@pytest.mark.parametrize("mode", ["L", "LA", "P", "1", "CMYK", "RGB", "RGBA"])
def test_open_various_pillow_modes(tmp_path, mode):
    Image.new(mode, (8, 8)).save(tmp_path / "m.tif" if mode in ("CMYK", "LA") else tmp_path / "m.png")
    path = tmp_path / ("m.tif" if mode in ("CMYK", "LA") else "m.png")
    d = pmio.open_document(str(path))
    assert d.layers[0].pixels.shape == (8, 8, 4)


def test_animated_gif_opens_first_frame(tmp_path):
    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(tmp_path / "an.gif", save_all=True, append_images=frames[1:])
    d = pmio.open_document(str(tmp_path / "an.gif"))
    assert d.layers[0].pixels[0, 0, 0] > 200 and d.layers[0].pixels[0, 0, 1] < 50


def test_save_does_not_modify_document(tmp_path):
    d = make_doc()
    before = d.layers[0].pixels.copy()
    pmio.save_document(d, str(tmp_path / "x.jpg"))
    assert np.array_equal(d.layers[0].pixels, before)
