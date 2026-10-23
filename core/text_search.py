"""Ricerca letterale tollerante alle varianti tipografiche.

Quando si cerca del testo scritto con apostrofi, virgolette o trattini
"tipografici" (’, “, –) capita spesso che il documento usi i corrispondenti
caratteri ASCII (' e ").  Lo stesso vale per le lettere accentate salvate in
forma composta (NFC) o decomposta (NFD).

:func:`literal_search_pattern` costruisce un'espressione regolare che tratta
queste varianti come equivalenti **senza modificare il testo**: ogni
alternativa consuma esattamente i caratteri originali, quindi gli offset
restituiti da ``finditer`` restano validi per QScintilla.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Gruppi di caratteri considerati equivalenti in una ricerca letterale.
_CHARACTER_GROUPS = (
    "'’‘‛′",                    # apostrofo ASCII e tipografico
    '"“”„‟″',                   # virgolette doppie
    "-–—−",                     # hyphen, en/em dash, segno meno
    " \u00a0\u2009\u202f",      # spazio, NBSP, thin space, narrow NBSP
)

_CHARACTER_CLASS: dict[str, str] = {}
for _group in _CHARACTER_GROUPS:
    _escaped = "".join(re.escape(char) for char in _group)
    for _char in _group:
        _CHARACTER_CLASS[_char] = _escaped


def _build_fold_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for group, canonical in zip(
        _CHARACTER_GROUPS, ("'", '"', "-", " "), strict=True
    ):
        for char in group:
            table[char] = canonical
    return table


_FOLD = str.maketrans(_build_fold_table())


def fold_typography(text: str) -> str:
    """Riporta apostrofi, virgolette, trattini e spazi alla forma ASCII.

    La sostituzione è uno-a-uno, quindi la lunghezza della stringa non cambia.
    """
    return text.translate(_FOLD)


@lru_cache(maxsize=256)
def literal_search_source(query: str) -> str:
    """Restituisce il sorgente regex di una ricerca letterale tollerante.

    Il sorgente usa soltanto costrutti supportati sia da :mod:`re` sia dal
    motore C++11 di QScintilla: classi di caratteri e gruppi non catturanti.
    """
    normalized = unicodedata.normalize("NFC", query)
    pieces: list[str] = []
    index = 0
    while index < len(normalized):
        # Sequenze tipografiche con lunghezza diversa: "..." ↔ "…" e "--" ↔ "—".
        if normalized.startswith("...", index):
            pieces.append(r"(?:\.\.\.|…)")
            index += 3
            continue
        if normalized.startswith("--", index):
            pieces.append(r"(?:--|—|–)")
            index += 2
            continue

        char = normalized[index]
        index += 1
        if char == "…":
            pieces.append(r"(?:…|\.\.\.)")
            continue
        if char in "—–":
            pieces.append(r"(?:[-–—−]|--)")
            continue
        group = _CHARACTER_CLASS.get(char)
        if group is not None:
            pieces.append(f"[{group}]")
            continue
        decomposed = unicodedata.normalize("NFD", char)
        if decomposed != char:
            # Accento composto (à) o decomposto (a + segno combinante).
            variants = sorted((char, decomposed), key=len, reverse=True)
            pieces.append("(?:" + "|".join(re.escape(v) for v in variants) + ")")
        else:
            pieces.append(re.escape(char))
    return "".join(pieces)


@lru_cache(maxsize=256)
def literal_search_pattern(
    query: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
) -> re.Pattern[str]:
    """Compila una ricerca letterale tollerante alle varianti tipografiche."""
    source = literal_search_source(query)
    if whole_word:
        source = rf"\b(?:{source})\b"
    return re.compile(source, 0 if case_sensitive else re.IGNORECASE)
