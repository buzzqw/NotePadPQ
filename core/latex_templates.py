"""Catalogo di template LaTeX built-in e configurabili.

I template configurabili sono file ``.tex`` (o senza estensione) collocati in
``.notepadpq/templates`` oppure nella sua sottodirectory ``latex``. I template
di progetto hanno precedenza su quelli utente, che a loro volta sostituiscono
i built-in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


_TEMPLATE_SUFFIXES = {"", ".tex", ".ltx", ".latex"}
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_VARIABLE_RE = re.compile(r"\{\{\s*(title|author|date|language)\s*\}\}")


_BUILTIN_TEMPLATES = {
    "article": r"""\documentclass[11pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[{{language}}]{babel}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{hyperref}

\title{{{title}}}
\author{{{author}}}
\date{{{date}}}

\begin{document}
\maketitle

\end{document}
""",
    "report": r"""\documentclass[11pt,a4paper]{report}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[{{language}}]{babel}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{hyperref}

\title{{{title}}}
\author{{{author}}}
\date{{{date}}}

\begin{document}
\maketitle
\tableofcontents

\chapter{Introduction}

\end{document}
""",
    "beamer": r"""\documentclass{beamer}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[{{language}}]{babel}

\title{{{title}}}
\author{{{author}}}
\date{{{date}}}

\begin{document}
\begin{frame}
    \titlepage
\end{frame}

\end{document}
""",
}

# Public read-only view useful to callers that want to display built-ins.
BUILTIN_TEMPLATES: Mapping[str, str] = MappingProxyType(_BUILTIN_TEMPLATES)


@dataclass(frozen=True, slots=True)
class LatexTemplate:
    """Template disponibile nel catalogo e relativa origine."""

    name: str
    content: str
    source: Path | None = None

    @property
    def is_builtin(self) -> bool:
        return self.source is None


def normalize_template_name(name: str | Path | None) -> str | None:
    """Restituisce il nome canonico sicuro, oppure ``None``.

    I nomi sono identificatori singoli, non percorsi: sono quindi rifiutati
    separatori, nomi riservati e caratteri fuori da lettere, numeri, ``._-``.
    Un'estensione LaTeX finale è facoltativa.
    """
    if not isinstance(name, (str, Path)):
        return None
    value = str(name).strip()
    if not value or value in {".", ".."}:
        return None
    if Path(value).is_absolute() or "/" in value or "\\" in value:
        return None

    suffix = Path(value).suffix.lower()
    if suffix in {".tex", ".ltx", ".latex"}:
        value = value[: -len(suffix)]
    if not value or not _SAFE_NAME_RE.fullmatch(value):
        return None
    return value


def _name_from_file(path: Path) -> str | None:
    if path.name.startswith(".") or path.suffix.lower() not in _TEMPLATE_SUFFIXES:
        return None
    return normalize_template_name(path.stem if path.suffix else path.name)


def _template_directories(base: Path | None) -> tuple[Path, ...]:
    """Restituisce directory generica e specifica senza uscire dal config root."""
    if base is None:
        return ()
    base = Path(base).expanduser()
    if base.name == "latex" and base.parent.name == "templates":
        return (base,)
    if base.name == "templates":
        return (base, base / "latex")
    root = base / ".notepadpq" / "templates"
    return (root, root / "latex")


def _project_template_bases(base: Path | None) -> tuple[Path, ...]:
    """Restituisce gli antenati, dal progetto più esterno al file corrente."""
    if base is None:
        return ()
    current = Path(base).expanduser().resolve()
    ancestors = []
    while True:
        ancestors.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(reversed(ancestors))


def _safe_file(path: Path, directory: Path) -> Path | None:
    """Accetta solo file che restano dentro la directory configurata."""
    try:
        resolved_directory = directory.resolve()
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_directory)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved_path if resolved_path.is_file() else None


class LatexTemplateCatalog:
    """Catalogo con precedenza built-in, utente, poi progetto.

    ``user_dir`` e ``project_dir`` sono directory radice. Per l'utente, se
    omesso, viene usata la home dell'utente corrente; passare una directory
    ``templates`` o ``latex`` è supportato per facilitare test e configurazioni
    personalizzate.
    """

    def __init__(
        self,
        project_dir: str | Path | None = None,
        user_dir: str | Path | None = None,
        fallback: str = "article",
    ) -> None:
        self.project_dir = None if project_dir is None else Path(project_dir).expanduser()
        self.user_dir = Path.home() if user_dir is None else Path(user_dir).expanduser()
        self.fallback = normalize_template_name(fallback) or "article"
        self._templates: dict[str, LatexTemplate] = {}
        self.reload()

    def reload(self) -> None:
        """Ricarica built-in e file configurabili dal filesystem."""
        templates = {
            name: LatexTemplate(name=name, content=content)
            for name, content in _BUILTIN_TEMPLATES.items()
        }
        # L'ordine è importante: ogni directory successiva può fare override.
        for base in (self.user_dir,):
            for directory in _template_directories(base):
                self._load_directory(directory, templates)
        for base in _project_template_bases(self.project_dir):
            for directory in _template_directories(base):
                self._load_directory(directory, templates)
        self._templates = templates

    @staticmethod
    def _load_directory(directory: Path, templates: dict[str, LatexTemplate]) -> None:
        try:
            files = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            return

        for file_path in files:
            name = _name_from_file(file_path)
            if name is None:
                continue
            safe_path = _safe_file(file_path, directory)
            if safe_path is None:
                continue
            try:
                content = safe_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                # Un template danneggiato non deve nascondere il fallback.
                continue
            templates[name] = LatexTemplate(name=name, content=content, source=safe_path)

    @property
    def templates(self) -> Mapping[str, LatexTemplate]:
        """Vista read-only dei template caricati, indicizzata per nome."""
        return MappingProxyType(self._templates)

    def list_templates(self) -> tuple[str, ...]:
        """Restituisce i nomi sicuri disponibili in ordine alfabetico."""
        return tuple(sorted(self._templates, key=str.casefold))

    def names(self) -> tuple[str, ...]:
        """Alias leggibile per :meth:`list_templates`."""
        return self.list_templates()

    def get(self, name: str | Path | None, fallback: str | None = None) -> LatexTemplate:
        """Restituisce un template o un built-in valido come fallback."""
        safe_name = normalize_template_name(name)
        if safe_name is not None and safe_name in self._templates:
            return self._templates[safe_name]

        fallback_name = normalize_template_name(fallback) if fallback is not None else self.fallback
        if fallback_name in self._templates:
            return self._templates[fallback_name]
        return LatexTemplate("article", _BUILTIN_TEMPLATES["article"])

    def load(self, name: str | Path | None, fallback: str | None = None) -> str:
        """Restituisce il solo contenuto del template richiesto."""
        return self.get(name, fallback).content

    def render(
        self,
        name: str | Path | None,
        variables: Mapping[str, object] | None = None,
        *,
        fallback: str | None = None,
        **values: object,
    ) -> str:
        """Carica e renderizza un template con le quattro variabili supportate.

        Placeholder sconosciuti restano invariati; questo consente ai template
        di contenere sintassi LaTeX o futuri placeholder senza corromperli.
        """
        context: dict[str, object] = {
            "title": "",
            "author": "",
            "date": date.today().isoformat(),
            "language": "english",
        }
        if variables is not None:
            context.update(variables)
        context.update(values)
        return _VARIABLE_RE.sub(
            lambda match: str(context.get(match.group(1), "")),
            self.load(name, fallback),
        )


def list_latex_templates(
    project_dir: str | Path | None = None,
    user_dir: str | Path | None = None,
) -> tuple[str, ...]:
    """Elenca i template disponibili senza creare dipendenze dalla UI."""
    return LatexTemplateCatalog(project_dir=project_dir, user_dir=user_dir).list_templates()


def load_latex_template(
    name: str | Path | None,
    project_dir: str | Path | None = None,
    user_dir: str | Path | None = None,
    fallback: str = "article",
) -> str:
    """Carica un template LaTeX con fallback sicuro."""
    return LatexTemplateCatalog(
        project_dir=project_dir,
        user_dir=user_dir,
        fallback=fallback,
    ).load(name)


def render_latex_template(
    name: str | Path | None,
    variables: Mapping[str, object] | None = None,
    project_dir: str | Path | None = None,
    user_dir: str | Path | None = None,
    fallback: str = "article",
    **values: object,
) -> str:
    """Carica e renderizza un template LaTeX con fallback sicuro."""
    return LatexTemplateCatalog(
        project_dir=project_dir,
        user_dir=user_dir,
        fallback=fallback,
    ).render(name, variables, **values)


__all__ = [
    "BUILTIN_TEMPLATES",
    "LatexTemplate",
    "LatexTemplateCatalog",
    "list_latex_templates",
    "load_latex_template",
    "normalize_template_name",
    "render_latex_template",
]
