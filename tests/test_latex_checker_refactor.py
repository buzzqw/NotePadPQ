import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from editor.latex_checker import _CheckWorker
from editor.latex_support import LaTeXSupport


class LatexCheckerRefactorTest(unittest.TestCase):
    def test_duplicate_and_unused_labels_ignore_comments_strings_and_similar_names(self):
        text = (
            "% \\label{ignored}\n"
            "\\label{same}\n"
            "\\label{same}\n"
            "\\label{unused}\n"
            "\\ref{same} \\ref{sameish}\n"
            "\\verb|\\label{string} \\ref{string}|\n"
            "\\texttt{\\label{text-string}}\n"
            "\\begin{verbatim}\n\\label{code}\n\\ref{code}\n\\end{verbatim}\n"
        )

        duplicates = LaTeXSupport.find_duplicate_labels(text)
        unused = LaTeXSupport.find_unused_labels(text)

        self.assertEqual([item["key"] for item in duplicates], ["same"])
        self.assertEqual([item["key"] for item in unused], ["unused"])
        self.assertEqual(LaTeXSupport.extract_labels(text), ["same", "unused"])
        self.assertEqual(LaTeXSupport.extract_ref_keys(text), ["same", "sameish"])

    def test_worker_reports_duplicate_unused_and_undefined_labels(self):
        worker = _CheckWorker(
            "\\label{same}\n\\label{same}\n\\label{unused}\n\\ref{missing}",
            None,
            1,
        )

        issues = worker._check_undefined_labels() + worker._check_label_consistency()
        messages = [issue["msg"] for issue in issues]
        self.assertIn("Undefined label: 'missing'", messages)
        self.assertIn("Duplicate label: 'same'", messages)
        self.assertIn("Unused label: 'unused'", messages)

    def test_rename_label_updates_reachable_files_only_and_exact_tokens(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            child = root / "chapter.tex"
            unrelated = root / "unrelated.tex"
            main.write_text(
                "\\input{chapter}\n"
                "\\ref{sec:old} \\ref{sec:oldish}\n"
                "% \\ref{sec:old}\n"
                "\\verb|\\ref{sec:old}|\n",
                encoding="utf-8",
            )
            child.write_text("\\label{sec:old}\n", encoding="utf-8")
            unrelated.write_text("\\label{sec:old}\n\\ref{sec:old}\n", encoding="utf-8")

            changed = LaTeXSupport.rename_label_multifile(
                main, "sec:old", "sec:new",
            )

            self.assertEqual(changed, [main.resolve(), child.resolve()])
            self.assertIn(r"\label{sec:new}", child.read_text(encoding="utf-8"))
            main_text = main.read_text(encoding="utf-8")
            self.assertIn(r"\ref{sec:new}", main_text)
            self.assertIn(r"\ref{sec:oldish}", main_text)
            self.assertIn(r"% \ref{sec:old}", main_text)
            self.assertIn(r"\verb|\ref{sec:old}|", main_text)
            self.assertIn(r"\label{sec:old}", unrelated.read_text(encoding="utf-8"))

    def test_rename_refuses_label_collision_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            child = root / "child.tex"
            main.write_text(r"\input{child}\ref{old}", encoding="utf-8")
            child.write_text(r"\label{old}\label{new}", encoding="utf-8")

            with self.assertRaises(ValueError):
                LaTeXSupport.rename_label_across_files(main, "old", "new")
            self.assertEqual(child.read_text(encoding="utf-8"), r"\label{old}\label{new}")


if __name__ == "__main__":
    unittest.main()
