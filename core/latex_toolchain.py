"""Read-only discovery of the command-line LaTeX toolchain.

This module only inspects executable availability and asks each executable for
its version. It does not compile documents, create files, or perform any work
at import time.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from threading import RLock
from typing import Final

TOOL_NAMES: Final[tuple[str, ...]] = (
    "pdflatex",
    "xelatex",
    "lualatex",
    "latexmk",
    "bibtex",
    "biber",
    "synctex",
    "texdoc",
    "chktex",
    "lacheck",
    "latexindent",
    "makeindex",
    "makeglossaries",
)
"""Executables included in a toolchain report, in stable display order."""

DEFAULT_VERSION_TIMEOUT: Final[float] = 2.0
"""Maximum number of seconds allowed for an individual version probe."""

_STATUS_AVAILABLE = "available"
_STATUS_MISSING = "missing"
_STATUS_FAILED = "failed"
_STATUS_TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class ToolInfo:
    """Availability and version-probe result for one executable.

    ``available`` and ``path`` describe the result of ``shutil.which``.
    ``status`` is ``"available"`` when the version probe succeeds, or one of
    ``"missing"``, ``"failed"``, and ``"timeout"`` otherwise. A present tool
    therefore has ``available=True`` even when its probe cannot be completed.
    """

    name: str
    available: bool
    path: str | None
    version: str | None
    status: str


_CACHE: dict[tuple[str, str], dict[str, ToolInfo]] = {}
_CACHE_LOCK = RLock()


def _context_key(context: str | os.PathLike[str] | None) -> str:
    if context is None:
        return ""
    return os.fspath(context)


def _version_line(result: subprocess.CompletedProcess[str]) -> str | None:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    for line in output.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def _probe_version(
    name: str,
    executable: str,
    path_value: str,
    timeout: float,
) -> ToolInfo:
    """Probe one known executable without allowing errors to escape."""
    probe_environment = os.environ.copy()
    probe_environment["PATH"] = path_value
    version_args = () if name == "makeindex" else ("--version",)
    try:
        result = subprocess.run(
            [executable, *version_args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=probe_environment,
        )
    except subprocess.TimeoutExpired:
        return ToolInfo(name, True, executable, None, _STATUS_TIMEOUT)
    except Exception:
        # A broken wrapper, decoding problem, or platform-specific subprocess
        # error should make this tool unknown, not break the whole report.
        return ToolInfo(name, True, executable, None, _STATUS_FAILED)

    if result.returncode != 0:
        return ToolInfo(name, True, executable, _version_line(result), _STATUS_FAILED)
    return ToolInfo(name, True, executable, _version_line(result), _STATUS_AVAILABLE)


def _detect(path_value: str, timeout: float) -> dict[str, ToolInfo]:
    report: dict[str, ToolInfo] = {}
    for name in TOOL_NAMES:
        try:
            executable = shutil.which(name, path=path_value)
        except Exception:
            executable = None

        if executable is None:
            report[name] = ToolInfo(name, False, None, None, _STATUS_MISSING)
        else:
            report[name] = _probe_version(name, executable, path_value, timeout)
    return report


def detect_latex_toolchain(
    *,
    path: str | os.PathLike[str] | None = None,
    context: str | os.PathLike[str] | None = None,
    refresh: bool = False,
    timeout: float = DEFAULT_VERSION_TIMEOUT,
) -> dict[str, ToolInfo]:
    """Return read-only availability data for the supported LaTeX tools.

    ``path`` is the PATH to inspect and defaults to the current process PATH.
    ``context`` is an optional caller-defined cache namespace, useful when the
    same PATH is used for different project or environment contexts. Results
    are cached by PATH and context. Set ``refresh=True`` to replace that entry;
    no subprocess is started until this function is called.

    The returned dictionary is a copy of the cached mapping. Its ``ToolInfo``
    values are immutable, so callers cannot alter cached results.
    """
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    path_value = os.environ.get("PATH", "") if path is None else os.fspath(path)
    cache_key = (path_value, _context_key(context))
    with _CACHE_LOCK:
        if not refresh and cache_key in _CACHE:
            return dict(_CACHE[cache_key])
        report = _detect(path_value, timeout)
        _CACHE[cache_key] = report
        return dict(report)


def clear_latex_toolchain_cache() -> None:
    """Discard all cached reports so the next detection probes again."""
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "DEFAULT_VERSION_TIMEOUT",
    "TOOL_NAMES",
    "ToolInfo",
    "clear_latex_toolchain_cache",
    "detect_latex_toolchain",
]
