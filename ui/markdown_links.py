"""Small workspace backlink browser for Markdown documents."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QVBoxLayout

from core.markdown_features import find_backlinks
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class MarkdownBacklinksDialog(QDialog):
    def __init__(
        self,
        main_window: MainWindow,
        document: Path,
        workspace_root: Path | None = None,
    ):
        super().__init__(main_window)
        self._mw = main_window
        self._document = document
        self._workspace_root = workspace_root or document.parent
        self.setWindowTitle(
            tr("dialog.markdown_backlinks", default="Backlink Markdown")
        )
        self.resize(620, 380)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                tr(
                    "label.markdown_backlinks_for",
                    default="Documenti che collegano a: {name}",
                    name=document.name,
                )
            )
        )
        self._list = QListWidget(self)
        self._list.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self._list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    def _populate(self) -> None:
        root = self._workspace_root
        try:
            files = [
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in {".md", ".markdown"}
                and ".git" not in path.parts
                and "node_modules" not in path.parts
            ]
        except OSError:
            files = []
        backlinks = find_backlinks(files, self._document, root)
        if not backlinks:
            self._list.addItem(
                tr("label.no_markdown_backlinks", default="Nessun backlink trovato")
            )
            self._list.item(self._list.count() - 1).setFlags(Qt.ItemFlag.NoItemFlags)
            return
        for path in backlinks:
            self._list.addItem(str(path.relative_to(root)))
            self._list.item(self._list.count() - 1).setData(Qt.ItemDataRole.UserRole, path)

    def _open_item(self, item) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(path, Path):
            self._mw.open_files([path])
            self.accept()
