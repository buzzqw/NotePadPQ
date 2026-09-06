import tempfile
import unittest
from pathlib import Path
from unittest import mock

from editor.synctex import SyncTeX


class SyncTeXTest(unittest.TestCase):
    def setUp(self):
        self._previous_cache = SyncTeX._available_cached
        SyncTeX._available_cached = None

    def tearDown(self):
        SyncTeX._available_cached = self._previous_cache

    def test_availability_is_cached(self):
        with mock.patch(
            "editor.synctex.subprocess.run",
            return_value=mock.Mock(returncode=0),
        ) as run:
            self.assertTrue(SyncTeX.is_available())
            self.assertTrue(SyncTeX.is_available())

        run.assert_called_once_with(
            ["synctex", "help"], capture_output=True, timeout=3
        )

    def test_availability_rejects_a_nonzero_exit_code(self):
        with mock.patch(
            "editor.synctex.subprocess.run",
            return_value=mock.Mock(returncode=1),
        ):
            self.assertFalse(SyncTeX.is_available())

    def test_availability_handles_os_errors(self):
        with mock.patch(
            "editor.synctex.subprocess.run", side_effect=PermissionError
        ):
            self.assertFalse(SyncTeX.is_available())

    def test_parsers_normalize_relative_input_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tex = root / "main.tex"
            pdf = root / "main.pdf"
            sync = SyncTeX(tex, pdf)

            view = sync._parse_view(
                "SyncTeX result begin\n"
                "Page: 2\n"
                "x: 101.5\n"
                "y: 202.5\n"
                "h: 10\n"
                "SyncTeX result end\n"
            )
            edit = sync._parse_edit(
                "SyncTeX result begin\n"
                "Input: ./chapter.tex\n"
                "Line: 12\n"
                "SyncTeX result end\n"
            )

            self.assertEqual(view["page"], 2)
            self.assertEqual(view["x"], 101.5)
            self.assertEqual(view["y"], 202.5)
            self.assertEqual(edit, {"file": str(root / "chapter.tex"), "line": 12})

    def test_tex_to_pdf_passes_the_requested_column(self):
        sync = SyncTeX(Path("/tmp/main.tex"), Path("/tmp/main.pdf"))
        output = "SyncTeX result begin\nPage: 1\nx: 10\ny: 20\n"
        with mock.patch.object(sync, "has_synctex_file", return_value=True), mock.patch(
            "editor.synctex.subprocess.run",
            return_value=mock.Mock(stdout=output),
        ) as run:
            result = sync.tex_to_pdf(line=8, col=14)

        self.assertEqual(result["page"], 1)
        self.assertEqual(
            run.call_args.args[0],
            [
                "synctex", "view", "-i", "8:14:/tmp/main.tex",
                "-o", "/tmp/main.pdf",
            ],
        )

    def test_has_synctex_file_checks_compressed_and_plain_variants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tex = root / "main.tex"
            pdf = root / "main.pdf"
            pdf.write_bytes(b"")
            sync = SyncTeX(tex, pdf)

            self.assertFalse(sync.has_synctex_file())
            (root / "main.synctex.gz").write_bytes(b"")
            self.assertTrue(sync.has_synctex_file())


if __name__ == "__main__":
    unittest.main()
