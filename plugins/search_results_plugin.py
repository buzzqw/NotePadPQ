"""
plugins/search_results_plugin.py — Plugin Search PQ / Trova-Sostituisci
NotePadPQ

Pannello dock multifunzione dedicato ai risultati di ricerca:
  - Ricerca nel documento aperto (text intelligente, regex, LIKE)
  - Ricerca nei file / directory (glob, ricorsivo)
  - Filtro rapido nei risultati (grep/AND/NOT, regex, LIKE)
  - Sostituisci nel file corrente o in tutti i file dei risultati
  - Navigazione prev/next con F4/Shift+F4
  - Evidenziazione di tutti i match nell'editor
  - Storico ricerche (ultime 20)
  - Validazione regex in tempo reale
  - Auto-search con toggle
  - Cerca nella selezione
  - Copia come testo/CSV
  - Tema automatico chiaro/scuro

Attivabile dal menu Plugin -> Search PQ (Ctrl+Alt+F)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel,
    QMenu, QLineEdit, QApplication, QMessageBox,
    QToolButton, QCheckBox, QComboBox, QFileDialog,
)
from PyQt6.QtGui import QColor, QBrush, QFont, QKeyEvent

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Costanti ─────────────────────────────────────────────────────────────────

_MAX_HISTORY = 20
_INDICATOR_MARK1 = 1  # INDICATOR_MARK1 da editor_widget.py


# ─── Helper traduzioni e tema ─────────────────────────────────────────────────

def _t(key: str, **kw) -> str:
    """Shortcut per le chiavi del plugin search_results."""
    return tr(f"plugin.search_results.{key}", **kw)


def _theme_colors() -> dict:
    """Colori del tema attivo per intestazioni e nodi dell'albero risultati."""
    try:
        from config.themes import ThemeManager
        tm     = ThemeManager.instance()
        theme  = tm.get_theme(tm._active_name) or {}
        tokens = theme.get("tokens", {}) or {}
        ui     = theme.get("ui", {}) or {}
        is_dark = bool(theme.get("meta", {}).get("dark", True))
    except Exception:
        tokens, ui, is_dark = {}, {}, True

    def _tok(name: str, default: str) -> str:
        v = tokens.get(name, {})
        return (v.get("fg") if isinstance(v, dict) else None) or default

    def _ui(name: str, default: str) -> str:
        v = ui.get(name)
        return v if isinstance(v, str) and v else default

    if is_dark:
        return {
            "header":  _tok("keyword", "#4fa3e0"),
            "section": _tok("function", "#7bb86f"),
            "file":    _tok("string", "#9bc36f"),
            "files_header": _tok("type", "#e0a060"),
            "bg":      _ui("editor_bg", "#1e1e1e"),
            "fg":      _ui("editor_fg", "#d4d4d4"),
            "alt_bg":  _ui("caret_line_bg", "#262a2d"),
            "sel_bg":  _ui("selection_bg", "#264f78"),
            "sel_fg":  "#ffffff",
            "border":  _ui("fold_bg", "#3a3d41"),
            "hover_bg": _ui("caret_line_bg", "#2d3338"),
            "regex_ok": "#4caf50",
            "regex_err": "#f44336",
        }
    return {
        "header":  _tok("keyword", "#2060a0"),
        "section": _tok("function", "#206040"),
        "file":    _tok("string", "#206020"),
        "files_header": _tok("type", "#a06020"),
        "bg":      _ui("editor_bg", "#ffffff"),
        "fg":      _ui("editor_fg", "#1e1e1e"),
        "alt_bg":  "#f1f3f5",
        "sel_bg":  "#cfe3ff",
        "sel_fg":  "#0a2b4a",
        "border":  "#c8cdd2",
        "hover_bg": "#e6f0fb",
        "regex_ok": "#2e7d32",
        "regex_err": "#c62828",
    }


def _tree_stylesheet(c: dict) -> str:
    """Foglio di stile per il QTreeWidget dei risultati, a tema."""
    return f"""
        QTreeWidget {{
            background-color: {c.get('bg', '#1e1e1e')};
            alternate-background-color: {c.get('alt_bg', '#262a2d')};
            color: {c.get('fg', '#d4d4d4')};
            border: 1px solid {c.get('border', '#3a3d41')};
            outline: 0;
        }}
        QTreeWidget::item {{
            padding: 2px 0px;
            border: 0px;
        }}
        QTreeWidget::item:hover {{
            background-color: {c.get('hover_bg', '#2d3338')};
        }}
        QTreeWidget::item:selected {{
            background-color: {c.get('sel_bg', '#264f78')};
            color: {c.get('sel_fg', '#ffffff')};
        }}
        QHeaderView::section {{
            background-color: {c.get('alt_bg', '#262a2d')};
            color: {c.get('fg', '#d4d4d4')};
            padding: 3px 6px;
            border: 0px;
            border-bottom: 1px solid {c.get('border', '#3a3d41')};
            font-weight: bold;
        }}
    """


# ─── Pannello risultati ───────────────────────────────────────────────────────

class _SearchResultsPanel(QWidget):
    """Pannello multifunzione per i risultati di trova/sostituisci."""
    navigate_requested = pyqtSignal(str, int)

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._all_results: list[dict] = []
        self._current_query: str = ""
        self._search_history: list[str] = []
        self._colors = _theme_colors()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._do_search_in_doc)
        self._setup_ui()
        self.navigate_requested.connect(self._do_navigate)
        self._restore_history()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.setSpacing(3)

        # ══════════════════════════════════════════════════════════════════════
        # SEZIONE 1: CERCA NEL DOCUMENTO
        # ══════════════════════════════════════════════════════════════════════

        lbl_search_doc = QLabel(_t("section_search_doc"))
        lbl_search_doc.setToolTip(_t("section_search_doc_tooltip"))
        lbl_search_doc.setStyleSheet(
            f"font-weight: bold; color: {self._colors['header']}; padding: 1px 0;")
        vl.addWidget(lbl_search_doc)

        # ── Riga A: campo testo + opzioni ricerca ─────────────────────────────
        sl = QHBoxLayout()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(_t("search_doc_placeholder"))
        self._search_edit.setToolTip(_t("search_doc_tooltip"))
        self._search_edit.setFixedHeight(22)
        self._search_edit.returnPressed.connect(self._do_search_in_doc)
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        sl.addWidget(self._search_edit, 1)

        # Pulsante storico ricerche
        self._history_btn = QToolButton()
        self._history_btn.setText("⏱")
        self._history_btn.setToolTip(_t("search_history_tooltip"))
        self._history_btn.setFixedSize(22, 22)
        self._history_btn.clicked.connect(self._show_search_history)
        sl.addWidget(self._history_btn)

        # Indicatore validità regex (visibile solo in modalità regex)
        self._regex_indicator = QLabel("")
        self._regex_indicator.setFixedSize(18, 22)
        self._regex_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._regex_indicator.setToolTip("")
        self._regex_indicator.hide()
        sl.addWidget(self._regex_indicator)

        self._chk_case = QCheckBox(_t("search_case"))
        self._chk_case.setToolTip(_t("search_case_tooltip"))
        self._chk_case.setFixedHeight(22)
        self._chk_case.stateChanged.connect(self._on_option_changed)
        sl.addWidget(self._chk_case)

        self._chk_whole_word = QCheckBox(_t("search_whole_word"))
        self._chk_whole_word.setToolTip(_t("search_whole_word_tooltip"))
        self._chk_whole_word.setFixedHeight(22)
        self._chk_whole_word.stateChanged.connect(self._on_option_changed)
        sl.addWidget(self._chk_whole_word)

        self._search_mode = QComboBox()
        self._search_mode.addItem(_t("search_mode_text"), "text")
        self._search_mode.addItem(_t("search_mode_regex"), "regex")
        self._search_mode.addItem(_t("search_mode_like"), "like")
        self._search_mode.setFixedHeight(22)
        self._search_mode.setToolTip(_t("search_mode_tooltip"))
        self._search_mode.currentIndexChanged.connect(self._on_search_mode_changed)
        sl.addWidget(self._search_mode)

        btn_search = QPushButton(_t("btn_search"))
        btn_search.setFixedHeight(22)
        btn_search.setToolTip(_t("btn_search_tooltip"))
        btn_search.clicked.connect(self._do_search_in_doc)
        sl.addWidget(btn_search)

        self._chk_append = QCheckBox(_t("append_results"))
        self._chk_append.setToolTip(_t("append_results_tooltip"))
        self._chk_append.setFixedHeight(22)
        sl.addWidget(self._chk_append)

        vl.addLayout(sl)

        # ── Riga A2: opzioni aggiuntive ────────────────────────────────────────
        opts = QHBoxLayout()

        self._chk_auto_search = QCheckBox(_t("auto_search"))
        self._chk_auto_search.setToolTip(_t("auto_search_tooltip"))
        self._chk_auto_search.setChecked(True)
        self._chk_auto_search.setFixedHeight(22)
        self._chk_auto_search.stateChanged.connect(self._on_auto_search_toggled)
        opts.addWidget(self._chk_auto_search)

        self._chk_in_selection = QCheckBox(_t("search_in_selection"))
        self._chk_in_selection.setToolTip(_t("search_in_selection_tooltip"))
        self._chk_in_selection.setFixedHeight(22)
        self._chk_in_selection.stateChanged.connect(self._on_option_changed)
        opts.addWidget(self._chk_in_selection)

        opts.addStretch(1)
        vl.addLayout(opts)

        # ── Riga B: sommario + pulsanti navigazione ───────────────────────────
        tb = QHBoxLayout()
        self._lbl_summary = QLabel(_t("no_search"))
        self._lbl_summary.setStyleSheet("font-weight: bold;")
        tb.addWidget(self._lbl_summary, 1)

        btn_prev = QToolButton()
        btn_prev.setText("▲")
        btn_prev.setToolTip(_t("btn_prev"))
        btn_prev.setFixedSize(26, 22)
        btn_prev.clicked.connect(self._navigate_prev)
        tb.addWidget(btn_prev)

        btn_next = QToolButton()
        btn_next.setText("▼")
        btn_next.setToolTip(_t("btn_next"))
        btn_next.setFixedSize(26, 22)
        btn_next.clicked.connect(self._navigate_next)
        tb.addWidget(btn_next)

        btn_clear = QToolButton()
        btn_clear.setText("🗑")
        btn_clear.setToolTip(_t("btn_clear"))
        btn_clear.setFixedSize(26, 22)
        btn_clear.clicked.connect(self.clear_all)
        tb.addWidget(btn_clear)

        vl.addLayout(tb)

        # ══════════════════════════════════════════════════════════════════════
        # SEZIONE 2: CERCA NEI FILE
        # ══════════════════════════════════════════════════════════════════════

        lbl_files = QLabel(_t("section_search_files"))
        lbl_files.setToolTip(_t("section_search_files_tooltip"))
        lbl_files.setStyleSheet(
            f"font-weight: bold; color: {self._colors['files_header']}; padding: 1px 0;")
        vl.addWidget(lbl_files)

        # Riga: path + glob
        ff1 = QHBoxLayout()

        self._files_path_edit = QLineEdit()
        self._files_path_edit.setPlaceholderText(_t("search_files_path_placeholder"))
        self._files_path_edit.setToolTip(_t("search_files_path_tooltip"))
        self._files_path_edit.setFixedHeight(22)
        self._files_path_edit.returnPressed.connect(self._do_search_in_files)
        ff1.addWidget(self._files_path_edit, 1)

        btn_browse = QToolButton()
        btn_browse.setText("…")
        btn_browse.setToolTip(_t("search_files_browse_tooltip"))
        btn_browse.setFixedSize(26, 22)
        btn_browse.clicked.connect(self._browse_files_path)
        ff1.addWidget(btn_browse)

        self._files_glob_edit = QLineEdit()
        self._files_glob_edit.setPlaceholderText(_t("search_files_glob_placeholder"))
        self._files_glob_edit.setToolTip(_t("search_files_glob_tooltip"))
        self._files_glob_edit.setFixedHeight(22)
        self._files_glob_edit.setMaximumWidth(120)
        self._files_glob_edit.returnPressed.connect(self._do_search_in_files)
        ff1.addWidget(self._files_glob_edit)

        vl.addLayout(ff1)

        # Riga: opzioni + bottone cerca
        ff2 = QHBoxLayout()

        self._chk_files_recursive = QCheckBox(_t("search_files_recursive"))
        self._chk_files_recursive.setToolTip(_t("search_files_recursive_tooltip"))
        self._chk_files_recursive.setChecked(True)
        self._chk_files_recursive.setFixedHeight(22)
        ff2.addWidget(self._chk_files_recursive)

        self._chk_files_hidden = QCheckBox(_t("search_files_hidden"))
        self._chk_files_hidden.setToolTip(_t("search_files_hidden_tooltip"))
        self._chk_files_hidden.setFixedHeight(22)
        ff2.addWidget(self._chk_files_hidden)

        btn_search_files = QPushButton(_t("btn_search_files"))
        btn_search_files.setFixedHeight(22)
        btn_search_files.setToolTip(_t("btn_search_files_tooltip"))
        btn_search_files.clicked.connect(self._do_search_in_files)
        ff2.addWidget(btn_search_files)

        ff2.addStretch(1)
        vl.addLayout(ff2)

        # ══════════════════════════════════════════════════════════════════════
        # SEZIONE 3: FILTRA NEI RISULTATI
        # ══════════════════════════════════════════════════════════════════════

        lbl_filter = QLabel(_t("section_filter"))
        lbl_filter.setToolTip(_t("section_filter_tooltip"))
        lbl_filter.setStyleSheet(
            f"font-weight: bold; color: {self._colors['section']}; padding: 1px 0;")
        vl.addWidget(lbl_filter)

        fl = QHBoxLayout()

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(_t("filter_placeholder"))
        self._filter_edit.setToolTip(_t("filter_tooltip"))
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._filter_edit.setFixedHeight(22)
        fl.addWidget(self._filter_edit, 1)

        self._filter_mode = QComboBox()
        self._filter_mode.addItem(_t("filter_mode_grep"), "grep")
        self._filter_mode.addItem(_t("filter_mode_regex"), "regex")
        self._filter_mode.addItem(_t("filter_mode_like"), "like")
        self._filter_mode.setFixedHeight(22)
        self._filter_mode.setToolTip(_t("filter_mode_tooltip"))
        self._filter_mode.currentIndexChanged.connect(self._apply_filter)
        fl.addWidget(self._filter_mode)

        btn_expand = QToolButton()
        btn_expand.setText("⊞")
        btn_expand.setToolTip(_t("btn_expand"))
        btn_expand.setFixedSize(26, 22)
        btn_expand.clicked.connect(self._expand_all)
        fl.addWidget(btn_expand)

        btn_collapse = QToolButton()
        btn_collapse.setText("⊟")
        btn_collapse.setToolTip(_t("btn_collapse"))
        btn_collapse.setFixedSize(26, 22)
        btn_collapse.clicked.connect(self._collapse_all)
        fl.addWidget(btn_collapse)

        vl.addLayout(fl)

        # ══════════════════════════════════════════════════════════════════════
        # SEZIONE 4: SOSTITUISCI
        # ══════════════════════════════════════════════════════════════════════

        rl = QHBoxLayout()

        lbl_replace = QLabel(_t("replace_label"))
        lbl_replace.setFixedHeight(22)
        rl.addWidget(lbl_replace)

        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText(_t("replace_placeholder"))
        self._replace_edit.setFixedHeight(22)
        rl.addWidget(self._replace_edit, 1)

        btn_replace_sel = QPushButton(_t("btn_replace_sel"))
        btn_replace_sel.setFixedHeight(22)
        btn_replace_sel.setToolTip(_t("replace_tooltip"))
        btn_replace_sel.clicked.connect(self._replace_selected)
        rl.addWidget(btn_replace_sel)

        btn_replace_all = QPushButton(_t("btn_replace_all"))
        btn_replace_all.setFixedHeight(22)
        btn_replace_all.setToolTip(_t("replace_all_tooltip"))
        btn_replace_all.clicked.connect(self._replace_all)
        rl.addWidget(btn_replace_all)

        self._btn_replace_all_files = QPushButton(_t("btn_replace_all_files"))
        self._btn_replace_all_files.setFixedHeight(22)
        self._btn_replace_all_files.setToolTip(_t("replace_all_files_tooltip"))
        self._btn_replace_all_files.clicked.connect(self._replace_all_in_files)
        self._btn_replace_all_files.hide()
        rl.addWidget(self._btn_replace_all_files)

        vl.addLayout(rl)

        # ── Albero risultati ──────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels([tr("action.go_to_line") or "Posizione", "Testo"])
        self._tree.setColumnWidth(0, 200)
        self._tree.header().setStretchLastSection(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemClicked.connect(self._on_item_activated)
        self._tree.itemActivated.connect(self._on_item_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        vl.addWidget(self._tree, 1)

        self._mono = QFont("Monospace")
        self._mono.setStyleHint(QFont.StyleHint.Monospace)
        self._mono.setPointSize(9)

        self.apply_theme()
        self._update_replace_buttons_visibility()

    # ── Tema ───────────────────────────────────────────────────────────────────

    def apply_theme(self) -> None:
        """(Ri)applica i colori del tema attivo alla lista risultati."""
        self._colors = _theme_colors()
        if hasattr(self, "_tree"):
            self._tree.setStyleSheet(_tree_stylesheet(self._colors))
        if hasattr(self, "_lbl_summary"):
            self._lbl_summary.setStyleSheet(
                f"font-weight: bold; color: {self._colors['header']};"
            )

    # ── Storico ricerche ──────────────────────────────────────────────────────

    def _restore_history(self) -> None:
        """Carica lo storico ricerche da QSettings."""
        from PyQt6.QtCore import QSettings
        settings = QSettings("NotePadPQ", "NotePadPQ")
        raw = settings.value("search_pq/history", [])
        if isinstance(raw, list):
            self._search_history = [str(x) for x in raw[-_MAX_HISTORY:]]

    def _save_history(self) -> None:
        """Salva lo storico ricerche su QSettings."""
        from PyQt6.QtCore import QSettings
        settings = QSettings("NotePadPQ", "NotePadPQ")
        settings.setValue("search_pq/history", self._search_history)

    def _add_to_history(self, query: str) -> None:
        """Aggiunge una query allo storico (evita duplicati, max _MAX_HISTORY)."""
        query = query.strip()
        if not query:
            return
        if query in self._search_history:
            self._search_history.remove(query)
        self._search_history.append(query)
        if len(self._search_history) > _MAX_HISTORY:
            self._search_history = self._search_history[-_MAX_HISTORY:]
        self._save_history()

    def _show_search_history(self) -> None:
        """Mostra il menu a tendina con lo storico ricerche."""
        menu = QMenu(self)
        if not self._search_history:
            menu.addAction(_t("history_empty")).setEnabled(False)
        else:
            for q in reversed(self._search_history):
                act = menu.addAction(q)
                act.triggered.connect(lambda checked, query=q: self._history_item_clicked(query))
            menu.addSeparator()
            act_clear = menu.addAction(_t("history_clear"))
            act_clear.triggered.connect(self._clear_history)
        menu.exec(self._history_btn.mapToGlobal(self._history_btn.rect().bottomLeft()))

    def _history_item_clicked(self, query: str) -> None:
        """Imposta la query cliccata dallo storico nel campo di ricerca."""
        self._search_edit.setText(query)
        self._do_search_in_doc()

    def _clear_history(self) -> None:
        """Cancella tutto lo storico ricerche."""
        self._search_history.clear()
        self._save_history()

    # ── API pubblica ──────────────────────────────────────────────────────────

    def add_results(self, query: str, results: list[dict],
                    color: str = "header") -> None:
        """Aggiunge un gruppo di risultati al pannello.

        results: lista di dict con chiavi: 'file', 'line' (0-based), 'text', 'col' (opz.)
        color: chiave colore ('header' per ricerca doc, 'files_header' per files)
        """
        if not results:
            # Se era una ricerca nel documento, mostra messaggio
            if color == "header" and not self._chk_append.isChecked():
                self._lbl_summary.setText(_t("msg_no_results_doc", query=query))
            return
        self._current_query = query
        self._all_results = list(results)
        self._add_to_history(query)

        by_file: dict[str, list] = {}
        for r in results:
            by_file.setdefault(r["file"], []).append(r)

        total = len(results)
        n_files = len(by_file)
        self._lbl_summary.setText(
            f'\U0001f50d "{query}" \u2014 {total} '
            f'{tr("msg.results_count_files", matches=total, files=n_files) or f"{total} in {n_files} file"}'
        )

        root = QTreeWidgetItem(self._tree)
        root.setText(0, _t("root_label", query=query, total=total, n_files=n_files))
        root.setForeground(0, QBrush(QColor(self._colors[color])))
        root.setFont(0, QFont())
        root.setData(0, Qt.ItemDataRole.UserRole, {
            "_is_search_header": True,
            "query": query,
            "mode": self._search_mode.currentData() if hasattr(self, '_search_mode') else "text",
            "case": self._chk_case.isChecked() if hasattr(self, '_chk_case') else False,
            "whole_word": self._chk_whole_word.isChecked() if hasattr(self, '_chk_whole_word') else False,
            "is_file_search": color == "files_header",
        })

        for file_path, file_results in by_file.items():
            fname = os.path.basename(file_path)
            file_item = QTreeWidgetItem(root)
            file_item.setText(0, _t("file_label", fname=fname, count=len(file_results)))
            file_item.setText(1, file_path)
            file_item.setForeground(0, QBrush(QColor(self._colors["file"])))
            file_item.setData(0, Qt.ItemDataRole.UserRole, None)
            file_item.setToolTip(1, file_path)

            for r in file_results:
                item = QTreeWidgetItem(file_item)
                line_no = r["line"] + 1
                col = r.get("col", 0)
                item.setText(0, _t("row_label", line=line_no, col=col + 1))
                item.setText(1, r["text"].rstrip())
                item.setFont(1, self._mono)
                item.setData(0, Qt.ItemDataRole.UserRole, (r["file"], r["line"], r.get("col", 0)))

        root.setExpanded(True)
        for i in range(root.childCount()):
            root.child(i).setExpanded(True)

        self._tree.scrollToBottom()
        self._apply_filter(self._filter_edit.text())
        self._highlight_all_matches()
        self._update_replace_buttons_visibility()

    # ── Evidenziazione tutti i match ──────────────────────────────────────────

    def _highlight_all_matches(self) -> None:
        """Evidenzia tutti i match nell'editor corrente usando INDICATOR_MARK1."""
        editor = self._mw._current_editor()
        if editor is None:
            return
        try:
            editor.clear_indicator(_INDICATOR_MARK1)
        except AttributeError:
            editor.clearIndicatorRange(0, 0, editor.lines(), 0, _INDICATOR_MARK1)
        file_path = str(editor.file_path) if editor.file_path else ""
        pattern = self._compile_query_pattern()
        if pattern is None:
            return
        for r in self._all_results:
            if r["file"] != file_path:
                continue
            line = r["line"]
            line_text = r["text"].rstrip("\n").rstrip("\r")
            col = r.get("col", 0)
            start, end = self._match_span(line_text, col)
            if start is None or end is None or end <= start:
                continue
            try:
                if hasattr(editor, "char_col_to_byte_col"):
                    start = editor.char_col_to_byte_col(line, start)
                    end   = editor.char_col_to_byte_col(line, end)
            except Exception:
                pass
            try:
                editor.fillIndicatorRange(line, start, line, end, _INDICATOR_MARK1)
            except Exception:
                pass

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _all_leaf_items(self) -> list:
        """Elenco dei risultati navigabili con Prev/Next (F4).

        Esclude gli item nascosti dal filtro live (sezione "Filtra nei
        risultati"): altrimenti Prev/Next salterebbe anche a righe non
        corrispondenti al filtro corrente, "andando oltre" i risultati
        effettivamente mostrati nell'albero.
        """
        items = []
        def _walk(item):
            if (item.childCount() == 0
                    and item.data(0, Qt.ItemDataRole.UserRole)
                    and not item.isHidden()):
                items.append(item)
            for i in range(item.childCount()):
                _walk(item.child(i))
        for i in range(self._tree.topLevelItemCount()):
            _walk(self._tree.topLevelItem(i))
        return items

    def _navigate_next(self) -> None:
        items = self._all_leaf_items()
        if not items:
            return
        cur = self._tree.currentItem()
        try:
            idx = items.index(cur)
            nxt = items[(idx + 1) % len(items)]
        except ValueError:
            nxt = items[0]
        self._tree.setCurrentItem(nxt)
        self._on_item_activated(nxt, 0)

    def _navigate_prev(self) -> None:
        items = self._all_leaf_items()
        if not items:
            return
        cur = self._tree.currentItem()
        try:
            idx = items.index(cur)
            prv = items[(idx - 1) % len(items)]
        except ValueError:
            prv = items[-1]
        self._tree.setCurrentItem(prv)
        self._on_item_activated(prv, 0)

    def _on_item_activated(self, item: QTreeWidgetItem, col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if isinstance(data, dict) and data.get("_is_search_header"):
            self._restore_search_params(data)
            return
        if isinstance(data, tuple):
            file_path = data[0]
            line      = data[1]
            col       = data[2] if len(data) > 2 else 0
            self._navigate_and_highlight(file_path, line, col)

    def _restore_search_params(self, params: dict) -> None:
        """Ripristina i campi di ricerca con i parametri di una ricerca precedente."""
        self._search_edit.setText(params.get("query", ""))
        mode = params.get("mode", "text")
        idx = self._search_mode.findData(mode)
        if idx >= 0:
            self._search_mode.setCurrentIndex(idx)
        # Se era una ricerca nei file, potremmo anche ripristinare il path
        file_path = params.get("file_path")
        if file_path:
            self._files_path_edit.setText(file_path)
        self._chk_case.setChecked(params.get("case", False))
        self._chk_whole_word.setChecked(params.get("whole_word", False))
        self._search_edit.setFocus()

    def _do_navigate(self, file_path: str, line: int) -> None:
        self._navigate_and_highlight(file_path, line, 0)

    def _navigate_and_highlight(self, file_path: str, line: int, col: int) -> None:
        """Apre il file alla riga indicata ed evidenzia il match."""
        if file_path:
            self._mw.open_files([Path(file_path)])
        editor = self._mw._current_editor()
        if editor is None:
            return

        line = max(0, min(line, max(0, editor.lines() - 1)))
        try:
            line_text = editor.text(line)
        except Exception:
            line_text = ""
        line_text = line_text.rstrip("\n").rstrip("\r")

        start, end = self._match_span(line_text, col)
        if start is None:
            start, end = 0, len(line_text)

        if hasattr(editor, "char_col_to_byte_col"):
            try:
                start = editor.char_col_to_byte_col(line, start)
                end   = editor.char_col_to_byte_col(line, end)
            except Exception:
                pass

        if hasattr(editor, "highlight_find_match"):
            editor.highlight_find_match(line, start, end)
        else:
            editor.setSelection(line, start, line, end)
            editor.ensureLineVisible(line)
        editor.setFocus()

    def _compile_query_pattern(self) -> Optional[re.Pattern]:
        """Compila un pattern regex coerente con modalità e opzioni correnti."""
        query = self._current_query
        if not query:
            return None
        case_sensitive = self._chk_case.isChecked()
        whole_word     = self._chk_whole_word.isChecked()
        mode           = self._search_mode.currentData()
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            if mode == "regex":
                return re.compile(query, flags)
            if mode == "like":
                base = self._like_to_regex(query)
                return re.compile(base.pattern, flags | re.DOTALL)
            tokens = [t for t in query.split()
                      if not t.startswith(("-", "!"))]
            word = tokens[0] if tokens else query
            escaped = re.escape(word)
            if whole_word:
                escaped = rf"\b{escaped}\b"
            return re.compile(escaped, flags)
        except re.error:
            return None

    def _compile_full_pattern(self) -> Optional[tuple]:
        """Compila il pattern di ricerca completo per il matching reale.

        Restituisce (must_pats, must_not_pats, smart_mode) o None se errore.
        In modalità regex e LIKE esiste solo must_pats[0].
        In modalità text smart_mode=True con must_pats e must_not_pats multipli.
        """
        query = self._current_query
        if not query:
            return None
        case_sensitive = self._chk_case.isChecked()
        whole_word     = self._chk_whole_word.isChecked()
        mode           = self._search_mode.currentData()
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            if mode == "regex":
                pat = re.compile(query, flags)
                return ([pat], [], False)
            elif mode == "like":
                pat = self._like_to_regex(query)
                if case_sensitive:
                    pat = re.compile(pat.pattern, 0)
                return ([pat], [], False)
            else:
                tokens = query.split()
                must_pats = []
                must_not_pats = []
                if not tokens:
                    escaped = re.escape(query)
                    return ([re.compile(escaped, flags)], [], True)
                for token in tokens:
                    negated = token.startswith("-") or token.startswith("!")
                    word = token[1:] if negated else token
                    if not word:
                        continue
                    escaped = re.escape(word)
                    if whole_word:
                        escaped = rf"\b{escaped}\b"
                    compiled = re.compile(escaped, flags)
                    if negated:
                        must_not_pats.append(compiled)
                    else:
                        must_pats.append(compiled)
                if not must_pats and not must_not_pats:
                    return None
                return (must_pats, must_not_pats, True)
        except re.error:
            return None

    def _match_span(self, line_text: str, col: int) -> tuple[Optional[int], Optional[int]]:
        """Calcola (start, end) del match sulla riga, coerente con la ricerca."""
        if not line_text:
            return None, None
        pat = self._compile_query_pattern()
        if pat is None:
            return None, None
        col = max(0, min(col, len(line_text)))
        m = pat.search(line_text, col) or pat.search(line_text)
        if m and m.end() > m.start():
            return m.start(), m.end()
        return None, None

    # ── Auto-ricerca (debounce) ───────────────────────────────────────────────

    def _on_search_text_changed(self, text: str) -> None:
        """Avvia la ricerca automatica dopo debounce se auto-search è attivo."""
        self._update_regex_indicator()
        if not self._chk_auto_search.isChecked():
            return
        self._debounce_timer.stop()
        if len(text) >= 1:
            self._debounce_timer.start()

    def _on_option_changed(self, *_) -> None:
        """Riesegue la ricerca quando cambia una modalità."""
        if not self._chk_auto_search.isChecked():
            return
        if len(self._search_edit.text()) >= 1:
            self._debounce_timer.stop()
            self._do_search_in_doc()

    def _on_auto_search_toggled(self, state: int) -> None:
        """Quando auto-search viene (ri)attivato, avvia subito la ricerca corrente."""
        if state == Qt.CheckState.Checked.value and len(self._search_edit.text()) >= 1:
            self._do_search_in_doc()

    def _on_search_mode_changed(self, _index: int) -> None:
        """Aggiorna visibilità indicatore regex e riesegue ricerca."""
        self._update_regex_indicator()
        self._on_option_changed()

    def _update_regex_indicator(self) -> None:
        """Mostra/nasconde l'indicatore di validità regex e lo aggiorna."""
        mode = self._search_mode.currentData()
        if mode == "regex":
            self._regex_indicator.show()
            text = self._search_edit.text()
            if not text:
                self._regex_indicator.setText("")
                self._regex_indicator.setToolTip("")
            else:
                try:
                    re.compile(text, 0 if self._chk_case.isChecked() else re.IGNORECASE)
                    self._regex_indicator.setText("✓")
                    self._regex_indicator.setStyleSheet(
                        f"color: {self._colors['regex_ok']}; font-weight: bold;")
                    self._regex_indicator.setToolTip(_t("regex_valid"))
                except re.error as e:
                    self._regex_indicator.setText("✗")
                    self._regex_indicator.setStyleSheet(
                        f"color: {self._colors['regex_err']}; font-weight: bold;")
                    self._regex_indicator.setToolTip(_t("regex_invalid", error=str(e)))
        else:
            self._regex_indicator.hide()
            self._regex_indicator.setText("")

    def clear_all(self) -> None:
        """Cancella tutti i risultati e le evidenziazioni."""
        editor = self._mw._current_editor()
        if editor is not None:
            try:
                editor.clear_indicator(_INDICATOR_MARK1)
            except AttributeError:
                editor.clearIndicatorRange(0, 0, editor.lines(), 0, _INDICATOR_MARK1)
        self._tree.clear()
        self._all_results.clear()
        self._current_query = ""
        self._lbl_summary.setText(_t("no_search"))
        self._update_replace_buttons_visibility()

    # ── Cerca nel documento ───────────────────────────────────────────────────

    def _get_editor_lines_iter(self):
        """Restituisce un iteratore di (n_riga, testo_riga) per la ricerca.

        Se 'cerca nella selezione' è attivo e c'è testo selezionato, restituisce
        solo le righe coinvolte nella selezione (con il testo eventualmente
        troncato). Altrimenti, tutto il documento.
        """
        editor = self._mw._current_editor()
        if editor is None:
            return []

        if self._chk_in_selection.isChecked() and editor.hasSelectedText():
            start_line, start_col, end_line, end_col, _ = editor.getSelection()
            if start_line == end_line:
                line_text = editor.text(start_line).rstrip("\n").rstrip("\r")
                return [(start_line, line_text[start_col:end_col])]
            else:
                items = []
                for i in range(start_line, end_line + 1):
                    lt = editor.text(i).rstrip("\n").rstrip("\r")
                    if i == start_line:
                        lt = lt[start_col:]
                    elif i == end_line:
                        lt = lt[:end_col]
                    items.append((i, lt))
                return items

        # Documento intero
        return [(i, t.rstrip("\n").rstrip("\r"))
                for i, t in enumerate(editor.text().split("\n"))]

    def _do_search_in_doc(self) -> None:
        """Cerca nel documento/editor attivo."""
        query = self._search_edit.text()
        if not query:
            return
        editor = self._mw._current_editor()
        if editor is None:
            return

        self._current_query = query
        pattern_data = self._compile_full_pattern()
        if pattern_data is None:
            return
        must_pats, must_not_pats, smart_mode = pattern_data

        file_path = str(editor.file_path) if editor.file_path else ""
        line_iter = self._get_editor_lines_iter()

        results = []
        for line_idx, line_text in line_iter:
            if smart_mode:
                if not all(p.search(line_text) for p in must_pats):
                    continue
                if any(p.search(line_text) for p in must_not_pats):
                    continue
                first_match = must_pats[0].search(line_text) if must_pats else None
                col = first_match.start() if first_match else 0
            else:
                for m in must_pats[0].finditer(line_text):
                    results.append({
                        "file": file_path,
                        "line": line_idx,
                        "text": editor.text(line_idx).rstrip("\n").rstrip("\r"),
                        "col": m.start(),
                    })
                continue
            results.append({
                "file": file_path,
                "line": line_idx,
                "text": editor.text(line_idx).rstrip("\n").rstrip("\r"),
                "col": col,
            })

        if not self._chk_append.isChecked():
            self._tree.clear()
            self._all_results.clear()
        if not results:
            self._lbl_summary.setText(_t("msg_no_results_doc", query=query))
            self._current_query = query
            self._update_replace_buttons_visibility()
            return

        self.add_results(query, results)

    # ── Cerca nei file ────────────────────────────────────────────────────────

    def _browse_files_path(self) -> None:
        """Apre un dialogo per selezionare una directory o file."""
        path = QFileDialog.getExistingDirectory(
            self, _t("search_files_browse_title"),
            self._files_path_edit.text() or os.path.expanduser("~"),
        )
        if path:
            self._files_path_edit.setText(path)

    def _do_search_in_files(self) -> None:
        """Cerca in tutti i file che matchano il glob nella directory indicata."""
        base_path = self._files_path_edit.text().strip()
        if not base_path:
            QMessageBox.information(self, _t("btn_search_files"), _t("msg_no_path"))
            return
        base = Path(base_path).expanduser()
        if not base.exists():
            QMessageBox.information(self, _t("btn_search_files"),
                                    _t("msg_path_not_found", path=str(base)))
            return

        glob_str = self._files_glob_edit.text().strip() or "**/*"
        recursive = self._chk_files_recursive.isChecked()
        include_hidden = self._chk_files_hidden.isChecked()
        query = self._search_edit.text().strip()
        self._current_query = query

        pattern_data = self._compile_full_pattern()
        if pattern_data is None:
            return
        must_pats, must_not_pats, smart_mode = pattern_data

        # Raccogli i file
        if recursive:
            candidates = list(base.rglob(glob_str))
        else:
            candidates = list(base.glob(glob_str))

        # Filtra: solo file regolari, escludi hidden se non richiesti
        files_to_search = []
        for f in candidates:
            if not f.is_file():
                continue
            if not include_hidden and _is_hidden_relative(f, base):
                continue
            files_to_search.append(f)

        if not files_to_search:
            self._lbl_summary.setText(
                _t("msg_no_files_matched", path=str(base), glob=glob_str))
            return

        # Esegui la ricerca
        if not self._chk_append.isChecked():
            self._tree.clear()
            self._all_results.clear()

        self._lbl_summary.setText(_t("msg_searching_files", count=len(files_to_search)))
        QApplication.processEvents()

        all_results = []
        for f in files_to_search:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            lines = content.split("\n")
            for line_idx, line_text in enumerate(lines):
                if smart_mode:
                    if not all(p.search(line_text) for p in must_pats):
                        continue
                    if any(p.search(line_text) for p in must_not_pats):
                        continue
                    first_match = must_pats[0].search(line_text) if must_pats else None
                    col = first_match.start() if first_match else 0
                else:
                    for m in must_pats[0].finditer(line_text):
                        all_results.append({
                            "file": str(f),
                            "line": line_idx,
                            "text": line_text,
                            "col": m.start(),
                        })
                    continue
                all_results.append({
                    "file": str(f),
                    "line": line_idx,
                    "text": line_text,
                    "col": col,
                })
            QApplication.processEvents()

        if not all_results:
            self._lbl_summary.setText(
                _t("msg_no_results_files", query=query, path=str(base)))
            self._update_replace_buttons_visibility()
            return

        self._current_query = query
        self.add_results(query, all_results, color="files_header")

    # ── Filtro ────────────────────────────────────────────────────────────────

    @staticmethod
    def _like_to_regex(pattern: str) -> re.Pattern:
        """Converte una stringa LIKE SQL in un regex Python."""
        parts = []
        for ch in pattern:
            if ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
        return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)

    def _apply_filter(self, text=None) -> None:
        if not isinstance(text, str):
            # Chiamato anche da filter_mode.currentIndexChanged(int) e da
            # add_results() senza argomenti: in questi casi va riletto il
            # testo corrente del campo filtro, non l'indice del combobox.
            text = self._filter_edit.text()
        mode = self._filter_mode.currentData()
        text = text.strip()

        if not text:
            matcher = None
        elif mode == "regex":
            try:
                pat = re.compile(text, re.IGNORECASE)
                matcher = lambda s: bool(pat.search(s))
            except re.error:
                matcher = None
        elif mode == "like":
            try:
                pat = self._like_to_regex(text)
                matcher = lambda s: bool(pat.search(s))
            except re.error:
                matcher = None
        else:
            # grep-like: AND (+parola) NOT (-parola o !parola)
            tokens = text.lower().split()
            must_have = [t for t in tokens if not t.startswith(("-", "!"))]
            must_not  = [t.lstrip("-!") for t in tokens if t.startswith(("-", "!"))]
            if tokens:
                def matcher(s: str) -> bool:
                    sl = s.lower()
                    return (all(w in sl for w in must_have) and
                            not any(w in sl for w in must_not))
            else:
                matcher = None

        def _walk(item):
            is_leaf = item.childCount() == 0
            if is_leaf:
                if matcher is None:
                    visible = True
                else:
                    combined = item.text(1) + " " + item.text(0)
                    visible = matcher(combined)
                item.setHidden(not visible)
                return visible
            else:
                any_visible = False
                for i in range(item.childCount()):
                    if _walk(item.child(i)):
                        any_visible = True
                item.setHidden(not any_visible)
                return any_visible

        for i in range(self._tree.topLevelItemCount()):
            _walk(self._tree.topLevelItem(i))

    def _expand_all(self) -> None:
        self._tree.expandAll()

    def _collapse_all(self) -> None:
        self._tree.collapseAll()

    # ── Sostituisci ───────────────────────────────────────────────────────────

    def _get_selected_result(self) -> Optional[tuple]:
        """Restituisce (file_path, line_0based, col) del risultato selezionato, o None."""
        item = self._tree.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple):
            return None
        return data

    def _has_multiple_files(self) -> bool:
        """Verifica se i risultati correnti coprono più file."""
        files = set(r["file"] for r in self._all_results)
        return len(files) > 1

    def _update_replace_buttons_visibility(self) -> None:
        """Mostra/nasconde il pulsante 'Sostituisci in tutti i file'."""
        if self._has_multiple_files():
            self._btn_replace_all_files.show()
        else:
            self._btn_replace_all_files.hide()

    def _replace_selected(self) -> None:
        """Sostituisce l'occorrenza selezionata."""
        result = self._get_selected_result()
        if result is None:
            QMessageBox.information(self, _t("btn_replace_sel"), _t("msg_select_first"))
            return
        file_path, line_0, col = result[0], result[1], result[2] if len(result) > 2 else 0
        replace_text = self._replace_edit.text()
        query = self._current_query
        if not query:
            QMessageBox.information(self, _t("btn_replace_sel"), _t("msg_run_search_first"))
            return

        self._mw.open_files([Path(file_path)])
        editor = self._mw._current_editor()
        if editor is None:
            return
        editor.beginUndoAction()
        try:
            editor.setCursorPosition(line_0, col)
            editor.ensureLineVisible(line_0)
            editor.setFocus()

            pat = self._compile_query_pattern()
            if pat is None:
                return
            line_text = editor.text(line_0).rstrip("\n").rstrip("\r")
            col = max(0, min(col, len(line_text)))
            match = pat.search(line_text, col) or pat.search(line_text)
            if match and match.end() > match.start():
                abs_start = match.start()
                abs_end   = match.end()
                mode = self._search_mode.currentData()
                if mode == "regex":
                    try:
                        replace_text = match.expand(replace_text)
                    except (re.error, IndexError):
                        pass
                editor.setSelection(line_0, abs_start, line_0, abs_end)
                editor.replaceSelectedText(replace_text)
        finally:
            editor.endUndoAction()

        # Ricerca per aggiornare l'albero
        self._do_search_in_doc()

    def _replace_all(self) -> None:
        """Sostituisce tutte le occorrenze della query nell'editor attivo."""
        query = self._current_query
        if not query:
            QMessageBox.information(self, _t("btn_replace_all"), _t("msg_run_search_first"))
            return
        replace_text = self._replace_edit.text()
        editor = self._mw._current_editor()
        if editor is None:
            return

        # Conta le occorrenze nel file corrente
        editor_file = str(editor.file_path) if editor.file_path else ""
        count_in_file = sum(1 for r in self._all_results if r["file"] == editor_file)
        if count_in_file == 0:
            QMessageBox.information(self, _t("btn_replace_all"),
                                    _t("msg_no_results_for_file"))
            return

        answer = QMessageBox.question(
            self,
            _t("msg_replace_confirm_title"),
            _t("msg_replace_confirm", query=query, count=count_in_file,
               file=os.path.basename(editor_file) if editor_file else _t("current_file")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        pat = self._compile_query_pattern()
        if pat is None:
            return
        text = editor.text()
        mode = self._search_mode.currentData()
        repl = replace_text if mode == "regex" else replace_text.replace("\\", "\\\\")
        try:
            new_text, count = pat.subn(repl, text)
        except re.error:
            return
        if count > 0:
            cursor = editor.getCursorPosition()
            editor.beginUndoAction()
            editor.selectAll()
            editor.replaceSelectedText(new_text)
            editor.endUndoAction()
            line = min(cursor[0], max(0, editor.lines() - 1))
            editor.setCursorPosition(line, cursor[1])
        QMessageBox.information(self, _t("btn_replace_all"),
                                _t("msg_replaced_n", count=count))

        # Ricerca per aggiornare l'albero
        self._do_search_in_doc()

    def _replace_all_in_files(self) -> None:
        """Sostituisce tutte le occorrenze in TUTTI i file dei risultati."""
        if not self._has_multiple_files():
            QMessageBox.information(self, _t("btn_replace_all_files"),
                                    _t("msg_multiple_files_needed"))
            return
        query = self._current_query
        if not query:
            QMessageBox.information(self, _t("btn_replace_all_files"),
                                    _t("msg_run_search_first"))
            return
        replace_text = self._replace_edit.text()

        unique_files = list(dict.fromkeys(r["file"] for r in self._all_results))
        answer = QMessageBox.question(
            self,
            _t("msg_replace_files_confirm_title"),
            _t("msg_replace_files_confirm", query=query, count=len(unique_files)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        pat = self._compile_query_pattern()
        if pat is None:
            return
        mode = self._search_mode.currentData()
        repl = replace_text if mode == "regex" else replace_text.replace("\\", "\\\\")

        total_count = 0
        for file_path_str in unique_files:
            fpath = Path(file_path_str)
            if not fpath.is_file():
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                new_content, cnt = pat.subn(repl, content)
            except re.error:
                continue
            if cnt > 0:
                total_count += cnt
                try:
                    fpath.write_text(new_content, encoding="utf-8")
                except OSError:
                    pass
            QApplication.processEvents()

        # Apri il primo file per mostrare il risultato
        if unique_files:
            self._mw.open_files([Path(unique_files[0])])

        QMessageBox.information(
            self, _t("btn_replace_all_files"),
            _t("msg_replaced_n_files", count=total_count, n_files=len(unique_files)))

        # Ricerca per aggiornare l'albero
        if not self._chk_append.isChecked():
            self._tree.clear()
            self._all_results.clear()
        self._do_search_in_doc()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        act_goto     = menu.addAction(_t("ctx_goto"))
        act_copy     = menu.addAction(_t("ctx_copy_text"))
        act_copy_pos = menu.addAction(_t("ctx_copy_pos"))
        menu.addSeparator()
        act_copy_all  = menu.addAction(_t("ctx_copy_all"))
        act_copy_csv  = menu.addAction(_t("ctx_copy_csv"))
        menu.addSeparator()
        act_replace_sel = menu.addAction(_t("ctx_replace_sel"))
        act_replace_all = menu.addAction(_t("ctx_replace_all"))
        menu.addSeparator()
        act_clear = menu.addAction(_t("ctx_clear"))

        if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
            act_goto.setEnabled(False)
            act_copy.setEnabled(False)
            act_copy_pos.setEnabled(False)
            act_replace_sel.setEnabled(False)

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen == act_goto and item:
            self._on_item_activated(item, 0)
        elif chosen == act_copy and item:
            QApplication.clipboard().setText(item.text(1))
        elif chosen == act_copy_pos and item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple):
                fp, ln, *_ = data
                QApplication.clipboard().setText(f"{fp}:{ln + 1}")
        elif chosen == act_copy_all:
            self._copy_all()
        elif chosen == act_copy_csv:
            self._copy_csv()
        elif chosen == act_replace_sel:
            self._replace_selected()
        elif chosen == act_replace_all:
            self._replace_all()
        elif chosen == act_clear:
            self.clear_all()

    def _copy_all(self) -> None:
        lines = []
        def _walk(item, depth=0):
            lines.append("  " * depth + item.text(0) + "  " + item.text(1))
            for i in range(item.childCount()):
                _walk(item.child(i), depth + 1)
        for i in range(self._tree.topLevelItemCount()):
            _walk(self._tree.topLevelItem(i))
        QApplication.clipboard().setText("\n".join(lines))

    def _copy_csv(self) -> None:
        lines = [_t("csv_header")]
        for r in self._all_results:
            row = f"{r['file']},{r['line'] + 1},{r.get('col', 0) + 1},{r['text'].rstrip()}"
            lines.append(row)
        QApplication.clipboard().setText("\n".join(lines))

    # ── Scorciatoie da tastiera ───────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Gestisce scorciatoie globali nel pannello."""
        key = event.key()
        mods = event.modifiers()

        # F4 / Shift+F4 = navigazione risultati
        if key == Qt.Key.Key_F4:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._navigate_prev()
            else:
                self._navigate_next()
            event.accept()
            return

        # Ctrl+F = focus campo cerca
        if key == Qt.Key.Key_F and mods == Qt.KeyboardModifier.ControlModifier:
            self._search_edit.setFocus()
            self._search_edit.selectAll()
            event.accept()
            return

        # Ctrl+R = focus campo sostituisci
        if key == Qt.Key.Key_R and mods == Qt.KeyboardModifier.ControlModifier:
            self._replace_edit.setFocus()
            self._replace_edit.selectAll()
            event.accept()
            return

        # Escape = focus editor
        if key == Qt.Key.Key_Escape:
            editor = self._mw._current_editor()
            if editor is not None:
                editor.setFocus()
            event.accept()
            return

        super().keyPressEvent(event)


# ─── Utility ──────────────────────────────────────────────────────────────────

def _is_hidden_relative(path: Path, base: Path) -> bool:
    """Verifica se un path ha una componente nascosta dopo la directory base."""
    try:
        rel = path.relative_to(base)
    except ValueError:
        return False
    for part in str(rel).replace("\\", "/").split("/"):
        if part.startswith("."):
            return True
    return False


# ─── Plugin ───────────────────────────────────────────────────────────────────

class SearchResultsPlugin(BasePlugin):

    NAME        = "Search PQ"
    VERSION     = "2.0"
    DESCRIPTION = (
        "Multi-function dock panel for find/replace: "
        "document search, file search, filter, inline and multi-file replace."
    )
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        self._panel = _SearchResultsPanel(main_window)

        self._dock = QDockWidget(_t("dock_title"), main_window)
        self._dock.setObjectName("SearchResultsDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(350)
        self._dock.setMinimumHeight(180)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._dock)
        self._dock.hide()

        main_window._find_result_panel = self._panel

        try:
            from config.themes import ThemeManager
            ThemeManager.instance().theme_changed.connect(
                lambda _=None: self._panel.apply_theme()
            )
        except Exception:
            pass

        self.add_menu_action(
            main_window,
            "plugins",
            _t("menu"),
            lambda: self._dock.setVisible(not self._dock.isVisible()),
            shortcut=_t("shortcut"),
            icon_key="plugin_search",
        )

    def on_unload(self) -> None:
        main_window = self._mw
        if hasattr(self, "_dock"):
            self._dock.hide()
            main_window.removeDockWidget(self._dock)
            self._dock.deleteLater()
        if main_window is not None and hasattr(main_window, "_find_result_panel"):
            del main_window._find_result_panel
        super().on_unload()
