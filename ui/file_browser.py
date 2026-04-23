"""
ui/file_browser.py — Pannello laterale File Browser
NotePadPQ

Mostra l'albero del filesystem a partire da una cartella radice.
Doppio click su un file → lo apre nell'editor.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QDir, pyqtSignal
from PyQt6.QtGui import QFileSystemModel, QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView,
    QToolButton, QLineEdit, QFileDialog, QMenu, QAbstractItemView,
)


class FileBrowser(QWidget):
    """
    Pannello laterale con albero del filesystem.
    Emette file_open_requested(Path) quando l'utente vuole aprire un file.
    """

    file_open_requested = pyqtSignal(object)   # Path

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._root: Path = Path.home()
        self._setup_ui()
        self._set_root(self._root)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Barra superiore: percorso corrente + pulsante cambia cartella
        bar = QHBoxLayout()
        bar.setSpacing(2)

        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setToolTip("Cartella radice corrente")
        bar.addWidget(self._path_edit)

        btn_home = QToolButton()
        btn_home.setText("🏠")
        btn_home.setToolTip("Vai alla home")
        btn_home.clicked.connect(lambda: self._set_root(Path.home()))
        bar.addWidget(btn_home)

        btn_choose = QToolButton()
        btn_choose.setText("📂")
        btn_choose.setToolTip("Scegli cartella...")
        btn_choose.clicked.connect(self._choose_root)
        bar.addWidget(btn_choose)

        btn_up = QToolButton()
        btn_up.setText("⬆")
        btn_up.setToolTip("Cartella superiore")
        btn_up.clicked.connect(self._go_up)
        bar.addWidget(btn_up)

        layout.addLayout(bar)

        # Albero filesystem
        self._model = QFileSystemModel()
        self._model.setRootPath("")
        self._model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden
        )

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        # Nascondi colonne inutili (dimensione, tipo, data)
        self._tree.setColumnHidden(1, True)
        self._tree.setColumnHidden(2, True)
        self._tree.setColumnHidden(3, True)

        self._tree.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self._tree)

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _set_root(self, path: Path) -> None:
        self._root = path
        self._path_edit.setText(str(path))
        idx = self._model.setRootPath(str(path))
        self._tree.setRootIndex(idx)

    def _choose_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Scegli cartella", str(self._root)
        )
        if folder:
            self._set_root(Path(folder))

    def _go_up(self) -> None:
        parent = self._root.parent
        if parent != self._root:
            self._set_root(parent)

    def set_root_from_file(self, file_path: Path) -> None:
        """Imposta la radice alla cartella del file aperto."""
        self._set_root(file_path.parent)

    # ── Interazione ───────────────────────────────────────────────────────────

    def _on_double_click(self, index) -> None:
        path = Path(self._model.filePath(index))
        if path.is_file():
            self.file_open_requested.emit(path)
        elif path.is_dir():
            if self._tree.isExpanded(index):
                self._tree.collapse(index)
            else:
                self._tree.expand(index)

    def _on_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        path = Path(self._model.filePath(index))
        menu = QMenu(self)

        if path.is_file():
            act_open = QAction("Apri", self)
            act_open.triggered.connect(lambda: self.file_open_requested.emit(path))
            menu.addAction(act_open)
            menu.addSeparator()

        act_set_root = QAction("Imposta come cartella radice", self)
        act_set_root.triggered.connect(
            lambda: self._set_root(path if path.is_dir() else path.parent)
        )
        menu.addAction(act_set_root)

        act_reveal = QAction("Mostra nel file manager", self)
        act_reveal.triggered.connect(lambda: self._reveal(path))
        menu.addAction(act_reveal)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _reveal(self, path: Path) -> None:
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        target = path if path.is_dir() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
