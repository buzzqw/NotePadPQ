from __future__ import annotations

import sys
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


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
