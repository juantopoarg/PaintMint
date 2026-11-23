"""Punto de entrada de la aplicación."""

from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write('PyQt5 is not installed. Run scripts/install_deps.sh (see README.md).\n')
        return 2
    from . import APP_NAME
    from .ui.main_window import MainWindow, app_icon
    from .ui.qtutil import install_excepthook

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PaintMint")
    app.setDesktopFileName("paintmint")   # asocia la ventana con paintmint.desktop (icono en la barra de tareas)
    app.setWindowIcon(app_icon())
    install_excepthook()
    from .desktop import ensure_launcher
    ensure_launcher()                      # deja el acceso directo en Menú > Gráficos (solo la primera vez / si cambió la ruta)
    win = MainWindow(files=[a for a in argv[1:] if not a.startswith("-")], open_blank=True)
    win.show()
    return app.exec_()
