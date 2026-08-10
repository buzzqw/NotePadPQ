import tempfile
import unittest
from datetime import date
from pathlib import Path

from core.latex_templates import LatexTemplateCatalog, normalize_template_name


class LatexTemplatesTest(unittest.TestCase):
    def test_builtins_are_available_and_variables_are_rendered(self):
        catalog = LatexTemplateCatalog(user_dir=Path(tempfile.gettempdir()) / "missing-notepadpq")

        self.assertIn("article", catalog.list_templates())
        rendered = catalog.render(
            "article",
            {"title": "Titolo à", "author": "Ada", "date": "2026-08-10", "language": "italian"},
        )

        self.assertIn(r"\title{Titolo à}", rendered)
        self.assertIn(r"\author{Ada}", rendered)
        self.assertIn(r"\date{2026-08-10}", rendered)
        self.assertNotIn("{{language}}", rendered)
        self.assertIn("italian", rendered)

    def test_project_latex_directory_overrides_user_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            user = root / "user"
            project = root / "project"
            (user / ".notepadpq" / "templates").mkdir(parents=True)
            (project / ".notepadpq" / "templates" / "latex").mkdir(parents=True)
            (user / ".notepadpq" / "templates" / "custom.tex").write_text(
                "utente {{title}}", encoding="utf-8"
            )
            (user / ".notepadpq" / "templates" / "shared.tex").write_text(
                "utente", encoding="utf-8"
            )
            (project / ".notepadpq" / "templates" / "latex" / "shared.tex").write_text(
                "progetto {{title}}", encoding="utf-8"
            )

            catalog = LatexTemplateCatalog(project_dir=project, user_dir=user)

            self.assertEqual(catalog.load("custom"), "utente {{title}}")
            self.assertEqual(catalog.render("shared", title="Documento"), "progetto Documento")

    def test_utf8_errors_and_missing_names_use_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            templates = root / ".notepadpq" / "templates"
            templates.mkdir(parents=True)
            (templates / "unicode.tex").write_text("città {{title}}", encoding="utf-8")
            (templates / "broken.tex").write_bytes(b"\xff\xfe")
            catalog = LatexTemplateCatalog(project_dir=root, user_dir=root / "missing-user")

            self.assertEqual(catalog.render("unicode", title="à"), "città à")
            self.assertEqual(catalog.load("broken"), catalog.load("article"))
            self.assertEqual(catalog.load("../article"), catalog.load("article"))

    def test_unknown_variables_are_preserved_and_defaults_are_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            templates = root / ".notepadpq" / "templates"
            templates.mkdir(parents=True)
            (templates / "plain.tex").write_text(
                "{{title}} {{unknown}} {{date}}", encoding="utf-8"
            )
            catalog = LatexTemplateCatalog(project_dir=root, user_dir=root / "missing-user")

            rendered = catalog.render("plain", title="X")

            self.assertEqual(rendered, f"X {{{{unknown}}}} {date.today().isoformat()}")

    def test_template_names_reject_paths_and_unsafe_files(self):
        self.assertEqual(normalize_template_name("article.tex"), "article")
        self.assertEqual(normalize_template_name("my-template"), "my-template")
        for name in ("", ".", "..", "../secret", "a/b", "/tmp/template", "bad name"):
            self.assertIsNone(normalize_template_name(name))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            templates = root / ".notepadpq" / "templates"
            templates.mkdir(parents=True)
            (templates / "not safe.tex").write_text("unsafe", encoding="utf-8")
            catalog = LatexTemplateCatalog(project_dir=root, user_dir=root / "missing-user")

            self.assertNotIn("not safe", catalog.list_templates())

    def test_nested_file_finds_project_template_in_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            nested = project / "src" / "chapters"
            (project / ".notepadpq" / "templates").mkdir(parents=True)
            nested.mkdir(parents=True)
            (project / ".notepadpq" / "templates" / "article.tex").write_text(
                "project template", encoding="utf-8")

            catalog = LatexTemplateCatalog(project_dir=nested,
                                           user_dir=project / "missing-user")
            self.assertEqual(catalog.load("article"), "project template")


if __name__ == "__main__":
    unittest.main()
