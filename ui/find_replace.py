"""
ui/find_replace.py — Dialog Cerca e Sostituisci
NotePadPQ

Dialog unificato con tab: Cerca / Sostituisci / Cerca nei file / Tutti i doc.
Supporta: testo semplice, regex PCRE, maiuscole/minuscole, parola intera,
          wrap-around, ricerca nella selezione, backreference, mark.
"""

from __future__ import annotations

import bisect
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
    QRadioButton, QButtonGroup, QSpinBox, QSlider,
)
from PyQt6.Qsci import QsciScintilla

from i18n.i18n import tr
from editor.editor_widget import (
    EditorWidget, INDICATOR_FIND, INDICATOR_MARK1, INDICATOR_FIND_LINE,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# Singleton per condividere l'ultimo termine cercato tra sessioni
_last_find_text   = ""
_last_replace_text= ""
_last_flags: dict = {}
_instance: Optional["FindReplaceDialog"] = None

def _results_colors() -> dict:
    """Colori della lista risultati derivati dal tema attivo, così l'elenco
    resta leggibile su qualunque tema (prima era hardcoded a sfondo scuro,
    quindi testo poco leggibile sui temi chiari)."""
    try:
        from config.themes import ThemeManager
        tm      = ThemeManager.instance()
        theme   = tm.get_theme(tm._active_name) or {}
        ui      = theme.get("ui", {}) or {}
        is_dark = bool(theme.get("meta", {}).get("dark", True))
    except Exception:
        ui, is_dark = {}, True

    def _ui(name: str, default: str) -> str:
        v = ui.get(name)
        return v if isinstance(v, str) and v else default

    if is_dark:
        return {
            "bg":       _ui("editor_bg", "#1e1e1e"),
            "fg":       _ui("editor_fg", "#d4d4d4"),
            "alt_bg":   _ui("caret_line_bg", "#252526"),
            "sel_bg":   _ui("selection_bg", "#264f78"),
            "sel_fg":   "#ffffff",
            "border":   _ui("fold_bg", "#444444"),
            "hover_bg": _ui("caret_line_bg", "#2a2d2e"),
            "hdr_bg":   "#333333",
            "hdr_fg":   "#cccccc",
        }
    return {
        "bg":       _ui("editor_bg", "#ffffff"),
        "fg":       _ui("editor_fg", "#1e1e1e"),
        "alt_bg":   "#f1f3f5",
        "sel_bg":   "#cfe3ff",
        "sel_fg":   "#0a2b4a",
        "border":   "#c8cdd2",
        "hover_bg": "#e6f0fb",
        "hdr_bg":   "#e9edf1",
        "hdr_fg":   "#1e1e1e",
    }


def _results_stylesheet() -> str:
    """Foglio di stile a tema per i QTreeWidget dei risultati (lista occorrenze,
    cerca nei file, tutti i documenti). Leggibile su temi chiari e scuri, con
    riga selezionata ben evidente."""
    c = _results_colors()
    return f"""
    QTreeWidget {{
        background-color: {c['bg']}; color: {c['fg']};
        font-family: monospace; font-size: 12px;
        border: 1px solid {c['border']}; border-radius: 3px;
        outline: 0;
    }}
    QTreeWidget::item {{ padding: 2px 4px; }}
    QTreeWidget::item:alternate {{ background-color: {c['alt_bg']}; }}
    QTreeWidget::item:selected {{ background-color: {c['sel_bg']}; color: {c['sel_fg']}; }}
    QTreeWidget::item:hover {{ background-color: {c['hover_bg']}; }}
    QHeaderView::section {{
        background-color: {c['hdr_bg']}; color: {c['hdr_fg']};
        padding: 4px; border: 1px solid {c['border']}; font-weight: bold;
    }}
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

        layout.addLayout(self._build_transparency_bar())

    def _build_transparency_bar(self) -> QHBoxLayout:
        """Barra in fondo al dialog per rendere la finestra Cerca trasparente.

        Come negli editor PRO (es. la mini-toolbar "always on top" di vari
        IDE): un check attiva la trasparenza e uno slider regola il livello,
        così il pannello non copre completamente il testo sottostante. Lo stato
        è persistito nei Settings.

        Comportamento "smart": quando il mouse entra nel dialog la finestra
        torna piena opacità (per non disturbare la digitazione), e quando esce
        riapplica il livello trasparente scelto — vedi enterEvent/leaveEvent.
        """
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 0, 4, 2)

        self._chk_transparent = QCheckBox(tr("label.transparent"))
        self._chk_transparent.setToolTip(tr("tooltip.find_transparent"))
        self._chk_transparent.toggled.connect(self._on_transparency_toggled)
        bar.addWidget(self._chk_transparent)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setMinimum(20)   # mai sotto il 20%: resta usabile
        self._opacity_slider.setMaximum(100)
        self._opacity_slider.setValue(70)
        self._opacity_slider.setFixedWidth(160)
        self._opacity_slider.setToolTip(tr("tooltip.find_opacity"))
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        bar.addWidget(self._opacity_slider)

        self._opacity_label = QLabel("70%")
        self._opacity_label.setMinimumWidth(40)
        bar.addWidget(self._opacity_label)

        bar.addStretch()
        return bar

    # ── Trasparenza finestra ───────────────────────────────────────────────────

    def _current_opacity(self) -> float:
        """Opacità (0.2–1.0) corrispondente al valore dello slider."""
        try:
            return max(20, min(100, self._opacity_slider.value())) / 100.0
        except Exception:
            return 1.0

    def _apply_transparency(self) -> None:
        """Applica l'opacità in base al check: piena opacità se disattivato,
        altrimenti il livello scelto dallo slider."""
        try:
            if self._chk_transparent.isChecked():
                self.setWindowOpacity(self._current_opacity())
            else:
                self.setWindowOpacity(1.0)
        except Exception:
            pass

    def _on_transparency_toggled(self, checked: bool) -> None:
        try:
            self._opacity_slider.setEnabled(checked)
            self._opacity_label.setEnabled(checked)
        except Exception:
            pass
        self._apply_transparency()
        try:
            from config.settings import Settings
            Settings.instance().set("find/transparent_enabled", bool(checked))
        except Exception:
            pass

    def _on_opacity_changed(self, value: int) -> None:
        try:
            self._opacity_label.setText(f"{int(value)}%")
        except Exception:
            pass
        self._apply_transparency()
        try:
            from config.settings import Settings
            Settings.instance().set("find/opacity", int(value))
        except Exception:
            pass

    def enterEvent(self, event) -> None:
        """Mouse sopra il dialog → piena opacità, così digiti/leggi senza
        disturbo (comportamento "smart" da editor PRO)."""
        try:
            self.setWindowOpacity(1.0)
        except Exception:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """Mouse fuori dal dialog → riapplica il livello trasparente scelto,
        così la finestra non copre il testo mentre lavori nell'editor."""
        self._apply_transparency()
        super().leaveEvent(event)

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
        self._find_edit.setToolTip(tr("tooltip.find_edit"))
        g.addWidget(self._find_edit, 0, 1)

        # Opzioni checkbox
        self._chk_case    = QCheckBox(tr("label.match_case"))
        self._chk_word    = QCheckBox(tr("label.whole_word"))
        self._chk_regex   = QCheckBox(tr("label.regex"))
        self._chk_wrap    = QCheckBox(tr("label.wrap_around"))
        self._chk_wrap.setChecked(True)
        self._chk_sel     = QCheckBox(tr("label.in_selection"))
        self._chk_case.setToolTip(tr("tooltip.find_case"))
        self._chk_word.setToolTip(tr("tooltip.find_word"))
        self._chk_regex.setToolTip(tr("tooltip.find_regex_help"))
        self._chk_wrap.setToolTip(tr("tooltip.find_wrap"))
        self._chk_sel.setToolTip(tr("tooltip.find_in_selection"))
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
        self._radio_fwd.setToolTip(tr("tooltip.find_direction_fwd"))
        self._radio_bwd.setToolTip(tr("tooltip.find_direction_bwd"))
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
        self._btn_count     = QPushButton(tr("button.count"))
        self._btn_find_next.setToolTip(tr("tooltip.find_next"))
        self._btn_find_prev.setToolTip(tr("tooltip.find_prev"))
        self._btn_mark_all.setToolTip(tr("tooltip.find_mark_all"))
        self._btn_count.setToolTip(tr("tooltip.find_count"))
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
        self._find_occurrences.setHeaderLabels([tr("label.col_line"), tr("label.col_text")])
        self._find_occurrences.setRootIsDecorated(False)
        self._find_occurrences.setAlternatingRowColors(True)
        self._find_occurrences.setStyleSheet(_results_stylesheet())
        self._find_occurrences.header().setStretchLastSection(True)
        # Colonna Riga: larghezza fissa, testo allineato a destra
        self._find_occurrences.header().setSectionResizeMode(
            0, self._find_occurrences.header().ResizeMode.Fixed
        )
        self._find_occurrences.setColumnWidth(0, 58)  # abbastanza per 5 cifre senza troncamento
        self._find_occurrences.itemDoubleClicked.connect(self._goto_occurrence)
        # Click singolo: naviga ed evidenzia subito (più reattivo/user-friendly).
        self._find_occurrences.itemClicked.connect(self._goto_occurrence)
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
        self._find_edit2.setToolTip(tr("tooltip.find_edit"))
        g.addWidget(self._find_edit2, 0, 1)

        g.addWidget(QLabel(tr("label.replace_with")), 1, 0)
        self._replace_edit = QComboBox()
        self._replace_edit.setEditable(True)
        self._replace_edit.setToolTip(tr("tooltip.replace_edit"))
        g.addWidget(self._replace_edit, 1, 1)

        # Stesse opzioni del tab Cerca
        self._chk_case2  = QCheckBox(tr("label.match_case"))
        self._chk_word2  = QCheckBox(tr("label.whole_word"))
        self._chk_regex2 = QCheckBox(tr("label.regex"))
        self._chk_regex2.setToolTip(tr("tooltip.find_regex_help"))
        self._chk_wrap2  = QCheckBox(tr("label.wrap_around"))
        self._chk_wrap2.setChecked(True)
        self._chk_case2.setToolTip(tr("tooltip.find_case"))
        self._chk_word2.setToolTip(tr("tooltip.find_word"))
        self._chk_wrap2.setToolTip(tr("tooltip.find_wrap"))
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
        self._btn_find_next2.setToolTip(tr("tooltip.find_next"))
        self._btn_replace.setToolTip(tr("tooltip.replace_one"))
        self._btn_replace_all.setToolTip(tr("tooltip.replace_all"))
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
        self._fif_find.setToolTip(tr("tooltip.fif_find"))
        top.addWidget(self._fif_find, 0, 1)

        top.addWidget(QLabel(tr("label.replace_with")), 1, 0)
        self._fif_replace = QLineEdit()
        self._fif_replace.setToolTip(tr("tooltip.fif_replace"))
        top.addWidget(self._fif_replace, 1, 1)

        top.addWidget(QLabel(tr("label.directory")), 2, 0)
        dir_layout = QHBoxLayout()
        self._fif_dir  = QLineEdit(str(Path.home()))
        self._fif_dir.setToolTip(tr("tooltip.fif_dir"))
        btn_browse = QPushButton(tr("button.browse"))
        btn_browse.setToolTip(tr("tooltip.fif_browse"))
        btn_browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self._fif_dir)
        dir_layout.addWidget(btn_browse)
        top.addLayout(dir_layout, 2, 1)

        top.addWidget(QLabel(tr("label.file_filter")), 3, 0)
        self._fif_filter = QLineEdit("*.py;*.txt;*.md;*.tex")
        self._fif_filter.setToolTip(tr("tooltip.fif_filter"))
        top.addWidget(self._fif_filter, 3, 1)

        self._fif_case   = QCheckBox(tr("label.match_case"))
        self._fif_regex  = QCheckBox(tr("label.regex"))
        self._fif_sub    = QCheckBox(tr("label.subdirectories"))
        self._fif_sub.setChecked(True)
        self._fif_case.setToolTip(tr("tooltip.fif_case"))
        self._fif_regex.setToolTip(tr("tooltip.fif_regex"))
        self._fif_sub.setToolTip(tr("tooltip.fif_sub"))
        opts = QHBoxLayout()
        for w2 in [self._fif_case, self._fif_regex, self._fif_sub]:
            opts.addWidget(w2)
        opts.addStretch()
        top.addLayout(opts, 4, 0, 1, 2)

        btn_row = QHBoxLayout()
        btn_find = QPushButton("🔍 " + tr("action.find"))
        btn_find.setToolTip(tr("tooltip.fif_search"))
        btn_find.clicked.connect(self._do_find_in_files)
        btn_replace_all = QPushButton("↔ " + tr("action.replace_in_files"))
        btn_replace_all.setToolTip(tr("tooltip.fif_replace_all"))
        btn_replace_all.clicked.connect(self._do_replace_in_files)
        self._fif_status = QLabel("")
        self._fif_status.setStyleSheet("color: #888; font-size: 11px;")
        btn_row.addWidget(btn_find)
        btn_row.addWidget(btn_replace_all)
        btn_row.addWidget(self._fif_status)
        btn_row.addStretch()
        top.addLayout(btn_row, 5, 0, 1, 2)

        layout.addLayout(top)

        # Risultati integrati nel dialog — 3 colonne: File/Riga | Testo | ↔
        from PyQt6.QtWidgets import QHeaderView
        self._fif_results = QTreeWidget()
        self._fif_results.setHeaderLabels([tr("label.col_file_line"), tr("label.col_text"), ""])
        self._fif_results.setRootIsDecorated(True)
        self._fif_results.setAlternatingRowColors(True)
        self._fif_results.setMinimumHeight(200)
        self._fif_results.setStyleSheet(_results_stylesheet())
        self._fif_results.itemDoubleClicked.connect(self._open_fif_result)
        hdr = self._fif_results.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._fif_results.setColumnWidth(2, 84)
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
        self._all_find.setToolTip(tr("tooltip.all_find"))
        grid.addWidget(self._all_find, 0, 1)

        grid.addWidget(QLabel(tr("label.replace_with")), 1, 0)
        self._all_replace = QLineEdit()
        self._all_replace.setToolTip(tr("tooltip.all_replace"))
        grid.addWidget(self._all_replace, 1, 1)

        self._all_case  = QCheckBox(tr("label.match_case"))
        self._all_regex = QCheckBox(tr("label.regex"))
        self._all_case.setToolTip(tr("tooltip.all_case"))
        self._all_regex.setToolTip(tr("tooltip.all_regex"))
        opts = QHBoxLayout()
        opts.addWidget(self._all_case)
        opts.addWidget(self._all_regex)
        opts.addStretch()
        grid.addLayout(opts, 2, 0, 1, 2)

        btns = QHBoxLayout()
        btn_fa = QPushButton("🔍 " + tr("action.find"))
        btn_ra = QPushButton("↔ " + tr("action.replace_in_all_docs"))
        btn_fa.setToolTip(tr("tooltip.all_search"))
        btn_ra.setToolTip(tr("tooltip.all_replace_btn"))
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
        self._all_results.setHeaderLabels([tr("label.col_doc_line"), tr("label.col_text")])
        self._all_results.setRootIsDecorated(True)
        self._all_results.setAlternatingRowColors(True)
        self._all_results.setMinimumHeight(200)
        self._all_results.setStyleSheet(_results_stylesheet())
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

    def _do_find(self, edit_widget, forward: bool = True,
                 highlight_all: bool = True) -> bool:
        editor = self._current_editor()
        if not editor:
            return False
        text = edit_widget.currentText() if hasattr(edit_widget, "currentText") else edit_widget.text()
        if not text:
            return False

        flags = self._get_flags()
        # Comportamento "PRO editor": mantieni evidenziate TUTTE le occorrenze
        # mentre navighi (Find Next/Prev). Le riapplichiamo ad ogni ricerca così
        # da ripulire eventuali residui di pattern precedenti.
        if highlight_all:
            editor.clear_indicator(INDICATOR_MARK1)
            self._highlight_all(editor, text, flags, INDICATOR_MARK1)
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
            # findFirst seleziona il match, ma QScintilla disegna la selezione
            # attenuata quando l'editor non ha il focus (dopo Ctrl+F il focus
            # resta sul dialog) e non centra la riga. Rinforziamo con
            # highlight_find_match: indicatore marcato sulla parola + riga
            # centrata, sempre visibili.
            self._emphasize_find_selection(editor)
        else:
            self._lbl_status.setText(tr("msg.no_results", query=text))
        return found

    def _emphasize_find_selection(self, editor) -> None:
        """Dopo un match nativo (findFirst), evidenzia la parola con
        l'indicatore marcato e centra la riga, anche se il focus è sul dialog.
        """
        if not hasattr(editor, "highlight_find_match"):
            return
        try:
            sel = editor.getSelection()  # (lineFrom, idxFrom, lineTo, idxTo)
            line_from, col_from, line_to, col_to = sel
            if line_from < 0:
                return
            if line_to == line_from and col_to > col_from:
                editor.highlight_find_match(line_from, col_from, col_to)
            else:
                # Match multiriga (es. regex): centra/evidenzia la prima riga.
                editor.highlight_find_match(line_from, col_from, col_from)
        except Exception:
            pass

    def _clear_find_highlights(self, editor) -> None:
        """Rimuove TUTTE le evidenziazioni della ricerca (match corrente, riga e
        occorrenze "tutte"). Chiamato prima di ogni nuova ricerca e alla chiusura
        del dialog, così non restano marcature "fantasma" di ricerche precedenti
        — comportamento dei comuni editor PRO (VS Code, Sublime, Notepad++)."""
        if not editor:
            return
        for ind in (INDICATOR_FIND, INDICATOR_FIND_LINE, INDICATOR_MARK1):
            try:
                editor.clear_indicator(ind)
            except Exception:
                pass

    def _suspend_smart_highlight(self) -> None:
        """Sospende temporaneamente l'"Evidenziazione automatica parola" (smart
        highlight della parola sotto il cursore) mentre il pannello Cerca è
        aperto. È il comportamento di VS Code / Sublime: durante una ricerca
        l'unica evidenziazione che deve restare è quella dei risultati cercati,
        senza il "rumore" della parola sotto il cursore — che usa colori simili
        e confonde l'utente.

        NB: non tocca le impostazioni persistenti (Settings); è una sospensione
        volatile, ripristinata alla chiusura del dialog.
        """
        # 1) Smart highlight INTERNO dell'editor (INDICATOR_SMART_HL): sospendi
        #    su tutti gli editor aperti e ripulisci i residui.
        try:
            editors = self._mw._tab_manager.all_editors()
        except Exception:
            editors = []
        for ed in editors:
            try:
                if getattr(ed, "_smart_highlight_enabled", False):
                    ed.set_smart_highlight_enabled(False)
            except Exception:
                pass

        # 2) Smart highlight ESTERNO (SmartHighlighter, ui/smart_highlight.py):
        #    disabilita e pulisci. Manteniamo lo stato precedente per ripristino.
        hl = getattr(self._mw, "_smart_highlighter", None)
        self._sh_was_enabled = bool(getattr(hl, "_enabled", False)) if hl else False
        if hl is not None:
            try:
                # set_enabled propaga anche agli editor (e salverebbe nei Settings):
                # evitiamo di persistere, agiamo direttamente sullo stato volatile.
                hl._enabled = False
                hl.clear()
                if hasattr(hl, "_timer"):
                    hl._timer.stop()
                hl._last_word = ""
            except Exception:
                pass

    def _resume_smart_highlight(self) -> None:
        """Ripristina l'"Evidenziazione automatica parola" allo stato che aveva
        prima dell'apertura del dialog Cerca (rispettando le impostazioni)."""
        from config.settings import Settings
        # Stato persistente "vero" dello smart highlight (impostazioni utente).
        try:
            enabled = bool(Settings.instance().get(
                "editor/smart_highlight_enabled", True))
        except Exception:
            enabled = True

        # 1) Editor interni: ripristina secondo le impostazioni.
        try:
            editors = self._mw._tab_manager.all_editors()
        except Exception:
            editors = []
        for ed in editors:
            try:
                ed.set_smart_highlight_enabled(enabled)
            except Exception:
                pass

        # 2) SmartHighlighter esterno: ripristina lo stato che aveva prima.
        hl = getattr(self._mw, "_smart_highlighter", None)
        if hl is not None:
            try:
                hl._enabled = bool(getattr(self, "_sh_was_enabled", enabled))
            except Exception:
                pass

    def showEvent(self, event) -> None:
        """All'apertura del dialog Cerca sospendi lo smart highlight, così
        durante la ricerca restano visibili solo i risultati (riga corrente +
        match corrente + tutte le occorrenze), come negli editor PRO."""
        super().showEvent(event)
        try:
            self._suspend_smart_highlight()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        """Alla chiusura del dialog rimuovi le evidenziazioni della ricerca e
        ripristina lo smart highlight: chiuso il pannello Trova, l'editor torna
        al suo stato normale senza marcature residue (come negli editor PRO)."""
        try:
            self._clear_find_highlights(self._current_editor())
        except Exception:
            pass
        try:
            self._resume_smart_highlight()
        except Exception:
            pass
        super().closeEvent(event)

    def _do_incremental(self) -> None:
        """Cerca mentre si digita e aggiorna la lista occorrenze."""
        editor = self._current_editor()
        if not editor:
            return
        text = self._find_edit.currentText()
        if len(text) < 1:
            # Query svuotata → via tutte le evidenziazioni (niente fantasmi).
            self._clear_find_highlights(editor)
            self._find_occurrences.clear()
            self._lbl_status.setText("")
            return
        flags = self._get_flags()
        # Comportamento "PRO editor": ogni nuova ricerca azzera le evidenziazioni
        # precedenti (niente fantasmi), poi evidenzia TUTTE le occorrenze
        # (highlight secondario) e marca il match corrente in modo distinto
        # (highlight forte). La pulizia di riga/match la fa highlight_find_match.
        editor.clear_indicator(INDICATOR_FIND_LINE)
        self._do_find(self._find_edit, forward=True, highlight_all=True)
        # Aggiorna lista occorrenze con un minimo di 2 caratteri
        if len(text) >= 2:
            self._populate_occurrences(editor, text, flags)

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
                # Bugfix: prima era un no-op (rf"{pat}"), quindi "parola intera"
                # non aveva alcun effetto su lista occorrenze e conteggio.
                pat = rf"\b{pat}\b"
            compiled = re.compile(pat, re_flags)
        except re.error as e:
            self._lbl_status.setText(tr("msg.regex_error", error=str(e)))
            return

        _ROLE = Qt.ItemDataRole.UserRole
        lines = editor.text().split("\n")
        count = 0
        panel_results = []
        items_to_add = []
        file_path = str(editor.file_path) if editor.file_path else ""
        _MAX_ITEMS = 2_000
        for line_idx, line_text in enumerate(lines):
            line_matches = list(compiled.finditer(line_text))
            if not line_matches:
                continue
            # Count all occurrences but add only one list entry per line
            # (standard behaviour: Notepad++, VS Code, Sublime Text).
            count += len(line_matches)
            if len(items_to_add) < _MAX_ITEMS:
                m = line_matches[0]
                item = QTreeWidgetItem([
                    str(line_idx + 1),
                    line_text.strip()[:120]
                ])
                item.setTextAlignment(0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setData(0, _ROLE, {
                    "line": line_idx + 1,
                    "col":  m.start(),
                    "len":  m.end() - m.start(),
                })
                items_to_add.append(item)
                panel_results.append({
                    "file": file_path,
                    "line": line_idx,
                    "text": line_text,
                    "col":  m.start(),
                })

        # Inserimento batch per evitare repaint per ogni riga
        self._find_occurrences.setUpdatesEnabled(False)
        for item in items_to_add:
            self._find_occurrences.addTopLevelItem(item)
        self._find_occurrences.setUpdatesEnabled(True)

        if count:
            self._lbl_status.setText(tr("msg.occurrences_n", count=count))
            panel = getattr(self._mw, "_find_result_panel", None)
            if panel and file_path:
                panel.add_results(pattern_text, panel_results)
        else:
            self._lbl_status.setText(tr("msg.no_results_query", query=pattern_text))

    def _goto_occurrence(self, item: QTreeWidgetItem) -> None:
        """Vai alla riga dell'occorrenza cliccata, evidenziando in modo marcato
        sia la riga di destinazione sia la parola trovata (visibile anche sui
        temi chiari, dove il caret-line del tema è spesso troppo tenue)."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        editor = self._current_editor()
        if not editor:
            return

        line0 = max(0, data["line"] - 1)   # numero riga 0-based
        # `col`/`len` salvati da _populate_occurrences sono offset di CARATTERE
        # (da re.finditer sulla riga). QScintilla lavora in byte: su righe con
        # accenti vanno convertiti, altrimenti la selezione/indicatore finisce
        # sulla parola sbagliata.
        char_col = data.get("col", 0)
        char_len = data.get("len", 0)
        try:
            byte_start = editor.char_col_to_byte_col(line0, char_col)
            byte_end   = editor.char_col_to_byte_col(line0, char_col + char_len)
        except Exception:
            byte_start, byte_end = char_col, char_col + char_len

        editor.go_to_line(data["line"])
        # Evidenzia riga intera + parola trovata con gli indicatori marcati.
        if hasattr(editor, "highlight_find_match"):
            try:
                editor.highlight_find_match(line0, byte_start, byte_end)
            except Exception:
                pass
        # Seleziona anche la parola, così resta evidente dopo il focus.
        try:
            if byte_end > byte_start:
                editor.setSelection(line0, byte_start, line0, byte_end)
        except Exception:
            pass
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
            matches = list(compiled.finditer(text))
            if not matches:
                return 0

            # Costruisce la tabella degli offset di inizio riga (in caratteri)
            # una sola volta, invece di richiamare self.text() per ogni match.
            line_starts = [0]
            for i, ch in enumerate(text):
                if ch == '\n':
                    line_starts.append(i + 1)

            def char_to_line_bytecol(char_off: int) -> tuple[int, int]:
                char_off = max(0, min(char_off, len(text)))
                line = bisect.bisect_right(line_starts, char_off) - 1
                ls = line_starts[line]
                col_bytes = len(text[ls:char_off].encode("utf-8"))
                return line, col_bytes

            # Cap: non evidenziare più di 10 000 occorrenze per non bloccare l'UI
            _MAX = 10_000
            for m in matches[:_MAX]:
                ls, cs = char_to_line_bytecol(m.start())
                le, ce = char_to_line_bytecol(m.end())
                editor.fillIndicatorRange(ls, cs, le, ce, indicator)
            return len(matches)
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
        path = QFileDialog.getExistingDirectory(self, tr("msg.select_directory"))
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
            self._fif_status.setText(tr("msg.enter_search_text"))
            return
        if not base_dir.is_dir():
            self._fif_status.setText(tr("msg.invalid_directory"))
            return

        self._fif_results.clear()
        self._fif_status.setText(tr("msg.searching"))
        QApplication.processEvents()

        re_flags = 0 if case_s else re.IGNORECASE
        try:
            pattern = re.compile(query if use_re else re.escape(query), re_flags)
        except re.error as e:
            self._fif_status.setText(tr("msg.regex_error", error=str(e)))
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
                # One list entry per line; count all occurrences for the header
                # (Notepad++ / VS Code style: no duplicate rows for same line).
                file_match_count = 0
                file_line_entries = []
                for i, line in enumerate(lines):
                    lm = list(pattern.finditer(line))
                    if lm:
                        file_match_count += len(lm)
                        file_line_entries.append((i + 1, line, lm[0].start(), lm[0].end()))
                if not file_line_entries:
                    continue
                total_files   += 1
                total_matches += file_match_count
                try:
                    rel = str(fpath.relative_to(base_dir))
                except ValueError:
                    rel = str(fpath)
                file_item = QTreeWidgetItem(
                    self._fif_results,
                    [f"📄 {rel}  (" + tr("msg.file_matches", matches=file_match_count) + ")", "", ""]
                )
                file_item.setData(0, _ROLE, {"path": str(fpath)})
                btn_f = QPushButton(tr("button.replace"))
                btn_f.setFixedSize(80, 22)
                btn_f.setToolTip(tr("tooltip.fif_replace_in_file"))
                btn_f.clicked.connect(lambda _checked, fi=file_item: self._replace_fif_file(fi))
                self._fif_results.setItemWidget(file_item, 2, btn_f)

                for line_num, line_text, col_s, col_e in file_line_entries:
                    child = QTreeWidgetItem([
                        "  " + tr("msg.row_n", n=line_num), line_text.strip()[:140], ""
                    ])
                    child.setData(0, _ROLE, {
                        "path": str(fpath), "line": line_num,
                        "col_start": col_s, "col_end": col_e,
                    })
                    file_item.addChild(child)   # addChild prima di setItemWidget
                    btn_m = QPushButton(tr("button.replace"))
                    btn_m.setFixedSize(80, 22)
                    btn_m.setToolTip(tr("tooltip.fif_replace_match"))
                    btn_m.clicked.connect(lambda _checked, ci=child: self._replace_fif_single(ci))
                    self._fif_results.setItemWidget(child, 2, btn_m)
                file_item.setExpanded(True)

        if total_matches == 0:
            QTreeWidgetItem(self._fif_results, [tr("msg.no_results_found"), "", ""])
            self._fif_status.setText(tr("msg.zero_results", query=query))
        else:
            self._fif_status.setText(
                tr("msg.results_count_files", matches=total_matches, files=total_files)
            )
            self._send_to_result_panel(query, self._fif_results)
        self._fif_results.resizeColumnToContents(0)

    def _open_fif_result(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        path_str  = data.get("path")
        line_num  = data.get("line")
        col_start = data.get("col_start")
        col_end   = data.get("col_end")
        if path_str:
            self._mw.open_files([Path(path_str)])
            editor = self._mw._tab_manager.current_editor()
            if editor and line_num:
                ln = int(line_num) - 1
                if col_start is not None and col_end is not None:
                    editor.setSelection(ln, col_start, ln, col_end)
                else:
                    editor.go_to_line(int(line_num))
                editor.ensureLineVisible(ln)
                editor.setFocus()

    def _do_replace_in_files(self) -> None:
        import os, fnmatch
        from PyQt6.QtWidgets import QMessageBox
        query        = self._fif_find.text().strip()
        replace_text = self._fif_replace.text()
        base_dir     = Path(self._fif_dir.text())
        filters      = [f.strip() for f in self._fif_filter.text().split(";") if f.strip()]
        use_re       = self._fif_regex.isChecked()
        case_s       = self._fif_case.isChecked()
        recurse      = self._fif_sub.isChecked()

        if not query:
            self._fif_status.setText(tr("msg.enter_search_text"))
            return
        if not base_dir.is_dir():
            self._fif_status.setText(tr("msg.invalid_directory"))
            return

        re_flags = 0 if case_s else re.IGNORECASE
        try:
            pattern = re.compile(query if use_re else re.escape(query), re_flags)
        except re.error as e:
            self._fif_status.setText(tr("msg.regex_error", error=str(e)))
            return

        walker = os.walk(str(base_dir)) if recurse \
            else [(str(base_dir), [], os.listdir(str(base_dir)))]

        files_to_modify = []
        for root, _, files in walker:
            for fname in files:
                if filters and not any(fnmatch.fnmatch(fname, f) for f in filters):
                    continue
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                new_text, count = pattern.subn(replace_text, text)
                if count > 0:
                    files_to_modify.append((fpath, new_text, count))

        if not files_to_modify:
            self._fif_status.setText(tr("msg.replace_no_matches"))
            return

        total_matches = sum(c for _, _, c in files_to_modify)
        total_files   = len(files_to_modify)

        reply = QMessageBox.question(
            self,
            tr("action.replace_in_files"),
            tr("msg.confirm_replace_files", count=total_matches, files=total_files),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        errors = []
        for fpath, new_text, _ in files_to_modify:
            try:
                fpath.write_text(new_text, encoding="utf-8")
                for editor in self._mw._tab_manager.all_editors():
                    if editor.file_path and editor.file_path.resolve() == fpath.resolve():
                        cursor = editor.getCursorPosition()
                        editor.beginUndoAction()
                        editor.selectAll()
                        editor.replaceSelectedText(new_text)
                        editor.endUndoAction()
                        line = min(cursor[0], max(0, editor.lines() - 1))
                        editor.setCursorPosition(line, 0)
                        editor.mark_saved()
            except Exception as exc:
                errors.append(tr("msg.replace_file_error", path=str(fpath), error=str(exc)))

        if errors:
            QMessageBox.warning(self, tr("action.replace_in_files"), "\n".join(errors))

        self._fif_status.setText(
            tr("msg.replaced_in_files", count=total_matches, files=total_files)
        )
        self._do_find_in_files()

    def _replace_fif_file(self, file_item: QTreeWidgetItem) -> None:
        """Sostituisce tutte le corrispondenze in un singolo file (pulsante ↔ del nodo file)."""
        replace_text = self._fif_replace.text()
        data = file_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        fpath  = Path(data["path"])
        query  = self._fif_find.text().strip()
        use_re = self._fif_regex.isChecked()
        case_s = self._fif_case.isChecked()
        re_flags = 0 if case_s else re.IGNORECASE
        try:
            pattern = re.compile(query if use_re else re.escape(query), re_flags)
        except re.error:
            return
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            new_content, count = pattern.subn(replace_text, content)
            fpath.write_text(new_content, encoding="utf-8")
            self._update_open_editor(fpath, new_content)
        except Exception as exc:
            self._fif_status.setText(tr("msg.replace_file_error", path=str(fpath), error=str(exc)))
            return
        self._fif_results.invisibleRootItem().removeChild(file_item)
        self._fif_status.setText(tr("msg.replaced_in_files", count=count, files=1))

    def _replace_fif_single(self, match_item: QTreeWidgetItem) -> None:
        """Sostituisce una singola corrispondenza (pulsante ↔ del nodo riga)."""
        replace_text = self._fif_replace.text()
        data = match_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        fpath     = Path(data["path"])
        line_num  = data["line"]     # 1-based
        col_start = data["col_start"]
        col_end   = data["col_end"]

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self._fif_status.setText(tr("msg.replace_file_error", path=str(fpath), error=str(exc)))
            return

        lines = content.split("\n")
        if line_num - 1 >= len(lines):
            return
        line = lines[line_num - 1]

        if self._fif_regex.isChecked():
            query    = self._fif_find.text().strip()
            re_flags = 0 if self._fif_case.isChecked() else re.IGNORECASE
            try:
                m = re.compile(query, re_flags).search(line, col_start)
                repl = m.expand(replace_text) if (m and m.start() == col_start) else replace_text
            except re.error:
                repl = replace_text
        else:
            repl = replace_text

        lines[line_num - 1] = line[:col_start] + repl + line[col_end:]
        new_content = "\n".join(lines)

        try:
            fpath.write_text(new_content, encoding="utf-8")
            self._update_open_editor(fpath, new_content)
        except Exception as exc:
            self._fif_status.setText(tr("msg.replace_file_error", path=str(fpath), error=str(exc)))
            return

        file_item = match_item.parent()
        if file_item is None:
            return
        file_item.removeChild(match_item)
        remaining = file_item.childCount()
        if remaining == 0:
            self._fif_results.invisibleRootItem().removeChild(file_item)
        else:
            fp = Path(file_item.data(0, Qt.ItemDataRole.UserRole)["path"])
            base_dir = Path(self._fif_dir.text())
            try:
                rel = str(fp.relative_to(base_dir))
            except ValueError:
                rel = str(fp)
            file_item.setText(
                0, f"📄 {rel}  (" + tr("msg.file_matches", matches=remaining) + ")"
            )
        self._fif_status.setText(tr("msg.replaced_in_files", count=1, files=1))

    def _update_open_editor(self, fpath: Path, new_content: str) -> None:
        """Aggiorna l'editor in memoria se il file è già aperto."""
        for editor in self._mw._tab_manager.all_editors():
            if editor.file_path and editor.file_path.resolve() == fpath.resolve():
                cursor = editor.getCursorPosition()
                editor.beginUndoAction()
                editor.selectAll()
                editor.replaceSelectedText(new_content)
                editor.endUndoAction()
                line = min(cursor[0], max(0, editor.lines() - 1))
                editor.setCursorPosition(line, 0)
                editor.mark_saved()

    # ── Find in All Docs ──────────────────────────────────────────────────────

    def _do_find_all_docs(self) -> None:
        query = self._all_find.text().strip()
        if not query:
            self._all_status.setText(tr("msg.enter_search_text"))
            return
        use_re = self._all_regex.isChecked()
        case_s = self._all_case.isChecked()
        re_flags = 0 if case_s else re.IGNORECASE
        try:
            pattern = re.compile(query if use_re else re.escape(query), re_flags)
        except re.error as e:
            self._all_status.setText(tr("msg.regex_error", error=str(e)))
            return

        self._all_results.clear()
        _ROLE = Qt.ItemDataRole.UserRole
        total_matches = 0

        for editor in self._mw._tab_manager.all_editors():
            text = editor.text()
            name = editor.file_path.name if editor.file_path else tr("label.untitled")
            matches = []
            for i, line in enumerate(text.split("\n")):
                m = pattern.search(line)
                if m:
                    matches.append((i + 1, line, m.start()))
            if not matches:
                continue
            total_matches += len(matches)
            doc_item = QTreeWidgetItem(
                self._all_results,
                [f"📄 {name}  (" + tr("msg.file_matches", matches=len(matches)) + ")", ""]
            )
            doc_item.setData(0, _ROLE, {"editor": editor})
            for ln, lt, col in matches:
                child = QTreeWidgetItem(["  " + tr("msg.row_n", n=ln), lt.strip()[:140]])
                # Salva anche la colonna del match così il pannello risultati
                # può evidenziare la parola con precisione (non solo la riga).
                child.setData(0, _ROLE, {"editor": editor, "line": ln, "col": col})
                doc_item.addChild(child)
            doc_item.setExpanded(True)

        if total_matches == 0:
            QTreeWidgetItem(self._all_results, [tr("msg.no_results_found"), ""])
            self._all_status.setText(tr("msg.zero_results", query=query))
        else:
            self._all_status.setText(tr("msg.results_count", matches=total_matches))
            self._send_to_result_panel(query, self._all_results, in_docs=True)
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
        col      = data.get("col")
        if editor is not None:
            self._mw._tab_manager.set_current_editor(editor)
            if line_num:
                ln = int(line_num) - 1
                if col is not None:
                    # Evidenzia la parola: seleziona dal match fino a fine parola
                    # ricalcolata, o almeno posiziona il cursore sulla colonna.
                    line_text = editor.text(ln).rstrip("\n").rstrip("\r")
                    end = col
                    while end < len(line_text) and (line_text[end].isalnum() or line_text[end] == "_"):
                        end += 1
                    editor.setSelection(ln, col, ln, max(end, col + 1))
                    editor.ensureLineVisible(ln)
                else:
                    editor.go_to_line(int(line_num))
                editor.setFocus()

    # ── Stato ─────────────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        if _last_find_text:
            self._find_edit.setCurrentText(_last_find_text)
            self._find_edit2.setCurrentText(_last_find_text)
        self._restore_transparency_state()

    def _restore_transparency_state(self) -> None:
        """Ripristina lo stato del controllo trasparenza dai Settings (livello
        opacità e attivazione), così la scelta dell'utente persiste tra le
        sessioni."""
        try:
            from config.settings import Settings
            s = Settings.instance()
            opacity = int(s.get("find/opacity", 70))
            enabled = bool(s.get("find/transparent_enabled", False))
        except Exception:
            opacity, enabled = 70, False

        opacity = max(20, min(100, opacity))
        # blockSignals: impostiamo i valori senza ri-salvare nei Settings.
        try:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(opacity)
            self._opacity_slider.blockSignals(False)
            self._opacity_label.setText(f"{opacity}%")
            self._chk_transparent.blockSignals(True)
            self._chk_transparent.setChecked(enabled)
            self._chk_transparent.blockSignals(False)
            self._opacity_slider.setEnabled(enabled)
            self._opacity_label.setEnabled(enabled)
        except Exception:
            pass
        self._apply_transparency()

    # ── API pubblica (chiamata da MainWindow) ─────────────────────────────────

    @classmethod
    def _get_or_create(cls, main_window: "MainWindow") -> "FindReplaceDialog":
        global _instance
        if _instance is None or _instance._mw is not main_window:
            _instance = cls(main_window)
        return _instance

    @classmethod
    def _get_selected_text(cls, main_window: "MainWindow") -> str:
        editor = main_window._current_editor()
        if editor is None:
            return ""
        sel = editor.selectedText()
        if "\n" in sel:
            return ""
        return sel

    @classmethod
    def show_find(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(0)
        sel = cls._get_selected_text(main_window)
        if sel:
            dlg._find_edit.setCurrentText(sel)
        dlg.show()
        dlg.raise_()
        dlg._find_edit.setFocus()

    def _send_to_result_panel(self, query: str, tree: "QTreeWidget",
                              in_docs: bool = False) -> None:
        """Invia i risultati al FindResultPanel nel pannello inferiore."""
        panel = getattr(self._mw, "_find_result_panel", None)
        if panel is None:
            return
        _ROLE = Qt.ItemDataRole.UserRole
        results = []
        for fi in range(tree.topLevelItemCount()):
            file_item = tree.topLevelItem(fi)
            file_data = file_item.data(0, _ROLE)
            if not isinstance(file_data, dict):
                continue
            for ci in range(file_item.childCount()):
                child = file_item.child(ci)
                child_data = child.data(0, _ROLE)
                if not isinstance(child_data, dict):
                    continue
                line_raw = child_data.get("line", 1)
                line_0 = int(line_raw) - 1 if line_raw else 0
                if in_docs:
                    editor = child_data.get("editor")
                    fp = str(editor.file_path) if editor and editor.file_path else ""
                else:
                    fp = child_data.get("path", "")
                results.append({
                    "file": fp,
                    "line": line_0,
                    "text": child.text(1),
                    "col":  child_data.get("col", 0),
                })
        if results:
            panel.add_results(query, results)

    @classmethod
    def show_replace(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(1)
        sel = cls._get_selected_text(main_window)
        if sel:
            dlg._find_edit2.setCurrentText(sel)
        dlg.show()
        dlg.raise_()
        dlg._find_edit2.setFocus()

    @classmethod
    def show_find_in_files(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(2)
        sel = cls._get_selected_text(main_window)
        if sel:
            dlg._fif_find.setText(sel)
        dlg.show()
        dlg.raise_()

    @classmethod
    def show_find_all_docs(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(3)
        sel = cls._get_selected_text(main_window)
        if sel:
            dlg._all_find.setText(sel)
        dlg.show()
        dlg.raise_()

    @classmethod
    def show_replace_all_docs(cls, main_window: "MainWindow") -> None:
        dlg = cls._get_or_create(main_window)
        dlg._tabs.setCurrentIndex(3)
        sel = cls._get_selected_text(main_window)
        if sel:
            dlg._all_find.setText(sel)
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
