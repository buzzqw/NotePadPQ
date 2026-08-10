"""UI per ChkTeX/lacheck e latexindent, senza modificare il checker interno."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.latex_external_tools import (
    LatexDiagnostic,
    format_latex,
    run_chktex,
    run_lacheck,
)


class _ExternalToolWorker(QThread):
    completed = pyqtSignal(str, object)

    def __init__(self, operation: str, path: Path, text: str) -> None:
        super().__init__()
        self._operation = operation
        self._path = path
        self._text = text

    def run(self) -> None:
        if self._operation == "chktex":
            self.completed.emit(
                self._operation,
                run_chktex(self._path, cwd=self._path.parent),
            )
        elif self._operation == "lacheck":
            self.completed.emit(
                self._operation,
                run_lacheck(self._path, cwd=self._path.parent),
            )
        else:
            self.completed.emit(
                self._operation,
                format_latex(self._text, file_path=self._path, cwd=self._path.parent),
            )


class LatexExternalToolsDialog(QDialog):
    """Esegue strumenti esterni solo su richiesta esplicita dell'utente."""

    navigate_requested = pyqtSignal(object, int, int)

    def __init__(self, editor, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LaTeX external tools")
        self.setMinimumSize(760, 480)
        self._editor = editor
        self._worker: _ExternalToolWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._status = QLabel("Strumenti opzionali: ChkTeX, lacheck e latexindent")
        self._status.setStyleSheet("color: #9cdcfe;")
        layout.addWidget(self._status)
        buttons = QHBoxLayout()
        for label, operation in [
            ("Esegui ChkTeX", "chktex"),
            ("Esegui lacheck", "lacheck"),
            ("Formatta con latexindent", "latexindent"),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, op=operation: self._start(op))
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Severità", "File", "Riga", "Colonna", "Messaggio"])
        self._tree.setAlternatingRowColors(True)
        self._tree.itemDoubleClicked.connect(self._navigate)
        layout.addWidget(self._tree, 1)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _start(self, operation: str) -> None:
        path = getattr(self._editor, "file_path", None)
        if path is None:
            self._status.setText("Salva il documento prima di usare lo strumento esterno.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._status.setText(f"Esecuzione di {operation}…")
        self._tree.clear()
        self._worker = _ExternalToolWorker(operation, Path(path), self._editor.get_content())
        self._worker.completed.connect(self._completed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _completed(self, operation: str, result) -> None:
        if operation == "latexindent":
            original = self._editor.get_content()
            if isinstance(result, str) and result != original:
                self._editor.beginUndoAction()
                try:
                    self._editor.setText(result)
                    self._editor.setModified(True)
                    self._editor.refresh_language_support(force_check=True)
                finally:
                    self._editor.endUndoAction()
                self._status.setText("Documento formattato con latexindent.")
            else:
                self._status.setText("latexindent non disponibile o nessuna modifica prodotta.")
            return

        diagnostics = list(getattr(result, "diagnostics", ()))
        for diagnostic in diagnostics:
            self._add_diagnostic(diagnostic)
        error = getattr(result, "error", None)
        if error:
            self._status.setText(f"Errore: {error}")
        else:
            self._status.setText(f"{operation}: {len(diagnostics)} diagnostica/e")

    def _add_diagnostic(self, diagnostic: LatexDiagnostic) -> None:
        file_path = diagnostic.file or str(getattr(self._editor, "file_path", ""))
        item = QTreeWidgetItem([
            diagnostic.severity.upper(),
            Path(file_path).name,
            str(diagnostic.line or ""),
            str(diagnostic.column or ""),
            diagnostic.message,
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, diagnostic)
        item.setForeground(0, QColor("#f44747" if diagnostic.severity == "error" else "#ffcc00"))
        self._tree.addTopLevelItem(item)

    def _navigate(self, item: QTreeWidgetItem, _column: int) -> None:
        diagnostic = item.data(0, Qt.ItemDataRole.UserRole)
        if diagnostic is None or diagnostic.line is None:
            return
        path = Path(diagnostic.file or self._editor.file_path)
        if not path.is_absolute() and self._editor.file_path:
            path = self._editor.file_path.parent / path
        self.navigate_requested.emit(path, diagnostic.line, max(0, (diagnostic.column or 1) - 1))

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait()
        super().closeEvent(event)


__all__ = ["LatexExternalToolsDialog"]
