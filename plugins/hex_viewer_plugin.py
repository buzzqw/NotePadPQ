"""
plugins/hex_viewer_plugin.py — Plugin Hex Viewer
NotePadPQ

Visualizza il file corrente in modalità esadecimale read-only,
stile classico: offset | hex bytes | ASCII printable.
Layout a 16 byte per riga, offset a 8 cifre hex.

Attivazione:
  Menu Plugin → Hex Viewer
  oppure Ctrl+Alt+H
"""

from __future__ import annotations

import mmap
import threading
from pathlib import Path
from typing import BinaryIO, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QLineEdit, QSpinBox,
)
from PyQt6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Costanti ─────────────────────────────────────────────────────────────────

BYTES_PER_ROW = 16
MAX_BYTES     = 4 * 1024 * 1024   # Mostra max 4MB (oltre è lento con QTextEdit)
SEARCH_CHUNK  = 4 * 1024 * 1024

_ORPHANED_SEARCH_WORKERS: set[QThread] = set()


class _HexSearchWorker(QThread):
    """Cerca a blocchi, con un mapping indipendente e cancellabile."""

    completed = pyqtSignal(int, str)

    def __init__(self, source: Path | bytes, needle: bytes):
        super().__init__()
        self._source = source
        self._needle = needle
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        handle = None
        mapped = None
        try:
            if isinstance(self._source, Path):
                handle = self._source.open("rb")
                size = self._source.stat().st_size
                if not size:
                    self.completed.emit(-1, "")
                    return
                mapped = mmap.mmap(handle.fileno(), length=0, access=mmap.ACCESS_READ)
                source = mapped
            else:
                source = self._source
                size = len(source)

            overlap = max(0, len(self._needle) - 1)
            offset = 0
            while offset < size and not self._cancelled.is_set():
                end = min(size, offset + SEARCH_CHUNK + overlap)
                found = source[offset:end].find(self._needle)
                if found >= 0:
                    self.completed.emit(offset + found, "")
                    return
                offset += SEARCH_CHUNK
            if not self._cancelled.is_set():
                self.completed.emit(-1, "")
        except (OSError, ValueError) as exc:
            if not self._cancelled.is_set():
                self.completed.emit(-1, str(exc))
        finally:
            if mapped is not None:
                mapped.close()
            if handle is not None:
                handle.close()


# ─── _HexPanel ────────────────────────────────────────────────────────────────

class _HexPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._raw: Optional[bytes] = b""
        self._file: Optional[BinaryIO] = None
        self._mapped: Optional[mmap.mmap] = None
        self._source_path: Optional[Path] = None
        self._size = 0
        self._search_worker: Optional[_HexSearchWorker] = None
        self._search_generation = 0
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Barra superiore
        top = QHBoxLayout()
        self._file_label = QLabel("Nessun file")
        self._file_label.setStyleSheet("font-size: 11px; color: #888;")
        top.addWidget(self._file_label, 1)

        btn_load = QPushButton("⟳ Carica file corrente")
        btn_load.setFixedHeight(24)
        btn_load.clicked.connect(self.load_current)
        top.addWidget(btn_load)
        layout.addLayout(top)

        # Ricerca byte
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Cerca byte (hex):"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("es. 4D 5A  oppure  FF FE")
        self._search_input.setMaximumWidth(200)
        search_row.addWidget(self._search_input)
        self._btn_search = QPushButton("Cerca")
        self._btn_search.setFixedWidth(70)
        self._btn_search.clicked.connect(self._search_bytes)
        search_row.addWidget(self._btn_search)
        search_row.addStretch()

        search_row.addWidget(QLabel("Offset iniziale:"))
        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(0, 0)
        self._offset_spin.setSingleStep(256)
        self._offset_spin.valueChanged.connect(self._render_from_offset)
        search_row.addWidget(self._offset_spin)
        layout.addLayout(search_row)

        # Vista hex
        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setFont(QFont("Monospace", 10))
        self._view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._view.setStyleSheet("background: #1a1a1a; color: #d4d4d4;")
        layout.addWidget(self._view, 1)

        # Info
        self._info = QLabel("")
        self._info.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self._info)

    # ── Caricamento ───────────────────────────────────────────────────────────

    def load_current(self) -> None:
        """Carica il file del tab corrente."""
        self.close_source()
        editor = self._mw._tab_manager.current_editor()
        if not editor or not editor.file_path:
            self._view.setPlainText("(Nessun file aperto)")
            return

        path = editor.file_path
        if not path.exists():
            self._view.setPlainText("(File non trovato su disco)")
            return

        try:
            self._file = path.open("rb")
            self._size = path.stat().st_size
            if self._size:
                self._mapped = mmap.mmap(
                    self._file.fileno(), length=0, access=mmap.ACCESS_READ
                )
            self._raw = None
            self._source_path = path
        except Exception as e:
            self.close_source()
            self._view.setPlainText(f"Errore lettura: {e}")
            return

        size = self._size
        self._file_label.setText(f"{path.name}  ({size:,} byte)")
        self._offset_spin.setMaximum(max(0, size - BYTES_PER_ROW))
        self._offset_spin.setValue(0)

        truncated = size > MAX_BYTES
        self._info.setText(
            f"Dimensione: {size:,} byte"
            + (f"  (visualizzati primi {MAX_BYTES // 1024}KB)" if truncated else "")
        )
        self._render_from_offset(0)

    def load_bytes(self, raw: bytes, label: str = "") -> None:
        """Carica bytes direttamente (usato da test/altri plugin)."""
        self.close_source()
        self._raw = raw
        self._source_path = None
        self._size = len(raw)
        self._file_label.setText(label or f"{len(raw):,} byte")
        self._offset_spin.setMaximum(max(0, len(raw) - BYTES_PER_ROW))
        self._offset_spin.setValue(0)
        self._render_from_offset(0)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_from_offset(self, offset: int) -> None:
        data = self._read_window(offset, MAX_BYTES)
        lines = []
        for i in range(0, len(data), BYTES_PER_ROW):
            chunk = data[i:i + BYTES_PER_ROW]
            abs_offset = offset + i
            hex_part  = " ".join(f"{b:02X}" for b in chunk)
            hex_part  = hex_part.ljust(BYTES_PER_ROW * 3 - 1)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "·" for b in chunk)
            lines.append(f"{abs_offset:08X}  {hex_part}  │{ascii_part}│")

        self._view.setPlainText("\n".join(lines))

    def _read_window(self, offset: int, length: int) -> bytes:
        end = min(self._size, offset + length)
        if offset < 0 or offset >= end:
            return b""
        if self._mapped is not None:
            return self._mapped[offset:end]
        return (self._raw or b"")[offset:end]

    def close_source(self) -> None:
        """Rilascia mapping e descrittore prima di caricare un'altra sorgente."""
        self._stop_search_worker()
        if self._mapped is not None:
            self._mapped.close()
            self._mapped = None
        if self._file is not None:
            self._file.close()
            self._file = None
        self._raw = b""
        self._source_path = None
        self._size = 0

    # ── Ricerca byte ──────────────────────────────────────────────────────────

    def _search_bytes(self) -> None:
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
            self._info.setText("Annullamento ricerca…")
            return
        hex_str = self._search_input.text().strip()
        if not hex_str:
            return
        try:
            needle = bytes.fromhex(hex_str.replace(" ", ""))
        except ValueError:
            self._info.setText("⚠ Sequenza hex non valida")
            return

        source: Path | bytes
        source = self._source_path if self._source_path is not None else (self._raw or b"")
        self._search_generation += 1
        generation = self._search_generation
        worker = _HexSearchWorker(source, needle)
        self._search_worker = worker
        self._btn_search.setText("Annulla")
        self._info.setText("Ricerca in corso…")
        worker.completed.connect(
            lambda pos, error, g=generation, text=hex_str:
                self._search_completed(pos, error, text, g))
        worker.finished.connect(lambda w=worker: self._search_thread_finished(w))
        worker.start()

    def _search_completed(self, pos: int, error: str, hex_str: str,
                          generation: int) -> None:
        if generation != self._search_generation:
            return
        self._btn_search.setText("Cerca")
        if error:
            self._info.setText(f"Errore ricerca: {error}")
            return
        if pos == -1:
            self._info.setText(f"Byte non trovati: {hex_str}")
            return

        # Salta all'offset trovato
        aligned = (pos // BYTES_PER_ROW) * BYTES_PER_ROW
        self._offset_spin.setValue(aligned)
        self._info.setText(f"✓ Trovato a offset 0x{pos:08X} ({pos:,})")

        # Evidenzia la riga
        row_in_view = (pos - aligned) // BYTES_PER_ROW
        doc = self._view.document()
        block = doc.findBlockByNumber(row_in_view)
        cursor = QTextCursor(block)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#2a4a2a"))
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        cursor.setCharFormat(fmt)
        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()

    def _search_thread_finished(self, worker: _HexSearchWorker) -> None:
        if self._search_worker is worker:
            self._search_worker = None
            self._btn_search.setText("Cerca")
        worker.deleteLater()

    def _stop_search_worker(self) -> None:
        worker = self._search_worker
        self._search_generation += 1
        if worker:
            if worker.isRunning():
                worker.cancel()
            worker.disconnect()
            if worker.isRunning() and not worker.wait(2000):
                _ORPHANED_SEARCH_WORKERS.add(worker)
                worker.finished.connect(
                    lambda w=worker: _ORPHANED_SEARCH_WORKERS.discard(w))
                if not worker.isRunning():
                    _ORPHANED_SEARCH_WORKERS.discard(worker)
        self._search_worker = None
        if hasattr(self, "_btn_search"):
            self._btn_search.setText("Cerca")


# ─── Plugin ───────────────────────────────────────────────────────────────────

class HexViewerPlugin(BasePlugin):

    NAME        = "Hex Viewer"
    VERSION     = "1.0"
    DESCRIPTION = "Visualizza il file corrente in formato esadecimale (read-only)."
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._panel = _HexPanel(main_window)

        self._dock = QDockWidget(tr("hex_viewer.dock_title"), main_window)
        self._dock.setObjectName("HexViewerDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(600)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._dock)
        self._dock.hide()

        self.add_menu_action(
            main_window, "plugins",
            tr("hex_viewer.menu"),
            self._toggle,
            shortcut="Ctrl+Alt+H",
            icon_key="plugin_hex"
        )
        main_window._menus["plugins"].menuAction().setVisible(True)

    def _toggle(self) -> None:
        if self._dock.isVisible():
            self._dock.hide()
        else:
            self._dock.show()
            self._panel.load_current()

    def on_editor_changed(self, editor) -> None:
        if hasattr(self, "_dock") and self._dock.isVisible():
            self._panel.load_current()

    def on_file_opened(self, path) -> None:
        if hasattr(self, "_dock") and self._dock.isVisible():
            self._panel.load_current()

    def on_unload(self) -> None:
        if hasattr(self, "_panel"):
            self._panel.close_source()
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()
