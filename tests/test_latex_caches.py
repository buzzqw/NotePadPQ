"""Tests for the encapsulated LaTeX caches (P5)."""

import tempfile
import unittest
from pathlib import Path

from core.latex_index import (
    LatexAnalysisCache,
    get_latex_index,
    invalidate_latex_index,
)
from core.latex_project import LatexSourceCache


class SourceCacheTest(unittest.TestCase):
    def test_instances_are_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text("body % note\n")
            first = LatexSourceCache()
            second = LatexSourceCache()

            self.assertEqual(first.read_stripped(source), "body \n")
            # A different instance must not have inherited the first one's data.
            self.assertEqual(second.read(source), "body % note\n")
            first.invalidate(source)
            self.assertEqual(second.read(source), "body % note\n")

    def test_clear_drops_everything(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.tex"
            source.write_text("x")
            cache = LatexSourceCache()
            self.assertEqual(cache.read(source), "x")
            cache.clear()
            self.assertEqual(cache.read(source), "x")


class AnalysisCacheTest(unittest.TestCase):
    def tearDown(self):
        invalidate_latex_index()

    def test_lru_evicts_oldest(self):
        cache = LatexAnalysisCache(max_indexes=2)
        cache.put_index(("a",), object())
        cache.put_index(("b",), object())
        cache.put_index(("c",), object())
        self.assertIsNone(cache.get_index(("a",)))
        self.assertIsNotNone(cache.get_index(("b",)))
        self.assertIsNotNone(cache.get_index(("c",)))

    def test_invalidate_by_path_drops_matching_index(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "main.tex"
            path.write_text("\\documentclass{article}\n", encoding="utf-8")
            index = get_latex_index(path.read_text(encoding="utf-8"), path)
            invalidate_latex_index(path)
            refreshed = get_latex_index(path.read_text(encoding="utf-8"), path)
            self.assertIsNot(index, refreshed)


if __name__ == "__main__":
    unittest.main()
