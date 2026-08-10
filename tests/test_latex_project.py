import tempfile
import unittest
from pathlib import Path

from core.latex_project import (
    LatexProjectContext,
    collect_included_files,
    expected_pdf_path,
    get_output_directory,
    resolve_project_root,
    resolve_relative_path,
)


class TestLatexProject(unittest.TestCase):
    def test_root_marker_and_nested_includes(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "chapters").mkdir()
            main = project / "main.tex"
            chapter = project / "chapters" / "chapter.tex"
            section = project / "chapters" / "section.tex"
            main.write_text(r"\documentclass{article}\input{chapters/chapter}")
            chapter.write_text(r"\input{section}")
            section.write_text("Section")

            current = "% !TEX root = ../main.tex\n\\section{Chapter}"
            self.assertEqual(resolve_project_root(chapter, current), main.resolve())
            self.assertEqual(
                resolve_relative_path(chapter.parent, "../main.tex"), main.resolve()
            )
            self.assertEqual(
                collect_included_files(main),
                [main.resolve(), chapter.resolve(), section.resolve()],
            )

    def test_root_falls_back_to_main_file(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            main = project / "main.tex"
            chapter = project / "chapter.tex"
            main.write_text("% root selected by name\n")
            chapter.write_text("\\section{Chapter}")

            self.assertEqual(resolve_project_root(chapter), main.resolve())

    def test_root_falls_back_to_documentclass(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "paper.tex"
            source.write_text("\\documentclass{article}\n\\begin{document}")

            self.assertEqual(resolve_project_root(source), source.resolve())

    def test_latexmkrc_can_declare_root_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            main = project / "thesis.tex"
            chapter = project / "chapters" / "one.tex"
            chapter.parent.mkdir()
            main.write_text(r"\documentclass{report}")
            chapter.write_text("chapter")
            (project / ".latexmkrc").write_text(
                "$root_filename = 'thesis.tex';\n")
            self.assertEqual(resolve_project_root(chapter), main.resolve())

    def test_context_uses_relative_and_absolute_output_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            main = project / "main.tex"
            main.write_text("\\documentclass{article}")
            context = LatexProjectContext(main, output_dir=Path("build"))

            self.assertEqual(context.root, main.resolve())
            self.assertEqual(context.output_directory, (project / "build").resolve())
            self.assertEqual(context.pdf_path, (project / "build" / "main.pdf").resolve())
            self.assertEqual(
                get_output_directory(main, project / "artifacts"),
                (project / "artifacts").resolve(),
            )
            self.assertEqual(
                expected_pdf_path(main, "artifacts"),
                (project / "artifacts" / "main.pdf").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
