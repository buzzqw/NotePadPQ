import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import latex_project
from core.latex_project import (
    LatexProjectContext,
    collect_included_files,
    expected_pdf_path,
    get_output_directory,
    invalidate_cached_text,
    read_cached_text,
    read_cached_text_stripped,
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

    def test_cache_refreshes_after_same_size_file_change(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text("old")

            self.assertEqual(read_cached_text(source), "old")
            first_signature = source.stat().st_mtime_ns
            source.write_text("new")
            os.utime(source, ns=(first_signature, first_signature + 1_000_000))

            self.assertEqual(read_cached_text(source), "new")

    def test_stripped_cache_and_explicit_invalidation_refresh_together(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text("visible % hidden\n")

            self.assertEqual(read_cached_text_stripped(source), "visible \n")
            source.write_text("updated % hidden\n")
            invalidate_cached_text(source)

            self.assertEqual(read_cached_text(source), "updated % hidden\n")
            self.assertEqual(read_cached_text_stripped(source), "updated \n")

    def test_cache_does_not_associate_old_text_with_new_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text("old")
            old_signature = (1, 3, 1)
            new_signature = (2, 3, 2)

            with (
                patch.object(
                    latex_project,
                    "_file_signature",
                    side_effect=[old_signature, old_signature, new_signature,
                                 new_signature, new_signature],
                ),
                patch.object(Path, "read_text", side_effect=["old", "new"]),
            ):
                self.assertEqual(read_cached_text(source), "new")

            with patch.object(latex_project, "_file_signature", return_value=new_signature):
                self.assertEqual(read_cached_text(source), "new")

    def test_invalidation_refreshes_root_fallback_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            current = project / "chapter.tex"
            root = project / "paper.tex"
            current.write_text("chapter")

            self.assertEqual(resolve_project_root(current), current.resolve())
            root.write_text("\\documentclass{article}")
            invalidate_cached_text(root)

            self.assertEqual(resolve_project_root(current), root.resolve())


if __name__ == "__main__":
    unittest.main()
