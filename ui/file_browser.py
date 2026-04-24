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
    QInputDialog, QMessageBox,
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
        path = Path(self._model.filePath(index)) if index.isValid() else None
        folder = path.parent if (path and path.is_file()) else (path or self._root)
        menu = QMenu(self)

        if path and path.is_file():
            act_open = QAction("Apri", self)
            act_open.triggered.connect(lambda: self.file_open_requested.emit(path))
            menu.addAction(act_open)
            menu.addSeparator()

        # Nuovo file / Nuova cartella
        act_new_file = QAction("Nuovo file…", self)
        act_new_file.triggered.connect(lambda: self._new_file(folder))
        menu.addAction(act_new_file)

        act_new_folder = QAction("Nuova cartella…", self)
        act_new_folder.triggered.connect(lambda: self._new_folder(folder))
        menu.addAction(act_new_folder)

        if path:
            menu.addSeparator()
            act_rename = QAction("Rinomina…", self)
            act_rename.triggered.connect(lambda: self._rename(path))
            menu.addAction(act_rename)

            act_delete = QAction("Elimina", self)
            act_delete.triggered.connect(lambda: self._delete(path))
            menu.addAction(act_delete)

            menu.addSeparator()
            act_set_root = QAction("Imposta come cartella radice", self)
            act_set_root.triggered.connect(
                lambda: self._set_root(path if path.is_dir() else path.parent)
            )
            menu.addAction(act_set_root)

        act_reveal = QAction("Mostra nel file manager", self)
        act_reveal.triggered.connect(lambda: self._reveal(path or self._root))
        menu.addAction(act_reveal)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ── Operazioni filesystem ─────────────────────────────────────────────────

    def _new_file(self, folder: Path) -> None:
        name, ok = QInputDialog.getText(self, "Nuovo file", "Nome del file:")
        if not ok or not name.strip():
            return
        target = folder / name.strip()
        try:
            target.touch(exist_ok=False)
            self.file_open_requested.emit(target)
        except FileExistsError:
            QMessageBox.warning(self, "Errore", f"Il file '{name}' esiste già.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", str(e))

    def _new_folder(self, folder: Path) -> None:
        name, ok = QInputDialog.getText(self, "Nuova cartella", "Nome della cartella:")
        if not ok or not name.strip():
            return
        target = folder / name.strip()
        try:
            target.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            QMessageBox.warning(self, "Errore", f"La cartella '{name}' esiste già.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", str(e))

    def _rename(self, path: Path) -> None:
        new_name, ok = QInputDialog.getText(
            self, "Rinomina", "Nuovo nome:", text=path.name
        )
        if not ok or not new_name.strip() or new_name.strip() == path.name:
            return
        target = path.parent / new_name.strip()
        try:
            path.rename(target)
        except Exception as e:
            QMessageBox.critical(self, "Errore rinomina", str(e))

    def _delete(self, path: Path) -> None:
        kind = "la cartella" if path.is_dir() else "il file"
        reply = QMessageBox.question(
            self,
            "Conferma eliminazione",
            f"Eliminare {kind} '{path.name}'?\nL'operazione non è reversibile.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                path.unlink()
        except Exception as e:
            QMessageBox.critical(self, "Errore eliminazione", str(e))

    def _reveal(self, path: Path) -> None:
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        target = path if path.is_dir() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
