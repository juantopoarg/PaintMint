from paintmint import desktop


def test_launcher_is_created_in_graphics_category_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("PAINTMINT_NO_DESKTOP", raising=False)
    assert desktop.ensure_launcher(str(tmp_path)) is True
    f = tmp_path / "applications" / "paintmint.desktop"
    text = f.read_text(encoding="utf-8")
    assert "Categories=Graphics;" in text and str(desktop.ROOT / "paintmint.sh") in text and "Exec=bash " in text
    assert (tmp_path / "icons" / "hicolor" / "48x48" / "apps" / "paintmint.png").exists()
    assert desktop.ensure_launcher(str(tmp_path)) is False          # sin cambios: no reescribe
    f.write_text("viejo")
    assert desktop.ensure_launcher(str(tmp_path)) is True           # ruta cambiada: se corrige


def test_launcher_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PAINTMINT_NO_DESKTOP", "1")
    assert desktop.ensure_launcher(str(tmp_path)) is False and not (tmp_path / "applications").exists()
