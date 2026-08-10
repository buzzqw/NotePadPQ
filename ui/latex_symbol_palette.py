"""Palette ricercabile di simboli e comandi LaTeX."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

_SYMBOLS = (
    ("Greek", "alpha", "\\alpha", ""), ("Greek", "beta", "\\beta", ""),
    ("Greek", "gamma", "\\gamma", ""), ("Greek", "delta", "\\delta", ""),
    ("Greek", "epsilon", "\\epsilon", ""), ("Greek", "theta", "\\theta", ""),
    ("Greek", "lambda", "\\lambda", ""), ("Greek", "mu", "\\mu", ""),
    ("Greek", "pi", "\\pi", ""), ("Greek", "sigma", "\\sigma", ""),
    ("Greek", "phi", "\\phi", ""), ("Greek", "omega", "\\omega", ""),
    ("Operators", "sum", "\\sum", ""), ("Operators", "prod", "\\prod", ""),
    ("Operators", "int", "\\int", ""), ("Operators", "iint", "\\iint", "amsmath"),
    ("Operators", "partial", "\\partial", ""), ("Operators", "nabla", "\\nabla", ""),
    ("Operators", "sqrt", "\\sqrt{}", ""), ("Operators", "frac", "\\frac{}{}", ""),
    ("Operators", "lim", "\\lim", ""), ("Operators", "infty", "\\infty", ""),
    ("Relations", "leq", "\\leq", ""), ("Relations", "geq", "\\geq", ""),
    ("Relations", "neq", "\\neq", ""), ("Relations", "approx", "\\approx", ""),
    ("Relations", "equiv", "\\equiv", ""), ("Relations", "propto", "\\propto", ""),
    ("Relations", "subseteq", "\\subseteq", ""), ("Relations", "in", "\\in", ""),
    ("Arrows", "to", "\\to", ""), ("Arrows", "leftarrow", "\\leftarrow", ""),
    ("Arrows", "rightarrow", "\\rightarrow", ""), ("Arrows", "leftrightarrow", "\\leftrightarrow", ""),
    ("Arrows", "Rightarrow", "\\Rightarrow", ""), ("Arrows", "mapsto", "\\mapsto", ""),
    ("Delimiters", "left( right)", "\\left( \\right)", ""),
    ("Delimiters", "left[ right]", "\\left[ \\right]", ""),
    ("Delimiters", "left\\{ right\\}", "\\left\\{ \\right\\}", ""),
    ("Fonts", "mathbf{}", "\\mathbf{}", ""), ("Fonts", "mathrm{}", "\\mathrm{}", ""),
    ("Fonts", "mathcal{}", "\\mathcal{}", ""), ("Fonts", "mathbb{}", "\\mathbb{}", "amsfonts"),
    ("Fonts", "mathsf{}", "\\mathsf{}", ""), ("Fonts", "text{}", "\\text{}", "amsmath"),
)


class LatexSymbolPaletteDialog(QDialog):
    """Selettore non distruttivo: inserisce solo il comando selezionato."""

    def __init__(self, editor=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LaTeX symbol palette")
        self.setMinimumSize(520, 500)
        self._editor = editor
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Categoria:"))
        self._category = QComboBox()
        self._category.addItem("Tutte", "*")
        for category in sorted({item[0] for item in _SYMBOLS} | {"Packages"}):
            self._category.addItem(category, category)
        self._category.currentIndexChanged.connect(self._populate)
        row.addWidget(self._category)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Cerca nome o comando…")
        self._search.textChanged.connect(self._populate)
        row.addWidget(self._search, 1)
        layout.addLayout(row)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._insert())
        layout.addWidget(self._list, 1)
        self._hint = QLabel("I comandi con pacchetto richiesto mostrano il pacchetto tra parentesi.")
        self._hint.setStyleSheet("color: #858585;")
        layout.addWidget(self._hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._insert)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self) -> None:
        self._list.clear()
        category = self._category.currentData()
        query = self._search.text().strip().casefold()
        entries = list(_SYMBOLS)
        try:
            from editor.latex_support import PACKAGE_COMMANDS
            for package, commands in PACKAGE_COMMANDS.items():
                entries.extend(
                    ("Packages", command, command, package)
                    for command in commands
                )
        except Exception:
            pass
        seen: set[tuple[str, str]] = set()
        for group, name, command, package in entries:
            if category != "*" and group != category:
                continue
            haystack = f"{group} {name} {command} {package}".casefold()
            if query and query not in haystack:
                continue
            identity = (command, package)
            if identity in seen:
                continue
            seen.add(identity)
            suffix = f"  [{package}]" if package else ""
            item = QListWidgetItem(f"{name:<20} {command}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, command)
            self._list.addItem(item)

    def _insert(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        command = item.data(Qt.ItemDataRole.UserRole)
        if self._editor is not None:
            self._editor.beginUndoAction()
            try:
                line, column = self._editor.getCursorPosition()
                self._editor.insert(command)
                brace = command.find("{")
                if brace >= 0 and "}" in command[brace:]:
                    self._editor.setCursorPosition(line, column + brace + 1)
            finally:
                self._editor.endUndoAction()
            self._editor.setFocus()
        self.accept()


__all__ = ["LatexSymbolPaletteDialog"]
