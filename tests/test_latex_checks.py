"""Tests for the shared, Qt-free LaTeX checks (core.latex_checks).

These pin the behaviour that used to live in ``_CheckWorker`` and in
``LaTeXSupport.check_environment_balance`` so the consolidation cannot drift.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.latex_checks import (
    count_row_cols,
    count_tabular_cols,
    environment_balance,
    format_balance_issue,
    tabular_column_issues,
    tikz_semicolon_issues,
)
from core.latex_index import get_latex_index, invalidate_latex_index
from editor.latex_checker import _CheckWorker
from editor.latex_support import LaTeXSupport


class EnvironmentBalanceTest(unittest.TestCase):
    def test_mismatch_does_not_pop_and_reports_both_sides(self):
        issues = environment_balance(r"\begin{a} \begin{b} \end{a} \end{b}")
        self.assertEqual([i.kind for i in issues], ["mismatch", "unclosed"])
        self.assertEqual(issues[0].environment, "a")
        self.assertEqual(issues[0].open_environment, "b")
        self.assertEqual(issues[1].environment, "a")

    def test_unmatched_end_and_no_match_reports(self):
        issues = environment_balance(r"\end{only}")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "unmatched_end")

    def test_format_matches_support_wording(self):
        issues = environment_balance(r"\begin{a} \begin{b} \end{a} \end{b}")
        first = format_balance_issue(issues[0], line=0, open_line=0)
        second = format_balance_issue(issues[1], line=0)
        self.assertIn("closes 'b'", first["msg"])
        self.assertIn("opened at line 1", first["msg"])
        self.assertIn("a} not closed", second["msg"])


class BalanceConsolidationTest(unittest.TestCase):
    def tearDown(self):
        invalidate_latex_index()

    def test_index_and_support_agree_on_balance(self):
        text = r"\begin{a} \begin{b} \end{a} \end{b}"
        index = get_latex_index(text, None, include_project=False)
        index_issues = [dict(i) for i in index.balance_issues]
        support_issues = LaTeXSupport.check_environment_balance(text)
        support_issues = [
            {k: v for k, v in d.items() if k in ("line", "env", "msg")}
            for d in support_issues
        ]
        self.assertEqual(
            [i["msg"] for i in index_issues],
            [i["msg"] for i in support_issues],
        )
        self.assertEqual(
            [i["env"] for i in index_issues],
            [i["env"] for i in support_issues],
        )

    def test_worker_indexed_path_reuses_the_index_snapshot(self):
        text = r"\begin{a} \begin{b} \end{a} \end{b}"
        index = get_latex_index(text, None, include_project=False)
        worker = _CheckWorker(text, None, 1, include_project=False)
        worker._index = index
        self.assertEqual(
            worker._check_balance(),
            [dict(i) for i in index.balance_issues],
        )

    def test_worker_fallback_path_scans_without_index(self):
        worker = _CheckWorker(
            r"\begin{a} \begin{b} \end{a} \end{b}", None, 1, include_project=False,
        )
        worker._index = None
        issues = worker._check_balance()
        self.assertEqual(len(issues), 2)
        self.assertIn("closes 'b'", issues[0]["msg"])


class TabularAndTikzTest(unittest.TestCase):
    def test_pure_helpers_are_reachable_through_worker_aliases(self):
        self.assertEqual(_CheckWorker._count_row_cols(r"a \& b & c"), 2)
        self.assertEqual(count_row_cols(r"a \& b & c"), 2)
        self.assertEqual(count_tabular_cols(r"*{2}{c}"), 2)

    def test_tabular_column_issues_is_pure(self):
        text = "\\begin{tabular}{ll}\na & b & c\n\\end{tabular}"
        issues = tabular_column_issues(text)
        self.assertTrue(any("Colonne" in issue["msg"] for issue in issues))

    def test_tblr_colspec_is_checked(self):
        text = (
            "\\begin{tblr}{colspec={ll}}\n"
            "a & b \\\\\n"
            "c & d & e \\\\\n"
            "\\end{tblr}"
        )
        issues = tabular_column_issues(text)
        self.assertTrue(any("3 nella riga" in issue["msg"] for issue in issues))

    def test_longtblr_caption_does_not_break_colspec(self):
        text = (
            "\\begin{longtblr}[caption={A {nested} caption}]{colspec={lcr}, hlines}\n"
            "a & b & c \\\\\n"
            "d & e \\\\\n"
            "\\end{longtblr}"
        )
        issues = tabular_column_issues(text)
        self.assertTrue(any("2 nella riga" in issue["msg"] for issue in issues))
        self.assertTrue(all("lcr" in issue["msg"] for issue in issues
                            if "colspec" in issue["msg"]))

    def test_tblr_without_colspec_is_ignored(self):
        text = "\\begin{tblr}\na & b \\\\\n\\end{tblr}"
        self.assertEqual(tabular_column_issues(text), [])

    def test_tblr_x_column_options_are_not_counted_as_columns(self):
        self.assertEqual(count_tabular_cols("|l|X[c]|X[2,m]|"), 3)

    def test_tikz_semicolon_issues_is_pure(self):
        text = "\\begin{tikzpicture}\n\\draw (0,0) -- (1,1)\n\\end{tikzpicture}"
        issues = tikz_semicolon_issues(text)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["line"], 1)


if __name__ == "__main__":
    unittest.main()
