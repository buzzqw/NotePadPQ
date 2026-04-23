"""
plugins/compare_plugin.py — Plugin Compare & Merge (v1.4)
NotePadPQ

Miglioramenti:
- Fix NameError (_COLOR_NONE)
- Logica di merge bidirezionale corretta
- Highlight azzurro per il blocco attivo
- Sincronizzazione automatica della vista dopo il merge
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List, Tuple
import difflib
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QTextEdit, QPushButton, QLabel, QComboBox,
    QDialogButtonBox, QFileDialog, QWidget, QCheckBox, QMessageBox
)
from PyQt6.QtGui import QColor, QTextCharFormat, QFont, QTextCursor

from plugins.base_plugin import BasePlugin

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# ─── Configurazione Colori (Ottimizzati per leggibilità) ─────────────────────
_COLOR_ADD      = QColor("#e6ffed")  # Verde pastello (GitHub style)
_COLOR_DEL      = QColor("#ffeef0")  # Rosso pastello
_COLOR_CHG      = QColor("#fffdef")  # Giallo pastello
_COLOR_ACTIVE   = QColor("#d1e9ff")  # Azzurro per il blocco selezionato
_COLOR_NONE     = QColor("transparent") 
_COLOR_TEXT     = QColor("#24292e")  # Testo scuro ad alto contrasto

class CompareDialog(QDialog):
    """Finestra di confronto e merge side-by-side."""
    
    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self.setWindowTitle("Compare & Merge Files")
        self.resize(1100, 750)
        
        # Stato del confronto
        self._lines_a: List[str] = []
        self._lines_b: List[str] = []
        self._opcodes: List[Tuple] = []
        self._diff_blocks: List[int] = [] 
        self._diff_idx = -1
        self._source_data: dict[str, str] = {}

        self._build_ui()
        self._populate_sources()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Toolbar Selezione
        top = QHBoxLayout()
        top.addWidget(QLabel("A:"))
        self._src_a = QComboBox()
        self._src_a.setMinimumWidth(220)
        top.addWidget(self._src_a)
        
        btn_file_a = QPushButton("📂")
        btn_file_a.setFixedWidth(30)
        btn_file_a.clicked.connect(lambda: self._pick_file("a"))
        top.addWidget(btn_file_a)

        top.addWidget(QLabel(" B:"))
        self._src_b = QComboBox()
        self._src_b.setMinimumWidth(220)
        top.addWidget(self._src_b)
        
        btn_file_b = QPushButton("📂")
        btn_file_b.setFixedWidth(30)
        btn_file_b.clicked.connect(lambda: self._pick_file("b"))
        top.addWidget(btn_file_b)

        self._ignore_ws = QCheckBox("Ignora spazi")
        top.addWidget(self._ignore_ws)

        btn_compare = QPushButton("⇄ Confronta")
        btn_compare.setStyleSheet("font-weight: bold; padding: 0 10px;")
        btn_compare.clicked.connect(self._run_compare)
        top.addWidget(btn_compare)
        layout.addLayout(top)

        # Toolbar Navigazione e Merge
        nav = QHBoxLayout()
        self._diff_label = QLabel("Differenze: 0")
        nav.addWidget(self._diff_label)
        
        btn_prev = QPushButton("▲ Prec.")
        btn_next = QPushButton("▼ Succ.")
        btn_prev.clicked.connect(self._prev_diff)
        btn_next.clicked.connect(self._next_diff)
        nav.addWidget(btn_prev)
        nav.addWidget(btn_next)
        
        nav.addSpacing(30)
        self._btn_to_right = QPushButton("Copia A ➔ B")
        self._btn_to_left = QPushButton("Copia B ➔ A")
        self._btn_to_right.setStyleSheet("background-color: #f0fff0; border: 1px solid #c0e0c0;")
        self._btn_to_left.setStyleSheet("background-color: #f0fff0; border: 1px solid #c0e0c0;")
        
        self._btn_to_right.clicked.connect(lambda: self._merge_action("right"))
        self._btn_to_left.clicked.connect(lambda: self._merge_action("left"))
        nav.addWidget(self._btn_to_left)
        nav.addWidget(self._btn_to_right)
        
        nav.addStretch()
        layout.addLayout(nav)

        # Area di visualizzazione
        splitter = QSplitter(Qt.Orientation.Horizontal)
        mono = QFont("Monospace", 10)

        self._view_a = QTextEdit()
        self._view_b = QTextEdit()
        for v in [self._view_a, self._view_b]:
            v.setReadOnly(True)
            v.setFont(mono)
            v.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            v.setStyleSheet("background-color: white; color: #24292e;")

        splitter.addWidget(self._view_a)
        splitter.addWidget(self._view_b)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)

        # Sincronizzazione scroll
        self._view_a.verticalScrollBar().valueChanged.connect(self._view_b.verticalScrollBar().setValue)
        self._view_b.verticalScrollBar().valueChanged.connect(self._view_a.verticalScrollBar().setValue)

        # Footer Azioni
        footer = QHBoxLayout()
        btn_apply = QPushButton("✅ Salva modifiche negli editor di NotePadPQ")
        btn_apply.setHeight = 35
        btn_apply.clicked.connect(self._apply_to_editors)
        footer.addWidget(btn_apply)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.accept)
        footer.addStretch()
        footer.addWidget(btns)
        layout.addLayout(footer)

    def _populate_sources(self) -> None:
        """Carica i tab correnti."""
        editors = self._mw._tab_manager.all_editors()
        self._src_a.clear()
        self._src_b.clear()
        for i, ed in enumerate(editors):
            name = ed.file_path.name if ed.file_path else f"(Tab {i+1}) Senza nome"
            self._source_data[name] = ed.get_content()
            self._src_a.addItem(name)
            self._src_b.addItem(name)
        if self._src_b.count() > 1:
            self._src_b.setCurrentIndex(1)

    def _pick_file(self, side: str) -> None:
        """Apre un file esterno."""
        path, _ = QFileDialog.getOpenFileName(self, "Apri file", "", "Tutti (*)")
        if path:
            p = Path(path)
            text = p.read_text(encoding="utf-8", errors="replace")
            name = f"[File] {p.name}"
            self._source_data[name] = text
            combo = self._src_a if side == "a" else self._src_b
            combo.addItem(name)
            combo.setCurrentText(name)

    def _run_compare(self) -> None:
        """Esegue l'algoritmo di diff."""
        text_a = self._source_data.get(self._src_a.currentText(), "")
        text_b = self._source_data.get(self._src_b.currentText(), "")

        self._lines_a = text_a.splitlines(keepends=True)
        self._lines_b = text_b.splitlines(keepends=True)

        matcher = difflib.SequenceMatcher(None, 
            [l.strip() if self._ignore_ws.isChecked() else l for l in self._lines_a], 
            [l.strip() if self._ignore_ws.isChecked() else l for l in self._lines_b], 
            autojunk=False)

        self._opcodes = matcher.get_opcodes()
        self._diff_blocks = [i for i, op in enumerate(self._opcodes) if op[0] != 'equal']
        
        # Reset posizione se necessario
        if not self._diff_blocks:
            self._diff_idx = -1
        elif self._diff_idx >= len(self._diff_blocks):
            self._diff_idx = 0

        self._render_diff()
        self._update_ui_state()
        self._diff_label.setText(f"Differenze: {len(self._diff_blocks)}")

    def _render_diff(self) -> None:
        """Ridisegna il testo con i colori corretti."""
        self._view_a.clear()
        self._view_b.clear()
        
        cursor_a = self._view_a.textCursor()
        cursor_b = self._view_b.textCursor()

        def _append(cursor, text, bg: QColor):
            fmt = QTextCharFormat()
            fmt.setBackground(bg)
            fmt.setForeground(_COLOR_TEXT)
            cursor.insertText(text, fmt)

        active_opcode_idx = self._diff_blocks[self._diff_idx] if (self._diff_idx >= 0 and self._diff_blocks) else -1

        for idx, (tag, i1, i2, j1, j2) in enumerate(self._opcodes):
            is_active = (idx == active_opcode_idx)
            chunk_a = "".join(self._lines_a[i1:i2])
            chunk_b = "".join(self._lines_b[j1:j2])

            # Calcolo colori con gestione del blocco attivo
            if tag == "equal":
                bg_a = bg_b = _COLOR_NONE
            elif tag == "replace":
                bg_a = _COLOR_ACTIVE if is_active else _COLOR_CHG
                bg_b = _COLOR_ACTIVE if is_active else _COLOR_CHG
            elif tag == "delete":
                bg_a = _COLOR_ACTIVE if is_active else _COLOR_DEL
                bg_b = _COLOR_DEL
                chunk_b = "\n" * (i2 - i1) # Padding per mantenere l'allineamento
            elif tag == "insert":
                bg_a = _COLOR_ADD
                bg_b = _COLOR_ACTIVE if is_active else _COLOR_ADD
                chunk_a = "\n" * (j2 - j1) # Padding

            _append(cursor_a, chunk_a, bg_a)
            _append(cursor_b, chunk_b, bg_b)

    def _update_ui_state(self) -> None:
        """Abilita/disabilita i pulsanti di merge."""
        valid = (self._diff_idx >= 0 and self._diff_idx < len(self._diff_blocks))
        self._btn_to_right.setEnabled(valid)
        self._btn_to_left.setEnabled(valid)

    def _goto_diff(self, idx: int) -> None:
        """Sposta la vista alla differenza specificata."""
        if not self._diff_blocks: return
        self._diff_idx = idx % len(self._diff_blocks)
        
        opcode_idx = self._diff_blocks[self._diff_idx]
        _, i1, _, _, _ = self._opcodes[opcode_idx]
        
        self._render_diff() # Aggiorna l'highlight blu
        
        block = self._view_a.document().findBlockByLineNumber(i1)
        cursor = QTextCursor(block)
        self._view_a.setTextCursor(cursor)
        self._view_a.ensureCursorVisible()
        self._update_ui_state()

    def _merge_action(self, direction: str) -> None:
        """Esegue il merge fisico delle linee."""
        if self._diff_idx < 0: return
        
        opcode_idx = self._diff_blocks[self._diff_idx]
        tag, i1, i2, j1, j2 = self._opcodes[opcode_idx]

        if direction == "right":
            self._lines_b[j1:j2] = self._lines_a[i1:i2]
        else:
            self._lines_a[i1:i2] = self._lines_b[j1:j2]

        # Aggiorna i dati temporanei
        self._source_data[self._src_a.currentText()] = "".join(self._lines_a)
        self._source_data[self._src_b.currentText()] = "".join(self._lines_b)
        
        old_idx = self._diff_idx
        self._run_compare() # Ricalcola il diff
        
        if self._diff_blocks:
            # Rimani sulla stessa posizione (o l'ultima valida)
            self._goto_diff(min(old_idx, len(self._diff_blocks) - 1))
        else:
            self._diff_idx = -1
            self._render_diff()
            self._update_ui_state()

    def _prev_diff(self) -> None: self._goto_diff(self._diff_idx - 1)
    def _next_diff(self) -> None: self._goto_diff(self._diff_idx + 1)

    def _apply_to_editors(self) -> None:
        """Riporta le modifiche nei tab aperti dell'applicazione."""
        editors = self._mw._tab_manager.all_editors()
        applied = 0
        for i, ed in enumerate(editors):
            name = ed.file_path.name if ed.file_path else f"(Tab {i+1}) Senza nome"
            if name in self._source_data:
                ed.set_content(self._source_data[name])
                applied += 1
        QMessageBox.information(self, "Merge Completato", f"Modifiche applicate a {applied} tab.")

class ComparePlugin(BasePlugin):
    """Entry point del plugin per NotePadPQ."""
    NAME = "Compare & Merge"
    VERSION = "1.4"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self.add_menu_action(
            main_window, "plugins", 
            "⇄ Compare & Merge...", 
            self._open_compare, 
            shortcut="F7"
        )

    def _open_compare(self) -> None:
        dlg = CompareDialog(self._mw)
        dlg.exec()
