"""Actualizaciones desde el repositorio de GitHub (sin dependencias: solo biblioteca estándar).

Flujo: se lee ``paintmint/__init__.py`` de la rama ``main`` para conocer la última versión; si es
mayor que la instalada y el usuario lo acepta, se instala con ``git pull --ff-only`` (si la carpeta
es un clon de git) o descargando el ZIP de la rama, validándolo (sin rutas fuera del destino) y
copiándolo sobre la instalación, con copia de seguridad previa y marcha atrás si algo falla.
Nunca se sustituye código sin confirmación del usuario.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from . import __version__
from .i18n import tr

REPO_URL = "https://github.com/juantopoarg/PaintMint"
RAW_INIT_URL = "https://raw.githubusercontent.com/juantopoarg/PaintMint/main/paintmint/__init__.py"
ZIP_URL = "https://github.com/juantopoarg/PaintMint/archive/refs/heads/main.zip"
TIMEOUT = 8.0
MAX_ZIP_BYTES = 60 * 1024 * 1024
CHECK_INTERVAL = 24 * 3600          # como mucho una comprobación automática al día

_urlopen: Callable = urllib.request.urlopen   # sustituible en las pruebas (sin red)


class UpdateError(Exception):
    """Fallo al comprobar o instalar una actualización (el mensaje es apto para el usuario)."""


@dataclass
class UpdateInfo:
    current: str
    latest: str

    @property
    def available(self) -> bool:
        return version_tuple(self.latest) > version_tuple(self.current)


def version_tuple(text: str) -> Tuple[int, ...]:
    parts = re.findall(r"\d+", text or "")
    return tuple(int(p) for p in parts[:4]) or (0,)


def parse_version(source: str) -> Optional[str]:
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.M)
    return m.group(1) if m else None


def _read(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "PaintMint-updater"})
    try:
        with _urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(limit + 1)
    except Exception as exc:   # urllib.error.URLError, socket.timeout, ssl, ...
        raise UpdateError(tr("Could not reach GitHub ({error}).").format(error=getattr(exc, "reason", exc))) from exc
    if len(data) > limit:
        raise UpdateError(tr("The downloaded file is too large."))
    return data


def check_for_update() -> UpdateInfo:
    """Consulta la última versión publicada. Lanza ``UpdateError`` si no se puede."""
    text = _read(RAW_INIT_URL, 64 * 1024).decode("utf-8", "replace")
    latest = parse_version(text)
    if not latest:
        raise UpdateError(tr("Could not determine the latest version."))
    return UpdateInfo(__version__, latest)


def due_for_auto_check(last_check: float, now: Optional[float] = None) -> bool:
    return (now if now is not None else time.time()) - float(last_check or 0) >= CHECK_INTERVAL


# -- instalación -----------------------------------------------------------------------------------------
def install_root() -> str:
    """Carpeta que contiene el paquete ``paintmint`` (raíz del proyecto)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_git_checkout(root: Optional[str] = None) -> bool:
    root = root or install_root()
    return os.path.isdir(os.path.join(root, ".git")) and shutil.which("git") is not None


def validate_zip(zf: zipfile.ZipFile) -> str:
    """Comprueba el ZIP y devuelve el prefijo de su carpeta raíz (p. ej. ``PaintMint-main/``)."""
    names = zf.namelist()
    if not names:
        raise UpdateError(tr("The downloaded update is empty."))
    for n in names:
        norm = os.path.normpath(n)
        if n.startswith(("/", "\\")) or norm.startswith("..") or os.path.isabs(norm) or ".." in n.split("/"):
            raise UpdateError(tr("The downloaded update contains unsafe paths and was rejected."))
    top = {n.split("/", 1)[0] for n in names}
    if len(top) != 1:
        raise UpdateError(tr("The downloaded update has an unexpected structure."))
    prefix = top.pop() + "/"
    if prefix + "paintmint/__init__.py" not in names:
        raise UpdateError(tr("The downloaded update does not look like PaintMint."))
    return prefix


def _extract(zf: zipfile.ZipFile, prefix: str, dest: str) -> None:
    dest_real = os.path.realpath(dest)
    for info in zf.infolist():
        if not info.filename.startswith(prefix) or info.filename == prefix:
            continue
        rel = info.filename[len(prefix):]
        target = os.path.realpath(os.path.join(dest, rel))
        if not (target == dest_real or target.startswith(dest_real + os.sep)):
            raise UpdateError(tr("The downloaded update contains unsafe paths and was rejected."))
        if info.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if info.external_attr >> 16 & 0o111:
                os.chmod(target, os.stat(target).st_mode | 0o111)


def _install_from_dir(src: str, root: str) -> None:
    """Copia ``src`` sobre ``root`` con copia de seguridad del paquete y marcha atrás si falla."""
    pkg_old = os.path.join(root, "paintmint")
    backup = os.path.join(root, ".paintmint-backup")
    if os.path.isdir(backup):
        shutil.rmtree(backup, ignore_errors=True)
    shutil.copytree(pkg_old, backup, ignore=shutil.ignore_patterns("__pycache__"))
    try:
        for entry in os.listdir(src):
            if entry in (".git", ".github"):
                continue
            s, d = os.path.join(src, entry), os.path.join(root, entry)
            if os.path.isdir(s):
                if os.path.isdir(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
    except Exception:
        shutil.rmtree(pkg_old, ignore_errors=True)
        shutil.copytree(backup, pkg_old)
        raise


def install_from_zip_bytes(data: bytes, root: Optional[str] = None) -> str:
    """Instala un ZIP descargado; devuelve la versión instalada."""
    root = root or install_root()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UpdateError(tr("The downloaded update is corrupt.")) from exc
    with zf:
        prefix = validate_zip(zf)
        with tempfile.TemporaryDirectory(prefix="paintmint-update-") as tmp:
            _extract(zf, prefix, tmp)
            version = parse_version(open(os.path.join(tmp, "paintmint", "__init__.py"), encoding="utf-8").read())
            if not version:
                raise UpdateError(tr("The downloaded update does not look like PaintMint."))
            if not os.access(root, os.W_OK):
                raise UpdateError(tr("You do not have write permission for the installation folder:\n{folder}").format(folder=root))
            try:
                _install_from_dir(tmp, root)
            except OSError as exc:
                raise UpdateError(tr("Could not install the update: {error}").format(error=exc)) from exc
    return version


def install_update(root: Optional[str] = None) -> str:
    """Instala la última versión (git o ZIP). Devuelve un mensaje para el usuario."""
    root = root or install_root()
    if is_git_checkout(root):
        try:
            res = subprocess.run(["git", "-C", root, "pull", "--ff-only"], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(tr("Could not install the update: {error}").format(error=exc)) from exc
        if res.returncode != 0:
            raise UpdateError(tr("git could not update the folder:\n{output}").format(output=(res.stderr or res.stdout).strip()))
        return tr("Updated with git.")
    data = _read(ZIP_URL, MAX_ZIP_BYTES)
    version = install_from_zip_bytes(data, root)
    return tr("Updated to version {version}.").format(version=version)
