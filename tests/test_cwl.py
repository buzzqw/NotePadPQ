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

    def test_optional_cwl_arguments_expose_key_value_hints(self):
        from editor.cwl import CWLModel

        package = parse_cwl(r"\custom[width][mode]{value}", package="custom")
        model = CWLModel(
            packages={"custom": package},
            commands=package.commands,
        )

        self.assertEqual(model.option_candidates_for(r"\custom", ["custom"]),
                         ["mode=", "width="])

    def test_package_queries_keep_supporting_manually_constructed_models(self):
        from editor.cwl import CWLModel

        package = parse_cwl(
            r"\custom{value}" "\n" r"\begin{customenv}" "\n",
            package="custom",
        )
        model = CWLModel(commands=package.commands)

        self.assertEqual(
            [command.name for command in model.commands_for(["custom"])],
            [r"\custom"],
        )
        environment_model = CWLModel(environments=package.environments)
        self.assertEqual(
            [environment.name for environment in environment_model.environments_for(["custom"])],
            ["customenv"],
        )

    def test_keyvals_blocks_expose_flags_values_and_typed_options(self):
        package = parse_cwl(
            "#keyvals:\\rotatebox\n"
            "origin=\n"
            "units=%<number%>\n"
            "direction#left,right\n"
            "draft\n"
            "#endkeyvals\n"
            r"\rotatebox[options]{angle}{content}",
            package="graphicx",
        )
        from editor.cwl import CWLModel
        model = CWLModel(packages={"graphicx": package}, commands=package.commands)

        self.assertEqual(
            model.option_candidates_for(r"\rotatebox", ["graphicx"]),
            ["direction=left", "direction=right", "draft", "origin=", "units="],
        )

    def test_cwl_metadata_and_non_brace_arguments_are_parsed(self):
        package = parse_cwl(
            r"\sqrt{arg}#m" "\n"
            r"\line(xslope,yslope){length}#*/picture" "\n"
            r"\alt<overlay spec>{a}{b}" "\n"
            r"\tag_attr_new:nn {%<name%>} {%<content%>}#/%expl3" "\n"
            r"\verb{verbatimSymbol}#S" "\n",
            package="demo",
        )

        self.assertEqual(package.commands[r"\sqrt"].signature, r"\sqrt{arg}")
        line = package.commands[r"\line"]
        self.assertEqual(
            [(argument.name, argument.optional) for argument in line.arguments],
            [("xslope,yslope", False), ("length", False)],
        )
        self.assertEqual(line.completion, r"\line(){}")
        alt = package.commands[r"\alt"]
        self.assertEqual(alt.completion, r"\alt<>{}{}")
        self.assertIn(r"\tag_attr_new:nn", package.commands)
        self.assertNotIn(r"\verb", package.commands)

    def test_keyval_enumerations_and_context_selectors_are_preserved(self):
        package = parse_cwl(
            "#keyvals:\\foo#o1,\\foo#o2\n"
            "backend=#bibtex,biber\n"
            "draft\n"
            "#endkeyvals\n",
            package="demo",
        )

        from editor.cwl import CWLModel
        model = CWLModel(packages={"demo": package})

        self.assertEqual(
            model.option_candidates_for(r"\foo", ["demo"]),
            ["backend=biber", "backend=bibtex", "draft"],
        )
        self.assertIn(r"\foo#o1", package.keyvals)
        self.assertIn(r"\foo#o2", package.keyvals)

    def test_keyvals_header_ignores_metadata_suffix_and_supports_multiple_contexts(self):
        package = parse_cwl(
            "#keyvals:\\foo,\\bar#c\n"
            "mode#fast,slow\n"
            "#endkeyvals\n",
            package="demo",
        )

        from editor.cwl import CWLModel
        model = CWLModel(packages={"demo": package})

        self.assertEqual(model.option_candidates_for(r"\foo", ["demo"]),
                         ["mode=fast", "mode=slow"])
        self.assertEqual(model.option_candidates_for(r"\bar", ["demo"]),
                         ["mode=fast", "mode=slow"])

        package = parse_cwl(
            "#keyvals:\\usepackage/demo#c\n"
            "draft\n"
            "#endkeyvals\n",
            package="demo",
        )
        model = CWLModel(packages={"demo": package})
        self.assertEqual(model.option_candidates_for(r"\usepackage", ["demo"]), ["draft"])

    def test_builtin_graphicx_keyvals_reach_option_completion(self):
        from editor.cwl import load_cwl_directories

        model = load_cwl_directories([Path(__file__).parents[1] / "editor" / "cwl"])

        options = model.option_candidates_for(r"\rotatebox", ["graphicx"])

        self.assertEqual(options, ["origin=", "units="])

    def test_keyvals_reach_latex_option_popup(self):
        from editor.cwl import load_cwl_directories

        editor = EditorWidget()
        manager = AutoCompleteManager(editor)
        shown = []
        editor.showUserList = lambda list_id, labels: shown.append((list_id, labels))
        editor.setText(r"\usepackage{graphicx}\rotatebox[")
        editor.setCursorPosition(0, len(editor.text(0)))
        model = load_cwl_directories([Path(__file__).parents[1] / "editor" / "cwl"])
        try:
            with mock.patch.object(LaTeXSupport, "get_cwl_model", return_value=model):
                manager.set_language("latex")
                self.assertTrue(manager.handle_latex_option("["))
            self.assertEqual(shown[-1], (10, ["origin=", "units="]))
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()

    def test_keyvals_merge_with_static_includegraphics_options(self):
        from editor.cwl import load_cwl_directories

        editor = EditorWidget()
        manager = AutoCompleteManager(editor)
        shown = []
        editor.showUserList = lambda list_id, labels: shown.append((list_id, labels))
        editor.setText(r"\usepackage{graphicx}\includegraphics[")
        editor.setCursorPosition(0, len(editor.text(0)))
        model = load_cwl_directories([Path(__file__).parents[1] / "editor" / "cwl"])
        try:
            with mock.patch.object(LaTeXSupport, "get_cwl_model", return_value=model):
                manager.set_language("latex")
                self.assertTrue(manager.handle_latex_option("["))
            self.assertIn("width=", shown[-1][1])
            self.assertIn("keepaspectratio=true", shown[-1][1])
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()

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

    def test_cwl_includes_merge_entries_into_the_including_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "base.cwl").write_text(
                "#keyvals:\\derivedcommand\n"
                "baseflag\n"
                "#endkeyvals\n"
                r"\basecommand{value}" "\n"
                r"\begin{baseenvironment}" "\n"
            )
            (root / "derived.cwl").write_text(
                "#include:base\n"
                r"\derivedcommand[customoption]{value}" "\n"
                r"\basecommand{local-value}" "\n"
            )

            model = load_cwl_directories([root])

            self.assertEqual(model.packages["derived"].includes, ("base",))
            commands = {command.name: command for command in model.commands_for(["derived"])}
            self.assertEqual(commands[r"\basecommand"].signature, r"\basecommand{local-value}")
            self.assertEqual(commands[r"\derivedcommand"].package, "derived")
            self.assertEqual(
                model.environments_for(["derived"])[0].name,
                "baseenvironment",
            )
            self.assertEqual(
                model.option_candidates_for(r"\derivedcommand", ["derived"]),
                ["baseflag", "customoption="],
            )

    def test_cwl_included_keyvals_are_merged_on_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "first.cwl").write_text(
                "#keyvals:\\command\nfirst\n#endkeyvals\n"
            )
            (root / "second.cwl").write_text(
                "#keyvals:\\command\nsecond\n#endkeyvals\n"
            )
            (root / "derived.cwl").write_text(
                "#include:first\n#include:second\n"
            )

            model = load_cwl_directories([root])

            self.assertEqual(
                model.option_candidates_for(r"\command", ["derived"]),
                ["first", "second"],
            )

    def test_conditional_cwl_includes_follow_package_options(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "skins.cwl").write_text(r"\skincommand" "\n")
            (root / "plain.cwl").write_text(r"\plaincommand" "\n")
            (root / "tcolorbox.cwl").write_text(
                "#ifOption:skins\n"
                "#include:skins\n"
                "#else\n"
                "#include:plain\n"
                "#endif\n"
                r"\boxcommand" "\n"
            )

            without_option = load_cwl_directories([root])
            with_option = load_cwl_directories(
                [root], package_options={"tcolorbox": {"skins"}}
            )

            self.assertNotIn(
                r"\skincommand",
                {command.name for command in without_option.commands_for(["tcolorbox"])},
            )
            self.assertIn(
                r"\plaincommand",
                {command.name for command in without_option.commands_for(["tcolorbox"])},
            )
            self.assertIn(
                r"\skincommand",
                {command.name for command in with_option.commands_for(["tcolorbox"])},
            )

    def test_cwl_include_cycles_are_ignored_without_recursing_forever(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "first.cwl").write_text(
                "#include:second\n" r"\firstcommand" "\n"
            )
            (root / "second.cwl").write_text(
                "#include:first\n" r"\secondcommand" "\n"
            )

            model = load_cwl_directories([root])

            self.assertEqual(
                {command.name for command in model.commands_for(["first"])},
                {r"\firstcommand", r"\secondcommand"},
            )
            self.assertEqual(
                {command.name for command in model.commands_for(["second"])},
                {r"\firstcommand", r"\secondcommand"},
            )

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

    def test_custom_cwl_option_completion_uses_optional_argument_names(self):
        editor = EditorWidget()
        manager = AutoCompleteManager(editor)
        shown = []
        editor.showUserList = lambda list_id, labels: shown.append((list_id, labels))
        editor.setText(r"\usepackage{mycwl}\mycommand[")
        editor.setCursorPosition(0, len(editor.text(0)))
        try:
            with mock.patch.object(
                    LaTeXSupport, "get_cwl_model",
                    return_value=mock.Mock(
                        option_candidates_for=lambda command, packages: ["width=", "mode="],
                    )):
                manager.set_language("latex")
                self.assertTrue(manager.handle_latex_option("["))
                self.assertEqual(shown[-1], (10, ["width=", "mode="]))

                editor.setText(r"\usepackage{mycwl}\mycommand[width=, mo")
                editor.setCursorPosition(0, len(editor.text(0)))
                self.assertTrue(manager.handle_latex_option(","))
                self.assertEqual(shown[-1], (12, ["mode="]))
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
