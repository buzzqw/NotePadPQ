"""Small, dependency-free reader for TeXstudio-style ``.cwl`` files.

The format is intentionally parsed conservatively.  A malformed line is
ignored (or reduced to its command name) and no executable or structured data
is evaluated.  Directory arguments are ordered from lowest to highest
precedence.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

_COMMAND_RE = re.compile(r"^(\\[A-Za-z@:_]+)(\*?)(.*)$")
_GROUP_RE = re.compile(
    r"(\[[^\]]*\]|\{[^{}]*\}|\([^()]*\)|<[^<>]*>)"
)
_DESCRIPTION_RE = re.compile(
    r"#D(?:\{([^{}]*)\}|\s+(.*?))"
    r"(?=\s*#|$)"
)
_PACKAGE_DESCRIPTION_RE = re.compile(
    r"^[#%]\s*(?:package|description)\s*:\s*(.+)$", re.IGNORECASE
)


@dataclass(frozen=True)
class CWLArgument:
    """One command argument as written in a CWL signature."""

    name: str
    optional: bool = False
    opening: str = "{"
    closing: str = "}"


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
        suffix = "".join(
            f"{arg.opening}{arg.closing}" for arg in self.arguments
        )
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
    keyvals: dict[str, tuple[str, ...]] = field(default_factory=dict)
    includes: tuple[str, ...] = ()
    conditional_includes: tuple[tuple[str, tuple[str, ...]], ...] = ()

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
        if not wanted:
            return list(self.commands.values())
        commands = []
        seen: set[tuple[str, str]] = set()
        for package in self.packages.values():
            if package.name.casefold() not in wanted:
                continue
            for command in package.commands.values():
                key = (command.package.casefold(), command.name.casefold())
                if key not in seen:
                    seen.add(key)
                    commands.append(command)
        for command in self.commands.values():
            key = (command.package.casefold(), command.name.casefold())
            if command.package.casefold() in wanted and key not in seen:
                seen.add(key)
                commands.append(command)
        return commands

    def environments_for(self, packages: Iterable[str]) -> list[CWLEnvironment]:
        wanted = {str(package).strip().casefold() for package in packages}
        if not wanted:
            return list(self.environments.values())
        environments = []
        seen: set[tuple[str, str]] = set()
        for package in self.packages.values():
            if package.name.casefold() not in wanted:
                continue
            for environment in package.environments.values():
                key = (environment.package.casefold(), environment.name.casefold())
                if key not in seen:
                    seen.add(key)
                    environments.append(environment)
        for environment in self.environments.values():
            key = (environment.package.casefold(), environment.name.casefold())
            if environment.package.casefold() in wanted and key not in seen:
                seen.add(key)
                environments.append(environment)
        return environments

    def option_candidates_for(self, command: str,
                              packages: Iterable[str] = ()) -> list[str]:
        """Return optional arguments and ``#keyvals`` hints for a command."""
        wanted = {str(package).strip().casefold() for package in packages}
        command_name = str(command).casefold()
        candidates: set[str] = set()
        entries = self.commands.values() if not wanted else self.commands_for(wanted)
        for entry in entries:
            if entry.name.casefold() != command_name:
                continue
            for argument in entry.arguments:
                name = argument.name.strip().strip("<>")
                if not argument.optional or not name or (
                        name.casefold() in {"option", "options"}
                        or name.casefold().endswith("%keyvals")
                ):
                    continue
                candidates.add(name if name.endswith("=") else f"{name}=")
        for package in self.packages.values():
            if wanted and package.name.casefold() not in wanted:
                continue
            for context, entries in package.keyvals.items():
                context_name = context.split("#", 1)[0]
                base_context = context_name.split("/", 1)[0]
                if context_name == command_name or base_context == command_name:
                    candidates.update(entries)
        return sorted(candidates)


def _description_and_metadata(
    line: str,
) -> tuple[str, str, int | None, bool]:
    """Split a command line into its signature and supported CWL metadata."""
    description = ""
    hidden = bool(re.search(r"#S(?:\s|$)", line))
    number_match = re.search(r"#N\{(\d+)\}", line)
    number = int(number_match.group(1)) if number_match else None
    description_match = _DESCRIPTION_RE.search(line)
    if description_match:
        description = (description_match.group(1) or description_match.group(2) or "").strip()
        line = line[:description_match.start()].rstrip()

    # All remaining hash-suffixed classifiers are metadata, not signature text.
    metadata_start = line.find("#")
    if metadata_start >= 0:
        line = line[:metadata_start].rstrip()
    return line, description, number, hidden


def parse_cwl(text: str, package: str = "", source: Path | None = None) -> CWLPackage:
    """Parse a CWL string without raising for malformed input.

    The package name normally comes from the file name and is supplied by the
    loader.  ``#D{...}`` descriptions, optional ``[...]`` arguments, hidden
    ``#S`` entries, and ``#N{n}`` argument counts are supported.  ``\\begin``
    entries are exposed as environments.
    """
    package_name = str(package or "").strip()
    result = CWLPackage(package_name, source=source)
    includes: list[str] = []
    conditional_includes: list[tuple[str, tuple[str, ...]]] = []
    conditions: list[tuple[str, bool]] = []
    keyval_contexts: tuple[str, ...] | None = None
    keyval_entries: list[str] = []

    def finish_keyvals() -> None:
        if not keyval_contexts:
            return
        entries = tuple(dict.fromkeys(keyval_entries))
        for context in keyval_contexts:
            key = context.casefold()
            result.keyvals[key] = tuple(dict.fromkeys(
                (*result.keyvals.get(key, ()), *entries)
            ))

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if keyval_contexts is not None:
            if line.casefold().startswith("#endkeyvals"):
                finish_keyvals()
                keyval_contexts = None
                keyval_entries = []
                continue
            if line and not line.startswith("#"):
                if "#" in line:
                    key, values = line.split("#", 1)
                    key = key.strip()
                    if key.endswith("=") and values.startswith("#"):
                        keyval_entries.append(key)
                        continue
                    values = [value.strip() for value in values.split(",") if value.strip()]
                    if key and values:
                        key = key.split("=", 1)[0].strip()
                        keyval_entries.extend(
                            f"{key}={value}" for value in values
                        )
                elif "=" in line:
                    key = line.split("=", 1)[0].strip()
                    if key:
                        keyval_entries.append(f"{key}=")
                else:
                    keyval_entries.append(line)
            continue

        if line.casefold().startswith("#keyvals:"):
            header = line.split(":", 1)[1]
            contexts = tuple(
                context.strip() for context in header.split(",") if context.strip()
            )
            if contexts:
                keyval_contexts = contexts
                keyval_entries = []
            continue

        if line.casefold().startswith("#ifoption:"):
            condition = line.split(":", 1)[1].strip()
            if condition:
                conditions.append((condition, True))
            continue

        if line.casefold().startswith("#else"):
            if conditions:
                condition, enabled = conditions[-1]
                conditions[-1] = (condition, not enabled)
            continue

        if line.casefold().startswith("#endif"):
            if conditions:
                conditions.pop()
            continue

        if line.casefold().startswith("#include:"):
            include = line.split(":", 1)[1].strip()
            if include:
                if conditions:
                    conditional_includes.append((
                        include,
                        tuple(
                            condition if enabled else f"!{condition}"
                            for condition, enabled in conditions
                        ),
                    ))
                else:
                    includes.append(include)
            continue

        if not line or line.startswith("%") or line.startswith("#"):
            match = _PACKAGE_DESCRIPTION_RE.match(line)
            if match and not result.description:
                result.description = match.group(1).strip()
            continue

        signature, description, number, hidden = _description_and_metadata(line)
        if hidden:
            continue
        match = _COMMAND_RE.match(signature)
        if not match:
            continue

        name, explicit_star, tail = match.groups()
        star = bool(explicit_star)
        groups = _GROUP_RE.findall(tail)
        arguments = tuple(
            CWLArgument(
                group[1:-1].strip(),
                group.startswith("["),
                group[0],
                group[-1],
            )
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
    if keyval_contexts is not None:
        finish_keyvals()
    result.includes = tuple(dict.fromkeys(includes))
    result.conditional_includes = tuple(dict.fromkeys(conditional_includes))
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


# Cache in-processo: {directory tuple: (signature, model)}. Il chiamante più
# frequente (popup pacchetti su \usepackage{) invoca questo path in modo
# sincrono sul thread UI a ogni trigger, quindi rileggere e riparsare tutti i
# .cwl da zero ogni volta produceva uno stallo percettibile con directory
# utente/progetto popolate. La signature (path, mtime, size) costa solo
# iterdir+stat — niente lettura di contenuto — quindi resta economica anche
# quando invalida la cache.
_MODEL_CACHE: dict[tuple, tuple[tuple, CWLModel]] = {}


def _cwl_signature(directories: Sequence[Path]) -> tuple:
    signature = []
    for directory in directories:
        for path in _iter_cwl_files(directory):
            try:
                stat = path.stat()
            except OSError:
                continue
            signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def load_cwl_directories(
    directories: Sequence[Path | str],
    package_options: Mapping[str, Iterable[str]] | None = None,
) -> CWLModel:
    """Load immediate ``.cwl`` files in low-to-high precedence order.

    A higher-precedence file with the same package name replaces the complete
    lower-precedence package.  Commands and environments from different
    packages are also resolved in the same deterministic file order.

    Risultato cachato per directory set finché nessun file .cwl coinvolto
    cambia (vedi _cwl_signature): il caso comune (nessuna modifica ai .cwl
    tra un trigger di completion e il successivo) evita completamente la
    rilettura/parsing da disco.
    """
    resolved: list[Path] = []
    seen_directories: set[Path] = set()
    for raw_directory in directories:
        try:
            directory = Path(raw_directory).expanduser().resolve()
        except (OSError, TypeError, ValueError):
            continue
        if directory in seen_directories:
            continue
        seen_directories.add(directory)
        resolved.append(directory)

    normalized_options = {
        str(package).casefold(): frozenset(
            str(option).strip().casefold().split("=", 1)[0]
            for option in options
            if str(option).strip()
        )
        for package, options in (package_options or {}).items()
    }
    option_signature = tuple(sorted(
        (package, tuple(sorted(options)))
        for package, options in normalized_options.items()
    ))
    cache_key = (tuple(resolved), option_signature)
    signature = _cwl_signature(resolved)
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    packages: dict[str, CWLPackage] = {}
    for directory in resolved:
        for path in _iter_cwl_files(directory):
            parsed = parse_cwl_file(path)
            if (not parsed.commands and not parsed.environments
                    and not parsed.keyvals and not parsed.description
                    and not parsed.includes):
                continue
            packages[parsed.name.casefold()] = parsed

    effective_packages: dict[str, CWLPackage] = {}

    def resolve_package(name: str, resolving: set[str]) -> CWLPackage:
        if name in effective_packages:
            return effective_packages[name]
        package = packages[name]
        if name in resolving:
            return package

        resolving = {*resolving, name}
        commands = dict(package.commands)
        environments = dict(package.environments)
        keyvals = dict(package.keyvals)
        includes = [(raw_include, ()) for raw_include in package.includes]
        package_options_for_package = normalized_options.get(name, frozenset())
        includes.extend(
            (raw_include, conditions)
            for raw_include, conditions in package.conditional_includes
            if all(
                (condition.casefold().lstrip("!") in package_options_for_package)
                != condition.startswith("!")
                for condition in conditions
            )
        )
        for raw_include, _conditions in includes:
            include_name = Path(raw_include).stem.casefold()
            included = packages.get(include_name)
            if included is None:
                continue
            included = resolve_package(include_name, resolving)
            for key, command in included.commands.items():
                commands.setdefault(key, replace(command, package=package.name))
            for key, environment in included.environments.items():
                environments.setdefault(
                    key, replace(environment, package=package.name)
                )
            for key, entries in included.keyvals.items():
                keyvals[key] = tuple(dict.fromkeys(
                    (*keyvals.get(key, ()), *entries)
                ))

        effective = replace(
            package,
            commands=commands,
            environments=environments,
            keyvals=keyvals,
        )
        effective_packages[name] = effective
        return effective

    for name in packages:
        resolve_package(name, set())

    model = CWLModel(packages=effective_packages)
    # Dict assignment deliberately makes the later source win while retaining
    # stable ordering for entries that do not collide.
    # Resolve lazily, but merge in the original file order so later sources
    # retain their documented precedence when command names collide.
    for name in packages:
        package = effective_packages[name]
        for key, command in package.commands.items():
            model.commands[key] = command
        for key, environment in package.environments.items():
            model.environments[key] = environment
    _MODEL_CACHE[cache_key] = (signature, model)
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
    package_options: dict[str, set[str]] = {}
    if project_path is not None:
        try:
            from editor.latex_support import LaTeXSupport
            package_options = LaTeXSupport.extract_package_options_multifile(
                project_path
            )
        except Exception:
            package_options = {}
    return load_cwl_directories(
        cwl_directories(project_path, configured=configured),
        package_options=package_options,
    )


class CWLParser:
    """Compatibility facade for callers preferring an object-oriented API."""

    parse = staticmethod(parse_cwl)
    parse_file = staticmethod(parse_cwl_file)
    load_directories = staticmethod(load_cwl_directories)
