"""Pannello persistente che mostra i risultati delle ricerche (Trova tutto / Cerca nei file)."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont


_COL_INFO  = 0   # "file:riga" o testo risultato
_COL_TEXT  = 1   # testo della riga


class FindResultPanel(QWidget):
    # Emesso quando l'utente vuole aprire un risultato: (percorso, numero_riga_0based)
    navigate_requested = pyqtSignal(str, int)

    def __init__(self, main_window):
        super().__init__(main_window)
        self._mw = main_window

        vl = QVBoxLayout(self)
        vl.setContentsMargins(2, 2, 2, 2)
        vl.setSpacing(2)

        # ── Toolbar compatta ──────────────────────────────────────────────────
        tb = QHBoxLayout()
        self._lbl_summary = QLabel("Nessuna ricerca effettuata.")
        self._lbl_summary.setStyleSheet("font-weight: bold;")
        btn_clear  = QPushButton("🗑 Pulisci")
        btn_clear.setFixedHeight(22)
        btn_clear.setToolTip("Rimuove tutti i risultati")
        btn_prev   = QPushButton("▲")
        btn_prev.setFixedWidth(28); btn_prev.setFixedHeight(22)
        btn_prev.setToolTip("Risultato precedente")
        btn_next   = QPushButton("▼")
        btn_next.setFixedWidth(28); btn_next.setFixedHeight(22)
        btn_next.setToolTip("Risultato successivo")
        tb.addWidget(self._lbl_summary, 1)
        tb.addWidget(btn_prev)
        tb.addWidget(btn_next)
        tb.addWidget(btn_clear)
        vl.addLayout(tb)

        # ── Albero risultati ──────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Posizione", "Testo"])
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
        root.setForeground(0, QBrush(QColor("#2060a0")))
        root.setData(0, Qt.ItemDataRole.UserRole, None)

        for file_path, file_results in by_file.items():
            import os
            fname = os.path.basename(file_path)
            file_item = QTreeWidgetItem(root)
            file_item.setText(0, f"📄 {fname}  ({len(file_results)})")
            file_item.setText(1, file_path)
            file_item.setForeground(0, QBrush(QColor("#206020")))
            file_item.setData(0, Qt.ItemDataRole.UserRole, None)
            file_item.setToolTip(1, file_path)

            for r in file_results:
                item = QTreeWidgetItem(file_item)
                line_no = r["line"] + 1  # 1-based per visualizzazione
                item.setText(0, f"  riga {line_no:>5}")
                item.setText(1, r["text"].rstrip())
                item.setFont(1, self._mono)
                item.setData(0, Qt.ItemDataRole.UserRole, (r["file"], r["line"]))

        root.setExpanded(True)
        for i in range(root.childCount()):
            root.child(i).setExpanded(True)

        self._tree.scrollToBottom()
        self.show()
        self.raise_()

    def clear_all(self) -> None:
        self._tree.clear()
        self._lbl_summary.setText("Nessuna ricerca effettuata.")

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
        if data:
            file_path, line = data
            self.navigate_requested.emit(file_path, line)

    def _do_navigate(self, file_path: str, line: int) -> None:
        from pathlib import Path
        self._mw.open_files([Path(file_path)])
        editor = self._mw._current_editor()
        if editor:
            editor.setCursorPosition(line, 0)
            editor.ensureLineVisible(line)
            editor.setFocus()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        act_copy = menu.addAction("📋 Copia testo riga")
        act_copy_all = menu.addAction("📋 Copia tutti i risultati")
        menu.addSeparator()
        act_clear = menu.addAction("🗑 Pulisci tutti i risultati")

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
