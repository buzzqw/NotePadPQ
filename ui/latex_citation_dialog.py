"""Small project citation chooser used by the LaTeX menu."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


def project_bibtex_keys(editor: EditorWidget) -> list[str]:
    """Return BibTeX keys known to the current LaTeX project.

    The project-wide extractor handles included TeX files and referenced .bib
    resources.  The second call keeps unsaved changes in the current editor
    visible to the chooser.
    """
    from editor.latex_support import LaTeXSupport

    path = getattr(editor, "file_path", None)
    keys: set[str] = set()
    if path:
        keys.update(LaTeXSupport.extract_bibtex_keys_multifile(path))
    keys.update(LaTeXSupport.extract_bibtex_keys(editor.text(), path))
    return sorted(keys, key=str.casefold)


class LatexCitationChooserDialog(QDialog):
    """Search and select one existing BibTeX key."""

    def __init__(self, keys: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._keys = sorted(set(keys), key=str.casefold)
        self._selected_key = ""
        self.setWindowTitle(tr("latex_citation.title", default="Scegli citazione"))
        self.setMinimumSize(420, 340)
        self._build_ui()
        self._refresh_list("")

    @property
    def selected_key(self) -> str:
        return self._selected_key

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(7)

        row = QHBoxLayout()
        row.addWidget(QLabel(
            tr("latex_citation.search", default="Cerca:")
        ))
        self._search = QLineEdit(self)
        self._search.setPlaceholderText(
            tr("latex_citation.placeholder", default="Filtra chiavi BibTeX...")
        )
        self._search.textChanged.connect(self._refresh_list)
        row.addWidget(self._search, 1)
        layout.addLayout(row)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(self._accept_item)
        layout.addWidget(self._list, 1)

        self._info = QLabel(self)
        self._info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._info)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_list(self, query: str) -> None:
        query = query.casefold().strip()
        self._list.clear()
        for key in self._keys:
            if query in key.casefold():
                self._list.addItem(QListWidgetItem(key))
        self._info.setText(
            tr("latex_citation.count", default="{count} chiavi").format(
                count=self._list.count()
            )
        )
        if self._list.count():
            self._list.setCurrentRow(0)

    def _accept_item(self, item: QListWidgetItem) -> None:
        self._selected_key = item.text()
        self.accept()

    def _accept_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._selected_key = item.text()
        self.accept()
