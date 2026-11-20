"""Idiomas (catálogo completo, inglés por defecto) y actualizador (sin red real)."""

import ast
import io
import os
import zipfile

import pytest

import paintmint
from paintmint import config, i18n, updater
from paintmint.translations_es import ES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tr_ids():
    ids = set()
    for dp, _, fs in os.walk(os.path.join(ROOT, "paintmint")):
        for f in fs:
            if f.endswith(".py") and f != "translations_es.py":
                tree = ast.parse(open(os.path.join(dp, f), encoding="utf-8").read())
                for n in ast.walk(tree):
                    if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args \
                            and isinstance(n.args[0], ast.Constant):
                        ids.add(n.args[0].value)
    return ids


@pytest.fixture
def restore_lang():
    yield
    i18n.set_language("en")


def test_default_language_is_english(monkeypatch, tmp_path):
    monkeypatch.delenv("PAINTMINT_LANG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert i18n._initial_language() == "en"


def test_config_and_env_select_language(monkeypatch, tmp_path):
    monkeypatch.delenv("PAINTMINT_LANG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.set_value("language", "es")
    assert i18n._initial_language() == "es"
    monkeypatch.setenv("PAINTMINT_LANG", "en")
    assert i18n._initial_language() == "en"


def test_every_message_has_a_spanish_translation():
    missing = sorted(_tr_ids() - set(ES))
    assert not missing, missing


def test_switching_language_translates_and_falls_back(restore_lang):
    i18n.set_language("es")
    assert i18n.tr("Layers") == "Capas" and i18n.tr("never translated text") == "never translated text"
    i18n.set_language("en")
    assert i18n.tr("Layers") == "Layers"


def test_placeholders_survive_translation():
    import re
    pat = re.compile(r"\{[^}]*\}")
    for en, es in ES.items():
        assert sorted(pat.findall(en)) == sorted(pat.findall(es)), en


# ------------------------------------------------------------------ updater
def make_zip(version="9.9.9", extra=None, prefix="PaintMint-main/"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(prefix + "paintmint/__init__.py", '__version__ = "%s"\nAPP_NAME = "PaintMint"\n' % version)
        z.writestr(prefix + "README.md", "new readme")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_urlopen(routes):
    def opener(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if url not in routes:
            raise OSError("no route")
        return FakeResp(routes[url])
    return opener


def test_version_parsing_and_comparison():
    assert updater.parse_version('x = 1\n__version__ = "1.3.0"\n') == "1.3.0"
    assert updater.version_tuple("1.10.0") > updater.version_tuple("1.9.9")
    assert updater.UpdateInfo("1.2.0", "1.2.1").available
    assert not updater.UpdateInfo("1.2.0", "1.2.0").available


def test_check_for_update_detects_newer_version(monkeypatch):
    monkeypatch.setattr(updater, "_urlopen", fake_urlopen({updater.RAW_INIT_URL: b'__version__ = "99.0.0"\n'}))
    info = updater.check_for_update()
    assert info.available and info.latest == "99.0.0" and info.current == paintmint.__version__


def test_check_for_update_reports_network_failure_cleanly(monkeypatch):
    monkeypatch.setattr(updater, "_urlopen", fake_urlopen({}))
    with pytest.raises(updater.UpdateError, match="GitHub"):
        updater.check_for_update()


def test_check_rejects_garbage(monkeypatch):
    monkeypatch.setattr(updater, "_urlopen", fake_urlopen({updater.RAW_INIT_URL: b"<html>404</html>"}))
    with pytest.raises(updater.UpdateError):
        updater.check_for_update()


def test_auto_check_is_rate_limited():
    assert updater.due_for_auto_check(0)
    assert not updater.due_for_auto_check(1000, now=1000 + 60)
    assert updater.due_for_auto_check(1000, now=1000 + updater.CHECK_INTERVAL)


def _fake_install(tmp_path):
    root = tmp_path / "install"
    (root / "paintmint").mkdir(parents=True)
    (root / "paintmint" / "__init__.py").write_text('__version__ = "1.0.0"\n')
    (root / "paintmint" / "old_module.py").write_text("old")
    return root


def test_install_from_zip_replaces_package_and_keeps_backup(tmp_path):
    root = _fake_install(tmp_path)
    version = updater.install_from_zip_bytes(make_zip("2.0.0"), str(root))
    assert version == "2.0.0"
    assert '2.0.0' in (root / "paintmint" / "__init__.py").read_text()
    assert not (root / "paintmint" / "old_module.py").exists()
    assert (root / ".paintmint-backup" / "old_module.py").exists()
    assert (root / "README.md").read_text() == "new readme"


def test_zip_with_path_traversal_is_rejected_and_nothing_changes(tmp_path):
    root = _fake_install(tmp_path)
    evil = make_zip("2.0.0", extra={"PaintMint-main/../../evil.txt": "x"})
    with pytest.raises(updater.UpdateError, match="unsafe"):
        updater.install_from_zip_bytes(evil, str(root))
    assert "1.0.0" in (root / "paintmint" / "__init__.py").read_text()
    assert not (tmp_path / "evil.txt").exists()


def test_zip_that_is_not_paintmint_or_corrupt_is_rejected(tmp_path):
    root = _fake_install(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other/readme.txt", "hi")
    with pytest.raises(updater.UpdateError):
        updater.install_from_zip_bytes(buf.getvalue(), str(root))
    with pytest.raises(updater.UpdateError, match="corrupt"):
        updater.install_from_zip_bytes(b"not a zip", str(root))
    assert "1.0.0" in (root / "paintmint" / "__init__.py").read_text()


def test_install_update_downloads_zip_when_not_a_git_clone(monkeypatch, tmp_path):
    root = _fake_install(tmp_path)
    monkeypatch.setattr(updater, "_urlopen", fake_urlopen({updater.ZIP_URL: make_zip("3.1.4")}))
    msg = updater.install_update(str(root))
    assert "3.1.4" in msg and "3.1.4" in (root / "paintmint" / "__init__.py").read_text()


def test_install_update_uses_git_pull_in_a_clone(monkeypatch, tmp_path):
    root = _fake_install(tmp_path)
    (root / ".git").mkdir()
    calls = []

    class R:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(updater.shutil, "which", lambda n: "/usr/bin/git")
    monkeypatch.setattr(updater.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    updater.install_update(str(root))
    assert calls and calls[0][-2:] == ["pull", "--ff-only"]


def test_failed_copy_rolls_back(monkeypatch, tmp_path):
    root = _fake_install(tmp_path)
    real = updater.shutil.copytree
    state = {"n": 0}

    def flaky(src, dst, *a, **k):
        state["n"] += 1
        if state["n"] == 2:          # la primera copia es la de seguridad; la segunda, la instalación
            raise OSError("disk exploded")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(updater.shutil, "copytree", flaky)
    with pytest.raises(updater.UpdateError):
        updater.install_from_zip_bytes(make_zip("2.0.0"), str(root))
    assert (root / "paintmint" / "old_module.py").exists()
