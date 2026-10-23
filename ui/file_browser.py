"""
ui/file_browser.py — Pannello laterale File Browser
NotePadPQ

Mostra l'albero del filesystem a partire da una cartella radice.
Doppio click su un file → lo apre nell'editor.
"""

from pathlib import Path

from PyQt6.QtCore import QDir, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QDrag, QFileSystemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from config.settings import Settings
from core.external_open import open_url as _open_url
from i18n.i18n import tr

# MIME marker used to distinguish a drag started inside NotePadPQ's file
# browser from a file dropped by an external application.  The editor uses it
# to insert ``\include{...}`` for .tex files instead of opening a new tab.
FILEBROWSER_MIME = "application/x-notepadpq-filebrowser"


class _FileTreeView(QTreeView):
    """QTreeView that tags its drags with ``FILEBROWSER_MIME``."""

    def startDrag(self, supported_actions) -> None:  # Qt enum in signature
        indexes = self.selectedIndexes()
        if not indexes:
            return
        model = self.model()
        mime = model.mimeData(indexes) if model is not None else None
        if mime is None:
            return
        mime.setData(FILEBROWSER_MIME, b"1")
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class FileBrowser(QWidget):
    """
    Pannello laterale con albero del filesystem.
    Emette file_open_requested(Path) quando l'utente vuole aprire un file.
    """

    file_open_requested = pyqtSignal(object)   # Path
    follow_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root: Path | None = None
        self._follow_active = bool(
            Settings.instance().get("file_browser/follow_active_file", True)
        )
        self._setup_ui()
        self._set_root(Path.home())

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
        self._path_edit.setToolTip(tr("tooltip.filebrowser_path"))
        bar.addWidget(self._path_edit)

        btn_home = QToolButton()
        btn_home.setText("🏠")
        btn_home.setToolTip(tr("tooltip.filebrowser_home"))
        btn_home.setAccessibleName(tr("tooltip.filebrowser_home"))
        btn_home.setAccessibleDescription(tr("tooltip.filebrowser_home"))
        btn_home.clicked.connect(lambda: self._manual_set_root(Path.home()))
        bar.addWidget(btn_home)

        btn_choose = QToolButton()
        btn_choose.setText("📂")
        btn_choose.setToolTip(tr("tooltip.filebrowser_choose"))
        btn_choose.setAccessibleName(tr("tooltip.filebrowser_choose"))
        btn_choose.setAccessibleDescription(tr("tooltip.filebrowser_choose"))
        btn_choose.clicked.connect(self._choose_root)
        bar.addWidget(btn_choose)

        btn_up = QToolButton()
        btn_up.setText("⬆")
        btn_up.setToolTip(tr("tooltip.filebrowser_up"))
        btn_up.setAccessibleName(tr("tooltip.filebrowser_up"))
        btn_up.setAccessibleDescription(tr("tooltip.filebrowser_up"))
        btn_up.clicked.connect(self._go_up)
        bar.addWidget(btn_up)

        self._btn_follow = QToolButton()
        self._btn_follow.setText("📍")
        self._btn_follow.setCheckable(True)
        self._btn_follow.setChecked(self._follow_active)
        self._btn_follow.setToolTip(tr(
            "tooltip.filebrowser_follow",
            default="Segui il file attivo: imposta la radice alla cartella del documento",
        ))
        self._btn_follow.setAccessibleName(self._btn_follow.toolTip())
        self._btn_follow.toggled.connect(self._on_follow_toggled)
        bar.addWidget(self._btn_follow)

        layout.addLayout(bar)

        # Albero filesystem
        self._model = QFileSystemModel()
        # Don't watch the whole tree while the panel is hidden: QFileSystemModel
        # can generate a lot of inotify traffic on large roots (#4700 in
        # TeXstudio).  showEvent/hideEvent toggle this option.
        self._model.setOption(
            QFileSystemModel.Option.DontWatchForChanges, True
        )
        self._model.setRootPath("")
        self._model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden
        )

        self._tree = _FileTreeView()
        self._tree.setObjectName("FileBrowserTree")
        self._tree.setAccessibleName(tr("action.view_file_browser"))
        self._tree.setAccessibleDescription(tr("tooltip.filebrowser_path"))
        self._tree.setModel(self._model)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._tree.setDefaultDropAction(Qt.DropAction.CopyAction)
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
        path = Path(path)
        if self._root == path and self._model.rootPath():
            return
        self._root = path
        self._path_edit.setText(str(path))
        idx = self._model.setRootPath(str(path))
        self._tree.setRootIndex(idx)

    def _manual_set_root(self, path: Path) -> None:
        """Navigazione manuale: sblocca il "segui file attivo"."""
        if self._follow_active:
            self._btn_follow.setChecked(False)
        self._set_root(path)

    def _choose_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("file_browser.choose_folder", default="Scegli cartella"),
            str(self._root or Path.home()),
        )
        if folder:
            self._manual_set_root(Path(folder))

    def _go_up(self) -> None:
        if self._root is None:
            return
        parent = self._root.parent
        if parent != self._root:
            self._manual_set_root(parent)

    # ── Segui file attivo ─────────────────────────────────────────────────────

    def follows_active_file(self) -> bool:
        return self._follow_active

    def _on_follow_toggled(self, checked: bool) -> None:
        self._follow_active = checked
        Settings.instance().set("file_browser/follow_active_file", checked)
        self._btn_follow.setToolTip(tr(
            "tooltip.filebrowser_follow",
            default="Segui il file attivo: imposta la radice alla cartella del documento",
        ))
        self.follow_changed.emit(checked)

    def set_root_from_file(self, file_path: Path) -> None:
        """Imposta la radice alla cartella del file aperto e lo seleziona."""
        if not self._follow_active:
            return
        target = Path(file_path)
        self._set_root(target.parent)
        index = self._model.index(str(target))
        if index.isValid():
            self._tree.setCurrentIndex(index)
            self._tree.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    # ── Watcher ───────────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        self._model.setOption(
            QFileSystemModel.Option.DontWatchForChanges, False
        )
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._model.setOption(
            QFileSystemModel.Option.DontWatchForChanges, True
        )
        super().hideEvent(event)

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
        root = self._root or Path.home()
        folder = path.parent if (path and path.is_file()) else (path or root)
        menu = QMenu(self)

        if path and path.is_file():
            act_open = QAction(tr("file_browser.act_open"), self)
            act_open.triggered.connect(lambda: self.file_open_requested.emit(path))
            menu.addAction(act_open)
            menu.addSeparator()

        # Nuovo file / Nuova cartella
        act_new_file = QAction(tr("file_browser.act_new_file"), self)
        act_new_file.triggered.connect(lambda: self._new_file(folder))
        menu.addAction(act_new_file)

        act_new_folder = QAction(tr("file_browser.act_new_folder"), self)
        act_new_folder.triggered.connect(lambda: self._new_folder(folder))
        menu.addAction(act_new_folder)

        if path:
            menu.addSeparator()
            act_rename = QAction(tr("file_browser.act_rename"), self)
            act_rename.triggered.connect(lambda: self._rename(path))
            menu.addAction(act_rename)

            act_delete = QAction(tr("file_browser.act_delete"), self)
            act_delete.triggered.connect(lambda: self._delete(path))
            menu.addAction(act_delete)

            menu.addSeparator()
            act_set_root = QAction(tr("file_browser.act_set_root"), self)
            act_set_root.triggered.connect(
                lambda: self._manual_set_root(
                    path if path.is_dir() else path.parent
                )
            )
            menu.addAction(act_set_root)

        act_reveal = QAction(tr("file_browser.reveal_in_fm", default="Mostra nel file manager"), self)
        act_reveal.triggered.connect(lambda: self._reveal(path or root))
        menu.addAction(act_reveal)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ── Operazioni filesystem ─────────────────────────────────────────────────

    def _new_file(self, folder: Path) -> None:
        name, ok = QInputDialog.getText(self, tr("file_browser.new_file_title"), tr("file_browser.new_file_prompt"))
        if not ok or not name.strip():
            return
        target = folder / name.strip()
        try:
            target.touch(exist_ok=False)
            self.file_open_requested.emit(target)
        except FileExistsError:
            QMessageBox.warning(self, tr("file_browser.error_title"), tr("file_browser.file_exists_error", name=name))
        except Exception as e:
            QMessageBox.critical(self, tr("dialog.error", default="Error"), str(e))

    def _new_folder(self, folder: Path) -> None:
        name, ok = QInputDialog.getText(self, tr("file_browser.new_folder_title"), tr("file_browser.new_folder_prompt"))
        if not ok or not name.strip():
            return
        target = folder / name.strip()
        try:
            target.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            QMessageBox.warning(self, tr("file_browser.error_title"), tr("file_browser.folder_exists_error", name=name))
        except Exception as e:
            QMessageBox.critical(self, tr("dialog.error", default="Error"), str(e))

    def _rename(self, path: Path) -> None:
        new_name, ok = QInputDialog.getText(
            self, tr("file_browser.rename_title"), tr("file_browser.rename_prompt"), text=path.name
        )
        if not ok or not new_name.strip() or new_name.strip() == path.name:
            return
        target = path.parent / new_name.strip()
        try:
            path.rename(target)
        except Exception as e:
            QMessageBox.critical(self, tr("file_browser.rename_error", default="Errore rinomina"), str(e))

    def _delete(self, path: Path) -> None:
        try:
            from send2trash import send2trash
        except ImportError:
            send2trash = None
        message_key = (
            "file_browser.delete_folder_confirm" if path.is_dir()
            else "file_browser.delete_file_confirm"
        )
        message = tr(message_key, name=path.name)
        message += "\n\n" + tr(
            "file_browser.delete_to_trash" if send2trash else "file_browser.delete_permanently"
        )
        reply = QMessageBox.question(
            self,
            tr("file_browser.delete_confirm_title"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if send2trash:
                send2trash(str(path))
            elif path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                path.unlink()
        except Exception as e:
            QMessageBox.critical(self, tr("file_browser.delete_error", default="Errore eliminazione"), str(e))

    def _reveal(self, path: Path) -> None:
        from PyQt6.QtCore import QUrl
        target = path if path.is_dir() else path.parent
        _open_url(QUrl.fromLocalFile(str(target)))
