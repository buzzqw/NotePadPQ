import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.latex_references import analyze_latex_project
from ui.latex_references_panel import LatexReferencesModel, LatexReferencesPanel


class LatexReferencesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scan_resolved_project_and_keep_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            main = project / "main.tex"
            chapter = project / "chapter.tex"
            bib = project / "refs.bib"
            image = project / "figure.png"
            main.write_text(
                r"""\documentclass{article}
\input{chapter}
\addbibresource{refs}
\includegraphics{figure}
\includegraphics{missing-image}
\input{missing}
\ref{sec:chapter} \ref{missing-label} \cite{paper,missing-paper}
\label{duplicate}
"""
            )
            chapter.write_text(
                r"""\section{Chapter}\label{sec:chapter}
\label{duplicate}
\label{never-used}
"""
            )
            bib.write_text("@article{paper, title={Paper}}\n@book{never, title={Never}}")
            image.write_bytes(b"image")

            result = analyze_latex_project(main)

            self.assertEqual(result.root, main.resolve())
            self.assertEqual(result.files, (main.resolve(), chapter.resolve()))
            self.assertEqual({item.key for item in result.definitions},
                             {"sec:chapter", "duplicate", "never-used"})
            self.assertEqual([item.key for item in result.undefined], ["missing-label"])
            self.assertEqual([item.key for item in result.duplicates], ["duplicate"])
            self.assertEqual([item.key for item in result.unused], ["duplicate", "never-used"])
            self.assertEqual([item.key for item in result.citations],
                             ["paper", "missing-paper"])
            self.assertEqual([item.key for item in result.undefined_citations], ["missing-paper"])
            self.assertEqual(result.bibliography_files, (bib.resolve(),))
            self.assertEqual(result.missing_includes[0].requested, "missing")
            self.assertEqual(result.missing_assets[0].requested, "missing-image")
            self.assertEqual(result.definitions[0].line, 8)
            self.assertEqual([(item.kind, item.title) for item in result.sections],
                             [("section", "Chapter")])

    def test_unsaved_current_text_is_used_for_project_root_file(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / "main.tex"
            main.write_text(r"\documentclass{article}\label{old}")
            result = analyze_latex_project(main, r"\documentclass{article}\label{new}")
            self.assertEqual([item.key for item in result.definitions], ["new"])

    def test_sections_use_short_title_when_present(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / "main.tex"
            main.write_text(r"\section[Short title]{Long title}")

            result = analyze_latex_project(main)

            self.assertEqual([(item.kind, item.title) for item in result.sections],
                             [("section", "Short title")])

    def test_model_and_panel_have_standalone_navigation_api(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / "main.tex"
            main.write_text(r"\documentclass{article}\label{target}")
            model = LatexReferencesModel()
            model.set_project(main)
            result = model.refresh()
            self.assertEqual(result.definitions[0].key, "target")

            navigated = []
            panel = LatexReferencesPanel(
                navigation_target=lambda path, line, column: navigated.append(
                    (path, line, column),
                ),
            )
            panel.set_project(main, asynchronous=False)
            panel._tree.itemDoubleClicked.emit(panel._tree.topLevelItem(0), 0)
            self.assertEqual(navigated[0][0], main.resolve())
            self.assertEqual(navigated[0][1:], (1, 30))
            panel.close()
            model.close()


if __name__ == "__main__":
    unittest.main()
