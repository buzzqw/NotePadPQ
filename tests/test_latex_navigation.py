import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from editor.editor_widget import EditorWidget, extract_latex_citation_occurrences
from ui.latex_citation_dialog import (
    LatexCitationChooserDialog,
    project_bibtex_keys,
)
from ui.latex_menu import LatexMenuManager


class _Editor:
    def __init__(self, text: str, path: Path | None = None):
        self._text = text
        self.file_path = path

    def text(self):
        return self._text


class LatexNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_citation_parser_preserves_offsets_and_skips_comments(self):
        text = (
            r"\citep[see][p. 2]{ first,second } "
            r"% \cite{ignored}" + "\n" +
            r"\\cite{escaped} \texttt{\cite{opaque}} \textcite*{third}"
        )

        occurrences = extract_latex_citation_occurrences(text)

        self.assertEqual([item["key"] for item in occurrences],
                         ["first", "second", "third"])
        for item in occurrences:
            self.assertEqual(text[item["start"]:item["end"]], item["key"])
        self.assertNotIn("ignored", [item["key"] for item in occurrences])

    def test_project_keys_include_included_tex_and_unsaved_current_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            child = root / "child.tex"
            bib = root / "refs.bib"
            main.write_text(r"\input{child}\addbibresource{refs.bib}")
            child.write_text(r"\cite{saved}")
            bib.write_text("@article{saved, title={Saved}}")

            editor = _Editor(r"@misc{unsaved, title={In memory}}", main)
            self.assertEqual(
                project_bibtex_keys(editor), ["saved", "unsaved"]
            )

    def test_chooser_filters_and_accepts_selected_key(self):
        dialog = LatexCitationChooserDialog(["Zeta", "Alpha", "beta"])
        dialog._search.setText("be")

        self.assertEqual(dialog._list.count(), 1)
        self.assertEqual(dialog._list.item(0).text(), "beta")

        dialog._accept_selected()
        self.assertEqual(dialog.selected_key, "beta")
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_editor_resolves_labels_across_files_and_citations_to_bib(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            child = root / "chapter.tex"
            bib = root / "refs.bib"
            source = r"\input{chapter}\addbibresource{refs.bib}" + "\n" + r"\ref{sec:chapter} \citep{paper}"
            main.write_text(source)
            child.write_text(r"\section{Chapter}\label{sec:chapter}")
            bib.write_text("@article{paper, title={Paper}}")

            editor = EditorWidget()
            editor.file_path = main
            editor._current_language = "LaTeX"
            editor.load_content(source)

            reference = editor._latex_semantic_at_position(source.index("sec:chapter"))
            citation = editor._latex_semantic_at_position(source.index("paper"))
            ref_info = editor._latex_semantic_info(reference)
            cite_info = editor._latex_semantic_info(citation)

            self.assertEqual(reference["kind"], "reference")
            self.assertEqual(ref_info[0], child.resolve())
            self.assertEqual(citation["kind"], "citation")
            self.assertEqual(cite_info[0], bib.resolve())
            editor.deleteLater()

    def test_menu_citation_insertion_reuses_editor_partial_argument_path(self):
        editor = EditorWidget()
        editor.load_content(r"\cite{pa}")
        editor.setCursorPosition(0, len(r"\cite{pa"))
        manager = object.__new__(LatexMenuManager)
        manager._mw = SimpleNamespace(
            _tab_manager=SimpleNamespace(current_editor=lambda: editor)
        )

        manager._insert_citation_key("paper")

        self.assertEqual(editor.text(), r"\cite{paper}")
        editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
