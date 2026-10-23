"""Dashboard non invasivo per il progetto LaTeX corrente."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from core.latex_external_tools import detect_latex_auxiliary_tools
from core.latex_project import LatexProjectContext
from core.latex_references import analyze_latex_project
from core.latex_toolchain import detect_latex_toolchain

# I worker di analisi possono sopravvivere alla chiusura della finestra: li
# teniamo referenziati finché non terminano, altrimenti un QThread ancora in
# esecuzione verrebbe distrutto con il dialog.
_ACTIVE_ANALYSIS_WORKERS: set = set()


class _DashboardToolchainWorker(QThread):
    completed = pyqtSignal(object)

    def __init__(self, project_path: Path) -> None:
        super().__init__()
        self._project_path = project_path

    def run(self) -> None:
        self.completed.emit(
            detect_latex_toolchain(context=str(self._project_path), refresh=False)
        )


class _DashboardAnalysisWorker(QThread):
    """Analizza il progetto fuori dal thread GUI.

    ``analyze_latex_project`` legge tutti i file inclusi e può richiedere
    secondi su progetti grandi; eseguirlo in ``refresh()`` congelava la
    finestra all'apertura della dashboard.
    """

    completed = pyqtSignal(object)

    def __init__(self, path: Path, content: str) -> None:
        super().__init__()
        self._path = path
        self._content = content

    def run(self) -> None:
        try:
            context = LatexProjectContext(self._path, self._content)
            analysis = analyze_latex_project(self._path, self._content)
            auxiliary = detect_latex_auxiliary_tools(self._content)
            self.completed.emit((context, analysis, auxiliary))
        except Exception:
            self.completed.emit(None)


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
        self._analysis_worker: _DashboardAnalysisWorker | None = None
        self._analysis_pending: tuple[Path, str] | None = None
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
        content = self._editor.text()
        if self._analysis_worker is not None and self._analysis_worker.isRunning():
            # Una nuova richiesta durante l'analisi: eseguila appena termina.
            self._analysis_pending = (path, content)
            self._labels["health"].setText("Analisi in corso…")
            return
        self._analysis_pending = None
        self._labels["health"].setText("Analisi in corso…")
        self._analysis_worker = _DashboardAnalysisWorker(path, content)
        self._analysis_worker.completed.connect(self._on_analysis_done)
        self._analysis_worker.finished.connect(self._analysis_worker.deleteLater)
        self._analysis_worker.finished.connect(self._analysis_worker_finished)
        _ACTIVE_ANALYSIS_WORKERS.add(self._analysis_worker)
        self._analysis_worker.finished.connect(
            lambda w=self._analysis_worker: _ACTIVE_ANALYSIS_WORKERS.discard(w)
        )
        self._analysis_worker.start()

    def _analysis_worker_finished(self) -> None:
        self._analysis_worker = None
        pending = self._analysis_pending
        self._analysis_pending = None
        if pending is not None:
            self.refresh()

    def _on_analysis_done(self, result) -> None:
        if result is None:
            self._labels["health"].setText("Analisi non riuscita")
            return
        context, analysis, auxiliary = result
        profile = "-"
        try:
            from core.build_manager import BuildManager
            profile = BuildManager.instance().get_profile_for_file(
                context.current_file) or "-"
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
        self._labels["health"].setText(
            "OK" if problems == 0 else f"{problems} problema/i rilevato/i")
        self._labels["auxiliary"].setText(
            ", ".join(auxiliary) if auxiliary else "Nessuno rilevato"
        )
        self._labels["toolchain"].setText("Verifica in corso…")
        if self._toolchain_worker is None or not self._toolchain_worker.isRunning():
            self._toolchain_worker = _DashboardToolchainWorker(context.current_file)
            self._toolchain_worker.completed.connect(self._show_toolchain)
            self._toolchain_worker.finished.connect(
                self._toolchain_worker.deleteLater)
            self._toolchain_worker.finished.connect(
                self._toolchain_worker_finished)
            self._toolchain_worker.start()

    def _toolchain_worker_finished(self) -> None:
        self._toolchain_worker = None

    def _show_toolchain(self, report: dict) -> None:
        available = sum(1 for info in report.values() if info.status == "available")
        self._labels["toolchain"].setText(f"{available}/{len(report)} strumenti rilevati")

    def closeEvent(self, event) -> None:
        worker = self._analysis_worker
        if worker is not None:
            # Non bloccare la chiusura su un'analisi lunga: sgancia le
            # callback e lascia che il worker termini in background.
            for signal, slot in (
                    (worker.completed, self._on_analysis_done),
                    (worker.finished, self._analysis_worker_finished)):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self._analysis_worker = None
        if self._toolchain_worker is not None:
            try:
                if self._toolchain_worker.isRunning():
                    self._toolchain_worker.wait()
            except RuntimeError:
                # Il wrapper C++ è già stato eliminato da deleteLater.
                pass
        super().closeEvent(event)


__all__ = ["LatexProjectDashboardDialog"]
