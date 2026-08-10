"""Contesto riutilizzabile per progetti LaTeX multi-file.

Il modulo descrive il progetto senza avviare compilazione o anteprima. La
raccolta degli inclusi delega a :mod:`editor.latex_support`, così parser,
estensioni implicite e gestione dei cicli restano in un solo punto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_TEX_EXTENSIONS = (".tex", ".ltx", ".latex")
_ROOT_MARKER_RE = re.compile(
    r"^[ \t]*%[ \t]*!TEX[ \t]+root[ \t]*(?:=|:)[ \t]*(?P<path>[^%\r\n]+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\s*\[[^]]*\])?\s*\{", re.IGNORECASE)
_LATEXMK_ROOT_RE = re.compile(
    r"(?:root_filename|default_files)\s*=\s*(?:\(\s*)?['\"]([^'\"(),\s]+)",
    re.IGNORECASE,
)


def _resolved(path: str | Path) -> Path:
    """Normalizza un percorso senza richiedere che esista."""
    return Path(path).expanduser().resolve()


def resolve_relative_path(base_dir: str | Path, reference: str | Path) -> Path:
    """Risolvi ``reference`` rispetto a ``base_dir``.

    I percorsi assoluti restano assoluti; il risultato è normalizzato ma non
    deve necessariamente esistere. ``base_dir`` è sempre una directory, non
    il file che contiene il riferimento.
    """
    ref = Path(reference).expanduser()
    return _resolved(ref if ref.is_absolute() else Path(base_dir) / ref)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _latex_code(text: str) -> str:
    """Usa lo stesso trattamento dei commenti del supporto LaTeX esistente."""
    from editor.latex_support import strip_latex_comments

    return strip_latex_comments(text)


def _tex_candidate(base_dir: Path, reference: str | Path) -> Path:
    """Restituisce il candidato esistente più probabile per un riferimento TeX."""
    path = resolve_relative_path(base_dir, reference)
    candidates: Iterable[Path] = (path,)
    if path.suffix == "":
        candidates = (path, *(path.with_suffix(ext) for ext in _TEX_EXTENSIONS))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if path.suffix == "":
        return path.with_suffix(".tex")
    return path


def _ancestor_directories(directory: Path) -> Iterable[Path]:
    """Yield ``directory`` and its parents, once each."""
    current = directory
    while True:
        yield current
        if current.parent == current:
            return
        current = current.parent


def _is_document_root(path: Path) -> bool:
    return bool(_DOCUMENTCLASS_RE.search(_latex_code(_read_text(path))))


def resolve_project_root(current_file: str | Path, content: str | None = None) -> Path:
    """Determina il file radice del progetto LaTeX.

    La priorità è: marker ``% !TEX root = ...`` nel contenuto corrente,
    ``main.tex`` (o altra estensione TeX) in una directory antenata, il file
    corrente se contiene ``\\documentclass`` e infine il primo sorgente
    antenato plausibile che contiene ``\\documentclass``. Se nessun indizio è
    disponibile, viene restituito il file corrente.
    """
    current = _resolved(current_file)
    source = _read_text(current) if content is None else content

    marker = _ROOT_MARKER_RE.search(source)
    if marker:
        candidate = _tex_candidate(current.parent, marker.group("path").strip())
        if candidate.is_file():
            return candidate.resolve()

    for directory in _ancestor_directories(current.parent):
        latexmkrc = directory / ".latexmkrc"
        if not latexmkrc.is_file():
            continue
        match = _LATEXMK_ROOT_RE.search(_read_text(latexmkrc))
        if match:
            candidate = _tex_candidate(directory, match.group(1))
            if candidate.is_file():
                return candidate.resolve()
        break

    for directory in _ancestor_directories(current.parent):
        for extension in _TEX_EXTENSIONS:
            main = directory / f"main{extension}"
            if main.is_file():
                return main.resolve()

    if _DOCUMENTCLASS_RE.search(_latex_code(source)):
        return current

    for directory in _ancestor_directories(current.parent):
        candidates = sorted(
            (path for extension in _TEX_EXTENSIONS for path in directory.glob(f"*{extension}")),
            key=lambda path: path.name.lower(),
        )
        for candidate in candidates:
            if _is_document_root(candidate):
                return candidate.resolve()

    return current


def collect_included_files(root_file: str | Path, max_depth: int = 5) -> list[Path]:
    """Raccoglie ``root_file`` e i sorgenti inclusi, in ordine di visita.

    La logica di parsing è quella di ``LaTeXSupport.collect_project_files``;
    sono quindi supportati gli stessi comandi e la stessa gestione dei cicli.
    """
    from editor.latex_support import LaTeXSupport

    return LaTeXSupport.collect_project_files(_resolved(root_file), max_depth=max_depth)


def get_output_directory(root_file: str | Path, output_dir: str | Path | None = None) -> Path:
    """Restituisce la directory degli artefatti, di default accanto al root.

    Un ``output_dir`` relativo è interpretato rispetto alla directory del file
    radice; uno assoluto viene usato così com'è. La directory non viene creata.
    """
    root = _resolved(root_file)
    if output_dir is None:
        return root.parent
    return resolve_relative_path(root.parent, output_dir)


def expected_pdf_path(root_file: str | Path, output_dir: str | Path | None = None) -> Path:
    """Calcola il percorso del PDF prodotto dal file radice."""
    root = _resolved(root_file)
    return get_output_directory(root, output_dir) / f"{root.stem}.pdf"


@dataclass(frozen=True, slots=True)
class LatexProjectContext:
    """Contesto immutabile per interrogare un progetto LaTeX."""

    current_file: Path
    content: str | None = None
    output_dir: Path | None = None
    root: Path = field(init=False)

    def __post_init__(self) -> None:
        current = _resolved(self.current_file)
        output = None if self.output_dir is None else Path(self.output_dir)
        object.__setattr__(self, "current_file", current)
        object.__setattr__(self, "output_dir", output)
        object.__setattr__(self, "root", resolve_project_root(current, self.content))

    @property
    def output_directory(self) -> Path:
        """Directory configurata per gli artefatti del progetto."""
        return get_output_directory(self.root, self.output_dir)

    @property
    def pdf_path(self) -> Path:
        """Percorso del PDF atteso per il file radice."""
        return expected_pdf_path(self.root, self.output_dir)

    def resolve_path(self, reference: str | Path, base_dir: str | Path | None = None) -> Path:
        """Risolvi un riferimento rispetto al root o a una directory esplicita."""
        return resolve_relative_path(self.root.parent if base_dir is None else base_dir, reference)

    def included_files(self, max_depth: int = 5) -> list[Path]:
        """Restituisce i file del progetto raggiungibili dal root."""
        return collect_included_files(self.root, max_depth=max_depth)


__all__ = [
    "LatexProjectContext",
    "collect_included_files",
    "expected_pdf_path",
    "get_output_directory",
    "resolve_project_root",
    "resolve_relative_path",
]
