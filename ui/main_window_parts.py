"""Small, self-contained helpers for :mod:`ui.main_window`.

These ``QMenu``/``QObject``/``QThread`` helpers used to live at the top of the
(already very large) ``main_window`` module.  They do not depend on the window
beyond the callback passed in, so they live here to keep ``main_window`` focused
on the window itself.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QMenu

from i18n.i18n import tr


class _RecentFilesMenu(QMenu):
    """
    QMenu File recenti: tasto destro su una voce per fissarla in cima
    (pin) o rimuovere il fissaggio, così un file aperto spesso non
    scompare dalla lista spinto fuori da file temporanei/di appoggio.
    """

    def contextMenuEvent(self, event) -> None:
        action = self.actionAt(event.pos())
        path = action.data() if action else None
        if path is None:
            return
        from core.recent_files import RecentFiles
        rf = RecentFiles.instance()
        label = (tr("action.unpin_recent_file") if rf.is_pinned(path)
                 else tr("action.pin_recent_file"))
        ctx = QMenu(self)
        pin_act = ctx.addAction(label)
        chosen = ctx.exec(event.globalPos())
        if chosen is pin_act:
            rf.toggle_pin(path)
            mw = self.parentWidget()
            if hasattr(mw, "_populate_recent_menu"):
                mw._populate_recent_menu()


class TripleClickFilter(QObject):
    """Riconosce 3 click rapidi su un widget e lancia un'azione."""

    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        self.clicks = 0
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.reset)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.clicks += 1
            if self.clicks == 1:
                self.timer.start(600)  # Finestra di 600ms per fare i 3 click
            elif self.clicks == 3:
                self.callback()
                self.reset()
        return super().eventFilter(obj, event)

    def reset(self):
        self.clicks = 0


class _ExportAsWorker(QThread):
    """Esegue la conversione di 'Esporta come...' in background (pandoc può
    richiedere fino a 30s su documenti grandi)."""

    completed = pyqtSignal(str, bool)  # messaggio di errore ("" se riuscito), cancelled

    def __init__(self, content: str, fmt_in: str, dest, convert):
        super().__init__()
        self._content = content
        self._fmt_in = fmt_in
        self._dest = dest
        self._convert = convert
        self._proc = None
        self._cancelled = False

    def _register_proc(self, proc) -> None:
        self._proc = proc

    def cancel(self) -> None:
        # Segna "annullato" solo se esiste davvero un subprocess in corso da
        # interrompere: alcuni formati (HTML, DOCX via htmldocx) non passano
        # mai da pandoc, quindi non c'è nulla da terminare e l'esportazione
        # va comunque completata e riportata con il suo esito reale.
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                self._cancelled = True
            except Exception:
                pass

    def run(self) -> None:
        err = self._convert(
            self._content, self._fmt_in, self._dest,
            register_proc=self._register_proc)
        self.completed.emit(err, self._cancelled)


class _EditorSaveWorker(QThread):
    """Scrive uno snapshot dell'editor senza bloccare il thread GUI."""

    completed = pyqtSignal(bool, str)

    def __init__(self, path: Path, content: str, encoding: str,
                 write_bom: bool, backup: bool):
        super().__init__()
        self._path = path
        self._content = content
        self._encoding = encoding
        self._write_bom = write_bom
        self._backup = backup

    def run(self) -> None:
        try:
            from core.file_manager import FileManager
            FileManager.write(
                self._path,
                self._content,
                self._encoding,
                write_bom=self._write_bom,
                backup=self._backup,
            )
        except Exception as exc:
            self.completed.emit(False, str(exc))
        else:
            self.completed.emit(True, "")
