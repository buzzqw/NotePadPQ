"""Small, dependency-free reader for TeXstudio-style ``.cwl`` files.

The format is intentionally parsed conservatively.  A malformed line is
ignored (or reduced to its command name) and no executable or structured data
is evaluated.  Directory arguments are ordered from lowest to highest
precedence.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_COMMAND_RE = re.compile(r"^(\\[A-Za-z@]+)(\*?)(.*)$")
_GROUP_RE = re.compile(r"(\[[^\]]*\]|\{[^{}]*\})")
_DESCRIPTION_RE = re.compile(
    r"#D(?:\{([^{}]*)\}|\s+(.*?))"
    r"(?=\s*#(?:S|N\{\d+\}|[MO]\{[^{}]*\})\s*$|$)"
)
_PACKAGE_DESCRIPTION_RE = re.compile(
    r"^[#%]\s*(?:package|description)\s*:\s*(.+)$", re.IGNORECASE
)


@dataclass(frozen=True)
class CWLArgument:
    """One command argument as written in a CWL signature."""

    name: str
    optional: bool = False


@dataclass(frozen=True)
class CWLCommand:
    """A parsed command completion entry."""

    name: str
    signature: str
    arguments: tuple[CWLArgument, ...] = ()
    description: str = ""
    package: str = ""
    star: bool = False

    @property
    def command(self) -> str:
        """Alias matching the terminology used by CWL files."""
        return self.name

    @property
    def completion(self) -> str:
        """Return the safe insertion form used by QScintilla."""
        base = f"{self.name}*" if self.star else self.name
        if not self.arguments:
            return base
        suffix = "".join("[]" if arg.optional else "{}" for arg in self.arguments)
        return f"{base}{suffix}"

    def as_api_term(self) -> str:
        term = f"{self.completion}?1"
        return f"{term}\n{self.description}" if self.description else term


@dataclass(frozen=True)
class CWLEnvironment:
    """An environment supplied by a CWL package."""

    name: str
    description: str = ""
    package: str = ""


@dataclass
class CWLPackage:
    """All entries loaded from one package file."""

    name: str
    source: Path | None = None
    description: str = ""
    commands: dict[str, CWLCommand] = field(default_factory=dict)
    environments: dict[str, CWLEnvironment] = field(default_factory=dict)

    @property
    def package(self) -> str:
        return self.name


@dataclass
class CWLModel:
    """Merged CWL completion data."""

    packages: dict[str, CWLPackage] = field(default_factory=dict)
    commands: dict[str, CWLCommand] = field(default_factory=dict)
    environments: dict[str, CWLEnvironment] = field(default_factory=dict)

    @property
    def package_names(self) -> list[str]:
        return sorted(package.name for package in self.packages.values())

    def commands_for(self, packages: Iterable[str]) -> list[CWLCommand]:
        wanted = {str(package).strip().casefold() for package in packages}
        return [command for command in self.commands.values()
                if command.package.casefold() in wanted]

    def environments_for(self, packages: Iterable[str]) -> list[CWLEnvironment]:
        wanted = {str(package).strip().casefold() for package in packages}
        return [environment for environment in self.environments.values()
                if environment.package.casefold() in wanted]


def _description_and_metadata(line: str) -> tuple[str, str, bool, int | None]:
    """Split a command line into its signature and supported CWL metadata."""
    description = ""
    star = bool(re.search(r"#S(?:\s|$)", line))
    number_match = re.search(r"#N\{(\d+)\}", line)
    number = int(number_match.group(1)) if number_match else None
    description_match = _DESCRIPTION_RE.search(line)
    if description_match:
        description = (description_match.group(1) or description_match.group(2) or "").strip()
        line = line[:description_match.start()].rstrip()

    # These markers describe completion metadata rather than literal text.
    line = re.sub(r"#(?:S|N\{\d+\}|[MO]\{[^{}]*\})", "", line).rstrip()
    return line, description, star, number


def parse_cwl(text: str, package: str = "", source: Path | None = None) -> CWLPackage:
    """Parse a CWL string without raising for malformed input.

    The package name normally comes from the file name and is supplied by the
    loader.  ``#D{...}`` descriptions, optional ``[...]`` arguments, ``#S``
    star variants, and ``#N{n}`` argument counts are supported.  ``\\begin``
    entries are exposed as environments.
    """
    package_name = str(package or "").strip()
    result = CWLPackage(package_name, source=source)
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%") or line.startswith("#"):
            match = _PACKAGE_DESCRIPTION_RE.match(line)
            if match and not result.description:
                result.description = match.group(1).strip()
            continue

        signature, description, star, number = _description_and_metadata(line)
        match = _COMMAND_RE.match(signature)
        if not match:
            continue

        name, explicit_star, tail = match.groups()
        star = star or bool(explicit_star)
        groups = _GROUP_RE.findall(tail)
        arguments = tuple(
            CWLArgument(group[1:-1].strip(), group.startswith("["))
            for group in groups
        )
        if number is not None and not arguments:
            arguments = tuple(CWLArgument("") for _ in range(number))

        if name == r"\begin" and groups:
            environment_name = groups[0][1:-1].strip()
            if environment_name:
                result.environments[environment_name.casefold()] = CWLEnvironment(
                    environment_name, description, package_name
                )
            continue
        if name == r"\end":
            continue

        command = CWLCommand(
            name=name,
            signature=signature,
            arguments=arguments,
            description=description,
            package=package_name,
            star=star,
        )
        result.commands[name.casefold()] = command
    return result


def parse_cwl_file(path: Path) -> CWLPackage:
    """Read one CWL file, returning an empty package on I/O or decode errors."""
    path = Path(path)
    package = path.stem
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return CWLPackage(package, source=path)
    return parse_cwl(text, package, path)


def _iter_cwl_files(directory: Path) -> list[Path]:
    try:
        return sorted(
            (path for path in Path(directory).iterdir()
             if path.is_file() and path.suffix.casefold() == ".cwl"),
            key=lambda path: (path.name.casefold(), path.name),
        )
    except (OSError, TypeError):
        return []


def load_cwl_directories(directories: Sequence[Path | str]) -> CWLModel:
    """Load immediate ``.cwl`` files in low-to-high precedence order.

    A higher-precedence file with the same package name replaces the complete
    lower-precedence package.  Commands and environments from different
    packages are also resolved in the same deterministic file order.
    """
    packages: dict[str, CWLPackage] = {}
    seen_directories: set[Path] = set()
    for raw_directory in directories:
        try:
            directory = Path(raw_directory).expanduser().resolve()
        except (OSError, TypeError, ValueError):
            continue
        if directory in seen_directories:
            continue
        seen_directories.add(directory)
        for path in _iter_cwl_files(directory):
            parsed = parse_cwl_file(path)
            if not parsed.commands and not parsed.environments and not parsed.description:
                continue
            packages[parsed.name.casefold()] = parsed

    model = CWLModel(packages=packages)
    # Dict assignment deliberately makes the later source win while retaining
    # stable ordering for entries that do not collide.
    for package in packages.values():
        for key, command in package.commands.items():
            model.commands[key] = command
        for key, environment in package.environments.items():
            model.environments[key] = environment
    return model


def _configured_directories() -> list[Path]:
    directories: list[Path] = []
    try:
        from config.settings import Settings
        configured = Settings.instance().get("latex/cwl_directories", [])
    except Exception:
        configured = []
    if isinstance(configured, str):
        configured = configured.split(os.pathsep)
    if isinstance(configured, (list, tuple)):
        for value in configured:
            try:
                if str(value).strip():
                    directories.append(Path(value))
            except (TypeError, ValueError):
                continue
    env_directories = os.environ.get("NOTEPADPQ_CWL_DIRS", "")
    for value in env_directories.split(os.pathsep):
        try:
            if value:
                directories.append(Path(value))
        except (TypeError, ValueError):
            continue
    return directories


def cwl_directories(
    project_path: Path | None = None,
    configured: Sequence[Path | str] | None = None,
    built_in: Path | None = None,
    user: Path | None = None,
) -> list[Path]:
    """Return built-in, user, configured, then project CWL directories."""
    result = [Path(built_in) if built_in is not None else Path(__file__).parent / "cwl"]
    if user is None:
        try:
            from core.platform import get_config_dir
            user = get_config_dir() / "cwl"
        except Exception:
            user = Path.home() / ".config" / "NotePadPQ" / "cwl"
    result.append(Path(user))
    for value in (configured or _configured_directories()):
        try:
            result.append(Path(value))
        except (TypeError, ValueError):
            continue

    if project_path:
        path = Path(project_path).expanduser()
        root = path if path.is_dir() else path.parent
        try:
            from core.latex_project import resolve_project_root
            if path.is_file():
                resolved = resolve_project_root(path)
                if resolved:
                    root = Path(resolved).parent
        except (OSError, RuntimeError, ValueError):
            pass
        # Accept project-root files as well as the less noisy conventional
        # ``.cwl`` and ``cwl`` subdirectories.
        result.extend((root, root / ".cwl", root / "cwl"))

    unique: list[Path] = []
    seen: set[Path] = set()
    for directory in result:
        try:
            normalized = directory.expanduser().resolve()
        except (OSError, TypeError, ValueError):
            continue
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def load_cwl_for_project(
    project_path: Path | None = None,
    configured: Sequence[Path | str] | None = None,
) -> CWLModel:
    """Lazily load the configured CWL sources for a document/project."""
    return load_cwl_directories(cwl_directories(project_path, configured=configured))


class CWLParser:
    """Compatibility facade for callers preferring an object-oriented API."""

    parse = staticmethod(parse_cwl)
    parse_file = staticmethod(parse_cwl_file)
    load_directories = staticmethod(load_cwl_directories)
