import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from editor.synctex import SyncTeX


@unittest.skipUnless(
    shutil.which("latexmk") and shutil.which("pdflatex") and shutil.which("synctex"),
    "latexmk, pdflatex and synctex are required",
)
class LatexIntegrationTest(unittest.TestCase):
    def test_latexmk_generates_pdf_and_bidirectional_synctex(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            output = root / "build"
            main.write_text(
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "SyncTeX integration test.\n"
                "\\end{document}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "latexmk", "-pdf", "-interaction=nonstopmode",
                    "-halt-on-error", "-synctex=1", f"-outdir={output}",
                    str(main),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            pdf = output / "main.pdf"
            self.assertTrue(pdf.exists())

            synctex = SyncTeX(main, pdf)
            self.assertTrue(synctex.has_synctex_file())
            forward = synctex.tex_to_pdf(line=3, col=1)
            self.assertIsNotNone(forward)
            self.assertIn("page", forward)
            self.assertIn("x", forward)
            self.assertIn("y", forward)

            backward = synctex.pdf_to_tex(
                forward["page"], forward["x"], forward["y"]
            )
            self.assertIsNotNone(backward)
            self.assertEqual(Path(backward["file"]).resolve(), main.resolve())
            self.assertGreaterEqual(backward["line"], 3)


if __name__ == "__main__":
    unittest.main()
