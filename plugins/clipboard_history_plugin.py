"""
plugins/clipboard_history_plugin.py — Plugin Clipboard History
NotePadPQ

Mantiene una cronologia degli ultimi N elementi copiati negli appunti.
Funziona come il "Clipboard History" di Notepad++ (plugin più scaricato).

Funzionalità:
  - Cronologia ultimi 50 elementi (configurabile)
  - Pannello dock con lista scrollabile
  - Double-click → incolla nell'editor corrente
  - Ricerca nella cronologia
  - Cancellazione singola o totale
  - Persistenza su disco (tra sessioni)

Attivazione:
  Menu Plugin → Clipboard History
  Ctrl+Shift+V → apre il pannello
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel,
    QLineEdit, QApplication, QMenu, QSpinBox,
)

from plugins.base_plugin import BasePlugin

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Costanti ─────────────────────────────────────────────────────────────────

MAX_HISTORY    = 50      # massimo elementi in cronologia
MAX_PREVIEW    = 120     # caratteri di anteprima per elemento
POLL_INTERVAL  = 500     # ms tra un controllo e l'altro degli appunti


# ─── _ClipboardPanel ──────────────────────────────────────────────────────────

class _ClipboardPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw       = main_window
        self._history: List[str] = []    # testi completi
        self._last_text = ""

        self._load_history()
        self._build_ui()

        # Timer polling appunti
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_clipboard)
        self._timer.start(POLL_INTERVAL)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Barra superiore
        top = QHBoxLayout()
        top.addWidget(QLabel(f"Ultimi {MAX_HISTORY} elementi copiati:"))
        top.addStretch()
        btn_clear = QPushButton("🗑 Svuota")
        btn_clear.setFixedHeight(22)
        btn_clear.clicked.connect(self._clear_all)
        top.addWidget(btn_clear)
        layout.addLayout(top)

        # Ricerca
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtra cronologia…")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Lista cronologia
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._paste_item)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.setToolTip("Doppio clic per incollare nell'editor")
        layout.addWidget(self._list, 1)

        # Anteprima
        self._preview = QLabel("")
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet(
            "background: #2a2a2a; padding: 4px; border-radius: 3px; "
            "font-family: monospace; font-size: 11px; color: #ccc;"
        )
        self._preview.setMaximumHeight(60)
        self._preview.setMinimumHeight(40)
        layout.addWidget(self._preview)

        # Barra bassa
        bot = QHBoxLayout()
        self._count_label = QLabel("0 elementi")
        self._count_label.setStyleSheet("font-size: 11px; color: #888;")
        bot.addWidget(self._count_label, 1)
        btn_paste = QPushButton("Incolla selezionato")
        btn_paste.setFixedHeight(24)
        btn_paste.clicked.connect(self._paste_selected)
        bot.addWidget(btn_paste)
        layout.addLayout(bot)

        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._refresh_list()

    # ── Polling appunti ───────────────────────────────────────────────────────

    def _poll_clipboard(self) -> None:
        """Controlla se il contenuto degli appunti è cambiato."""
        cb = QApplication.clipboard()
        text = cb.text()
        if text and text != self._last_text:
            self._last_text = text
            self._add_to_history(text)

    def _add_to_history(self, text: str) -> None:
        if not text.strip():
            return
        # Rimuovi duplicato se presente
        if text in self._history:
            self._history.remove(text)
        # Inserisci in cima
        self._history.insert(0, text)
        # Tronca
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[:MAX_HISTORY]
        self._refresh_list()
        self._save_history()

    # ── Lista ─────────────────────────────────────────────────────────────────

    def _refresh_list(self, filter_text: str = "") -> None:
        self._list.clear()
        shown = 0
        for i, text in enumerate(self._history):
            if filter_text and filter_text.lower() not in text.lower():
                continue
            preview = text[:MAX_PREVIEW].replace("\n", "↵").replace("\t", "→")
            if len(text) > MAX_PREVIEW:
                preview += "…"
            item = QListWidgetItem(preview)
            item.setData(Qt.ItemDataRole.UserRole, i)   # indice in _history
            item.setToolTip(text[:500])
            self._list.addItem(item)
            shown += 1

        self._count_label.setText(
            f"{shown} elementi" if not filter_text
            else f"{shown} su {len(self._history)}"
        )

    def _filter(self, text: str) -> None:
        self._refresh_list(text)

    def _on_selection_changed(self, current: Optional[QListWidgetItem],
                              previous) -> None:
        if current is None:
            self._preview.clear()
            return
        idx = current.data(Qt.ItemDataRole.UserRole)
        if idx is not None and 0 <= idx < len(self._history):
            self._preview.setText(self._history[idx][:300])

    # ── Incolla ───────────────────────────────────────────────────────────────

    def _paste_item(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is not None and 0 <= idx < len(self._history):
            self._paste_text(self._history[idx])

    def _paste_selected(self) -> None:
        item = self._list.currentItem()
        if item:
            self._paste_item(item)

    def _paste_text(self, text: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            QApplication.clipboard().setText(text)
            return
        # Incolla direttamente sostituendo la selezione
        if editor.hasSelectedText():
            editor.replaceSelectedText(text)
        else:
            editor.insert(text)
        editor.setFocus()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        menu.addAction("Incolla nell'editor",    lambda: self._paste_item(item))
        menu.addAction("Copia negli appunti",    lambda: self._copy_to_clipboard(idx))
        menu.addSeparator()
        menu.addAction("Rimuovi dalla cronologia", lambda: self._remove(idx))
        menu.addAction("Svuota cronologia",        self._clear_all)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _copy_to_clipboard(self, idx: int) -> None:
        if 0 <= idx < len(self._history):
            QApplication.clipboard().setText(self._history[idx])

    def _remove(self, idx: int) -> None:
        if 0 <= idx < len(self._history):
            self._history.pop(idx)
            self._refresh_list(self._search.text())
            self._save_history()

    def _clear_all(self) -> None:
        self._history.clear()
        self._last_text = ""
        self._refresh_list()
        self._save_history()

    # ── Persistenza ───────────────────────────────────────────────────────────

    def _history_path(self) -> Path:
        from core.platform import get_data_dir
        return get_data_dir() / "clipboard_history.json"

    def _load_history(self) -> None:
        try:
            p = self._history_path()
            if p.exists():
                self._history = json.loads(p.read_text(encoding="utf-8"))
                self._last_text = self._history[0] if self._history else ""
        except Exception:
            self._history = []

    def _save_history(self) -> None:
        try:
            self._history_path().write_text(
                json.dumps(self._history[:MAX_HISTORY], ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def stop(self) -> None:
        self._timer.stop()


# ─── Plugin ───────────────────────────────────────────────────────────────────

class ClipboardHistoryPlugin(BasePlugin):

    NAME        = "Clipboard History"
    VERSION     = "1.0"
    DESCRIPTION = (
        "Cronologia appunti: mantiene gli ultimi 50 testi copiati "
        "con anteprima, ricerca e incolla rapido nell'editor."
    )
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._panel = _ClipboardPanel(main_window)

        self._dock = QDockWidget("📋  Clipboard History", main_window)
        self._dock.setObjectName("ClipboardHistoryDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(220)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
        self._dock.hide()

        self.add_menu_action(
            main_window, "plugins",
            "📋 Clipboard History",
            self._toggle,
            shortcut="Ctrl+Shift+V"
        )
        main_window._menus["plugins"].menuAction().setVisible(True)

    def _toggle(self) -> None:
        self._dock.setVisible(not self._dock.isVisible())

    def on_unload(self) -> None:
        if hasattr(self, "_panel"):
            self._panel.stop()
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()
