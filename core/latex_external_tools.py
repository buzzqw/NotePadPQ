"""Safe, reusable wrappers for external LaTeX tools.

The functions in this module deliberately accept and produce argument vectors,
never shell command strings.  They are suitable for use from a worker thread:
``run_external_command`` has both a wall-clock timeout and cooperative
cancellation, and terminates the child process when either limit is reached.

Line and column numbers in :class:`LatexDiagnostic` are one-based, matching the
conventions used by ChkTeX, lacheck, and most editor protocols.  Formatting is
an all-or-nothing operation: ``format_latex`` returns its input unless
``latexindent`` exits successfully.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_COMMAND_TIMEOUT: Final[float] = 10.0
DEFAULT_OUTPUT_LIMIT: Final[int] = 1024 * 1024
_POLL_INTERVAL: Final[float] = 0.02
_TERMINATE_TIMEOUT: Final[float] = 0.25


class CancellationToken:
    """Small thread-safe cancellation token for external tool operations."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_cancelled(self) -> bool:
        """Return whether cancellation was requested.

        This method makes the token usable anywhere a callable cancellation
        predicate is accepted.
        """
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class LatexDiagnostic:
    """A diagnostic emitted by ChkTeX or lacheck.

    ``file`` is the path as reported by the tool, or ``None`` when a tool did
    not identify one.  ``line`` and ``column`` are one-based when present.
    ``code`` contains a checker code such as ChkTeX's ``1`` when available.
    """

    file: str | None
    line: int | None
    column: int | None
    message: str
    severity: str
    source: str
    code: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalCommandResult:
    """Bounded result of one external command invocation."""

    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    output_limited: bool = False
    error: str | None = None
    diagnostics: tuple[LatexDiagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.cancelled
            and not self.output_limited
            and self.error is None
        )


Cancellation = CancellationToken | threading.Event | Callable[[], bool]


def _is_cancelled(token: Cancellation | None) -> bool:
    if token is None:
        return False
    if isinstance(token, (CancellationToken, threading.Event)):
        return token.is_set() if isinstance(token, threading.Event) else token.cancelled
    try:
        return bool(token())
    except Exception:
        # A broken cancellation callback must not accidentally skip the tool's
        # timeout or make a worker thread fail unexpectedly.
        return False


def _argv(values: Iterable[str | os.PathLike[str]]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, os.PathLike)):
        raise TypeError("external commands must be argument sequences, not strings")
    result: list[str] = []
    for value in values:
        if not isinstance(value, (str, os.PathLike)):
            raise TypeError("external command arguments must be strings or paths")
        item = os.fspath(value)
        if isinstance(item, bytes):
            raise TypeError("external command arguments must be text")
        if "\x00" in item:
            raise ValueError("external command arguments cannot contain NUL bytes")
        result.append(item)
    if not result or not result[0]:
        raise ValueError("external command must have an executable")
    return tuple(result)


def _extra_args(values: Sequence[str | os.PathLike[str]]) -> tuple[str | os.PathLike[str], ...]:
    if isinstance(values, (str, bytes, os.PathLike)):
        raise TypeError("extra_args must be a sequence of arguments")
    return tuple(values)


def _decode(data: bytes | bytearray | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    return str(data)


class _PipeReader(threading.Thread):
    """Read a pipe without retaining more than the configured output limit."""

    def __init__(self, stream, limit: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self.data = bytearray()
        self.limited = False

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(8192)
                if not chunk:
                    return
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")
                remaining = self._limit - len(self.data)
                if remaining > 0:
                    self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.limited = True
        except (OSError, ValueError):
            # The runner closes/terminates pipes while cancelling a process.
            return


def _stop_process(process) -> None:
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=_TERMINATE_TIMEOUT)
        return
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=_TERMINATE_TIMEOUT)
    except Exception:
        pass


def run_external_command(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
    cancel: Cancellation | None = None,
    input_text: str | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> ExternalCommandResult:
    """Run one executable without a shell and with bounded lifetime/output.

    ``argv`` must be an argument vector; passing a shell command string is
    rejected.  ``cancel`` may be a :class:`CancellationToken`, a
    ``threading.Event``, or a zero-argument predicate.  Process-start errors
    are represented in ``error`` rather than raised so callers can safely use
    this helper for optional tools.
    """
    command = _argv(argv)
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if output_limit <= 0:
        raise ValueError("output_limit must be greater than zero")
    if input_text is not None and not isinstance(input_text, str):
        raise TypeError("input_text must be a string or None")

    if _is_cancelled(cancel):
        return ExternalCommandResult(command, None, "", "", cancelled=True)

    try:
        process = subprocess.Popen(
            list(command),
            cwd=os.fspath(cwd) if cwd is not None else None,
            env=env,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except Exception as exc:
        return ExternalCommandResult(command, None, "", "", error=str(exc))

    readers = [
        _PipeReader(process.stdout, output_limit),
        _PipeReader(process.stderr, output_limit),
    ]
    for reader in readers:
        reader.start()

    if input_text is not None:
        input_bytes = input_text.encode("utf-8")

        def write_input() -> None:
            try:
                process.stdin.write(input_bytes)
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                return

        threading.Thread(target=write_input, daemon=True).start()

    timed_out = False
    cancelled = False
    output_limited = False
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        output_limited = any(reader.limited for reader in readers)
        if output_limited:
            _stop_process(process)
            break
        if _is_cancelled(cancel):
            cancelled = True
            _stop_process(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _stop_process(process)
            break
        time.sleep(_POLL_INTERVAL)

    for reader in readers:
        reader.join(timeout=_TERMINATE_TIMEOUT)
    # A process can exit just as a pipe exceeds its limit.
    output_limited = output_limited or any(reader.limited for reader in readers)
    try:
        returncode = process.returncode
    except Exception:
        returncode = None
    return ExternalCommandResult(
        command,
        returncode,
        _decode(readers[0].data),
        _decode(readers[1].data),
        timed_out=timed_out,
        cancelled=cancelled,
        output_limited=output_limited,
    )


_CHK_TEX_RE = re.compile(
    r"^\s*(?P<severity>Warning|Error|Info)\s+(?P<code>\d+)\s+in\s+"
    r"(?P<file>.+?)\s+line\s+(?P<line>\d+)\s*(?:column\s+(?P<column>\d+)\s*)?"
    r"(?:--\s*)?(?P<message>.*)$",
    re.IGNORECASE,
)
_FILE_LINE_RE = re.compile(
    r"^\s*(?P<file>(?:[A-Za-z]:[\\/])?[^:\n]+?):(?P<line>\d+)"
    r"(?::(?P<column>\d+))?(?:\s*:\s*|\s+-\s*|\s+)(?P<message>.+?)\s*$"
)
_QUOTED_LINE_RE = re.compile(
    r'^\s*["\']?(?P<file>.+?)["\']?,\s*line\s+(?P<line>\d+)'
    r"(?:,\s*column\s+(?P<column>\d+))?\s*:\s*(?P<message>.+?)\s*$",
    re.IGNORECASE,
)
_SEVERITY_RE = re.compile(r"\b(error|warning|info|fatal)\b", re.IGNORECASE)
_AUXILIARY_COMMANDS = (
    ("makeglossaries", re.compile(r"\\makeglossaries\b")),
    ("nomencl", re.compile(r"\\makenomenclature\b")),
    ("makeindex", re.compile(r"\\makeindex\b|\\printindex\b")),
)


def _diagnostic_from_match(match: re.Match[str], source: str) -> LatexDiagnostic:
    groups = match.groupdict()
    severity_match = _SEVERITY_RE.search(groups.get("message", ""))
    severity = groups.get("severity", "").lower()
    if not severity:
        severity = severity_match.group(1).lower() if severity_match else "warning"
    if severity == "fatal":
        severity = "error"
    return LatexDiagnostic(
        file=groups.get("file", "").strip().strip('"\''),
        line=int(groups["line"]) if groups.get("line") else None,
        column=int(groups["column"]) if groups.get("column") else None,
        message=groups.get("message", "").strip(),
        severity=severity,
        source=source,
        code=groups.get("code"),
    )


def parse_latex_diagnostics(
    output: str,
    *,
    source: str = "latex",
    default_file: str | os.PathLike[str] | None = None,
) -> list[LatexDiagnostic]:
    """Parse common ChkTeX/lacheck ``file:line[:column]`` diagnostics."""
    fallback = os.fspath(default_file) if default_file is not None else None
    diagnostics: list[LatexDiagnostic] = []
    seen: set[tuple[object, ...]] = set()
    for raw_line in output.splitlines():
        match = (
            _CHK_TEX_RE.match(raw_line)
            or _QUOTED_LINE_RE.match(raw_line)
            or _FILE_LINE_RE.match(raw_line)
        )
        if match is None:
            continue
        diagnostic = _diagnostic_from_match(match, source)
        if diagnostic.file is None or not diagnostic.file:
            diagnostic = LatexDiagnostic(
                fallback,
                diagnostic.line,
                diagnostic.column,
                diagnostic.message,
                diagnostic.severity,
                diagnostic.source,
                diagnostic.code,
            )
        key = (
            diagnostic.file,
            diagnostic.line,
            diagnostic.column,
            diagnostic.message,
            diagnostic.source,
        )
        if key not in seen:
            seen.add(key)
            diagnostics.append(diagnostic)
    return diagnostics


def detect_latex_auxiliary_tools(text: str) -> tuple[str, ...]:
    """Return auxiliary index/glossary tools requested by LaTeX source."""
    if not isinstance(text, str):
        return ()
    # A percent in an escaped command is not a comment marker.
    code = re.sub(r"(?<!\\)%[^\n]*", "", text)
    return tuple(name for name, pattern in _AUXILIARY_COMMANDS if pattern.search(code))


def quote_command(argv: Sequence[str | os.PathLike[str]]) -> str:
    """Quote an argument vector for the existing shell-based task runner."""
    values = [os.fspath(value) for value in _argv(argv)]
    if os.name == "nt":
        return subprocess.list2cmdline(values)
    return shlex.join(values)


def _run_checker(
    executable: str,
    file_path: str | os.PathLike[str],
    *,
    source: str,
    extra_args: Sequence[str | os.PathLike[str]],
    cwd: str | os.PathLike[str] | None,
    timeout: float,
    cancel: Cancellation | None,
    output_limit: int,
) -> ExternalCommandResult:
    path = os.fspath(file_path)
    command = _argv((executable, *_extra_args(extra_args), path))
    result = run_external_command(
        command,
        cwd=cwd,
        timeout=timeout,
        cancel=cancel,
        output_limit=output_limit,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    diagnostics = parse_latex_diagnostics(output, source=source, default_file=path)
    return ExternalCommandResult(
        result.argv,
        result.returncode,
        result.stdout,
        result.stderr,
        result.timed_out,
        result.cancelled,
        result.output_limited,
        result.error,
        tuple(diagnostics),
    )


def run_chktex(
    file_path: str | os.PathLike[str],
    *,
    executable: str = "chktex",
    extra_args: Sequence[str | os.PathLike[str]] = (),
    cwd: str | os.PathLike[str] | None = None,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
    cancel: Cancellation | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> ExternalCommandResult:
    """Run ChkTeX and attach parsed diagnostics to the result."""
    return _run_checker(
        executable,
        file_path,
        source="chktex",
        extra_args=extra_args,
        cwd=cwd,
        timeout=timeout,
        cancel=cancel,
        output_limit=output_limit,
    )


def run_lacheck(
    file_path: str | os.PathLike[str],
    *,
    executable: str = "lacheck",
    extra_args: Sequence[str | os.PathLike[str]] = (),
    cwd: str | os.PathLike[str] | None = None,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
    cancel: Cancellation | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> ExternalCommandResult:
    """Run lacheck and attach parsed diagnostics to the result."""
    return _run_checker(
        executable,
        file_path,
        source="lacheck",
        extra_args=extra_args,
        cwd=cwd,
        timeout=timeout,
        cancel=cancel,
        output_limit=output_limit,
    )


def format_latex(
    text: str,
    *,
    file_path: str | os.PathLike[str] | None = None,
    executable: str = "latexindent",
    extra_args: Sequence[str | os.PathLike[str]] = (),
    cwd: str | os.PathLike[str] | None = None,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
    cancel: Cancellation | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> str:
    """Return one formatted replacement, or ``text`` if formatting fails.

    The source is sent over stdin and ``-`` tells latexindent to write the
    formatted document to stdout.  No source file is changed by this helper.
    ``file_path`` only supplies a default working directory and is never
    interpolated into a shell command.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if cwd is None and file_path is not None:
        cwd = Path(file_path).parent
    try:
        result = run_external_command(
            _argv((executable, *_extra_args(extra_args), "-")),
            cwd=cwd,
            timeout=timeout,
            cancel=cancel,
            input_text=text,
            output_limit=output_limit,
        )
    except Exception:
        return text
    return result.stdout if result.ok else text


def makeindex_command(
    index_file: str | os.PathLike[str],
    *,
    executable: str = "makeindex",
    extra_args: Sequence[str | os.PathLike[str]] = (),
) -> list[str]:
    """Build an argv for makeindex without invoking a shell."""
    return list(_argv((executable, *_extra_args(extra_args), index_file)))


def makeglossaries_command(
    tex_file: str | os.PathLike[str],
    *,
    executable: str = "makeglossaries",
    extra_args: Sequence[str | os.PathLike[str]] = (),
) -> list[str]:
    """Build an argv for makeglossaries, which expects a basename."""
    path = Path(tex_file)
    basename = path.with_suffix("") if path.suffix.lower() == ".tex" else path
    return list(_argv((executable, *_extra_args(extra_args), basename)))


def nomencl_command(
    source: str | os.PathLike[str],
    *,
    executable: str = "makeindex",
    style_file: str | os.PathLike[str] | None = "nomencl.ist",
    output_file: str | os.PathLike[str] | None = None,
    extra_args: Sequence[str | os.PathLike[str]] = (),
) -> list[str]:
    """Build the makeindex invocation used to process a nomenclature file."""
    path = Path(source)
    input_file = path.with_suffix(".nlo") if path.suffix.lower() == ".tex" else path
    args: list[str | os.PathLike[str]] = [executable, *_extra_args(extra_args)]
    if style_file is not None:
        args.extend(("-s", style_file))
    if output_file is not None or (style_file is not None and str(style_file) != "nomencl.ist"):
        output = output_file if output_file is not None else Path(input_file).with_suffix(".nls")
        args.extend(("-o", output))
        args.append(input_file)
    elif style_file is not None:
        args.extend((Path(input_file).with_suffix(".nls"), input_file))
    else:
        args.append(input_file)
    return list(_argv(args))


__all__ = [
    "CancellationToken",
    "DEFAULT_COMMAND_TIMEOUT",
    "DEFAULT_OUTPUT_LIMIT",
    "ExternalCommandResult",
    "LatexDiagnostic",
    "format_latex",
    "detect_latex_auxiliary_tools",
    "makeglossaries_command",
    "makeindex_command",
    "nomencl_command",
    "parse_latex_diagnostics",
    "quote_command",
    "run_chktex",
    "run_external_command",
    "run_lacheck",
]
