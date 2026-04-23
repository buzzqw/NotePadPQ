"""
ui/find_replace.py — Dialog Cerca e Sostituisci
NotePadPQ

Dialog unificato con tab: Cerca / Sostituisci / Cerca nei file / Tutti i doc.
Supporta: testo semplice, regex PCRE, maiuscole/minuscole, parola intera,
          wrap-around, ricerca nella selezione, backreference, mark.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QCheckBox, QPushButton,
    QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QComboBox,
    QGroupBox, QSplitter, QFileDialog, QApplication,
    QRadioButton, QButtonGroup, QSpinBox,
)
from PyQt6.Qsci import QsciScintilla

from i18n.i18n import tr
from editor.editor_widget import EditorWidget, INDICATOR_FIND, INDICATOR_MARK1

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# Singleton per condividere l'ultimo termine cercato tra sessioni
_last_find_text   = ""
_last_replace_text= ""
_last_flags: dict = {}
_instance: Optional["FindReplaceDialog"] = None

# Stile condiviso per i pannelli risultati embedded
_RESULTS_STYLE = """
    QTreeWidget {
        background-color: #1e1e1e; color: #d4d4d4;
        font-family: monospace; font-size: 12px;
        border: 1px solid #444; border-radius: 3px;
    }
    QTreeWidget::item { padding: 2px 4px; }
    QTreeWidget::item:alternate { background-color: #252526; }
    QTreeWidget::item:selected { background-color: #264f78; color: #ffffff; }
    QTreeWidget::item:hover { background-color: #2a2d2e; }
    QHeaderView::section {
        background-color: #333333; color: #cccccc;
        padding: 4px; border: 1px solid #444; font-weight: bold;
    }
"""


class FindReplaceDialog(QDialog):
    """
    Dialog cerca/sostituisci. Singleton — una sola istanza per finestra.
    """

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self.setWindowTitle(tr("action.find"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.resize(780, 580)
        self.setMinimumSize(600, 400)

        self._build_ui()
        self._restore_state()

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_find_tab(),           tr("action.find"))
        self._tabs.addTab(self._build_replace_tab(),        tr("action.replace"))
        self._tabs.addTab(self._build_find_in_files_tab(),  tr("action.find_in_files"))
        self._tabs.addTab(self._build_all_docs_tab(),       tr("action.find_in_all_docs"))
        layout.addWidget(self._tabs)

    def _build_find_tab(self) -> QWidget:
        """
        Layout con QSplitter verticale:
          top  → controlli fissi (cerca, opzioni, direzione, pulsanti, status)
          bottom → lista risultati ridimensionabile
        Il manuale regex appare/sparisce tra i controlli senza spostare nulla.
        """
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(4, 4, 4, 4)
        outer_lay.setSpacing(4)

        # ── Pannello controlli (top) ───────────────────────────────────────
        top = QWidget()
        g = QGridLayout(top)
        g.setContentsMargins(0, 0, 0, 0)
        g.setVerticalSpacing(4)

        g.addWidget(QLabel(tr("label.find")), 0, 0)
        self._find_edit = QComboBox()
        self._find_edit.setEditable(True)
        self._find_edit.setMinimumWidth(300)
        g.addWidget(self._find_edit, 0, 1)

        # Opzioni checkbox
        self._chk_case    = QCheckBox(tr("label.match_case"))
        self._chk_word    = QCheckBox(tr("label.whole_word"))
        self._chk_regex   = QCheckBox(tr("label.regex"))
        self._chk_wrap    = QCheckBox(tr("label.wrap_around"))
        self._chk_wrap.setChecked(True)
        self._chk_sel     = QCheckBox(tr("label.in_selection"))
        opts = QHBoxLayout()
        for chk in [self._chk_case, self._chk_word, self._chk_regex,
                    self._chk_wrap, self._chk_sel]:
            opts.addWidget(chk)
        opts.addStretch()
        g.addLayout(opts, 1, 0, 1, 2)

        # Direzione
        self._radio_fwd = QRadioButton(tr("label.direction_forward"))
        self._radio_bwd = QRadioButton(tr("label.direction_backward"))
        self._radio_fwd.setChecked(True)
        dir_box = QGroupBox()
        dir_lay = QHBoxLayout(dir_box)
        dir_lay.addWidget(self._radio_fwd)
        dir_lay.addWidget(self._radio_bwd)
        g.addWidget(dir_box, 2, 0, 1, 2)

        # Pulsanti
        btn_layout = QHBoxLayout()
        self._btn_find_next = QPushButton(tr("button.find_next"))
        self._btn_find_prev = QPushButton(tr("button.find_prev"))
        self._btn_mark_all  = QPushButton(tr("button.mark_all"))
        self._btn_count     = QPushButton("Conta")
        for btn in [self._btn_find_next, self._btn_find_prev,
                    self._btn_mark_all, self._btn_count]:
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        g.addLayout(btn_layout, 3, 0, 1, 2)

        # Manuale regex — appare SOLO quando "Espressione regolare" è attivo
        self._regex_help = QPlainTextEdit()
        self._regex_help.setReadOnly(True)
        _REGEX_MANUAL = r"""SINTASSI ESPRESSIONI REGOLARI (Python re)
──────────────────────────────────────────
  .         qualsiasi carattere (tranne newline)
  \d        cifra [0-9]
  \D        non-cifra
  \w        carattere parola [a-zA-Z0-9_]
  \W        non-carattere parola
  \s        spazio bianco (spazio, tab, newline)
  \S        non-spazio
  \b        confine di parola
  \B        non-confine di parola

QUANTIFICATORI
  *         0 o più volte  (greedy)
  +         1 o più volte  (greedy)
  ?         0 o 1 volta
  *?  +?    versione non-greedy
  {n}       esattamente n volte
  {n,m}     da n a m volte

ANCORE
  ^         inizio riga
  $         fine riga

CLASSI E GRUPPI
  [abc]     uno tra a, b, c
  [^abc]    nessuno tra a, b, c
  [a-z]     range da a a z
  (...)     gruppo catturante
  (?:...)   gruppo non catturante
  a|b       alternativa: a oppure b

RIFERIMENTI (nel campo Sostituisci)
  \1  \2    valore del gruppo 1, 2, ...

ESEMPI
  \d+           sequenza di cifre
  \bparola\b    parola intera
  (\w+)@(\w+)   cattura utente ed host email
  ^\s*$         riga vuota o solo spazi
  <[^>]+>       tag HTML generico
"""
        self._regex_help.setPlainText(_REGEX_MANUAL)
        self._regex_help.setStyleSheet(
            "QPlainTextEdit {"
            "  background:#1a1f1a; color:#b5cea8;"
            "  font-family: monospace; font-size: 11px;"
            "  border: 1px solid #3a4a3a; border-radius: 3px;"
            "  padding: 4px;"
            "}"
        )
        self._regex_help.setFixedHeight(180)
        self._regex_help.setVisible(False)
        g.addWidget(self._regex_help, 4, 0, 1, 2)
        self._chk_regex.toggled.connect(self._regex_help.setVisible)

        # Status
        self._lbl_status = QLabel("")
        g.addWidget(self._lbl_status, 5, 0, 1, 2)

        outer_lay.addWidget(top)

        # ── Lista occorrenze (bottom, ridimensionabile) ────────────────────
        self._find_occurrences = QTreeWidget()
        self._find_occurrences.setHeaderLabels(["Riga", "Testo"])
        self._find_occurrences.setRootIsDecorated(False)
        self._find_occurrences.setAlternatingRowColors(True)
        self._find_occurrences.setStyleSheet(_RESULTS_STYLE)
        self._find_occurrences.header().setStretchLastSection(True)
        # Colonna Riga: larghezza fissa, testo allineato a destra
        self._find_occurrences.header().setSectionResizeMode(
            0, self._find_occurrences.header().ResizeMode.Fixed
        )
        self._find_occurrences.setColumnWidth(0, 58)  # abbastanza per 5 cifre senza troncamento
        self._find_occurrences.itemDoubleClicked.connect(self._goto_occurrence)
        outer_lay.addWidget(self._find_occurrences, 1)  # stretch=1 → prende spazio residuo

        # ── Connessioni ───────────────────────────────────────────────────
        self._btn_find_next.clicked.connect(self._do_find_next)
        self._btn_find_prev.clicked.connect(self._do_find_prev)
        self._btn_mark_all.clicked.connect(self._do_mark_all)
        self._btn_count.clicked.connect(self._do_count)
        self._find_edit.lineEdit().returnPressed.connect(self._do_find_next)

        # Search-as-you-type con delay
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)
        self._search_timer.timeout.connect(self._do_incremental)
        self._find_edit.currentTextChanged.connect(
            lambda: self._search_timer.start()
        )

        return outer

    def _build_replace_tab(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)

        g.addWidget(QLabel(tr("label.find")),         0, 0)
        self._find_edit2 = QComboBox()
        self._find_edit2.setEditable(True)
        g.addWidget(self._find_edit2, 0, 1)

        g.addWidget(QLabel(tr("label.replace_with")), 1, 0)
        self._replace_edit = QComboBox()
        self._replace_edit.setEditable(True)
        g.addWidget(self._replace_edit, 1, 1)

        # Stesse opzioni del tab Cerca
        self._chk_case2  = QCheckBox(tr("label.match_case"))
        self._chk_word2  = QCheckBox(tr("label.whole_word"))
        self._chk_regex2 = QCheckBox(tr("label.regex"))
        self._chk_regex2.setToolTip(
            "Espressione regolare (Python re):\n"
            "  .       qualsiasi carattere\n"
            "  \\d      cifra  |  \\w  parola  |  \\s  spazio\n"
            "  *       0 o più  |  +  1 o più  |  ?  0 o 1\n"
            "  ^       inizio riga  |  $  fine riga\n"
            "  [abc]   classe caratteri  |  [^abc]  negazione\n"
            "  (...)   gruppo  |  (?:...)  gruppo non catturante\n"
            "  \\1      riferimento al gruppo 1\n"
            "  a|b     alternativa (a oppure b)\n"
            "  \\b      confine di parola\n"
            "\nNel campo Sostituisci: \\1 \\2 ... per i gruppi catturati"
        )
        self._chk_wrap2  = QCheckBox(tr("label.wrap_around"))
        self._chk_wrap2.setChecked(True)
        opts2 = QHBoxLayout()
        for chk in [self._chk_case2, self._chk_word2,
                    self._chk_regex2, self._chk_wrap2]:
            opts2.addWidget(chk)
        opts2.addStretch()
        g.addLayout(opts2, 2, 0, 1, 2)

        btns = QHBoxLayout()
        self._btn_replace     = QPushButton(tr("button.replace"))
        self._btn_replace_all = QPushButton(tr("button.replace_all"))
        self._btn_find_next2  = QPushButton(tr("button.find_next"))
        for b in [self._btn_find_next2, self._btn_replace, self._btn_replace_all]:
            btns.addWidget(b)
        btns.addStretch()
        g.addLayout(btns, 3, 0, 1, 2)

        self._lbl_replace_status = QLabel("")
        g.addWidget(self._lbl_replace_status, 4, 0, 1, 2)

        self._btn_replace.clicked.connect(self._do_replace)
        self._btn_replace_all.clicked.connect(self._do_replace_all)
        self._btn_find_next2.clicked.connect(
            lambda: self._do_find(self._find_edit2, forward=True)
        )

        return w

    def _build_find_in_files_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)

        top = QGridLayout()
        top.addWidget(QLabel(tr("label.find")), 0, 0)
        self._fif_find = QLineEdit()
        self._fif_find.returnPressed.connect(self._do_find_in_files)
        top.addWidget(self._fif_find, 0, 1)

        top.addWidget(QLabel("Directory:"), 1, 0)
        dir_layout = QHBoxLayout()
        self._fif_dir  = QLineEdit(str(Path.home()))
        btn_browse = QPushButton(tr("button.browse"))
        btn_browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self._fif_dir)
        dir_layout.addWidget(btn_browse)
        top.addLayout(dir_layout, 1, 1)

        top.addWidget(QLabel("Filtro file:"), 2, 0)
        self._fif_filter = QLineEdit("*.py;*.txt;*.md;*.tex")
        top.addWidget(self._fif_filter, 2, 1)

        self._fif_case   = QCheckBox(tr("label.match_case"))
        self._fif_regex  = QCheckBox(tr("label.regex"))
        self._fif_sub    = QCheckBox("Sottodirectory")
        self._fif_sub.setChecked(True)
        opts = QHBoxLayout()
        for w2 in [self._fif_case, self._fif_regex, self._fif_sub]:
            opts.addWidget(w2)
        opts.addStretch()
        top.addLayout(opts, 3, 0, 1, 2)

        btn_row = QHBoxLayout()
        btn_find = QPushButton("🔍 " + tr("action.find_in_files"))
        btn_find.clicked.connect(self._do_find_in_files)
        self._fif_status = QLabel("")
        self._fif_status.setStyleSheet("color: #888; font-size: 11px;")
        btn_row.addWidget(btn_find)
        btn_row.addWidget(self._fif_status)
        btn_row.addStretch()
        top.addLayout(btn_row, 4, 0, 1, 2)

        layout.addLayout(top)

        # Risultati integrati nel dialog
        self._fif_results = QTreeWidget()
        self._fif_results.setHeaderLabels(["File / Riga", "Testo"])
        self._fif_results.setRootIsDecorated(True)
        self._fif_results.setAlternatingRowColors(True)
        self._fif_results.setMinimumHeight(200)
        self._fif_results.setStyleSheet(_RESULTS_STYLE)
        self._fif_results.itemDoubleClicked.connect(self._open_fif_result)
        layout.addWidget(self._fif_results, 1)

        return w

    def _build_all_docs_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)

        grid = QGridLayout()
        grid.addWidget(QLabel(tr("label.find")),         0, 0)
        self._all_find = QLineEdit()
        self._all_find.returnPressed.connect(self._do_find_all_docs)
        grid.addWidget(self._all_find, 0, 1)

        grid.addWidget(QLabel(tr("label.replace_with")), 1, 0)
        self._all_replace = QLineEdit()
        grid.addWidget(self._all_replace, 1, 1)

        self._all_case  = QCheckBox(tr("label.match_case"))
        self._all_regex = QCheckBox(tr("label.regex"))
        opts = QHBoxLayout()
        opts.addWidget(self._all_case)
        opts.addWidget(self._all_regex)
        opts.addStretch()
        grid.addLayout(opts, 2, 0, 1, 2)

        btns = QHBoxLayout()
        btn_fa = QPushButton("🔍 " + tr("action.find_in_all_docs"))
        btn_ra = QPushButton("↔ " + tr("action.replace_in_all_docs"))
        btn_fa.clicked.connect(self._do_find_all_docs)
        btn_ra.clicked.connect(self._do_replace_all_docs)
        self._all_status = QLabel("")
        self._all_status.setStyleSheet("color: #888; font-size: 11px;")
        btns.addWidget(btn_fa)
        btns.addWidget(btn_ra)
        btns.addWidget(self._all_status)
        btns.addStretch()
        grid.addLayout(btns, 3, 0, 1, 2)
        layout.addLayout(grid)

        # Risultati integrati
        self._all_results = QTreeWidget()
        self._all_results.setHeaderLabels(["Documento / Riga", "Testo"])
        self._all_results.setRootIsDecorated(True)
        self._all_results.setAlternatingRowColors(True)
        self._all_results.setMinimumHeight(200)
        self._all_results.setStyleSheet(_RESULTS_STYLE)
        self._all_results.itemDoubleClicked.connect(self._open_all_result)
        layout.addWidget(self._all_results)

        return w

    # ── Logica ricerca ────────────────────────────────────────────────────────

    def _get_flags(self) -> dict:
        return {
            "case_sensitive": self._chk_case.isChecked(),
            "whole_word":     self._chk_word.isChecked(),
            "regex":          self._chk_regex.isChecked(),
            "wrap":           self._chk_wrap.isChecked(),
        }

    def _current_editor(self) -> Optional[EditorWidget]:
        return self._mw._tab_manager.current_editor()

    def _do_find_next(self) -> None:
        self._do_find(self._find_edit, forward=True)

    def _do_find_prev(self) -> None:
        self._do_find(self._find_edit, forward=False)

    def _do_find(self, edit_widget, forward: bool = True) -> bool:
        editor = self._current_editor()
        if not editor:
            return False
        text = edit_widget.currentText() if hasattr(edit_widget, "currentText") else edit_widget.text()
        if not text:
            return False

        flags = self._get_flags()
        found = editor.findFirst(
            text,
            flags["regex"],
            flags["case_sensitive"],
            flags["whole_word"],
            flags["wrap"],
            forward,
        )
        if found:
            self._lbl_status.setText("")
        else:
            self._lbl_status.setText(tr("msg.no_results", query=text))
        return found

    def _do_incremental(self) -> None:
        """Cerca mentre si digita e aggiorna la lista occorrenze."""
        editor = self._current_editor()
        if not editor:
            return
        text = self._find_edit.currentText()
        if len(text) < 1:
            editor.clear_indicator(INDICATOR_FIND)
            self._find_occurrences.clear()
            self._lbl_status.setText("")
            return
        self._do_find(self._find_edit, forward=True)
        # Aggiorna lista occorrenze con un minimo di 2 caratteri
        if len(text) >= 2:
            self._populate_occurrences(editor, text, self._get_flags())

    def _do_mark_all(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        text = self._find_edit.currentText()
        if not text:
            return
        flags = self._get_flags()
        editor.clear_indicator(INDICATOR_MARK1)
        count = self._highlight_all(editor, text, flags, INDICATOR_MARK1)
        self._lbl_status.setText(tr("msg.marked_n", count=count))
        # Aggiorna anche la lista occorrenze
        self._populate_occurrences(editor, text, flags)

    def _do_count(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        text = self._find_edit.currentText()
        if not text:
            return
        flags = self._get_flags()
        self._populate_occurrences(editor, text, flags)

    def _populate_occurrences(self, editor, pattern_text: str, flags: dict) -> None:
        """Popola la lista occorrenze nel tab Cerca."""
        self._find_occurrences.clear()
        if not pattern_text:
            self._lbl_status.setText("")
            return
        try:
            re_flags = 0 if flags["case_sensitive"] else re.IGNORECASE
            pat = pattern_text if flags["regex"] else re.escape(pattern_text)
            if flags.get("whole_word"):
                pat = rf"{pat}"
            compiled = re.compile(pat, re_flags)
        except re.error as e:
            self._lbl_status.setText(f"Regex non valida: {e}")
            return

        _ROLE = Qt.ItemDataRole.UserRole
        lines = editor.text().split("\n")
        count = 0
        for line_idx, line_text in enumerate(lines):
            for m in compiled.finditer(line_text):
                item = QTreeWidgetItem([
                    str(line_idx + 1),
                    line_text.strip()[:120]
                ])
                item.setTextAlignment(0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                # Colore esplicito: garantisce leggibilità anche quando selezionato
                # (su Qt6 il colore da stylesheet non sempre si applica alla colonna selezionata)
                item.setForeground(0, Qt.GlobalColor.white)
                item.setForeground(1, Qt.GlobalColor.white)
                item.setData(0, _ROLE, {"line": line_idx + 1, "col": m.start()})
                self._find_occurrences.addTopLevelItem(item)
                count += 1
        if count:
            self._lbl_status.setText(f"✓ {count} occorrenze")
        else:
            self._lbl_status.setText(f"Nessun risultato per «{pattern_text}»")

    def _goto_occurrence(self, item: QTreeWidgetItem) -> None:
        """Vai alla riga dell'occorrenza cliccata."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        editor = self._current_editor()
        if editor:
            editor.go_to_line(data["line"])
            editor.setFocus()

    def _highlight_all(self, editor: EditorWidget, pattern: str,
                       flags: dict, indicator: int) -> int:
        """Evidenzia tutte le occorrenze con un indicatore. Restituisce il count."""
        editor.clear_indicator(indicator)
        text = editor.text()
        try:
            re_flags = 0 if flags["case_sensitive"] else re.IGNORECASE
            if flags["whole_word"]:
                pattern = rf"\b{re.escape(pattern)}\b"
            elif not flags["regex"]:
                pattern = re.escape(pattern)
            compiled = re.compile(pattern, re_flags)
            count = 0
            for m in compiled.finditer(text):
                editor.set_indicator_range(indicator, m.start(), m.end() - m.start())
                count += 1
            return count
        except re.error:
            return 0

    def _count_occurrences(self, text: str, pattern: str, flags: dict) -> int:
        try:
            re_flags = 0 if flags["case_sensitive"] else re.IGNORECASE
            if not flags["regex"]:
                pattern = re.escape(pattern)
            if flags["whole_word"]:
                pattern = rf"\b{pattern}\b"
            return len(re.findall(pattern, text, re_flags))
        except re.error:
            return 0

    def _do_replace(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        find_text    = self._find_edit2.currentText()
        replace_text = self._replace_edit.currentText()
        if editor.hasSelectedText():
            editor.replaceSelectedText(replace_text)
        self._do_find(self._find_edit2, forward=True)

    def _do_replace_all(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        find_text    = self._find_edit2.currentText()
        replace_text = self._replace_edit.currentText()
        flags = {
            "case_sensitive": self._chk_case2.isChecked(),
            "whole_word":     self._chk_word2.isChecked(),
            "regex":          self._chk_regex2.isChecked(),
        }
        text = editor.text()
        try:
            re_flags = 0 if flags["case_sensitive"] else re.IGNORECASE
            pattern  = find_text if flags["regex"] else re.escape(find_text)
            if flags["whole_word"]:
                pattern = rf"\b{pattern}\b"
            new_text, count = re.subn(pattern, replace_text, text, flags=re_flags)
            if count > 0:
                cursor = editor.getCursorPosition()
                editor.beginUndoAction()
                editor.selectAll()
                editor.replaceSelectedText(new_text)
                editor.endUndoAction()
                line = min(cursor[0], max(0, editor.lines() - 1))
                editor.setCursorPosition(line, cursor[1])
            self._lbl_replace_status.setText(
                tr("msg.replaced_n", count=count)
            )
        except re.error as e:
            self._lbl_replace_status.setText(
                tr("msg.regex_invalid", error=str(e))
            )

    # ── Find in Files ─────────────────────────────────────────────────────────

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Seleziona directory")
        if path:
            self._fif_dir.setText(path)

    def _do_find_in_files(self) -> None:
        import os, fnmatch
        query    = self._fif_find.text().strip()
        base_dir = Path(self._fif_dir.text())
        filters  = [f.strip() for f in self._fif_filter.text().split(";") if f.strip()]
        use_re   = self._fif_regex.isChecked()
        case_s   = self._fif_case.isChecked()
        recurse  = self._fif_sub.isChecked()

        if not query:
            self._fif_status.setText("⚠ Inserisci il testo da cercare")
            return
        if not base_dir.is_dir():
            self._fif_status.setText("⚠ Directory non valida")
            return

        self._fif_results.clear()
        self._fif_status.setText("🔍 Ricerca in corso…")
        QApplication.processEvents()

        re_flags = 0 if case_s else re.IGNORECASE
        try:
            pattern = re.compile(query if use_re else re.escape(query), re_flags)
        except re.error as e:
            self._fif_status.setText(f"⚠ Regex non valida: {e}")
            return

        walker = os.walk(str(base_dir)) if recurse \
            else [(str(base_dir), [], os.listdir(str(base_dir)))]

        total_matches = 0
        total_files   = 0
        _ROLE = Qt.ItemDataRole.UserRole

        for root, _, files in walker:
            for fname in files:
                if filters and not any(fnmatch.fnmatch(fname, f) for f in filters):
                    continue
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                lines = text.split("\n")
                matches = [(i + 1, line) for i, line in enumerate(lines)
                           if pattern.search(line)]
                if not matches:
                    continue
                total_files += 1
                total_matches += len(matches)
                try:
                    rel = str(fpath.relative_to(base_dir))
                except ValueError:
                    rel = str(fpath)
                file_item = QTreeWidgetItem(
                    self._fif_results,
                    [f"📄 {rel}  ({len(matches)} corrispondenze)", ""]
                )
                file_item.setData(0, _ROLE, {"path": str(fpath), "editor": None})
                for line_num, line_text in matches:
                    child = QTreeWidgetItem([
                        f"  Riga {line_num}", line_text.strip()[:140]
                    ])
                    child.setData(0, _ROLE, {"path": str(fpath), "line": line_num, "editor": None})
                    file_item.addChild(child)
                file_item.setExpanded(True)

        if total_matches == 0:
            QTreeWidgetItem(self._fif_results, ["Nessun risultato trovato.", ""])
            self._fif_status.setText(f"0 risultati per «{query}»")
        else:
            self._fif_status.setText(
                f"✓ {total_matches} corrispondenze in {total_files} file"
            )
        self._fif_results.resizeColumnToContents(0)

    def _open_fif_result(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        path_str = data.get("path")
        line_num = data.get("line")
        if path_str:
            self._mw.open_files([Path(path_str)])
            editor = self._mw._tab_manager.current_editor()
            if editor and line_num:
                editor.go_to_line(int(line_num))
                editor.setFocus()

    # ── Find in All Docs ──────────────────────────────────────────────────────

    def _do_find_all_docs(self) -> None:
        query = self._all_find.text().strip()
        if not query:
            self._all_status.setText("⚠ Inserisci il testo da cercare")
            return
        use_re = self._all_regex.isChecked()
        case_s = self._all_case.isChecked()
        re_flags = 0 if case_s else re.IGNORECASE
        try:
            pattern = re.compile(query if use_re else re.escape(query), re_flags)
        except re.error as e:
            self._all_status.setText(f"⚠ Regex non valida: {e}")
            return

        self._all_results.clear()
        _ROLE = Qt.ItemDataRole.UserRole
        total_matches = 0

        for editor in self._mw._tab_manager.all_editors():
            text = editor.text()
            name = editor.file_path.name if editor.file_path else tr("label.untitled")
            matches = [(i + 1, line) for i, line in enumerate(text.split("\n"))
                       if pattern.search(line)]
            if not matches:
                continue
            total_matches += len(matches)
            doc_item = QTreeWidgetItem(
                self._all_results,
                [f"📄 {name}  ({len(matches)} corrispondenze)", ""]
            )
            doc_item.setData(0, _ROLE, {"editor": editor})
            for ln, lt in matches:
                child = QTreeWidgetItem([f"  Riga {ln}", lt.strip()[:140]])
                child.setData(0, _ROLE, {"editor": editor, "line": ln})
                doc_item.addChild(child)
            doc_item.setExpanded(True)

        if total_matches == 0:
            QTreeWidgetItem(self._all_results, ["Nessun risultato trovato.", ""])
            self._all_status.setText(f"0 risultati per «{query}»")
        else:
            self._all_status.setText(f"✓ {total_matches} corrispondenze")
        self._all_results.resizeColumnToContents(0)

    def _do_replace_all_docs(self) -> None:
        find_text    = self._all_find.text()
        replace_text = self._all_replace.text()
        if not find_text:
            return
        use_re  = self._all_regex.isChecked()
        case_s  = self._all_case.isChecked()
        re_flags = 0 if case_s else re.IGNORECASE
        try:
            pattern = re.compile(
                find_text if use_re else re.escape(find_text), re_flags
            )
        except re.error:
            return

        total = 0
        for editor in self._mw._tab_manager.all_editors():
            text = editor.text()
            new_text, count = pattern.subn(replace_text, text)
            if count > 0:
                cursor = editor.getCursorPosition()
                editor.beginUndoAction()
                editor.selectAll()
                editor.replaceSelectedText(new_text)
                editor.endUndoAction()
                line = min(cursor[0], max(0, editor.lines() - 1))
                editor.setCursorPosition(line, cursor[1])
                total += count

    def _open_all_result(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        editor   = data.get("editor")
        line_num = data.get("line")
        if editor is not None:
            self._mw._tab_manager.set_current_editor(editor)
            if line_num:
                editor.go_to_line(int(line_num))
                editor.setFocus()

    # ── Stato ─────────────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        if _last_find_text:
            self._find_edit.setCurrentText(_last_find_text)
            self._find_edit2.setCurrentText(_last_find_text)

    # ── API pubblica (chiamata da MainWindow) ─────────────────────────────────

    @classmethod
    def _get_or_create(cls, main_window: "MainWindow") -> "FindReplaceDialog":
        global _instance
        if _instance is None or _instance._mw is not main_window:
            _instance = cls(main_window)
        return _instance

    @classmethod
    def show_find(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(0)
        dlg.show()
        dlg.raise_()
        dlg._find_edit.setFocus()

    @classmethod
    def show_replace(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(1)
        dlg.show()
        dlg.raise_()

    @classmethod
    def show_find_in_files(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(2)
        dlg.show()
        dlg.raise_()

    @classmethod
    def show_find_all_docs(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(3)
        dlg.show()
        dlg.raise_()

    @classmethod
    def show_replace_all_docs(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(3)
        dlg.show()
        dlg.raise_()

    @classmethod
    def find_next(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._do_find_next()

    @classmethod
    def find_prev(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._do_find_prev()

    @classmethod
    def mark_all(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._do_mark_all()
