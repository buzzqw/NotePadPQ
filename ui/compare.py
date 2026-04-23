"""
ui/compare.py — Confronto diff con funzioni di Merging (stile Meld)
NotePadPQ
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QPlainTextEdit, QLabel, QPushButton, QFileDialog,
    QComboBox, QGroupBox, QWidget, QDialogButtonBox,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# Colori diff
_COLOR_ADD    = QColor("#c8f7c5")   # verde
_COLOR_DEL    = QColor("#ffd7d5")   # rosso
_COLOR_CHG    = QColor("#fff3b0")   # giallo
_COLOR_EMPTY  = QColor("#f0f0f0")   # grigio

_TEXT_ADD     = QColor("#1a5c1a")
_TEXT_DEL     = QColor("#8b0000")
_TEXT_CHG     = QColor("#5c4a00")
_TEXT_DEFAULT = QColor("#1a1a1a")

_EDITOR_BG    = QColor("#ffffff")
_EDITOR_FG    = QColor("#1a1a1a")

class CompareDialog(QDialog):

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self.setWindowTitle(tr("action.compare_files"))
        self.resize(1100, 750)
        
        # Memoria interna per il merging
        self._lines_a: list[str] = []
        self._lines_b: list[str] = []
        self._opcodes = []
        self._diff_positions: list[int] = []
        self._diff_idx = -1

        self._build_ui()
        self._populate_combos()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── Selezione file ────────────────────────────────────────────────
        sel_layout = QHBoxLayout()
        grp_a = QGroupBox("File A (Sinistra / Originale)")
        la = QHBoxLayout(grp_a)
        self._combo_a = QComboBox()
        btn_file_a = QPushButton("📂")
        btn_file_a.clicked.connect(lambda: self._browse("a"))
        la.addWidget(self._combo_a, 1)
        la.addWidget(btn_file_a)
        sel_layout.addWidget(grp_a, 1)

        grp_b = QGroupBox("File B (Destra / Modificato)")
        lb = QHBoxLayout(grp_b)
        self._combo_b = QComboBox()
        btn_file_b = QPushButton("📂")
        btn_file_b.clicked.connect(lambda: self._browse("b"))
        lb.addWidget(self._combo_b, 1)
        lb.addWidget(btn_file_b)
        sel_layout.addWidget(grp_b, 1)

        self._btn_compare = QPushButton("↔ Confronta")
        self._btn_compare.setMinimumHeight(40)
        self._btn_compare.clicked.connect(self._do_compare)
        sel_layout.addWidget(self._btn_compare)
        layout.addLayout(sel_layout)

        # ── Vista side-by-side ────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._view_a = self._create_editor()
        self._view_b = self._create_editor()
        
        left_w = QWidget(); lv = QVBoxLayout(left_w); self._lbl_a = QLabel("—"); lv.addWidget(self._lbl_a); lv.addWidget(self._view_a)
        right_w = QWidget(); rv = QVBoxLayout(right_w); self._lbl_b = QLabel("—"); rv.addWidget(self._lbl_b); rv.addWidget(self._view_b)
        
        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        layout.addWidget(splitter, 1)

        self._view_a.verticalScrollBar().valueChanged.connect(self._view_b.verticalScrollBar().setValue)
        self._view_b.verticalScrollBar().valueChanged.connect(self._view_a.verticalScrollBar().setValue)

        # ── BARRA STRUMENTI MERGE (STILE MELD) ───────────────────────────
        merge_bar = QHBoxLayout()
        
        self._btn_prev = QPushButton("▲ Prec."); self._btn_prev.clicked.connect(self._prev_diff)
        self._btn_next = QPushButton("▼ Succ."); self._btn_next.clicked.connect(self._next_diff)
        
        # Pulsanti per il merging
        self._btn_to_right = QPushButton("Copia a Destra ⮕")
        self._btn_to_right.setStyleSheet("background-color: #e1f5fe; font-weight: bold; padding: 5px;")
        self._btn_to_right.clicked.connect(self._merge_to_right)
        
        self._btn_to_left = QPushButton("⬅ Copia a Sinistra")
        self._btn_to_left.setStyleSheet("background-color: #f1f8e9; font-weight: bold; padding: 5px;")
        self._btn_to_left.clicked.connect(self._merge_to_left)

        merge_bar.addWidget(self._btn_prev)
        merge_bar.addWidget(self._btn_next)
        merge_bar.addSpacing(20)
        merge_bar.addWidget(self._btn_to_left)
        merge_bar.addWidget(self._btn_to_right)
        merge_bar.addStretch()
        
        self._lbl_stats = QLabel("")
        merge_bar.addWidget(self._lbl_stats)
        layout.addLayout(merge_bar)

        btns = QHBoxLayout()
        self._btn_apply = QPushButton("✅ Applica modifiche e Chiudi")
        self._btn_apply.clicked.connect(self._apply_and_close)
        self._btn_apply.hide()
        
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.reject)
        
        btns.addStretch()
        btns.addWidget(self._btn_apply)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    def _create_editor(self):
        ed = QPlainTextEdit()
        ed.setReadOnly(True)
        ed.setFont(QFont("Monospace", 10))
        ed.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        ed.setStyleSheet("background-color: #ffffff; color: #1a1a1a; border: 1px solid #cccccc;")
        return ed

    def set_files(self, path_a: Path, path_b: Path):
        for side, path in [("a", path_a), ("b", path_b)]:
            combo = self._combo_a if side == "a" else self._combo_b
            display = f"📄 {path.name} (Disco)" if "tmp" not in str(path) else "📝 Mia versione"
            combo.addItem(display, str(path))
            combo.setCurrentIndex(combo.count() - 1)
        self._do_compare()

    def _populate_combos(self):
        editors = self._mw._tab_manager.all_editors()
        for combo in [self._combo_a, self._combo_b]:
            combo.clear()
            for ed in editors:
                name = ed.file_path.name if ed.file_path else tr("label.untitled")
                combo.addItem(f"📂 {name}", ed)
        if self._combo_b.count() > 1: self._combo_b.setCurrentIndex(1)

    def _browse(self, side: str):
        path, _ = QFileDialog.getOpenFileName(self, "Seleziona file", "", "Tutti i file (*)")
        if path:
            combo = self._combo_a if side == "a" else self._combo_b
            combo.addItem(f"📁 {Path(path).name}", path)
            combo.setCurrentIndex(combo.count() - 1)

    def _get_text_lines(self, combo: QComboBox) -> list[str]:
        data = combo.currentData()
        if data is None: return []
        if isinstance(data, str):
            try: return Path(data).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            except: return []
        return data.text().splitlines(keepends=True)

    def _do_compare(self):
        self._lines_a = self._get_text_lines(self._combo_a)
        self._lines_b = self._get_text_lines(self._combo_b)
        self._lbl_a.setText(self._combo_a.currentText())
        self._lbl_b.setText(self._combo_b.currentText())
        self._refresh_diff()

    def _refresh_diff(self):
        matcher = difflib.SequenceMatcher(None, self._lines_a, self._lines_b)
        # Salviamo gli opcode che non sono uguali per la navigazione
        self._opcodes = [op for op in matcher.get_opcodes() if op[0] != 'equal']
        
        all_opcodes = matcher.get_opcodes()
        la_out, lb_out = [], []
        self._diff_positions = []

        for tag, i1, i2, j1, j2 in all_opcodes:
            if tag == 'equal':
                for l in self._lines_a[i1:i2]:
                    la_out.append((l.rstrip("\n"), None))
                    lb_out.append((l.rstrip("\n"), None))
            else:
                self._diff_positions.append(len(la_out))
                len_a, len_b = i2-i1, j2-j1
                for k in range(max(len_a, len_b)):
                    txt_a = self._lines_a[i1+k].rstrip("\n") if k < len_a else ""
                    txt_b = self._lines_b[j1+k].rstrip("\n") if k < len_b else ""
                    col_a = _COLOR_CHG if tag=='replace' else (_COLOR_DEL if tag=='delete' else _COLOR_EMPTY)
                    col_b = _COLOR_CHG if tag=='replace' else (_COLOR_ADD if tag=='insert' else _COLOR_EMPTY)
                    la_out.append((txt_a, col_a if k < len_a else _COLOR_EMPTY))
                    lb_out.append((txt_b, col_b if k < len_b else _COLOR_EMPTY))

        self._render_view(self._view_a, la_out)
        self._render_view(self._view_b, lb_out)
        self._lbl_stats.setText(f"Differenze trovate: {len(self._opcodes)}")
        self._btn_apply.show()
        
        if self._diff_idx == -1 and self._opcodes:
            self._diff_idx = 0
            self._go_to_diff(self._diff_positions[0])

    def _render_view(self, view, lines):
        view.clear()
        cursor = view.textCursor()
        for i, (text, color) in enumerate(lines):
            fmt = QTextCharFormat()
            if color: fmt.setBackground(color)
            cursor.insertText(text, fmt)
            if i < len(lines) - 1: cursor.insertBlock()

    def _merge_to_right(self):
        """Copia il blocco di differenze corrente da A a B."""
        if self._diff_idx < 0 or not self._opcodes: return
        tag, i1, i2, j1, j2 = self._opcodes[self._diff_idx]
        self._lines_b[j1:j2] = self._lines_a[i1:i2]
        self._refresh_diff()

    def _merge_to_left(self):
        """Copia il blocco di differenze corrente da B a A."""
        if self._diff_idx < 0 or not self._opcodes: return
        tag, i1, i2, j1, j2 = self._opcodes[self._diff_idx]
        self._lines_a[i1:i2] = self._lines_b[j1:j2]
        self._refresh_diff()

    def _apply_and_close(self):
        """Salva il risultato finale nell'editor attivo e chiude."""
        data_b = self._combo_b.currentData()
        new_text = "".join(self._lines_b)
        
        # Se B era un editor aperto, aggiorniamo il suo contenuto
        if hasattr(data_b, "set_text"): 
            data_b.set_text(new_text)
        elif isinstance(data_b, str) and "tmp" not in data_b:
            # Se B era un file su disco (non temporaneo), lo salviamo
            Path(data_b).write_text(new_text, encoding="utf-8")
        
        self.accept()

    def _prev_diff(self):
        if self._diff_idx > 0: 
            self._diff_idx -= 1
            self._go_to_diff(self._diff_positions[self._diff_idx])

    def _next_diff(self):
        if self._diff_idx < len(self._diff_positions) - 1: 
            self._diff_idx += 1
            self._go_to_diff(self._diff_positions[self._diff_idx])

    def _go_to_diff(self, line: int):
        for v in [self._view_a, self._view_b]:
            v.setTextCursor(QTextCursor(v.document().findBlockByLineNumber(line)))
            v.ensureCursorVisible()