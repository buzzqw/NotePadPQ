"""Recipe manager leggero sopra i profili BuildManager esistenti."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from core.build_manager import BuildManager

_LATEX_EXTENSIONS = {".tex", ".ltx", ".latex"}


class LatexRecipeDialog(QDialog):
    """Seleziona il profilo LaTeX attivo senza sostituire il dialogo completo."""

    def __init__(self, editor=None, edit_profiles=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LaTeX recipes")
        self.setMinimumSize(620, 420)
        self._editor = editor
        self._edit_profiles = edit_profiles
        self._profiles = self._latex_profiles()
        self._build_ui()

    def _latex_profiles(self) -> dict[str, dict]:
        profiles = BuildManager.instance().get_profiles()
        if self._editor is None or self._editor.file_path is None:
            return {
                name: profile for name, profile in profiles.items()
                if _LATEX_EXTENSIONS.intersection(profile.get("extensions", []))
            }
        project = BuildManager.instance().get_project_profiles(self._editor.file_path)
        merged = dict(profiles)
        merged.update(project)
        return {
            name: profile for name, profile in merged.items()
            if _LATEX_EXTENSIONS.intersection(profile.get("extensions", []))
        }

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Profilo/ricetta LaTeX da usare per i file .tex:"))
        self._combo = QComboBox()
        self._combo.addItems(sorted(self._profiles))
        current = ""
        if self._editor is not None and self._editor.file_path:
            current = BuildManager.instance().get_profile_for_file(self._editor.file_path) or ""
        if current:
            index = self._combo.findText(current)
            if index >= 0:
                self._combo.setCurrentIndex(index)
        self._combo.currentTextChanged.connect(self._show_profile)
        layout.addWidget(self._combo)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        layout.addWidget(self._details, 1)
        self._show_profile(self._combo.currentText())

        edit = QPushButton("Modifica profili completi…")
        edit.clicked.connect(self._open_editor)
        layout.addWidget(edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_profile(self, name: str) -> None:
        profile = self._profiles.get(name, {})
        lines = [
            f"Nome: {name}",
            f"Engine: {profile.get('compile', '')}",
            f"Build: {profile.get('build', '')}",
            f"Output: {profile.get('output_directory', profile.get('output_dir', '${OUTDIR}'))}",
        ]
        pipeline = profile.get("pipeline") or []
        if pipeline:
            lines.append("Pipeline:")
            lines.extend(f"  {step.get('name', 'step')}: {step.get('cmd', '')}" for step in pipeline)
        self._details.setPlainText("\n".join(lines))

    def _apply(self) -> None:
        if self._combo.currentText():
            BuildManager.instance().set_profile_override(".tex", self._combo.currentText())
        self.accept()

    def _open_editor(self) -> None:
        if self._edit_profiles is not None:
            self._edit_profiles()


__all__ = ["LatexRecipeDialog"]
