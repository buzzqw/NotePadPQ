import tempfile
import unittest
from pathlib import Path

from ui.function_list import _LaTeXParser, _MultiFileParser


class FunctionListMultifileTest(unittest.TestCase):
    def test_parser_keeps_source_file_for_included_symbols(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            child = root / "chapter.tex"
            parser = _MultiFileParser(_LaTeXParser(), [
                (main, r"\section{Main}"),
                (child, r"\section{Chapter}"),
            ])

            symbols = parser.parse("")

            self.assertEqual([symbol.name for symbol in symbols], ["Main", "Chapter"])
            self.assertEqual(symbols[1].file_path, child)


if __name__ == "__main__":
    unittest.main()
