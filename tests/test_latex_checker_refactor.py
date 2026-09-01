import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from editor.latex_checker import (
    _LIVE_CHECK_MAX_BYTES,
    _ORPHANED_WORKERS,
    _CheckWorker,
    LaTeXChecker,
    wait_for_orphaned_workers,
)
from editor.latex_support import LaTeXSupport


class LatexCheckerRefactorTest(unittest.TestCase):
    def test_large_documents_do_not_start_live_checker_on_each_edit(self):
        checker = LaTeXChecker.__new__(LaTeXChecker)
        checker._enabled = True
        checker._editor = mock.Mock()
        checker._editor.length.return_value = _LIVE_CHECK_MAX_BYTES + 1
        checker._timer = mock.Mock()

        checker._on_text_changed()

        checker._timer.start.assert_not_called()

    def test_orphaned_workers_are_waited_before_shutdown(self):
        class Worker:
            def __init__(self):
                self.cancelled = False
                self.waited = False
                self.deleted = False

            def cancel(self):
                self.cancelled = True

            def wait(self):
                self.waited = True

            def deleteLater(self):
                self.deleted = True

        worker = Worker()
        _ORPHANED_WORKERS.add(worker)
        try:
            wait_for_orphaned_workers()
            self.assertTrue(worker.cancelled)
            self.assertTrue(worker.waited)
            self.assertTrue(worker.deleted)
            self.assertNotIn(worker, _ORPHANED_WORKERS)
        finally:
            _ORPHANED_WORKERS.discard(worker)

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

    def test_worker_reuses_label_analysis_between_checks(self):
        worker = _CheckWorker("\\label{same}\n\\ref{missing}", None, 1)

        with mock.patch.object(
                LaTeXSupport, "analyze_label_references",
                wraps=LaTeXSupport.analyze_label_references) as analysis:
            worker._check_undefined_labels()
            worker._check_label_consistency()

        analysis.assert_called_once()

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

    def test_tikz_commands_require_terminating_semicolon(self):
        text = r"""\begin{tikzpicture}
\draw (0,0) -- (1,1)
\node at (0,0) {ok};
\end{tikzpicture}"""

        issues = _CheckWorker._check_tikz_semicolons_single(text)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["line"], 1)

    def test_tikz_commands_outside_environment_are_ignored(self):
        issues = _CheckWorker._check_tikz_semicolons_single(
            r"\draw (0,0) -- (1,1)",
        )
        self.assertEqual(issues, [])

    def test_foreach_control_command_does_not_require_semicolon(self):
        text = r"""\begin{tikzpicture}
\foreach \x in {1,2} {\draw (0,0) -- (\x,1);}
\end{tikzpicture}"""

        self.assertEqual(_CheckWorker._check_tikz_semicolons_single(text), [])


if __name__ == "__main__":
    unittest.main()
