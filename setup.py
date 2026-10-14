from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

_ROOT = Path(__file__).resolve().parent


def _generate_native_tables() -> None:
    """Regenerate native/latex_command_tables.inc from core.latex_commands.

    The C++ accelerator cannot import Python, so its command tables are
    generated from the single Python source of truth.  Regenerating here keeps
    every build (pip, setup.sh, CI, packaging) in sync instead of compiling a
    stale include.
    """
    generator = _ROOT / "native" / "generate_command_tables.py"
    if not generator.is_file():
        return
    spec = importlib.util.spec_from_file_location("_npq_generate_tables", generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main([])


class OptionalBuildExt(build_ext):
    """Build the accelerator when possible without making it mandatory."""

    def run(self):
        try:
            super().run()
        except Exception as exc:  # pragma: no cover - compiler/platform dependent
            self.announce(
                f"NotePadPQ: native LaTeX accelerator unavailable ({exc}); using Python fallback",
                level=3,
            )

    def build_extension(self, extension):
        try:
            _generate_native_tables()
        except Exception as exc:  # pragma: no cover - keep the committed include
            self.announce(
                f"NotePadPQ: could not regenerate native command tables ({exc}); "
                "using the committed include",
                level=3,
            )
        try:
            super().build_extension(extension)
        except Exception as exc:  # pragma: no cover - compiler/platform dependent
            self.announce(
                f"NotePadPQ: could not compile {extension.name} ({exc}); using Python fallback",
                level=3,
            )


compile_args = ["/O2"] if sys.platform == "win32" else ["-O3"]

setup(
    ext_modules=[
        Extension(
            "core._latex_native",
            ["native/latex_native.cpp"],
            language="c++",
            extra_compile_args=compile_args,
        )
    ],
    cmdclass={"build_ext": OptionalBuildExt},
)
