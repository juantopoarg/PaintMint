"""Diálogo «Acerca de»: versión, enlace al repositorio y donación."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QPixmap
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import APP_NAME, __version__
from ..i18n import tr

REPO_URL = "https://github.com/juantopoarg/PaintMint"
DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=Q9VZZG5U83NC8"
DONATE_TEXT = "Donation: If this project help you, you can give me a tip :) "   # texto exacto pedido


def open_url(url: str) -> bool:
    return QDesktopServices.openUrl(QUrl(url))


class AboutDialog(QDialog):
    def __init__(self, parent=None, icon_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("About {app}").format(app=APP_NAME))
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        if icon_path:
            pm = QPixmap(icon_path)
            if not pm.isNull():
                logo = QLabel()
                logo.setPixmap(pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                head.addWidget(logo)
        self.title = QLabel("<h2>%s</h2>%s" % (APP_NAME, tr("Version {version}").format(version=__version__)))
        head.addWidget(self.title, 1)
        lay.addLayout(head)

        self.description = QLabel(tr("Layered image editor for Linux, inspired by Paint.NET.")
                                  + "<br>Python · PyQt5 · NumPy · Pillow · SciPy")
        self.description.setWordWrap(True)
        lay.addWidget(self.description)

        self.repo_label = QLabel('%s <a href="%s">%s</a>' % (tr("Project page:"), REPO_URL, REPO_URL))
        self.repo_label.setOpenExternalLinks(True)
        self.repo_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(self.repo_label)

        self.donation_label = QLabel("<b>%s</b>" % DONATE_TEXT.strip())   # texto original, sin traducir
        self.donation_label.setWordWrap(True)
        lay.addWidget(self.donation_label)
        self.donate_button = QPushButton(tr("Donate with PayPal"))
        self.donate_button.setToolTip(DONATE_URL)
        self.donate_button.clicked.connect(lambda: open_url(DONATE_URL))
        lay.addWidget(self.donate_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
