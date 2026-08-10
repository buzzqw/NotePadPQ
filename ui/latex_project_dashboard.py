"""Dashboard non invasivo per il progetto LaTeX corrente."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from core.latex_external_tools import detect_latex_auxiliary_tools
from core.latex_project import LatexProjectContext
from core.latex_references import analyze_latex_project
from core.latex_toolchain import detect_latex_toolchain


class _DashboardToolchainWorker(QThread):
    completed = pyqtSignal(object)

    def __init__(self, project_path: Path) -> None:
        super().__init__()
        self._project_path = project_path

    def run(self) -> None:
        self.completed.emit(
            detect_latex_toolchain(context=str(self._project_path), refresh=False)
        )


class LatexProjectDashboardDialog(QDialog):
    """Riepiloga contesto, sorgenti, output e salute del progetto."""

    def __init__(self, editor=None, open_references=None, open_toolchain=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LaTeX project dashboard")
        self.setMinimumWidth(620)
        self._editor = editor
        self._open_references = open_references
        self._open_toolchain = open_toolchain
        self._toolchain_worker: _DashboardToolchainWorker | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._form = QFormLayout()
        self._labels: dict[str, QLabel] = {}
        for key, title in [
            ("root", "Root"), ("directory", "Project directory"),
            ("output", "Output directory"), ("pdf", "Expected PDF"),
            ("files", "Source files"), ("profile", "Build profile"),
            ("health", "Project health"), ("toolchain", "Toolchain"),
            ("auxiliary", "Auxiliary tools"),
        ]:
            value = QLabel("-")
            value.setWordWrap(True)
            self._labels[key] = value
            self._form.addRow(f"{title}:", value)
        layout.addLayout(self._form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        if self._open_references is not None:
            ref = buttons.addButton("Riferimenti globali", QDialogButtonBox.ButtonRole.ActionRole)
            ref.clicked.connect(self._open_references)
        if self._open_toolchain is not None:
            tools = buttons.addButton("Toolchain", QDialogButtonBox.ButtonRole.ActionRole)
            tools.clicked.connect(self._open_toolchain)
        refresh = buttons.addButton("Aggiorna", QDialogButtonBox.ButtonRole.ActionRole)
        refresh.clicked.connect(self.refresh)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def refresh(self) -> None:
        if self._editor is None or not getattr(self._editor, "file_path", None):
            for value in self._labels.values():
                value.setText("Nessun file LaTeX aperto")
            return
        path = Path(self._editor.file_path)
        context = LatexProjectContext(path, self._editor.get_content())
        analysis = analyze_latex_project(path, self._editor.get_content())
        profile = "-"
        try:
            from core.build_manager import BuildManager
            profile = BuildManager.instance().get_profile_for_file(path) or "-"
        except Exception:
            pass
        problems = (
            len(analysis.undefined) + len(analysis.undefined_citations)
            + len(analysis.duplicates) + len(analysis.missing_includes)
            + len(analysis.missing_assets)
        )
        self._labels["root"].setText(str(context.root))
        self._labels["directory"].setText(str(context.root.parent))
        self._labels["output"].setText(str(context.output_directory))
        self._labels["pdf"].setText(str(context.pdf_path))
        self._labels["files"].setText(str(len(analysis.files)))
        self._labels["profile"].setText(profile)
        self._labels["health"].setText("OK" if problems == 0 else f"{problems} problema/i rilevato/i")
        self._labels["toolchain"].setText("Verifica in corso…")
        if self._toolchain_worker is None or not self._toolchain_worker.isRunning():
            self._toolchain_worker = _DashboardToolchainWorker(path)
            self._toolchain_worker.completed.connect(self._show_toolchain)
            self._toolchain_worker.finished.connect(self._toolchain_worker.deleteLater)
            self._toolchain_worker.start()
        auxiliary = detect_latex_auxiliary_tools(self._editor.get_content())
        self._labels["auxiliary"].setText(
            ", ".join(auxiliary) if auxiliary else "Nessuno rilevato"
        )

    def _show_toolchain(self, report: dict) -> None:
        available = sum(1 for info in report.values() if info.status == "available")
        self._labels["toolchain"].setText(f"{available}/{len(report)} strumenti rilevati")

    def closeEvent(self, event) -> None:
        if self._toolchain_worker is not None and self._toolchain_worker.isRunning():
            self._toolchain_worker.wait()
        super().closeEvent(event)


__all__ = ["LatexProjectDashboardDialog"]
