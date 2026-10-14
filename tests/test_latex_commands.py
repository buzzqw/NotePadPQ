"""Guard the single source of truth for LaTeX command classification.

The optional C++ accelerator (native/latex_native.cpp) cannot import Python,
so its tables are parsed here and compared with ``core.latex_commands``.  This
turns "keep the two lists in sync by hand" into a failing test the moment they
diverge.
"""

import re
import unittest
from pathlib import Path

from core import latex_commands

_CPP = Path(__file__).resolve().parent.parent / "native" / "latex_native.cpp"

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


class NativeClassifierSyncTest(unittest.TestCase):
    def setUp(self):
        if not _CPP.is_file():
            self.skipTest("native source not present")
        self.native = {
            name: frozenset(_STRING_RE.findall(body))
            for name, body in _SET_RE.findall(_CPP.read_text(encoding="utf-8"))
        }

    def test_cpp_tables_match_python_source_of_truth(self):
        for native_name, attr in _EXPECTED.items():
            self.assertIn(native_name, self.native,
                          f"{native_name} not found in native/latex_native.cpp")
            expected = getattr(latex_commands, attr)
            self.assertEqual(
                self.native[native_name], expected,
                f"{native_name} drifted from core.latex_commands.{attr}: "
                f"only-native={sorted(self.native[native_name] - expected)} "
                f"only-python={sorted(expected - self.native[native_name])}",
            )

    def test_lexer_uses_the_shared_sets(self):
        from editor import lexer_latex_custom as lexer
        self.assertEqual(lexer._STRUCTURE_CMDS, latex_commands.STRUCTURE_COMMANDS)
        self.assertEqual(lexer._REFERENCE_CMDS, latex_commands.REFERENCE_COMMANDS)
        self.assertEqual(lexer._VERBATIM_ENVS, latex_commands.VERBATIM_ENVIRONMENTS)


if __name__ == "__main__":
    unittest.main()
