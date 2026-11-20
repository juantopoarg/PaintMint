"""Interfaz de las actualizaciones: comprobación en segundo plano e instalación con confirmación."""

from __future__ import annotations

import time
from typing import Callable

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox

from .. import config, updater
from ..i18n import tr


class Worker(QThread):
    """Ejecuta ``fn`` en un hilo; emite ``done(resultado)`` o ``failed(mensaje)``."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except updater.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:   # nunca dejar morir el hilo en silencio
            self.failed.emit(str(exc))


class UpdateController:
    """Orquesta comprobación (manual o automática) e instalación desde la ventana principal."""

    def __init__(self, window):
        self.window = window
        self._workers = []

    def _run(self, fn, ok, fail):
        w = Worker(fn, self.window)
        w.done.connect(ok)
        w.failed.connect(fail)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def check(self, manual: bool):
        """Busca una versión nueva. En modo automático los fallos y «ya actualizado» son silenciosos."""
        def ok(info):
            config.set_value("last_update_check", time.time())
            if info.available:
                self.offer(info)
            elif manual:
                QMessageBox.information(self.window, tr("Check for updates"),
                                        tr("You have the latest version ({version}).").format(version=info.current))

        def fail(msg):
            if manual:
                QMessageBox.warning(self.window, tr("Check for updates"), msg)

        self._run(updater.check_for_update, ok, fail)

    def offer(self, info) -> bool:
        box = QMessageBox(self.window)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(tr("Update available"))
        box.setText(tr("PaintMint {latest} is available (you have {current}).\nDo you want to install it now?")
                    .format(latest=info.latest, current=info.current))
        install = box.addButton(tr("Install update"), QMessageBox.AcceptRole)
        box.addButton(tr("Later"), QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is install:
            self.install()
            return True
        return False

    def install(self):
        def ok(msg):
            QMessageBox.information(self.window, tr("Update installed"),
                                    msg + "\n" + tr("Restart PaintMint to use the new version."))

        def fail(msg):
            QMessageBox.warning(self.window, tr("Update failed"), msg + "\n" + tr("Your current installation was not modified."))

        self._run(updater.install_update, ok, fail)
