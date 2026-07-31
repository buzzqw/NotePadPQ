"""
ui/busy_indicator.py — Indicatore "operazione in corso" con Annulla opzionale
NotePadPQ

Piccolo widget da inserire in una status bar o in un layout esistente:
un'etichetta di testo + una barra di progresso indeterminata + un
pulsante Annulla, entrambi visibili solo mentre è "busy".

Espone setText()/text()/setStyleSheet() delegati all'etichetta interna,
così può sostituire una QLabel già usata in molti punti del codice
chiamante senza dover riscrivere quelle chiamate.
"""

from __future__ import annotations

from typing import Optional, Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QToolButton, QStatusBar

from i18n.i18n import tr


class BusyIndicator(QWidget):
    """Etichetta + barra indeterminata + pulsante Annulla opzionale."""

    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.label = QLabel("")
        lay.addWidget(self.label, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # indeterminata
        self.bar.setFixedSize(60, 10)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        self._btn_cancel = QToolButton()
        self._btn_cancel.setText("✕")
        self._btn_cancel.setAutoRaise(True)
        self._btn_cancel.setToolTip(tr("button.cancel", default="Annulla"))
        self._btn_cancel.setVisible(False)
        self._btn_cancel.clicked.connect(self._on_cancel_clicked)
        lay.addWidget(self._btn_cancel)

    def _on_cancel_clicked(self) -> None:
        self._btn_cancel.setEnabled(False)
        self.cancelled.emit()

    def set_busy(self, busy: bool, cancellable: bool = False) -> None:
        """Mostra/nasconde la barra indeterminata e il pulsante Annulla."""
        self.bar.setVisible(busy)
        self._btn_cancel.setVisible(busy and cancellable)
        if busy:
            self._btn_cancel.setEnabled(True)

    # ── Delega a QLabel, per sostituire una QLabel esistente senza toccare
    #    tutte le chiamate .setText()/.setStyleSheet() del chiamante ────────

    def setText(self, text: str) -> None:
        self.label.setText(text)

    def text(self) -> str:
        return self.label.text()

    def setStyleSheet(self, css: str) -> None:
        self.label.setStyleSheet(css)


def show_busy(statusbar: QStatusBar, text: str, cancellable: bool = False,
              on_cancel: Optional[Callable[[], None]] = None) -> BusyIndicator:
    """Crea e mostra un BusyIndicator come widget permanente della status bar.

    Il chiamante deve rimuoverlo con hide_busy() al termine dell'operazione.
    """
    widget = BusyIndicator()
    widget.setText(text)
    widget.set_busy(True, cancellable)
    if on_cancel:
        widget.cancelled.connect(on_cancel)
    statusbar.addPermanentWidget(widget)
    widget.show()
    return widget


def hide_busy(statusbar: QStatusBar, widget: Optional[BusyIndicator]) -> None:
    if widget is None:
        return
    statusbar.removeWidget(widget)
    widget.deleteLater()
