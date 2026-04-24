"""
ui/latex_minimap.py — Pannello struttura documento LaTeX
NotePadPQ

Mostra la struttura gerarchica del documento LaTeX
(part/chapter/section/subsection/subsubsection/paragraph)
come albero navigabile: cliccando su una voce il cursore
salta alla riga corrispondente nell'editor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Dict, Any, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QSizePolicy,
)

from editor.latex_support import extract_structure

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Icone testuali per ogni livello
_SECTION_ICONS: Dict[str, str] = {
    "part":         "❶",
    "chapter":      "◉",
    "section":      "§",
    "subsection":   "›",
    "subsubsection":"·",
    "paragraph":    "¶",
    "subparagraph": "–",
}


class LaTeXMinimapWidget(QWidget):
    """
    Pannello struttura documento LaTeX.
    Mostra sezioni/sottosezioni come albero e permette di navigare
    cliccando su una voce.
    """

    def __init__(self, editor: "EditorWidget", parent: QWidget = None):
        super().__init__(parent)
        self._editor = editor
        self._needs_refresh = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self._rebuild)

        self._setup_ui()

        # Aggiorna quando il testo cambia
        self._editor.textChanged.connect(self._schedule_rebuild)

        # Prima costruzione
        self._rebuild()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("Struttura documento")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setBold(True)
        font.setPointSize(8)
        header.setFont(font)
        header.setStyleSheet(
            "background: #2d2d2d; color: #cccccc; padding: 3px;"
        )
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(12)
        self._tree.setAnimated(True)
        self._tree.setStyleSheet(
            "QTreeWidget { background: #1e1e1e; color: #d4d4d4; "
            "border: none; font-size: 11px; }"
            "QTreeWidget::item:hover { background: #2a2d2e; }"
            "QTreeWidget::item:selected { background: #094771; color: #ffffff; }"
        )
        self._tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, 1)

        self.setMinimumWidth(160)
        self.setMaximumWidth(280)

    # ── Rebuild ───────────────────────────────────────────────────────────────

    def _schedule_rebuild(self) -> None:
        if self.isVisible():
            self._timer.start()
        else:
            self._needs_refresh = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self._timer.start()

    def _rebuild(self) -> None:
        """Ricostruisce l'albero dalla struttura del documento."""
        text = self._editor.text()
        structure = extract_structure(text)

        self._tree.blockSignals(True)
        self._tree.clear()

        if not structure:
            placeholder = QTreeWidgetItem(["(nessuna sezione)"])
            placeholder.setForeground(0, self._tree.palette().mid().color())
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._tree.addTopLevelItem(placeholder)
            self._tree.blockSignals(False)
            return

        # Costruisce l'albero rispettando la gerarchia
        # stack: lista di (depth, QTreeWidgetItem)
        stack: List[tuple] = []

        for entry in structure:
            depth = entry["depth"]
            sec_type = entry["type"]
            title = entry["title"] or f"\\{sec_type}"
            line = entry["line"]

            icon = _SECTION_ICONS.get(sec_type, "•")
            label = f"{icon}  {title}"

            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, line)
            item.setToolTip(0, f"\\{sec_type}{{{title}}}  —  riga {line}")
            item.setForeground(0, _level_color(sec_type))

            # Trova il genitore corretto nello stack
            while stack and stack[-1][0] >= depth:
                stack.pop()

            if stack:
                stack[-1][1].addChild(item)
            else:
                self._tree.addTopLevelItem(item)

            stack.append((depth, item))

        self._tree.expandAll()
        self._tree.blockSignals(False)

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if line is None:
            return
        line_idx = int(line) - 1  # QScintilla usa indice 0-based
        self._editor.setCursorPosition(line_idx, 0)
        self._editor.ensureLineVisible(line_idx)
        self._editor.setFocus()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _level_color(sec_type: str) -> QColor:
    colors = {
        "part":         QColor("#ff6b6b"),
        "chapter":      QColor("#4ecdc4"),
        "section":      QColor("#61afef"),
        "subsection":   QColor("#98c379"),
        "subsubsection":QColor("#e5c07b"),
        "paragraph":    QColor("#c678dd"),
        "subparagraph": QColor("#56b6c2"),
    }
    return colors.get(sec_type, QColor("#d4d4d4"))
