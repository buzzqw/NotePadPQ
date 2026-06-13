"""
plugins/search_results_plugin.py — Plugin Search PQ / Trova-Sostituisci
NotePadPQ

Pannello dock multifunzione dedicato ai risultati di ricerca:
  - Mostra i risultati di "Trova tutto" e "Cerca nei file" SOLO se il pannello è aperto
  - Click su un risultato → naviga alla riga nel file corrispondente
  - Copia riga o tutti i risultati
  - Sostituisci occorrenza o tutte le occorrenze direttamente dal pannello
  - Filtro rapido nei risultati con supporto regexp/grep (regex e AND multi-parola)
  - Navigazione prev/next con tastiera

Attivabile dal menu Plugin → Search PQ (Ctrl+Alt+F)
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
    QToolButton, QCheckBox, QComboBox,
)
from PyQt6.QtGui import QColor, QBrush, QFont

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Pannello risultati ───────────────────────────────────────────────────────

def _t(key: str, **kw) -> str:
    """Shortcut per le chiavi del plugin search_results."""
    return tr(f"plugin.search_results.{key}", **kw)


def _theme_colors() -> dict:
    """Colori del tema attivo per intestazioni e nodi dell'albero risultati.

    Legge la palette dal ThemeManager corrente (come fa `_chat_palette` nel
    plugin AI) per non usare colori hardcoded (`#2060a0`/`#206020`): così le
    intestazioni restano leggibili su tutti i 40+ temi, chiari e scuri. Tutti i
    valori hanno un fallback sensato.
    """
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
            "header":  _tok("keyword", "#4fa3e0"),    # intestazioni sezione / root
            "section": _tok("function", "#7bb86f"),   # intestazione "Filtra"
            "file":    _tok("string", "#9bc36f"),      # nodo file
            "bg":      _ui("editor_bg", "#1e1e1e"),
            "fg":      _ui("editor_fg", "#d4d4d4"),
            "alt_bg":  _ui("caret_line_bg", "#262a2d"),
            "sel_bg":  _ui("selection_bg", "#264f78"),
            "sel_fg":  "#ffffff",
            "border":  _ui("fold_bg", "#3a3d41"),
            "hover_bg": _ui("caret_line_bg", "#2d3338"),
        }
    return {
        "header":  _tok("keyword", "#2060a0"),
        "section": _tok("function", "#206040"),
        "file":    _tok("string", "#206020"),
        "bg":      _ui("editor_bg", "#ffffff"),
        "fg":      _ui("editor_fg", "#1e1e1e"),
        "alt_bg":  "#f1f3f5",
        "sel_bg":  "#cfe3ff",
        "sel_fg":  "#0a2b4a",
        "border":  "#c8cdd2",
        "hover_bg": "#e6f0fb",
    }


def _tree_stylesheet(c: dict) -> str:
    """Foglio di stile leggibile per il QTreeWidget dei risultati, derivato dai
    colori del tema attivo: niente più testo poco leggibile su sfondo nero, e
    riga selezionata ben evidente su qualunque tema."""
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


class _SearchResultsPanel(QWidget):
    """
    Pannello multifunzione per i risultati di trova/sostituisci.
    """
    navigate_requested = pyqtSignal(str, int)

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._all_results: list[dict] = []
        self._current_query: str = ""
        self._colors = _theme_colors()
        # Timer per debounce auto-ricerca (300 ms dopo l'ultima digitazione)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._do_search_in_doc)
        self._setup_ui()
        self.navigate_requested.connect(self._do_navigate)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.setSpacing(3)

        # ══════════════════════════════════════════════════════════════════════
        # SEZIONE 1: CERCA NEL DOCUMENTO (ricerca vera sull'editor aperto)
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

        # Modalità ricerca nel documento: testo / regex / LIKE
        self._search_mode = QComboBox()
        self._search_mode.addItem("text", "text")
        self._search_mode.addItem(".*", "regex")
        self._search_mode.addItem("%LIKE%", "like")
        self._search_mode.setFixedHeight(22)
        self._search_mode.setToolTip(_t("search_mode_tooltip"))
        self._search_mode.currentIndexChanged.connect(self._on_option_changed)
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
        # SEZIONE 2: FILTRA NEI RISULTATI (filtro live sull'albero già popolato)
        # ══════════════════════════════════════════════════════════════════════

        lbl_filter = QLabel(_t("section_filter"))
        lbl_filter.setToolTip(_t("section_filter_tooltip"))
        lbl_filter.setStyleSheet(
            f"font-weight: bold; color: {self._colors['section']}; padding: 1px 0;")
        vl.addWidget(lbl_filter)

        # ── Riga C: filtro rapido con supporto grep/regexp/LIKE ───────────────
        fl = QHBoxLayout()

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(_t("filter_placeholder"))
        self._filter_edit.setToolTip(_t("filter_tooltip"))
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._filter_edit.setFixedHeight(22)
        fl.addWidget(self._filter_edit, 1)

        # Modalità filtro: grep / regex / LIKE
        self._filter_mode = QComboBox()
        self._filter_mode.addItem("grep", "grep")
        self._filter_mode.addItem(".*",   "regex")
        self._filter_mode.addItem("%LIKE%", "like")
        self._filter_mode.setFixedHeight(22)
        self._filter_mode.setToolTip(_t("filter_mode_tooltip"))
        self._filter_mode.currentIndexChanged.connect(self._apply_filter)
        fl.addWidget(self._filter_mode)

        self._chk_filter_regex = QCheckBox(".*")  # kept for back-compat, hidden
        self._chk_filter_regex.hide()

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
        # SEZIONE 3: SOSTITUISCI
        # ══════════════════════════════════════════════════════════════════════

        # ── Riga D: campo "Sostituisci con:" + pulsanti sostituzione ──────────
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

        vl.addLayout(rl)

        # ── Albero risultati ──────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels([tr("action.go_to_line") or "Posizione", "Testo"])
        self._tree.setColumnWidth(0, 200)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemClicked.connect(self._on_item_activated)
        # Anche doppio click / Invio aprono il risultato (più user-friendly).
        self._tree.itemActivated.connect(self._on_item_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        vl.addWidget(self._tree, 1)

        # Font mono per il testo
        self._mono = QFont("Monospace")
        self._mono.setStyleHint(QFont.StyleHint.Monospace)
        self._mono.setPointSize(9)

        # Stile a tema della lista (leggibilità + selezione marcata).
        self.apply_theme()

    # ── Tema ───────────────────────────────────────────────────────────────────

    def apply_theme(self) -> None:
        """(Ri)applica i colori del tema attivo alla lista risultati. Può essere
        richiamata dopo un cambio tema per aggiornare l'aspetto."""
        self._colors = _theme_colors()
        if hasattr(self, "_tree"):
            self._tree.setStyleSheet(_tree_stylesheet(self._colors))
        if hasattr(self, "_lbl_summary"):
            self._lbl_summary.setStyleSheet(
                f"font-weight: bold; color: {self._colors['header']};"
            )

    # ── API pubblica ──────────────────────────────────────────────────────────

    def add_results(self, query: str, results: list[dict]) -> None:
        """
        Aggiunge un gruppo di risultati al pannello.
        results: lista di dict con chiavi: 'file', 'line' (0-based), 'text', 'col' (opz.)
        """
        if not results:
            return
        self._current_query = query
        self._all_results = list(results)

        by_file: dict[str, list] = {}
        for r in results:
            by_file.setdefault(r["file"], []).append(r)

        total = len(results)
        n_files = len(by_file)
        self._lbl_summary.setText(
            f'🔍 "{query}" — {total} '
            f'{tr("msg.results_count_files", matches=total, files=n_files) or f"{total} in {n_files} file"}'
        )

        root = QTreeWidgetItem(self._tree)
        root.setText(0, _t("root_label", query=query, total=total, n_files=n_files))
        root.setForeground(0, QBrush(QColor(self._colors["header"])))
        root.setFont(0, QFont())
        # Memorizza i parametri di ricerca nel nodo root per ripristino al click
        root.setData(0, Qt.ItemDataRole.UserRole, {
            "_is_search_header": True,
            "query": query,
            "mode": self._search_mode.currentData() if hasattr(self, '_search_mode') else "text",
            "case": self._chk_case.isChecked() if hasattr(self, '_chk_case') else False,
            "whole_word": self._chk_whole_word.isChecked() if hasattr(self, '_chk_whole_word') else False,
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
                line_no = r["line"] + 1  # 1-based per visualizzazione
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

    def clear_all(self) -> None:
        self._tree.clear()
        self._all_results.clear()
        self._current_query = ""
        self._lbl_summary.setText(_t("no_search"))

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _all_leaf_items(self) -> list:
        items = []
        def _walk(item):
            if item.childCount() == 0 and item.data(0, Qt.ItemDataRole.UserRole):
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
        # Se è un nodo header (root della ricerca) → ripristina i campi
        if isinstance(data, dict) and data.get("_is_search_header"):
            self._restore_search_params(data)
            return
        # Altrimenti è una foglia → naviga (con colonna del match per evidenziarlo)
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
        self._chk_case.setChecked(params.get("case", False))
        self._chk_whole_word.setChecked(params.get("whole_word", False))
        self._search_edit.setFocus()

    def _do_navigate(self, file_path: str, line: int) -> None:
        # Compatibilità col segnale navigate_requested(str,int): naviga senza
        # colonna nota (evidenzia comunque il match se ricalcolabile).
        self._navigate_and_highlight(file_path, line, 0)

    def _navigate_and_highlight(self, file_path: str, line: int, col: int) -> None:
        """Apre il file alla riga indicata ed **evidenzia** (seleziona) il match.

        Ricalcola la lunghezza del match sulla riga di destinazione usando la
        query e la modalità correnti, così la parola trovata risulta selezionata
        (non solo il cursore posizionato). Se non riesce a determinare il match,
        seleziona l'intera riga come fallback visivo.
        """
        if file_path:
            self._mw.open_files([Path(file_path)])
        editor = self._mw._current_editor()
        if editor is None:
            return

        # Testo della riga di destinazione (clamp ai limiti del documento).
        line = max(0, min(line, max(0, editor.lines() - 1)))
        try:
            line_text = editor.text(line)
        except Exception:
            line_text = ""
        line_text = line_text.rstrip("\n").rstrip("\r")

        start, end = self._match_span(line_text, col)
        if start is None:
            # Fallback: seleziona tutta la riga per dare comunque evidenza visiva.
            start, end = 0, len(line_text)

        # `start`/`end` sono offset di CARATTERE (calcolati con re su line_text).
        # QScintilla lavora in byte: su righe con accenti vanno convertiti, o la
        # selezione/indicatore finisce sulla parola sbagliata.
        if hasattr(editor, "char_col_to_byte_col"):
            try:
                start = editor.char_col_to_byte_col(line, start)
                end   = editor.char_col_to_byte_col(line, end)
            except Exception:
                pass

        # Evidenziazione robusta: oltre alla selezione (attenuata da QScintilla
        # quando l'editor non ha il focus), applica l'indicatore persistente
        # sulla parola e mantiene visibile la riga corrente anche senza focus.
        if hasattr(editor, "highlight_find_match"):
            editor.highlight_find_match(line, start, end)
        else:
            editor.setSelection(line, start, line, end)
            editor.ensureLineVisible(line)
        editor.setFocus()

    def _compile_query_pattern(self) -> Optional[re.Pattern]:
        """Compila un singolo pattern regex che rappresenta la query corrente,
        coerente con la modalità (text/regex/like) e le opzioni (case, whole-word).

        Usato in modo condiviso da evidenziazione e sostituzione, così che ciò
        che viene **sostituito** corrisponda esattamente a ciò che è stato
        **cercato** (in passato la sostituzione ignorava regex/LIKE e l'opzione
        case, usando sempre `re.escape(query)` con IGNORECASE fisso).

        In modalità testo usa la prima parola "must" (i token negati `-x`/`!x`
        non sono sostituibili). Restituisce None se la query è vuota o invalida.
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
                return re.compile(query, flags)
            if mode == "like":
                base = self._like_to_regex(query)
                return re.compile(base.pattern, flags | re.DOTALL)
            # Modalità testo: prima parola "must" (no token negati).
            tokens = [t for t in query.split()
                      if not t.startswith(("-", "!"))]
            word = tokens[0] if tokens else query
            escaped = re.escape(word)
            if whole_word:
                escaped = rf"\b{escaped}\b"
            return re.compile(escaped, flags)
        except re.error:
            return None

    def _match_span(self, line_text: str, col: int) -> tuple[Optional[int], Optional[int]]:
        """Calcola (start, end) del match sulla riga, coerente con la ricerca
        corrente. Restituisce (None, None) se non determinabile.
        """
        if not line_text:
            return None, None
        pat = self._compile_query_pattern()
        if pat is None:
            return None, None
        # Cerca prima dalla colonna memorizzata, poi su tutta la riga.
        col = max(0, min(col, len(line_text)))
        m = pat.search(line_text, col) or pat.search(line_text)
        if m and m.end() > m.start():
            return m.start(), m.end()
        return None, None

    # ── Auto-ricerca (debounce) ───────────────────────────────────────────────

    def _on_search_text_changed(self, text: str) -> None:
        """Avvia la ricerca automatica dopo 300 ms se ci sono ≥ 3 caratteri (o ≥ 1 se solo spazi)."""
        self._debounce_timer.stop()
        if len(text) >= 1:
            self._debounce_timer.start()
        else:
            # Meno di 3 caratteri: non cercare, ma non cancellare i risultati
            # precedenti (potrebbero essere stati cercati manualmente)
            pass

    def _on_option_changed(self, *_) -> None:
        """Riesegue la ricerca corrente quando cambia una modalità (case, whole-word, mode)."""
        if len(self._search_edit.text()) >= 1:
            # Cancella il debounce pendente e cerca subito
            self._debounce_timer.stop()
            self._do_search_in_doc()

    # ── Cerca nel documento ───────────────────────────────────────────────────

    def _do_search_in_doc(self) -> None:
        """
        Cerca nel documento/editor attivo: esegue una vera find_all e popola
        l'albero con i risultati. Supporta modalità testo, regexp Python e
        SQL LIKE. I risultati sostituiscono quelli precedenti.
        """
        query = self._search_edit.text()
        if not query:
            return
        editor = self._mw._current_editor()
        if editor is None:
            return

        case_sensitive = self._chk_case.isChecked()
        whole_word = self._chk_whole_word.isChecked()
        mode = self._search_mode.currentData()   # "text" | "regex" | "like"
        re_flags = 0 if case_sensitive else re.IGNORECASE

        # Costruisce il pattern regex da usare per la ricerca
        # In modalità "text" la sintassi è intelligente:
        #   parole separate da spazio = AND (tutte devono essere presenti)
        #   -parola  o  !parola       = NOT (la parola NON deve essere presente)
        try:
            if mode == "regex":
                pat = re.compile(query, re_flags)
                must_pats  = [pat]
                must_not_pats = []
                smart_mode = False
            elif mode == "like":
                pat = self._like_to_regex(query)
                if case_sensitive:
                    pat = re.compile(pat.pattern, 0)
                must_pats  = [pat]
                must_not_pats = []
                smart_mode = False
            else:
                # Modalità testo intelligente: AND/NOT multi-token
                tokens = query.split()
                must_pats     = []
                must_not_pats = []
                smart_mode    = True
                if not tokens:
                    # La query è composta solo da spazi: cerca la stringa letterale
                    escaped = re.escape(query)
                    must_pats = [re.compile(escaped, re_flags)]
                else:
                    for token in tokens:
                        negated = token.startswith("-") or token.startswith("!")
                        word = token[1:] if negated else token
                        if not word:
                            continue
                        escaped = re.escape(word)
                        if whole_word:
                            escaped = rf"\b{escaped}\b"
                        compiled = re.compile(escaped, re_flags)
                        if negated:
                            must_not_pats.append(compiled)
                        else:
                            must_pats.append(compiled)
                if not must_pats and not must_not_pats:
                    return
        except re.error as e:
            self._lbl_summary.setText(_t("msg_regex_invalid", error=str(e)))
            return

        file_path = str(editor.file_path) if editor.file_path else ""
        lines = editor.text().split("\n")
        results = []
        for line_idx, line_text in enumerate(lines):
            if smart_mode or mode == "text":
                # Tutte le parole MUST devono matchare, nessuna MUST-NOT
                if not all(p.search(line_text) for p in must_pats):
                    continue
                if any(p.search(line_text) for p in must_not_pats):
                    continue
                # Usa la prima parola must come ancora per la colonna
                first_match = must_pats[0].search(line_text) if must_pats else None
                col = first_match.start() if first_match else 0
                results.append({
                    "file": file_path,
                    "line": line_idx,
                    "text": line_text,
                    "col":  col,
                })
            else:
                for m in must_pats[0].finditer(line_text):
                    results.append({
                        "file": file_path,
                        "line": line_idx,
                        "text": line_text,
                        "col":  m.start(),
                    })

        # Pulisce i vecchi risultati solo se NON si accoda
        if not self._chk_append.isChecked():
            self._tree.clear()
            self._all_results.clear()
        if not results:
            self._lbl_summary.setText(_t("msg_no_results_doc", query=query))
            self._current_query = query
            return

        self.add_results(query, results)

    # ── Filtro (grep/AND/NOT, regexp, LIKE) ───────────────────────────────────

    @staticmethod
    def _like_to_regex(pattern: str) -> re.Pattern:
        """
        Converte una stringa LIKE SQL in un regex Python.
        % → .* , _ → . , il resto viene escaped.
        """
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
        if text is None:
            text = self._filter_edit.text()
        mode = self._filter_mode.currentData()   # "grep" | "regex" | "like"
        text = text.strip()

        # Costruisce il matcher
        if not text:
            matcher = None
        elif mode == "regex":
            try:
                pat = re.compile(text, re.IGNORECASE)
                matcher = lambda s: bool(pat.search(s))
            except re.error:
                # regex invalida: non filtrare
                matcher = None
        elif mode == "like":
            try:
                pat = self._like_to_regex(text)
                matcher = lambda s: bool(pat.search(s))
            except re.error:
                matcher = None
        else:
            # grep-like: AND (+parola) NOT (-parola o !parola), case-insensitive
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

    def _replace_selected(self) -> None:
        """
        Sostituisce l'occorrenza selezionata: trova la query nella riga
        corrispondente e la rimpiazza con il testo del campo 'Sostituisci con:'.
        """
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
        editor.setCursorPosition(line_0, col)
        editor.ensureLineVisible(line_0)
        editor.setFocus()

        # Cerca e sostituisce solo quella occorrenza specifica, usando lo stesso
        # pattern della ricerca (coerente con modalità regex/LIKE/text e case).
        pat = self._compile_query_pattern()
        if pat is None:
            return
        line_text = editor.text(line_0).rstrip("\n").rstrip("\r")
        col = max(0, min(col, len(line_text)))
        match = pat.search(line_text, col) or pat.search(line_text)
        if match and match.end() > match.start():
            abs_start = match.start()
            abs_end   = match.end()
            # In modalità regex il replace può contenere riferimenti ai gruppi
            # (\1, \g<name>): espandili rispetto al match corrente.
            mode = self._search_mode.currentData()
            if mode == "regex":
                try:
                    replace_text = match.expand(replace_text)
                except (re.error, IndexError):
                    pass
            editor.setSelection(line_0, abs_start, line_0, abs_end)
            editor.replaceSelectedText(replace_text)

    def _replace_all(self) -> None:
        """
        Sostituisce tutte le occorrenze della query nell'editor attivo
        con il testo del campo 'Sostituisci con:'.
        """
        query = self._current_query
        if not query:
            QMessageBox.information(self, _t("btn_replace_all"), _t("msg_run_search_first"))
            return
        replace_text = self._replace_edit.text()
        editor = self._mw._current_editor()
        if editor is None:
            return
        # Usa lo stesso pattern della ricerca (coerente con regex/LIKE/text e case).
        pat = self._compile_query_pattern()
        if pat is None:
            return
        text = editor.text()
        mode = self._search_mode.currentData()
        # In modalità testo/LIKE il replace è letterale: neutralizza eventuali
        # sequenze di backreference (\1, \g<...>). In regex le lasciamo attive.
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


# ─── Plugin ───────────────────────────────────────────────────────────────────

class SearchResultsPlugin(BasePlugin):

    NAME        = "Search PQ"
    VERSION     = "1.1"
    DESCRIPTION = (
        "Multi-function dock panel for find/replace: "
        "shows clickable results, search bar, regex/grep/LIKE filter, copy and inline replace."
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

        # Espone il pannello su main_window per compatibilità con find_replace.py
        main_window._find_result_panel = self._panel

        # Aggiorna lo stile della lista risultati ad ogni cambio tema, così la
        # leggibilità resta coerente con il tema attivo (chiaro/scuro).
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

    def on_unload(self, main_window: "MainWindow") -> None:
        if hasattr(self, "_dock"):
            self._dock.hide()
            main_window.removeDockWidget(self._dock)
            self._dock.deleteLater()
        if hasattr(main_window, "_find_result_panel"):
            del main_window._find_result_panel
        super().on_unload(main_window)
