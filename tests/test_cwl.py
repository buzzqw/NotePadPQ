import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.autocomplete import AutoCompleteManager
from editor.cwl import load_cwl_directories, parse_cwl
from editor.editor_widget import EditorWidget
from editor.latex_support import LaTeXSupport


class CWLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_parser_reads_commands_arguments_descriptions_and_environments(self):
        package = parse_cwl(
            "# package: Demo package\n"
            r"\demo[option]{input}#D{Run the demo}" "\n"
            r"\begin{demoenv}#D{Demo environment}" "\n",
            package="demo",
        )

        command = package.commands[r"\demo"]
        self.assertEqual(package.description, "Demo package")
        self.assertEqual(command.signature, r"\demo[option]{input}")
        self.assertEqual(
            [(argument.name, argument.optional) for argument in command.arguments],
            [("option", True), ("input", False)],
        )
        self.assertEqual(command.completion, r"\demo[]{}")
        self.assertIn("Run the demo", command.as_api_term())
        self.assertEqual(package.environments["demoenv"].name, "demoenv")

    def test_directory_precedence_is_deterministic_and_package_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            built_in = root / "built-in"
            user = root / "user"
            project = root / "project"
            for directory in (built_in, user, project):
                directory.mkdir()
            (built_in / "demo.cwl").write_text(r"\demo{old}")
            (user / "demo.cwl").write_text(r"\demo{user}")
            (project / "demo.cwl").write_text(r"\demo{project}")

            model = load_cwl_directories([built_in, user, project])

            self.assertEqual(model.commands[r"\demo"].signature, r"\demo{project}")
            self.assertEqual(model.packages["demo"].source, (project / "demo.cwl").resolve())

    def test_load_cwl_directories_caches_until_a_file_changes(self):
        # _complete_packages (autocomplete.py) chiama load_cwl_directories in
        # modo sincrono sul thread UI a ogni \usepackage{: senza cache,
        # ogni trigger riparsa da zero tutti i .cwl configurati.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cwl_file = root / "demo.cwl"
            cwl_file.write_text(r"\demo{first}")

            import editor.cwl as cwl_module
            with mock.patch(
                "editor.cwl.parse_cwl_file", wraps=cwl_module.parse_cwl_file
            ) as spy:
                first = load_cwl_directories([root])
                self.assertEqual(first.commands[r"\demo"].signature, r"\demo{first}")
                self.assertEqual(spy.call_count, 1)

                # Stessa directory, nessuna modifica: la seconda chiamata deve
                # riusare il modello cachato senza riparsare da disco.
                second = load_cwl_directories([root])
                self.assertEqual(spy.call_count, 1)
                self.assertIs(second, first)

                # Il file cambia (contenuto + mtime): la cache deve
                # invalidarsi e restituire i dati aggiornati.
                new_mtime = cwl_file.stat().st_mtime + 5
                cwl_file.write_text(r"\demo{second}")
                os.utime(cwl_file, (new_mtime, new_mtime))
                third = load_cwl_directories([root])
                self.assertEqual(third.commands[r"\demo"].signature, r"\demo{second}")
                self.assertEqual(spy.call_count, 2)

    def test_malformed_files_are_ignored_without_losing_lower_precedence_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lower = root / "lower"
            higher = root / "higher"
            lower.mkdir()
            higher.mkdir()
            (lower / "demo.cwl").write_text(r"\demo{input}")
            (higher / "demo.cwl").write_bytes(b"\xff\xfe\x00")
            (higher / "other.cwl").write_text("not a command\n{broken")

            model = load_cwl_directories([lower, higher])

            self.assertEqual(model.commands[r"\demo"].signature, r"\demo{input}")
            self.assertNotIn("other", model.packages)

    def test_latex_support_merges_cwl_commands_and_environments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cwl_dir = root / "cwl"
            cwl_dir.mkdir()
            main = root / "main.tex"
            main.write_text(r"\usepackage{mycwl}")
            (cwl_dir / "mycwl.cwl").write_text(
                r"\mycommand{value}#D{Configured command}" "\n"
                r"\begin{myenvironment}#D{Configured environment}" "\n"
            )

            api = LaTeXSupport.build_dynamic_api("", main)

            self.assertTrue(any(r"\mycommand{}?1" in term for term in api))
            self.assertIn("myenvironment", LaTeXSupport.get_all_environments("", main))

    def test_package_completion_adds_cwl_packages_only_when_data_is_available(self):
        editor = EditorWidget()
        editor.file_path = Path("/tmp/notepadpq-cwl.tex")
        manager = AutoCompleteManager(editor)
        shown = []
        editor.showUserList = lambda list_id, labels: shown.append((list_id, labels))
        model = parse_cwl("# description: Project package\n", package="projectpkg")

        try:
            with mock.patch("editor.latex_support.LaTeXSupport.get_cwl_model", return_value=mock.Mock(
                    package_names=["projectpkg"],
                    packages={"projectpkg": model},
            )):
                manager._complete_packages()
            labels = shown[-1][1]
            self.assertIn("projectpkg  [Project package]", labels)
            self.assertIn("amsmath", labels)
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
