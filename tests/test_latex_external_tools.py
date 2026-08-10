import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import latex_external_tools


class _FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", returncode=0, running=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.stdin = io.BytesIO()
        self.returncode = None if running else returncode
        self._exit_code = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = self._exit_code

    def kill(self):
        self.terminated = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self._exit_code
        return self.returncode


class LatexExternalToolsTest(unittest.TestCase):
    def test_detects_auxiliary_tools_without_matching_comments(self):
        source = (
            r"\makeindex" + "\n"
            r"\makeglossaries" + "\n"
            r"% \makenomenclature" + "\n"
            r"\makenomenclature"
        )
        self.assertEqual(
            latex_external_tools.detect_latex_auxiliary_tools(source),
            ("makeglossaries", "nomencl", "makeindex"),
        )

    def test_parser_handles_chktex_lacheck_and_columns(self):
        diagnostics = latex_external_tools.parse_latex_diagnostics(
            "Warning 1 in doc.tex line 4 -- Missing space after command.\n"
            '"chapters/a.tex", line 12: Bad spelling.\n'
            "doc.tex:8:3: error: Undefined control sequence.\n",
            source="chktex",
        )

        self.assertEqual(len(diagnostics), 3)
        self.assertEqual(diagnostics[0].file, "doc.tex")
        self.assertEqual(diagnostics[0].line, 4)
        self.assertEqual(diagnostics[0].code, "1")
        self.assertEqual(diagnostics[0].severity, "warning")
        self.assertEqual(diagnostics[1].file, "chapters/a.tex")
        self.assertEqual(diagnostics[1].line, 12)
        self.assertEqual(diagnostics[2].column, 3)
        self.assertEqual(diagnostics[2].severity, "error")

    def test_checker_uses_argv_and_attaches_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "paper; touch unsafe.tex"
            path.write_text("\\section{Text}\n")
            process = _FakeProcess(
                stderr=b"paper; touch unsafe.tex:2:7: warning: check this\n",
            )
            with mock.patch.object(
                latex_external_tools.subprocess, "Popen", return_value=process
            ) as popen:
                result = latex_external_tools.run_chktex(path, timeout=1)

        command = popen.call_args.args[0]
        self.assertEqual(command[0], "chktex")
        self.assertEqual(command[-1], str(path))
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(result.diagnostics[0].line, 2)
        self.assertEqual(result.diagnostics[0].column, 7)

    def test_runner_can_be_cancelled_before_start(self):
        token = latex_external_tools.CancellationToken()
        token.cancel()
        with mock.patch.object(latex_external_tools.subprocess, "Popen") as popen:
            result = latex_external_tools.run_external_command(["tool"], cancel=token)

        popen.assert_not_called()
        self.assertTrue(result.cancelled)
        self.assertFalse(result.ok)

    def test_runner_terminates_after_timeout(self):
        process = _FakeProcess(running=True)
        with mock.patch.object(
            latex_external_tools.subprocess, "Popen", return_value=process
        ):
            result = latex_external_tools.run_external_command(["tool"], timeout=0.001)

        self.assertTrue(result.timed_out)
        self.assertTrue(process.terminated)

    def test_runner_caps_captured_output(self):
        process = _FakeProcess(stdout=b"0123456789")
        with mock.patch.object(
            latex_external_tools.subprocess, "Popen", return_value=process
        ):
            result = latex_external_tools.run_external_command(
                ["tool"], output_limit=4
            )

        self.assertTrue(result.output_limited)
        self.assertEqual(result.stdout, "0123")
        self.assertFalse(result.ok)

    def test_format_returns_one_replacement_or_original_text(self):
        original = "\\section{A}\n"
        formatted = "\\section{A}\n\n"
        success = latex_external_tools.ExternalCommandResult(
            ("latexindent", "-"), 0, formatted, ""
        )
        failure = latex_external_tools.ExternalCommandResult(
            ("latexindent", "-"), 2, "partial replacement", "error"
        )
        with mock.patch.object(
            latex_external_tools, "run_external_command", return_value=success
        ) as run:
            self.assertEqual(latex_external_tools.format_latex(original), formatted)
        self.assertEqual(run.call_args.args[0], ("latexindent", "-"))
        self.assertEqual(run.call_args.kwargs["input_text"], original)

        with mock.patch.object(
            latex_external_tools, "run_external_command", return_value=failure
        ):
            self.assertEqual(latex_external_tools.format_latex(original), original)

    def test_format_process_failure_keeps_original_and_does_not_use_shell(self):
        original = "\\textbf{not formatted}"
        process = _FakeProcess(returncode=1, stderr=b"latexindent failed")
        with mock.patch.object(
            latex_external_tools.subprocess, "Popen", return_value=process
        ) as popen:
            result = latex_external_tools.format_latex(original)

        self.assertEqual(result, original)
        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_index_commands_are_argument_vectors(self):
        with tempfile.TemporaryDirectory() as temp:
            tex = Path(temp) / "my document.tex"
            style = Path(temp) / "nomencl.ist"

            self.assertEqual(
                latex_external_tools.makeindex_command(tex.with_suffix(".idx")),
                ["makeindex", str(tex.with_suffix(".idx"))],
            )
            self.assertEqual(
                latex_external_tools.makeglossaries_command(tex),
                ["makeglossaries", str(tex.with_suffix(""))],
            )
            self.assertEqual(
                latex_external_tools.nomencl_command(tex, style_file=style),
                [
                    "makeindex",
                    "-s",
                    str(style),
                    "-o",
                    str(tex.with_suffix(".nls")),
                    str(tex.with_suffix(".nlo")),
                ],
            )
            self.assertEqual(
                latex_external_tools.nomencl_command(tex),
                ["makeindex", "-s", "nomencl.ist",
                 str(tex.with_suffix(".nls")), str(tex.with_suffix(".nlo"))],
            )

    def test_string_command_is_rejected(self):
        with self.assertRaises(TypeError):
            latex_external_tools.run_external_command("tool --unsafe")


if __name__ == "__main__":
    unittest.main()
