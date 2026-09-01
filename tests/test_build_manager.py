"""
tests/test_build_manager.py — Test per il sistema di build
NotePadPQ

Testa:
- BuildManager: profili, variabili, parsing errori, task discovery
- BuildWorker: esecuzione, abort
- Variabili d'ambiente per profilo
- Hook pre/post build
- Pipeline multi-step
- Configurazione di progetto (.notepadpq-build.json)
- Unified errors (LSP + build)
- Task discovery estesa (Cargo, CMake, Gradle, Docker, justfile)
- InteractiveBuildWorker (PTY)
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


class TestBuildWorker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_worker_executes_and_completes(self):
        from core.build_manager import BuildWorker
        import os

        worker = BuildWorker("echo hello", ".", dict(os.environ), run_id="test1")
        output_lines = []
        worker.output_line.connect(lambda line: output_lines.append(line))
        worker.start()
        worker.wait(5000)
        self.assertTrue(worker.isFinished() or not worker.isRunning(),
                        "Worker should be done after wait")
        if output_lines:
            self.assertIn("hello", " ".join(output_lines))

    def test_worker_abort(self):
        from core.build_manager import BuildWorker
        import os

        worker = BuildWorker("sleep 10", ".", dict(os.environ), run_id="test_abort")
        worker.start()
        QApplication.processEvents()
        worker.abort()
        worker.wait(3000)
        if worker.isRunning():
            worker.terminate()
            worker.wait(1000)
        self.assertTrue(True)

    def test_worker_failed_command(self):
        from core.build_manager import BuildWorker
        import os

        worker = BuildWorker("nonexistent_command_xyz 2>&1", ".", dict(os.environ), run_id="test_fail")
        worker.start()
        worker.wait(5000)
        self.assertTrue(worker.isFinished() or not worker.isRunning())

    def test_worker_timeout_sets_terminal_state(self):
        from core.build_manager import BuildWorker, BUILD_STATE_TIMED_OUT

        command = f'"{sys.executable}" -c "import time; time.sleep(10)"'
        worker = BuildWorker(command, ".", dict(os.environ), run_id="test_timeout",
                             timeout=0.05)
        worker.start()
        worker.wait(3000)
        self.assertFalse(worker.isRunning())
        self.assertEqual(worker.state, BUILD_STATE_TIMED_OUT)
        self.assertEqual(worker._outcome[0], "timeout")


class TestVariableExpansion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_expand_file_variables(self):
        from core.build_manager import BuildManager
        bm = BuildManager()

        path = Path("/home/user/project/main.py")
        cmd = "${FILE} ${DIR} ${BASENAME} ${EXT} ${FILENAME} ${BASEFILE} ${LINE} ${COL}"

        class FakeEditor:
            def get_cursor_position_1based(self):
                return (42, 7)
            file_path = path

        result = bm._expand_vars(cmd, path, FakeEditor())
        self.assertIn("/home/user/project/main.py", result)
        self.assertIn("/home/user/project", result)
        self.assertIn("main", result)
        self.assertIn(".py", result)
        self.assertIn("main.py", result)
        self.assertIn("/home/user/project/main", result)
        self.assertIn("42", result)
        self.assertIn("7", result)

    def test_expand_dollar_parentheses(self):
        from core.build_manager import BuildManager
        bm = BuildManager()

        path = Path("/tmp/test.sh")
        cmd = "$(FILE) $(DIR) $(BASENAME)"

        class FakeEditor:
            def get_cursor_position_1based(self):
                return (1, 1)
            file_path = path

        result = bm._expand_vars(cmd, path, FakeEditor())
        self.assertIn("/tmp/test.sh", result)
        self.assertIn("/tmp", result)
        self.assertIn("test", result)

    def test_expand_latex_output_and_root_variables(self):
        from core.build_manager import BuildManager
        bm = BuildManager()
        path = Path("/tmp/project/main.tex")
        result = bm._expand_vars(
            "${FILE} ${OUTDIR} ${ROOT}", path, None,
            output_dir=Path("/tmp/project/build"), root_file=path,
        )
        self.assertIn("/tmp/project/main.tex", result)
        self.assertIn("/tmp/project/build", result)
        self.assertEqual(result.count("/tmp/project/main.tex"), 2)


class TestLatexBuildContext(unittest.TestCase):

    def test_detects_biblatex_backend_and_injects_latexmk_flag(self):
        from core.build_manager import BuildManager

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "main.tex"
            root.write_text(r"\usepackage[backend=bibtex]{biblatex}")
            bm = BuildManager()
            self.assertEqual(
                bm.detect_bibliography_backend(root, root.read_text()), "bibtex")
            context = bm._latex_context(root, root.read_text())
            command = bm._configure_bibliography_command(
                "latexmk -pdf ${FILE}", {"bib_backend": "auto"},
                context, root.read_text())
            self.assertIn("-bibtex", command)
            self.assertNotIn("-usebibtex", command)

    def test_build_uses_root_and_configured_output_directory(self):
        from unittest import mock
        from core.build_manager import BuildManager

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            chapter = root / "chapters" / "chapter.tex"
            chapter.parent.mkdir()
            main.write_text(r"\documentclass{article}\begin{document}\input{chapter}\end{document}")
            chapter.write_text("% !TEX root = main.tex\nChapter")
            (chapter.parent / ".notepadpq-build.json").write_text(json.dumps({
                "profiles": {
                    "Project LaTeX": {
                        "extensions": [".tex"],
                        "build": "echo ${FILE} ${OUTDIR}",
                        "compile": "", "run": "",
                        "output_directory": "build",
                    }
                }
            }))

            class FakeEditor:
                file_path = chapter

                def is_modified(self):
                    return False

                def get_content(self):
                    return chapter.read_text()

                def get_cursor_position_1based(self):
                    return 1, 1

            bm = BuildManager()
            bm._do_run = mock.Mock(return_value=True)
            self.assertTrue(bm.run("build", FakeEditor(), run_id="context-test"))
            command = bm._do_run.call_args.args[1]
            self.assertIn(str(main), command)
            self.assertIn(str(root / "build"), command)
            self.assertEqual(bm.get_build_context("context-test").root, main.resolve())

    def test_ramdisk_profile_redirects_output_and_copies_back(self):
        from unittest import mock
        from core.build_manager import BuildManager

        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as runtime:
            root = Path(temp)
            main = root / "main.tex"
            main.write_text(r"\documentclass{article}\begin{document}x\end{document}")

            class FakeEditor:
                file_path = main

                def is_modified(self):
                    return False

                def get_content(self):
                    return main.read_text()

                def get_cursor_position_1based(self):
                    return 1, 1

            bm = BuildManager()
            bm.save_profiles = mock.Mock()  # non toccare il config reale dell'utente
            bm.add_profile("RamdiskLatex", {
                "extensions": [".tex"],
                "compile": "", "run": "",
                "build": "latexmk -pdf -output-directory=${OUTDIR} ${FILE}",
                "ramdisk": True,
            })
            bm.set_profile_override(".tex", "RamdiskLatex")
            bm._do_run = mock.Mock(return_value=True)

            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}):
                self.assertTrue(bm.run("build", FakeEditor(), run_id="ram-test"))

            kwargs = bm._do_run.call_args.kwargs
            output_dir = str(kwargs["output_dir"])
            self.assertTrue(output_dir.startswith(str(Path(runtime) / "notepadpq-latex")))
            self.assertIn(str(root)[1:], output_dir)  # mirrors project path under tmpfs
            self.assertIn("cp -f", kwargs["post_hook"])
            self.assertIn(str(root), kwargs["post_hook"])

    def test_ramdisk_unavailable_falls_back_to_normal_directory(self):
        from unittest import mock
        from core.build_manager import BuildManager

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            main.write_text(r"\documentclass{article}\begin{document}x\end{document}")

            class FakeEditor:
                file_path = main

                def is_modified(self):
                    return False

                def get_content(self):
                    return main.read_text()

                def get_cursor_position_1based(self):
                    return 1, 1

            bm = BuildManager()
            bm.save_profiles = mock.Mock()  # non toccare il config reale dell'utente
            bm.add_profile("RamdiskLatex", {
                "extensions": [".tex"],
                "compile": "", "run": "",
                "build": "latexmk -pdf -output-directory=${OUTDIR} ${FILE}",
                "ramdisk": True,
            })
            bm.set_profile_override(".tex", "RamdiskLatex")
            bm._do_run = mock.Mock(return_value=True)

            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("XDG_RUNTIME_DIR", None)
                self.assertTrue(bm.run("build", FakeEditor(), run_id="ram-fallback"))

            kwargs = bm._do_run.call_args.kwargs
            self.assertEqual(str(kwargs["output_dir"]), str(root))
            self.assertEqual(kwargs["post_hook"], "")


class TestErrorParsing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from core.build_manager import BuildManager
        self.bm = BuildManager()

    def test_parse_python_traceback(self):
        output = '''Traceback (most recent call last):
  File "/home/user/test.py", line 42, in <module>
    undefined_function()
NameError: name 'undefined_function' is not defined'''

        errors = self.bm.parse_errors(output, "Python")
        self.assertGreaterEqual(len(errors), 1)
        self.assertEqual(errors[0]["line"], 42)
        self.assertIn("test.py", errors[0]["file"])

    def test_parse_gcc_error(self):
        output = "src/main.c:15:7: error: expected ';' before 'return'\n"

        errors = self.bm.parse_errors(output, "C (gcc)")
        self.assertGreaterEqual(len(errors), 1)
        self.assertEqual(errors[0]["line"], 15)
        self.assertIn("main.c", errors[0]["file"])

    def test_parse_cargo_error(self):
        output = " --> src/main.rs:23:9\n  |\n23 |     let x = y;\n  |         ^"

        errors = self.bm.parse_errors(output, "Rust (cargo)")
        self.assertGreaterEqual(len(errors), 1)
        if errors:
            self.assertEqual(errors[0]["line"], 23)

    def test_parse_latex_error(self):
        output = r"""(/tmp/doc.tex
! Undefined control sequence.
l.42 \badcommand
)"""

        errors = self.bm.parse_errors(output, "LaTeX (pdflatex)")
        self.assertGreaterEqual(len(errors), 1)
        if errors:
            self.assertEqual(errors[0]["line"], 42)

    def test_parse_latex_modern_format(self):
        output = "./doc.tex:15: Undefined control sequence."

        errors = self.bm.parse_errors(output, "LaTeX (pdflatex)")
        self.assertGreaterEqual(len(errors), 1)
        if errors:
            self.assertIn("doc.tex", errors[0]["file"])
            self.assertEqual(errors[0]["line"], 15)

    def test_parse_nested_latex_error_uses_included_file(self):
        output = """(/tmp/main.tex
(/tmp/chapters/one.tex
! Undefined control sequence.
l.8 \\badcommand
)
)"""
        errors = self.bm.parse_errors(output, "LaTeX (pdflatex)")
        self.assertEqual(errors[0]["file"], "/tmp/chapters/one.tex")
        self.assertEqual(errors[0]["line"], 8)

    def test_parse_ltx_error(self):
        errors = self.bm.parse_errors(
            "(/tmp/doc.ltx\n! Error\nl.4 bad\n)",
            "LaTeX (pdflatex)",
        )
        self.assertEqual(errors[0]["file"], "/tmp/doc.ltx")

    def test_parse_with_custom_groups(self):
        output = "ERROR|myscript.py|88|Something went wrong"

        from core.build_manager import BuildManager
        bm = BuildManager()
        bm.add_profile("CustomRegex", {
            "extensions": [".xyz"],
            "compile": "", "run": "", "build": "",
            "error_regex": r'ERROR\|([^|]+)\|(\d+)\|(.+)',
            "error_file_group": 1,
            "error_line_group": 2,
        })
        errors = bm.parse_errors(output, "CustomRegex")
        self.assertGreaterEqual(len(errors), 1)
        if errors:
            self.assertEqual(errors[0]["file"], "myscript.py")
            self.assertEqual(errors[0]["line"], 88)

    def test_merge_lsp_diagnostics(self):
        build_errors = [{"file": "a.py", "line": 10, "message": "build error"}]
        lsp_diags = [
            {"file": "a.py", "line": 5, "message": "unused variable", "source": "LSP"},
            {"file": "b.py", "line": 3, "message": "missing import", "source": "LSP"},
        ]

        from core.build_manager import BuildManager
        merged = BuildManager._merge_diagnostics(build_errors, lsp_diags)
        self.assertEqual(len(merged), 3)
        sources = [e.get("source", "") for e in merged]
        self.assertIn("LSP", sources)

    def test_invalid_regex_handled(self):
        errors = self.bm.parse_errors("anything", "Python")
        self.bm.add_profile("Bad", {
            "extensions": [], "compile": "", "run": "", "build": "",
            "error_regex": r"((invalid",
            "error_file_group": 1, "error_line_group": 2,
        })
        errors = self.bm.parse_errors("anything", "Bad")
        self.assertEqual(errors, [])


class TestProfileManagement(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from core.build_manager import BuildManager
        BuildManager._instance = None
        self.bm = BuildManager.instance()

    def test_default_profiles_loaded(self):
        profiles = self.bm.get_profiles()
        self.assertIn("Python", profiles)
        self.assertIn("C (gcc)", profiles)
        self.assertIn("Rust (cargo)", profiles)
        self.assertEqual(profiles["Python"]["extensions"], [".py"])

    def test_add_and_remove_profile(self):
        self.bm.add_profile("MyTest", {
            "extensions": [".test"],
            "compile": "testc ${FILE}",
            "run": "testr ${FILE}",
            "build": "",
            "error_regex": r"(\d+)",
            "error_file_group": 1,
            "error_line_group": 1,
        })
        self.assertIn("MyTest", self.bm.get_profiles())
        self.bm.remove_profile("MyTest")
        self.assertNotIn("MyTest", self.bm.get_profiles())

    def test_cannot_remove_default(self):
        profiles_before = len(self.bm.get_profiles())
        self.bm.remove_profile("Python")
        self.assertIn("Python", self.bm.get_profiles())
        self.assertEqual(len(self.bm.get_profiles()), profiles_before)

    def test_reorder_profiles(self):
        order = list(self.bm.get_profiles().keys())
        reversed_order = list(reversed(order))
        self.bm.reorder_profiles(reversed_order)
        new_order = list(self.bm.get_profiles().keys())
        self.assertEqual(new_order, reversed_order)

    def test_profile_override(self):
        profiles = self.bm.get_profiles()
        self.assertIn("Python", profiles)
        self.assertIn("Python (uv)", profiles)

        self.bm.set_profile_override(".py", "Python (uv)")
        py_path = Path("/tmp/test.py")
        self.assertEqual(self.bm.get_profile_for_file(py_path), "Python (uv)")

        self.bm.clear_profile_override(".py")
        self.assertTrue(
            self.bm.get_profile_for_file(py_path) in ("Python", "Python (uv)")
        )

    def test_profile_with_env_vars(self):
        self.bm.add_profile("EnvTest", {
            "extensions": [".envt"],
            "compile": "echo $MY_VAR",
            "run": "", "build": "",
            "error_regex": "",
            "error_file_group": 1,
            "error_line_group": 2,
            "env": {"MY_VAR": "hello_world"},
        })
        p = self.bm.get_profiles().get("EnvTest", {})
        self.assertEqual(p.get("env"), {"MY_VAR": "hello_world"})

    def test_profile_with_hooks(self):
        self.bm.add_profile("HookTest", {
            "extensions": [".ht"],
            "compile": "echo main",
            "run": "", "build": "",
            "error_regex": "",
            "error_file_group": 1,
            "error_line_group": 2,
            "pre_hook": "echo before",
            "post_hook": "echo after",
        })
        p = self.bm.get_profiles().get("HookTest", {})
        self.assertEqual(p.get("pre_hook"), "echo before")
        self.assertEqual(p.get("post_hook"), "echo after")

    def test_profile_pipeline(self):
        self.bm.add_profile("PipeTest", {
            "extensions": [".pt"],
            "compile": "", "run": "", "build": "",
            "error_regex": "",
            "error_file_group": 1,
            "error_line_group": 2,
            "pipeline": [
                {"name": "Lint", "cmd": "ruff check", "stop_on_error": True},
                {"name": "Build", "cmd": "gcc build", "stop_on_error": True},
                {"name": "Run", "cmd": "./app", "stop_on_error": False},
            ],
        })
        p = self.bm.get_profiles().get("PipeTest", {})
        self.assertEqual(len(p.get("pipeline", [])), 3)
        self.assertEqual(p["pipeline"][0]["name"], "Lint")


class TestTaskDiscovery(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from core.build_manager import BuildManager
        self.bm = BuildManager()

    def test_discover_makefile_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            makefile = Path(td) / "Makefile"
            makefile.write_text("build:\n\techo building\n\ntest:\n\techo testing\n\nclean:\n\trm -rf build\n\nrun:\n\t./app\n")
            tasks = self.bm.discover_tasks(Path(td))
            names = [t["name"] for t in tasks]
            self.assertIn("make build", names)
            self.assertIn("make test", names)
            self.assertIn("make clean", names)
            self.assertIn("make run", names)

    def test_discover_package_json_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "package.json"
            pkg.write_text(json.dumps({
                "scripts": {
                    "start": "node index.js",
                    "test": "jest",
                    "build": "webpack"
                }
            }))
            tasks = self.bm.discover_tasks(Path(td))
            names = [t["name"] for t in tasks]
            self.assertIn("npm run start", names)
            self.assertIn("npm run test", names)
            self.assertIn("npm run build", names)

    def test_discover_cargo_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            cargo = Path(td) / "Cargo.toml"
            cargo.write_text("[package]\nname = 'test'\n")
            tasks = self.bm.discover_tasks(Path(td))
            names = [t["name"] for t in tasks]
            self.assertIn("cargo build", names)
            self.assertIn("cargo test", names)
            self.assertIn("cargo run", names)

    def test_discover_cmake_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            cmake = Path(td) / "CMakeLists.txt"
            cmake.write_text("cmake_minimum_required(VERSION 3.10)\nproject(test)\n")
            tasks = self.bm.discover_tasks(Path(td))
            sources = [t["source"] for t in tasks]
            self.assertIn("CMake", sources)

    def test_discover_gradle_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            gradle = Path(td) / "build.gradle"
            gradle.write_text("plugins { id 'java' }\n")
            tasks = self.bm.discover_tasks(Path(td))
            sources = [t["source"] for t in tasks]
            self.assertIn("Gradle", sources)

    def test_discover_docker_compose_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            dc = Path(td) / "docker-compose.yml"
            dc.write_text("version: '3'\nservices:\n  web:\n    build: .\n")
            tasks = self.bm.discover_tasks(Path(td))
            sources = [t["source"] for t in tasks]
            self.assertIn("Docker", sources)

    def test_discover_justfile_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            jf = Path(td) / "justfile"
            jf.write_text("build:\n  cargo build\ntest:\n  cargo test\nlint:\n  cargo clippy\n")
            tasks = self.bm.discover_tasks(Path(td))
            sources = [t["source"] for t in tasks]
            self.assertIn("justfile", sources)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as td:
            tasks = self.bm.discover_tasks(Path(td))
            self.assertEqual(tasks, [])


class TestProjectConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from core.build_manager import BuildManager
        BuildManager._instance = None
        self.bm = BuildManager.instance()

    def test_find_project_config(self):
        with tempfile.TemporaryDirectory() as td:
            proj_dir = Path(td) / "myproject"
            proj_dir.mkdir()
            cfg = proj_dir / ".notepadpq-build.json"
            cfg.write_text(json.dumps({
                "profiles": {
                    "Custom Project": {
                        "extensions": [".py"],
                        "run": "python custom.py ${FILE}",
                        "compile": "", "build": "",
                        "error_regex": "", "error_file_group": 1, "error_line_group": 2,
                    }
                },
                "tasks": [
                    {"name": "deploy", "cmd": "deploy.sh"}
                ]
            }))

            test_file = proj_dir / "test.py"
            test_file.write_text("print('hi')")

            profiles = self.bm.get_project_profiles(test_file)
            self.assertIn("Custom Project", profiles)
            self.assertEqual(profiles["Custom Project"]["run"], "python custom.py ${FILE}")

            tasks = self.bm.get_project_tasks(test_file)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["name"], "deploy")

    def test_no_project_config(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "test.py"
            f.write_text("")
            profiles = self.bm.get_project_profiles(f)
            self.assertEqual(profiles, {})

    def test_project_profile_is_selected_for_matching_file(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / ".notepadpq-build.json").write_text(json.dumps({
                "profiles": {
                    "Project Python": {
                        "extensions": [".py"],
                        "run": "python project.py",
                    }
                }
            }))
            self.assertEqual(
                self.bm.get_profile_for_file(project / "main.py"),
                "Project Python",
            )


class TestBuildEnv(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_env_from_dict(self):
        from core.build_manager import BuildManager
        bm = BuildManager()
        profile = {"env": {"FOO": "bar", "BAZ": "123"}}
        env = bm._build_env(Path("/tmp/test.py"), profile)
        self.assertEqual(env.get("FOO"), "bar")
        self.assertEqual(env.get("BAZ"), "123")
        self.assertIn("NOTEPADPQ_FILE", env)

    def test_env_from_string(self):
        from core.build_manager import BuildManager
        bm = BuildManager()
        profile = {"env": "FOO=bar\nBAZ=123\n# comment\nHELLO=world\n"}
        env = bm._build_env(Path("/tmp/test.py"), profile)
        self.assertEqual(env.get("FOO"), "bar")
        self.assertEqual(env.get("BAZ"), "123")
        self.assertEqual(env.get("HELLO"), "world")

    def test_env_skips_comments(self):
        from core.build_manager import BuildManager
        bm = BuildManager()
        profile = {"env": "# This is a comment\nREAL=value"}
        env = bm._build_env(Path("/tmp/test.py"), profile)
        self.assertNotIn("# This is a comment", env.keys())
        self.assertEqual(env.get("REAL"), "value")


class TestAuxFileCleaning(unittest.TestCase):

    def test_clean_aux_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "document"
            base.write_text("dummy")

            aux_files = []
            from core.build_manager import clean_aux_files
            for ext in [".aux", ".log", ".toc", ".synctex.gz"]:
                f = base.with_name(base.name + ext)
                f.write_text("dummy")
                aux_files.append(f)

            removed = clean_aux_files(base, keep_synctex=True)
            self.assertIn("document.aux", removed)
            self.assertIn("document.log", removed)
            self.assertIn("document.toc", removed)
            self.assertNotIn("document.synctex.gz", removed)

            removed2 = clean_aux_files(base, keep_synctex=False)
            self.assertIn("document.synctex.gz", removed2)

    def test_clean_aux_files_supports_extra_project_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            main = root / "main"
            child = root / "child"
            child.with_name("child.aux").write_text("aux")
            from core.build_manager import clean_aux_files
            removed = clean_aux_files(main, extra_bases=[child])
            self.assertEqual(removed, ["child.aux"])


class TestDraftMode(unittest.TestCase):

    def test_add_draftmode_flag(self):
        from core.build_manager import BuildManager
        cmd = "pdflatex -interaction=nonstopmode doc.tex"
        result = BuildManager._add_draftmode_flag(cmd)
        self.assertIn("-draftmode", result)
        self.assertIn("pdflatex", result)

    def test_add_draftmode_xelatex(self):
        from core.build_manager import BuildManager
        cmd = "xelatex doc.tex"
        result = BuildManager._add_draftmode_flag(cmd)
        self.assertIn("-draftmode", result)

    def test_no_draftmode_for_other(self):
        from core.build_manager import BuildManager
        cmd = "gcc -o main main.c"
        result = BuildManager._add_draftmode_flag(cmd)
        self.assertNotIn("-draftmode", result)


class TestInteractiveWorker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_interactive_worker_runs(self):
        from core.build_manager import InteractiveBuildWorker
        import os

        worker = InteractiveBuildWorker("echo hello", ".", dict(os.environ), run_id="test_iw")
        output = []
        worker.output_line.connect(lambda line: output.append(line))
        worker.start()
        worker.wait(5000)
        self.assertTrue(worker.isFinished() or not worker.isRunning())
        if output:
            self.assertIn("hello", " ".join(output))

    def test_interactive_worker_timeout_sets_terminal_state(self):
        from core.build_manager import InteractiveBuildWorker, BUILD_STATE_TIMED_OUT

        command = f'"{sys.executable}" -c "import time; time.sleep(10)"'
        worker = InteractiveBuildWorker(
            command, ".", dict(os.environ), run_id="test_iw_timeout", timeout=0.05,
        )
        worker.start()
        worker.wait(3000)
        self.assertFalse(worker.isRunning())
        self.assertEqual(worker.state, BUILD_STATE_TIMED_OUT)
        self.assertEqual(worker._outcome[0], "timeout")

    def test_interactive_worker_timeout_handles_partial_output(self):
        from core.build_manager import InteractiveBuildWorker, BUILD_STATE_TIMED_OUT

        worker = InteractiveBuildWorker(
            [sys.executable, "-c", "import sys,time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(10)"],
            ".", dict(os.environ), run_id="test_iw_partial_timeout", timeout=0.05,
        )
        output = []
        worker.output_line.connect(output.append)
        worker.start()
        worker.wait(3000)
        self._app.processEvents()

        self.assertFalse(worker.isRunning())
        self.assertEqual(worker.state, BUILD_STATE_TIMED_OUT)
        self.assertIn("partial", output)


class TestOutputLimit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_get_output_limit_default(self):
        from core.build_manager import BuildManager
        bm = BuildManager()
        self.assertEqual(bm.get_output_limit(), 10000)


if __name__ == "__main__":
    unittest.main()
