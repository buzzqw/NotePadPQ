import tempfile
import unittest
from pathlib import Path

from core.latex_index import get_latex_index, invalidate_latex_index


class LatexIndexTest(unittest.TestCase):
    def tearDown(self):
        invalidate_latex_index()

    def test_snapshot_is_reused_only_for_the_same_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "main.tex"
            path.write_text("\\documentclass{article}\n\\section{One}\n", encoding="utf-8")
            first_text = path.read_text(encoding="utf-8")

            first = get_latex_index(first_text, path, include_project=False)
            same = get_latex_index(first_text, path, include_project=False)
            changed_text = first_text + "\\section{Two}\n"
            changed = get_latex_index(changed_text, path, include_project=False)

            self.assertIs(first, same)
            self.assertIsNot(first, changed)
            self.assertEqual([item["name"] for item in changed.sections], ["One", "Two"])

    def test_comment_mask_keeps_editor_offsets_and_project_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = root / "chapter.tex"
            bib = root / "refs.bib"
            main = root / "main.tex"
            child.write_text("\\section{Child}\n\\label{child}\n", encoding="utf-8")
            bib.write_text("@book{known, title={Known}}\n", encoding="utf-8")
            text = (
                "\\documentclass{article}\n"
                "\\input{chapter}\n"
                "\\bibliography{refs}\n"
                "% \\label{ignored}\n"
                "\\ref{child}\n"
            )
            main.write_text(text, encoding="utf-8")

            index = get_latex_index(text, main)
            labels = {item["key"] for item in index.definitions}
            references = {item["key"] for item in index.references}

            self.assertIn("child", labels)
            self.assertNotIn("ignored", labels)
            self.assertIn("child", references)
            self.assertIn("known", index.bibtex_keys)


if __name__ == "__main__":
    unittest.main()
