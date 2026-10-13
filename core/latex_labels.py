"""Label-context classifier shared by the index and the support adapter.

Given a document and its ``\\label`` definitions, guess the *kind* of entity a
label belongs to (figure, table, equation, section, ...).  The heuristic first
looks at the key prefix and then at the nearest sectioning command or
environment in the preceding text.

Both consumers used to carry their own copy of this heuristic with slightly
different maps; this is now the single implementation.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from core.latex_parser import strip_latex_comments

_LABEL_PREFIX_TYPES = {
    "fig": "figura", "figure": "figura",
    "tab": "tabella", "tbl": "tabella", "table": "tabella",
    "eq": "equazione", "eqn": "equazione",
    "sec": "sezione", "sect": "sezione", "section": "sezione",
    "sub": "sottosezione", "subsec": "sottosezione",
    "ch": "capitolo", "chap": "capitolo",
    "alg": "algoritmo", "algo": "algoritmo",
    "lst": "codice", "listing": "codice", "code": "codice",
    "thm": "teorema", "theorem": "teorema", "lem": "lemma",
    "prop": "proposizione", "cor": "corollario",
    "def": "definizione", "app": "appendice",
}
_ENVIRONMENT_TYPES = {
    "figure": "figura", "figure*": "figura", "subfigure": "figura",
    "table": "tabella", "table*": "tabella",
    "equation": "equazione", "equation*": "equazione",
    "align": "equazione", "align*": "equazione",
    "gather": "equazione", "gather*": "equazione",
    "eqnarray": "equazione", "eqnarray*": "equazione",
    "multline": "equazione", "multline*": "equazione",
    "flalign": "equazione", "flalign*": "equazione",
    "algorithm": "algoritmo", "algorithm2e": "algoritmo",
    "lstlisting": "codice", "verbatim": "codice", "minted": "codice",
    "theorem": "teorema", "thm": "teorema", "lemma": "lemma",
    "lem": "lemma", "proposition": "proposizione",
    "corollary": "corollario", "definition": "definizione",
    "defn": "definizione", "proof": "dimostrazione", "frame": "slide",
}
_SECTION_TYPES = {
    "part": "parte", "chapter": "capitolo",
    "section": "sezione", "subsection": "sottosezione",
    "subsubsection": "sottosottosezione",
    "paragraph": "paragrafo", "subparagraph": "sottoparagrafo",
}
_SECTION_RE = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)")
_ENV_RE = re.compile(r"\\begin\{([^}]+)\}")


class SourceText(NamedTuple):
    """Minimal source view for :func:`label_contexts`."""

    path: object
    text: str


def label_contexts(definitions, sources) -> list[tuple[str, str]]:
    """Return sorted ``(key, kind)`` for the unique label definitions."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    source_by_path = {source.path: source for source in sources}
    for definition in definitions:
        key = str(definition["key"])
        if key in seen:
            continue
        seen.add(key)
        prefix = key.split(":", 1)[0].casefold() if ":" in key else ""
        if prefix in _LABEL_PREFIX_TYPES:
            result.append((key, _LABEL_PREFIX_TYPES[prefix]))
            continue
        source = source_by_path.get(definition.get("file"))
        if source is None:
            source = next((item for item in sources if item.path is None), None)
        context = ""
        if source is not None:
            start = int(definition.get("command_start", 0))
            # Match the historical helper: strip comments on the local window.
            context = strip_latex_comments(source.text[max(0, start - 600):start])
        section_matches = list(_SECTION_RE.finditer(context))
        env_matches = list(_ENV_RE.finditer(context))
        if section_matches and (
                not env_matches
                or section_matches[-1].start() >= env_matches[-1].start()):
            result.append(
                (key, _SECTION_TYPES.get(section_matches[-1].group(1), "sezione")))
        elif env_matches:
            env_name = env_matches[-1].group(1).casefold()
            result.append((key, _ENVIRONMENT_TYPES.get(env_name, "label")))
        else:
            result.append((key, "label"))
    return sorted(result, key=lambda item: item[0])


__all__ = ["SourceText", "label_contexts"]
