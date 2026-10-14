"""Guard the single source of truth for LaTeX command classification.

The optional C++ accelerator (``native/latex_native.cpp``) cannot import
Python, so its tables are generated into ``native/latex_command_tables.inc`` by
``native/generate_command_tables.py``.  These tests fail as soon as the
generated file goes stale or the accelerator stops using it.
"""

import importlib.util
import re
import unittest
from pathlib import Path

from core import latex_commands

_NATIVE_DIR = Path(__file__).resolve().parent.parent / "native"
_GENERATOR = _NATIVE_DIR / "generate_command_tables.py"
_INC = _NATIVE_DIR / "latex_command_tables.inc"
_CPP = _NATIVE_DIR / "latex_native.cpp"

_SET_RE = re.compile(
    r"const\s+std::unordered_set<std::string>\s+(\w+)\s*=\s*\{(.*?)\}\s*;",
    re.DOTALL,
)
_STRING_RE = re.compile(r'"([^"]*)"')

# Native table name -> core attribute
_EXPECTED = {
    "STRUCTURE_COMMANDS": "STRUCTURE_COMMANDS",
    "REFERENCE_COMMANDS": "REFERENCE_COMMANDS",
    "MATH_ENVIRONMENTS": "MATH_ENVIRONMENTS",
    "VERBATIM_ENVIRONMENTS": "VERBATIM_ENVIRONMENTS",
}


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_command_tables", _GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_tables(text: str) -> dict[str, frozenset[str]]:
    return {
        name: frozenset(_STRING_RE.findall(body))
        for name, body in _SET_RE.findall(text)
    }


class NativeClassifierSyncTest(unittest.TestCase):
    def setUp(self):
        if not _INC.is_file():
            self.skipTest("generated native tables not present")
        self.native = _parse_tables(_INC.read_text(encoding="utf-8"))

    def test_generated_tables_match_python_source_of_truth(self):
        for native_name, attr in _EXPECTED.items():
            self.assertIn(
                native_name, self.native,
                f"{native_name} not found in native/latex_command_tables.inc")
            expected = getattr(latex_commands, attr)
            self.assertEqual(
                self.native[native_name], expected,
                f"{native_name} drifted from core.latex_commands.{attr}: "
                f"only-native={sorted(self.native[native_name] - expected)} "
                f"only-python={sorted(expected - self.native[native_name])}",
            )

    def test_generated_tables_are_fresh(self):
        generator = _load_generator()
        self.assertEqual(
            generator.render(), _INC.read_text(encoding="utf-8"),
            "native/latex_command_tables.inc is stale; run "
            "native/generate_command_tables.py",
        )

    def test_native_source_uses_the_generated_tables(self):
        if not _CPP.is_file():
            self.skipTest("native source not present")
        self.assertIn(
            '#include "latex_command_tables.inc"',
            _CPP.read_text(encoding="utf-8"),
        )

    def test_lexer_uses_the_shared_sets(self):
        from editor import lexer_latex_custom as lexer
        self.assertEqual(lexer._STRUCTURE_CMDS, latex_commands.STRUCTURE_COMMANDS)
        self.assertEqual(lexer._REFERENCE_CMDS, latex_commands.REFERENCE_COMMANDS)
        self.assertEqual(lexer._VERBATIM_ENVS, latex_commands.VERBATIM_ENVIRONMENTS)


if __name__ == "__main__":
    unittest.main()
