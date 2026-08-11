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


def _ancestor_directories_bounded(directory: Path, max_depth: int = 8) -> Iterable[Path]:
    """Yield ``directory`` and its parents, once each — ma non risale oltre
    la home dell'utente né oltre ``max_depth`` livelli: senza questo limite,
    un file privo di ogni indizio di root (nessun marker ``%!TEX root``,
    nessun ``main.tex``, nessun ``\\documentclass``) fa risalire la ricerca
    fino alla radice del filesystem, scandendo ogni directory antenata.
    """
    home = Path.home()
    current = directory
    depth = 0
    while True:
        yield current
        if current == home or current.parent == current or depth >= max_depth:
            return
        current = current.parent
        depth += 1


def _is_document_root(path: Path) -> bool:
    from editor.latex_support import _cached_read_text_stripped
    try:
        stripped = _cached_read_text_stripped(path)
    except OSError:
        return False
    return bool(_DOCUMENTCLASS_RE.search(stripped))


_NOT_FOUND = object()
_ROOT_FALLBACK_CACHE: dict[Path, object] = {}
_ROOT_FALLBACK_CACHE_MAX = 256


def _find_root_by_scanning(start_dir: Path) -> Path | None:
    """Ultima spiaggia di ``resolve_project_root``: cerca tra gli antenati un
    file con ``\\documentclass``, leggendo e parsando ogni ``.tex`` trovato.

    È l'unico ramo di ``resolve_project_root`` che tocca il disco per file
    diversi da quello corrente, quindi è anche il più costoso — e viene
    invocato a ogni trigger del popup ambienti/pacchetti (praticamente a
    ogni parola scritta dopo ``\\`` in un file LaTeX). Cachato per directory
    di partenza: il progetto non cambia struttura tra un tasto e l'altro.
    """
    cached = _ROOT_FALLBACK_CACHE.get(start_dir, _NOT_FOUND)
    if cached is not _NOT_FOUND:
        return cached  # type: ignore[return-value]

    result: Path | None = None
    for directory in _ancestor_directories_bounded(start_dir):
        candidates = sorted(
            (path for extension in _TEX_EXTENSIONS for path in directory.glob(f"*{extension}")),
            key=lambda path: path.name.lower(),
        )
        for candidate in candidates:
            if _is_document_root(candidate):
                result = candidate.resolve()
                break
        if result is not None:
            break

    if len(_ROOT_FALLBACK_CACHE) >= _ROOT_FALLBACK_CACHE_MAX:
        _ROOT_FALLBACK_CACHE.clear()
    _ROOT_FALLBACK_CACHE[start_dir] = result
    return result


def resolve_project_root(current_file: str | Path, content: str | None = None) -> Path:
    """Determina il file radice del progetto LaTeX.

    La priorità è: marker ``% !TEX root = ...`` nel contenuto corrente,
    ``main.tex`` (o altra estensione TeX) in una directory antenata, il file
    corrente se contiene ``\\documentclass`` e infine il primo sorgente
    antenato plausibile che contiene ``\\documentclass``. Se nessun indizio è
    disponibile, viene restituito il file corrente.
    """
    current = _resolved(current_file)
    if content is None:
        # Nessun contenuto "live" passato dal chiamante (caso comune per
        # collect_project_files, cwl.py, ecc.): usa la cache condivisa per
        # path+mtime invece di rileggere il file da disco a ogni chiamata —
        # per un file di dimensioni non banali, ripetuto a ogni tasto
        # premuto in contesto \begin/\end, il costo diventava percepibile.
        from editor.latex_support import _cached_read_text
        try:
            source = _cached_read_text(current)
        except OSError:
            source = ""
    else:
        source = content

    # Per convenzione (TeXstudio, TeXShop, latexmk) il marker "%!TEX root="
    # vive nelle primissime righe del file: limitare la ricerca all'inizio
    # evita di far scandire alla regex MULTILINE l'intero documento — con
    # file di centinaia di KB/alcuni MB il costo diventava misurabile a
    # ogni chiamata, nonostante la cache sul contenuto.
    marker = _ROOT_MARKER_RE.search(source[:4096])
    if marker:
        candidate = _tex_candidate(current.parent, marker.group("path").strip())
        if candidate.is_file():
            return candidate.resolve()

    for directory in _ancestor_directories_bounded(current.parent):
        latexmkrc = directory / ".latexmkrc"
        if not latexmkrc.is_file():
            continue
        match = _LATEXMK_ROOT_RE.search(_read_text(latexmkrc))
        if match:
            candidate = _tex_candidate(directory, match.group(1))
            if candidate.is_file():
                return candidate.resolve()
        break

    for directory in _ancestor_directories_bounded(current.parent):
        for extension in _TEX_EXTENSIONS:
            main = directory / f"main{extension}"
            if main.is_file():
                return main.resolve()

    if content is None:
        from editor.latex_support import _cached_read_text_stripped
        try:
            stripped_source = _cached_read_text_stripped(current)
        except OSError:
            stripped_source = ""
    else:
        stripped_source = _latex_code(source)

    if _DOCUMENTCLASS_RE.search(stripped_source):
        return current

    found = _find_root_by_scanning(current.parent)
    if found is not None:
        return found

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
