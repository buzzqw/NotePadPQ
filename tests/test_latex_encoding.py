"""Tests for LaTeX source encoding detection (P7)."""

import tempfile
import unittest
from pathlib import Path

from core.latex_project import (
    detect_source_encoding,
    invalidate_cached_text,
    read_cached_text,
)


class EncodingDetectionTest(unittest.TestCase):
    def _write(self, name, data):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / name
        path.write_bytes(data)
        return path

    def test_default_is_utf8(self):
        path = self._write("a.tex", "caffè\n".encode())
        self.assertEqual(detect_source_encoding(path), "utf-8")
        self.assertEqual(read_cached_text(path), "caffè\n")

    def test_tex_encoding_marker_is_respected(self):
        path = self._write(
            "latin.tex", b"% !TeX encoding = latin1\ncaf\xe9\n")
        invalidate_cached_text(path)
        self.assertEqual(detect_source_encoding(path), "latin-1")
        self.assertEqual(read_cached_text(path), "% !TeX encoding = latin1\ncafé\n")

    def test_emacs_coding_marker(self):
        path = self._write("emacs.tex", b"%-*- coding: latin-1 -*-\ncaf\xe9\n")
        self.assertEqual(detect_source_encoding(path), "latin-1")

    def test_utf8_bom(self):
        path = self._write("bom.tex", b"\xef\xbb\xbfbody\n")
        self.assertEqual(detect_source_encoding(path), "utf-8-sig")
        self.assertEqual(read_cached_text(path), "body\n")


if __name__ == "__main__":
    unittest.main()
