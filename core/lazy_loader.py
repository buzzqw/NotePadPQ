"""
core/lazy_loader.py — Caricamento lazy per file di grandi dimensioni
NotePadPQ

Per file oltre la soglia (default 50MB, configurabile), il file viene
caricato in chunks nel thread di background. L'editor mostra subito
il primo chunk e aggiunge il resto progressivamente senza bloccare l'UI.

Per file oltre 1GB viene usata la modalità "view-only": il file viene
letto a pagine (chunk da 4MB), con navigazione tramite un cursore
virtuale sul disco. In questo caso l'editor è READ-ONLY per non
corrompere file enormi.

API:
    loader = LazyLoader(path, editor, main_window)
    loader.start()           # avvia il caricamento in background
    loader.cancel()          # annulla (es. tab chiuso)

    # Oppure, per file non enormi, usa il wrapper diretto:
    LazyLoader.open_file(path, editor, main_window)
"""

from __future__ import annotations

import io
import os
import threading
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QProgressDialog, QApplication, QLabel, QPushButton

from core.file_manager import FileManager
from editor.editor_widget import LineEnding

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget
    from ui.main_window import MainWindow

# ─── Soglie ───────────────────────────────────────────────────────────────────

MB  = 1024 * 1024
GB  = 1024 * MB

# Sotto questa soglia → caricamento normale sincrono
THRESHOLD_LAZY     = 50 * MB      # 50 MB

# Sopra questa soglia → modalità paged (sola lettura, cursore virtuale su disco)
THRESHOLD_PAGED    = 1 * GB       # 1 GB

# Dimensione chunk per loading progressivo (in bytes)
CHUNK_SIZE_BYTES   = 4 * MB       # 4 MB per chunk
CHUNK_SIZE_PAGED   = 4 * MB       # idem per paged mode

# Delay tra chunk successivi in ms (lascia respiro all'event loop)
CHUNK_DELAY_MS     = 30


# ─── _LoadWorker ──────────────────────────────────────────────────────────────

class _LoadWorker(QObject):
    """
    Worker che gira in un QThread separato e legge il file a chunks.
    Emette chunk_ready(str) per ogni porzione di testo letta,
    finished() quando ha finito o cancelled() se interrotto.
    """

    chunk_ready = pyqtSignal(str, int, int)  # text, chunk_index, total_chunks
    finished    = pyqtSignal(str, str)       # encoding, line_ending_label
    error       = pyqtSignal(str)

    def __init__(self, path: Path):
        super().__init__()
        self._path     = path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        """Eseguito nel thread di background."""
        try:
            file_size = self._path.stat().st_size

            # Rilevamento encoding dal header del file (primi 8KB)
            with open(self._path, "rb") as f:
                header = f.read(8192)

            encoding, bom_len = FileManager._detect_bom(header)
            if not encoding:
                encoding = FileManager._chardet_detect(header) or "UTF-8"

            # Calcola numero di chunk approssimativo
            total_chunks = max(1, file_size // CHUNK_SIZE_BYTES + 1)
            chunk_idx = 0
            detected_le = None

            with open(self._path, "rb") as f:
                # Salta BOM se presente
                if bom_len:
                    f.seek(bom_len)

                buffer = b""
                while True:
                    if self._cancelled:
                        return

                    raw = f.read(CHUNK_SIZE_BYTES)
                    if not raw:
                        break

                    buffer += raw

                    # Decodifica sicura: ritaglia alla fine dell'ultimo \n
                    # per non spezzare sequenze multibyte a metà
                    split_pos = buffer.rfind(b"\n")
                    if split_pos == -1 or f.peek(1):
                        # Non c'è ancora un \n o siamo nel mezzo del file:
                        # prova a decodificare tutto
                        try:
                            text = buffer.decode(encoding, errors="replace")
                            buffer = b""
                        except Exception:
                            text = buffer.decode("latin-1", errors="replace")
                            buffer = b""
                    else:
                        decode_part = buffer[:split_pos + 1]
                        buffer = buffer[split_pos + 1:]
                        try:
                            text = decode_part.decode(encoding, errors="replace")
                        except Exception:
                            text = decode_part.decode("latin-1", errors="replace")

                    if detected_le is None and text:
                        detected_le = LineEnding.detect(text)

                    self.chunk_ready.emit(text, chunk_idx, total_chunks)
                    chunk_idx += 1

                # Eventuale coda
                if buffer and not self._cancelled:
                    try:
                        text = buffer.decode(encoding, errors="replace")
                    except Exception:
                        text = buffer.decode("latin-1", errors="replace")
                    self.chunk_ready.emit(text, chunk_idx, total_chunks)

            le_label = (detected_le.label() if detected_le else "LF")
            enc_display = encoding.upper().replace("-SIG", " BOM")
            self.finished.emit(enc_display, le_label)

        except Exception as e:
            self.error.emit(str(e))


# ─── PagedFileView ────────────────────────────────────────────────────────────

class PagedFileView:
    """
    Vista paginata su un file enorme (>1GB). Legge pagine dal disco on-demand
    senza mai caricare l'intero file in memoria.

    Usato da LazyLoader in modalità PAGED per attacharsi a un EditorWidget
    e caricare la pagina corrente (read-only).
    """

    def __init__(self, path: Path):
        self._path = path
        self._file_size = path.stat().st_size
        self._page_size = CHUNK_SIZE_PAGED
        self._current_page = 0
        self._total_pages = max(1, self._file_size // self._page_size + 1)

        # Encoding rilevato dall'header
        with open(path, "rb") as f:
            header = f.read(8192)
        enc, self._bom_len = FileManager._detect_bom(header)
        self._encoding = enc or FileManager._chardet_detect(header) or "UTF-8"

    @property
    def total_pages(self) -> int:
        return self._total_pages

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def file_size_mb(self) -> float:
        return self._file_size / MB

    def read_page(self, page: int) -> str:
        """Legge e restituisce la pagina N (0-based)."""
        page = max(0, min(page, self._total_pages - 1))
        self._current_page = page

        offset = self._bom_len + page * self._page_size
        with open(self._path, "rb") as f:
            f.seek(offset)
            raw = f.read(self._page_size)

        try:
            return raw.decode(self._encoding, errors="replace")
        except Exception:
            return raw.decode("latin-1", errors="replace")

    def next_page(self) -> Optional[str]:
        if self._current_page + 1 >= self._total_pages:
            return None
        return self.read_page(self._current_page + 1)

    def prev_page(self) -> Optional[str]:
        if self._current_page <= 0:
            return None
        return self.read_page(self._current_page - 1)

    def encoding(self) -> str:
        return self._encoding.upper().replace("-SIG", " BOM")


# ─── LazyLoader ───────────────────────────────────────────────────────────────

class LazyLoader(QObject):
    """
    Gestisce il caricamento di file grandi in un EditorWidget.

    Modalità:
    - NORMAL  (<50MB):  caricamento sincrono standard (delega a FileManager)
    - LAZY    (50MB–1GB): caricamento progressivo in background con progress bar
    - PAGED   (>1GB):   vista paginata read-only, naviga con Pg↑/Pg↓

    Uso standard:
        LazyLoader.open_file(path, editor, main_window)
    """

    # Segnali
    load_started   = pyqtSignal(str)          # modalità: "normal"/"lazy"/"paged"
    progress       = pyqtSignal(int)          # 0–100
    load_finished  = pyqtSignal()
    load_error     = pyqtSignal(str)

    # Soglie (ridefinibili via config)
    THRESHOLD_LAZY  = THRESHOLD_LAZY
    THRESHOLD_PAGED = THRESHOLD_PAGED

    def __init__(self, path: Path, editor: "EditorWidget",
                 main_window: Optional["MainWindow"] = None):
        super().__init__()
        self._path        = path
        self._editor      = editor
        self._mw          = main_window
        self._thread      = None
        self._worker      = None
        self._progress_dlg: Optional[QProgressDialog] = None
        self._cancelled   = False
        self._paged_view: Optional[PagedFileView] = None
        self._accumulated = []   # chunks accumulati prima dell'append

    # ── Entry point statico ───────────────────────────────────────────────────

    @staticmethod
    def open_file(path: Path, editor: "EditorWidget",
                  main_window=None) -> "LazyLoader":
        """
        Apre path nell'editor con la strategia appropriata.
        Restituisce il LazyLoader per permettere cancel() se necessario.
        """
        loader = LazyLoader(path, editor, main_window)
        loader.start()
        return loader

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Avvia il caricamento con la strategia più adatta alla dimensione."""
        try:
            file_size = self._path.stat().st_size
        except OSError as e:
            self.load_error.emit(str(e))
            return

        if file_size >= self.THRESHOLD_PAGED:
            self._start_paged(file_size)
        elif file_size >= self.THRESHOLD_LAZY:
            self._start_lazy(file_size)
        else:
            self._start_normal()

    # ── Modalità NORMAL ───────────────────────────────────────────────────────

    def _start_normal(self) -> None:
        self.load_started.emit("normal")
        try:
            content, encoding, le = FileManager.read(self._path)
            self._editor.load_content(content, encoding, le)
            self.load_finished.emit()
        except Exception as e:
            self.load_error.emit(str(e))

    # ── Modalità LAZY ─────────────────────────────────────────────────────────

    def _start_lazy(self, file_size: int) -> None:
        self.load_started.emit("lazy")

        size_mb = file_size / MB
        self._show_progress(
            f"Apertura file ({size_mb:.1f} MB)…",
            "Il file è di grandi dimensioni. Caricamento in corso…"
        )

        # Thread di lettura
        self._worker = _LoadWorker(self._path)
        self._worker.chunk_ready.connect(self._on_chunk_ready)
        self._worker.finished.connect(self._on_lazy_finished)
        self._worker.error.connect(self._on_error)

        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

    def _on_chunk_ready(self, text: str, chunk_idx: int, total_chunks: int) -> None:
        if self._cancelled:
            return

        # Primo chunk: load_content (inizializza encoding/lexer)
        if chunk_idx == 0:
            self._editor.beginUndoAction()
            le = LineEnding.detect(text)
            self._editor.load_content(text, "UTF-8", le)
        else:
            # Append al fondo del documento
            end_line = self._editor.lines() - 1
            end_col  = len(self._editor.text(end_line))
            self._editor.insertAt(text, end_line, end_col)

        # Aggiorna progress bar
        pct = min(99, int((chunk_idx + 1) / max(1, total_chunks) * 100))
        self.progress.emit(pct)
        if self._progress_dlg:
            self._progress_dlg.setValue(pct)
            QApplication.processEvents()

    def _on_lazy_finished(self, encoding: str, le_label: str) -> None:
        self._editor.endUndoAction()
        # Aggiorna encoding/le definitivi
        self._editor.set_encoding(encoding)
        try:
            le = LineEnding[le_label]
            self._editor.set_line_ending(le)
        except (KeyError, AttributeError):
            pass
        # Torna all'inizio del file
        self._editor.setCursorPosition(0, 0)
        self._editor.ensureLineVisible(0)
        self._close_progress()
        self.progress.emit(100)
        self.load_finished.emit()

    # ── Modalità PAGED ────────────────────────────────────────────────────────

    def _start_paged(self, file_size: int) -> None:
        self.load_started.emit("paged")

        try:
            self._paged_view = PagedFileView(self._path)
        except Exception as e:
            self.load_error.emit(str(e))
            return

        size_gb = file_size / GB
        page_text = self._paged_view.read_page(0)
        le = LineEnding.detect(page_text)
        self._editor.load_content(page_text, self._paged_view.encoding(), le)

        # File enorme → sola lettura per sicurezza
        self._editor.set_read_only(True)

        # Barra di stato con info paginazione
        self._attach_pager_ui()

        self._show_paged_notice(size_gb)
        self.load_finished.emit()

    def _attach_pager_ui(self) -> None:
        """
        Aggiunge una barra di navigazione pagine alla statusbar di MainWindow.
        La barra persiste finché il tab rimane aperto.
        """
        if self._mw is None:
            return

        pv = self._paged_view
        editor = self._editor

        from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
        pager = QWidget()
        layout = QHBoxLayout(pager)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)

        lbl = QLabel()

        def _update_label():
            lbl.setText(
                f"📄 Pagina {pv.current_page + 1}/{pv.total_pages}  "
                f"({pv.file_size_mb:.0f} MB)  [SOLA LETTURA]"
            )

        btn_prev = QPushButton("◀ Pag. prec.")
        btn_next = QPushButton("Pag. succ. ▶")
        btn_prev.setFixedHeight(20)
        btn_next.setFixedHeight(20)

        def _go_prev():
            text = pv.prev_page()
            if text:
                le = LineEnding.detect(text)
                editor.load_content(text, pv.encoding(), le)
                editor.set_read_only(True)
                _update_label()

        def _go_next():
            text = pv.next_page()
            if text:
                le = LineEnding.detect(text)
                editor.load_content(text, pv.encoding(), le)
                editor.set_read_only(True)
                _update_label()

        btn_prev.clicked.connect(_go_prev)
        btn_next.clicked.connect(_go_next)

        layout.addWidget(btn_prev)
        layout.addWidget(lbl)
        layout.addWidget(btn_next)

        _update_label()

        # Aggiunge alla statusbar come widget permanente
        try:
            self._mw.statusBar().addPermanentWidget(pager)
            self._pager_widget = pager   # tienilo vivo
        except Exception:
            pass

    def _show_paged_notice(self, size_gb: float) -> None:
        if self._mw is None:
            return
        self._mw.statusBar().showMessage(
            f"⚠ File enorme ({size_gb:.2f} GB): modalità sola lettura, "
            f"navigazione a pagine attiva. Pagina 1/{self._paged_view.total_pages}.",
            8000
        )

    # ── Annullamento ──────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Annulla il caricamento (da chiamare quando il tab viene chiuso)."""
        self._cancelled = True
        if self._worker:
            self._worker.cancel()
        self._close_progress()

    # ── Progress dialog ───────────────────────────────────────────────────────

    def _show_progress(self, title: str, text: str) -> None:
        if self._mw is None:
            return
        dlg = QProgressDialog(text, "Annulla", 0, 100, self._mw)
        dlg.setWindowTitle(title)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(500)
        dlg.setValue(0)
        dlg.canceled.connect(self.cancel)
        dlg.show()
        self._progress_dlg = dlg

    def _close_progress(self) -> None:
        if self._progress_dlg:
            try:
                self._progress_dlg.close()
            except Exception:
                pass
            self._progress_dlg = None

    def _on_error(self, msg: str) -> None:
        self._close_progress()
        self.load_error.emit(msg)

    # ── Informazioni stato ────────────────────────────────────────────────────

    def is_paged(self) -> bool:
        return self._paged_view is not None

    def paged_view(self) -> Optional[PagedFileView]:
        return self._paged_view
