import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import latex_toolchain


class LatexToolchainTest(unittest.TestCase):
    def setUp(self):
        latex_toolchain.clear_latex_toolchain_cache()

    def tearDown(self):
        latex_toolchain.clear_latex_toolchain_cache()

    def test_missing_tools_are_reported_without_version_probes(self):
        with mock.patch.object(latex_toolchain.shutil, "which", return_value=None):
            with mock.patch.object(latex_toolchain.subprocess, "run") as run:
                report = latex_toolchain.detect_latex_toolchain(path="/empty")

        run.assert_not_called()
        self.assertEqual(set(report), set(latex_toolchain.TOOL_NAMES))
        self.assertTrue(all(not info.available for info in report.values()))
        self.assertTrue(all(info.status == "missing" for info in report.values()))

    def test_temp_path_reports_executable_path_and_version(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "pdflatex"
            executable.write_text("#!/bin/sh\nprintf '%s\\n' 'pdfTeX 3.141592'\n")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

            with mock.patch.dict(os.environ, {"PATH": temp}, clear=False):
                report = latex_toolchain.detect_latex_toolchain(context="test")

        info = report["pdflatex"]
        self.assertTrue(info.available)
        self.assertEqual(info.path, str(executable))
        self.assertEqual(info.version, "pdfTeX 3.141592")
        self.assertEqual(info.status, "available")
        self.assertEqual(report["xelatex"].status, "missing")

    def test_failed_and_timed_out_probes_are_safe(self):
        def which(name, path=None):
            if name in {"pdflatex", "xelatex"}:
                return f"/tools/{name}"
            return None

        def run(command, **kwargs):
            name = Path(command[0]).name
            if name == "pdflatex":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return subprocess.CompletedProcess(command, 1, "", "version unavailable")

        with mock.patch.object(latex_toolchain.shutil, "which", side_effect=which):
            with mock.patch.object(latex_toolchain.subprocess, "run", side_effect=run):
                report = latex_toolchain.detect_latex_toolchain(path="/tools")

        self.assertEqual(report["pdflatex"].status, "timeout")
        self.assertTrue(report["pdflatex"].available)
        self.assertEqual(report["xelatex"].status, "failed")
        self.assertEqual(report["xelatex"].version, "version unavailable")

    def test_makeindex_probe_uses_its_no_argument_version_mode(self):
        completed = subprocess.CompletedProcess([], 0, "This is makeindex, version 2.18", "")
        with mock.patch.object(
            latex_toolchain.subprocess, "run", return_value=completed
        ) as run:
            info = latex_toolchain._probe_version(
                "makeindex", "/tools/makeindex", "/tools", 1.0
            )

        self.assertEqual(info.status, "available")
        self.assertEqual(run.call_args.args[0], ["/tools/makeindex"])

    def test_results_are_cached_by_path_and_context_and_refreshable(self):
        completed = subprocess.CompletedProcess([], 0, "tool 1.0\n", "")
        with mock.patch.object(
            latex_toolchain.shutil,
            "which",
            side_effect=lambda name, path=None: (
                "/tools/pdflatex" if name == "pdflatex" else None
            ),
        ) as which:
            with mock.patch.object(
                latex_toolchain.subprocess, "run", return_value=completed
            ) as run:
                first = latex_toolchain.detect_latex_toolchain(
                    path="/tools", context="project"
                )
                second = latex_toolchain.detect_latex_toolchain(
                    path="/tools", context="project"
                )
                other_context = latex_toolchain.detect_latex_toolchain(
                    path="/tools", context="other-project"
                )
                refreshed = latex_toolchain.detect_latex_toolchain(
                    path="/tools", context="project", refresh=True
                )

        self.assertEqual(run.call_count, 3)
        self.assertEqual(which.call_count, len(latex_toolchain.TOOL_NAMES) * 3)
        self.assertEqual(first, second)
        self.assertEqual(first, refreshed)
        self.assertEqual(other_context["pdflatex"].version, "tool 1.0")


if __name__ == "__main__":
    unittest.main()
