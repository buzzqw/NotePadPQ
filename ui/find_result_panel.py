"""Pannello persistente che mostra i risultati delle ricerche (Trova tutto / Cerca nei file)."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont

from i18n.i18n import tr


_COL_INFO  = 0   # "file:riga" o testo risultato
_COL_TEXT  = 1   # testo della riga


def _theme_colors() -> dict:
    """Colori del tema attivo per intestazioni e nodi (root/file) dell'albero,
    al posto di valori hardcoded, leggibili su tutti i temi (chiari e scuri).
    """
    try:
        from config.themes import ThemeManager
        tm     = ThemeManager.instance()
        theme  = tm.get_theme(tm._active_name) or {}
        tokens = theme.get("tokens", {}) or {}
        is_dark = bool(theme.get("meta", {}).get("dark", True))
    except Exception:
        tokens, is_dark = {}, True

    def _tok(name: str, default: str) -> str:
        v = tokens.get(name, {})
        return (v.get("fg") if isinstance(v, dict) else None) or default

    if is_dark:
        return {"header": _tok("keyword", "#4fa3e0"),
                "file":   _tok("string", "#9bc36f")}
    return {"header": _tok("keyword", "#2060a0"),
            "file":   _tok("string", "#206020")}


class FindResultPanel(QWidget):
    # Emesso quando l'utente vuole aprire un risultato: (percorso, numero_riga_0based)
    navigate_requested = pyqtSignal(str, int)

    def __init__(self, main_window):
        super().__init__(main_window)
        self._mw = main_window
        self._current_query: str = ""
        self._colors = _theme_colors()

        vl = QVBoxLayout(self)
        vl.setContentsMargins(2, 2, 2, 2)
        vl.setSpacing(2)

        # ── Toolbar compatta ──────────────────────────────────────────────────
        tb = QHBoxLayout()
        self._lbl_summary = QLabel(tr("find_result_panel.no_search"))
        self._lbl_summary.setStyleSheet("font-weight: bold;")
        btn_clear  = QPushButton(tr("find_result_panel.btn_clear"))
        btn_clear.setFixedHeight(22)
        btn_clear.setToolTip("Rimuove tutti i risultati")
        btn_prev   = QPushButton("▲")
        btn_prev.setFixedWidth(28); btn_prev.setFixedHeight(22)
        btn_prev.setToolTip(tr("find_result_panel.tooltip_prev"))
        btn_next   = QPushButton("▼")
        btn_next.setFixedWidth(28); btn_next.setFixedHeight(22)
        btn_next.setToolTip(tr("find_result_panel.tooltip_next"))
        tb.addWidget(self._lbl_summary, 1)
        tb.addWidget(btn_prev)
        tb.addWidget(btn_next)
        tb.addWidget(btn_clear)
        vl.addLayout(tb)

        # ── Albero risultati ──────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels([
            tr("find_result_panel.col_position"),
            tr("find_result_panel.col_text"),
        ])
        self._tree.setColumnWidth(0, 200)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemActivated.connect(self._on_item_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        vl.addWidget(self._tree, 1)

        btn_clear.clicked.connect(self.clear_all)
        btn_prev.clicked.connect(self._navigate_prev)
        btn_next.clicked.connect(self._navigate_next)

        self.navigate_requested.connect(self._do_navigate)

        # Font mono per il testo delle righe
        self._mono = QFont("Monospace")
        self._mono.setStyleHint(QFont.StyleHint.Monospace)
        self._mono.setPointSize(9)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def add_results(self, query: str, results: list[dict]) -> None:
        """
        Aggiunge un gruppo di risultati al pannello.

        results: lista di dict con chiavi:
            - 'file': str (percorso file)
            - 'line': int (numero riga 0-based)
            - 'text': str (testo della riga)
            - 'col':  int (colonna di inizio match, opzionale)
        """
        if not results:
            return

        # Memorizza la query per poter evidenziare il match alla navigazione.
        self._current_query = query

        # Raggruppa per file
        by_file: dict[str, list] = {}
        for r in results:
            by_file.setdefault(r["file"], []).append(r)

        total = len(results)
        n_files = len(by_file)
        self._lbl_summary.setText(
            f'Cerca: "{query}" — {total} occorrenz{"e" if total!=1 else "a"} '
            f'in {n_files} file{"" if n_files==1 else ""}'
        )

        root = QTreeWidgetItem(self._tree)
        root.setText(0, f'🔍 "{query}"  ({total} occorrenze in {n_files} file)')
        root.setFont(0, QFont())
        root.setForeground(0, QBrush(QColor(self._colors["header"])))
        root.setData(0, Qt.ItemDataRole.UserRole, None)

        for file_path, file_results in by_file.items():
            import os
            fname = os.path.basename(file_path)
            file_item = QTreeWidgetItem(root)
            file_item.setText(0, f"📄 {fname}  ({len(file_results)})")
            file_item.setText(1, file_path)
            file_item.setForeground(0, QBrush(QColor(self._colors["file"])))
            file_item.setData(0, Qt.ItemDataRole.UserRole, None)
            file_item.setToolTip(1, file_path)

            for r in file_results:
                item = QTreeWidgetItem(file_item)
                line_no = r["line"] + 1  # 1-based per visualizzazione
                item.setText(0, f"  riga {line_no:>5}")
                item.setText(1, r["text"].rstrip())
                item.setFont(1, self._mono)
                item.setData(0, Qt.ItemDataRole.UserRole,
                             (r["file"], r["line"], r.get("col", 0)))

        root.setExpanded(True)
        for i in range(root.childCount()):
            root.child(i).setExpanded(True)

        self._tree.scrollToBottom()
        self.show()
        self.raise_()

    def clear_all(self) -> None:
        self._tree.clear()
        self._lbl_summary.setText(tr("find_result_panel.no_search"))

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
        file_path = data[0]
        line      = data[1]
        match_col = data[2] if len(data) > 2 else 0
        self._navigate_and_highlight(file_path, line, match_col)

    def _do_navigate(self, file_path: str, line: int) -> None:
        # Compatibilità col segnale navigate_requested(str,int).
        self._navigate_and_highlight(file_path, line, 0)

    def _navigate_and_highlight(self, file_path: str, line: int, col: int) -> None:
        """Apre il file alla riga indicata ed **evidenzia** (seleziona) il match,
        invece di limitarsi a posizionare il cursore. Se non riesce a calcolare
        il match (query sconosciuta o assente nella riga) seleziona l'intera riga.
        """
        from pathlib import Path
        import re
        if file_path:
            self._mw.open_files([Path(file_path)])
        editor = self._mw._current_editor()
        if editor is None:
            return

        line = max(0, min(line, max(0, editor.lines() - 1)))
        try:
            line_text = editor.text(line).rstrip("\n").rstrip("\r")
        except Exception:
            line_text = ""

        start, end = None, None
        if self._current_query and line_text:
            col = max(0, min(col, len(line_text)))
            try:
                pat = re.compile(re.escape(self._current_query), re.IGNORECASE)
            except re.error:
                pat = None
            if pat is not None:
                # `search(text, col)` cerca a partire da `col` senza creare
                # sotto-stringhe: gli offset restituiti sono già assoluti.
                m = pat.search(line_text, col) or pat.search(line_text)
                if m and m.end() > m.start():
                    start, end = m.start(), m.end()
        if start is None:
            start, end = 0, len(line_text)

        # Evidenziazione robusta: oltre alla selezione (attenuata da QScintilla
        # quando l'editor non ha il focus), applica l'indicatore persistente
        # sulla parola e mantiene visibile la riga corrente anche senza focus.
        if hasattr(editor, "highlight_find_match"):
            editor.highlight_find_match(line, start, end)
        else:
            editor.setSelection(line, start, line, end)
            editor.ensureLineVisible(line)
        editor.setFocus()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        act_copy = menu.addAction(tr("find_result_panel.copy_line"))
        act_copy_all = menu.addAction(tr("find_result_panel.copy_all"))
        menu.addSeparator()
        act_clear = menu.addAction(tr("find_result_panel.clear_all"))

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen == act_copy and item:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(item.text(1))
        elif chosen == act_copy_all:
            self._copy_all()
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
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText("\n".join(lines))
