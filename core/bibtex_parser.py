"""Dependency-free BibTeX entry scanning shared by core and the UI."""

from __future__ import annotations

import re

_ENTRY_HEADER_RE = re.compile(r"@([A-Za-z][\w-]*)\s*([{(])")
_BIB_COMMENT_RE = re.compile(r"(?<!\\)%[^\r\n]*")


def split_bibtex_items(text: str) -> list[str]:
    """Split an entry body on top-level commas, respecting braces and quotes."""
    items: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char in "{(":
            depth += 1
        elif not quoted and char in "})":
            depth = max(0, depth - 1)
        elif char == "," and not quoted and depth == 0:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    return items


def find_bibtex_entry_end(
    text: str,
    opening_index: int,
    opening: str,
) -> int | None:
    """Return the matching closing delimiter for a BibTeX entry."""
    closing = "}" if opening == "{" else ")"
    depth = 0
    quoted = False
    escaped = False
    for index in range(opening_index, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == opening:
            depth += 1
        elif not quoted and char == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def find_bibtex_keys(text: str) -> list[str]:
    """Extract ordinary entry keys, excluding comments and metadata entries."""
    uncommented = _BIB_COMMENT_RE.sub("", text or "")
    ignored = {"comment", "preamble", "string"}
    keys: list[str] = []
    index = 0
    while index < len(uncommented):
        match = _ENTRY_HEADER_RE.match(uncommented, index)
        if not match:
            index += 1
            continue
        end = find_bibtex_entry_end(uncommented, match.end() - 1, match.group(2))
        if end is None:
            index = match.end()
            continue
        parts = split_bibtex_items(uncommented[match.end():end])
        if match.group(1).lower() not in ignored and parts and parts[0].strip():
            keys.append(parts[0].strip())
        index = end + 1
    return keys


def _clean_bib_value(value: str) -> str:
    value = value.strip().rstrip(",").strip()
    while len(value) >= 2 and (
        (value[0] == "{" and value[-1] == "}")
        or (value[0] == '"' and value[-1] == '"')
    ):
        value = value[1:-1].strip()
    return " ".join(value.split())


def _first_author_surname(author: str) -> str:
    first = author.split(" and ", 1)[0].strip()
    if not first:
        return ""
    if "," in first:
        return first.split(",", 1)[0].strip()
    parts = first.split()
    return parts[-1] if parts else ""


def parse_bibtex_entries(text: str) -> dict[str, dict[str, str]]:
    """Return ``{key: metadata}`` for ordinary BibTeX entries.

    Metadata contains the entry type plus the fields useful in a citation
    popup: first author surname, year and title.  The parser is deliberately
    forgiving; malformed entries are skipped instead of raising.
    """
    uncommented = _BIB_COMMENT_RE.sub("", text or "")
    ignored = {"comment", "preamble", "string"}
    entries: dict[str, dict[str, str]] = {}
    index = 0
    while index < len(uncommented):
        match = _ENTRY_HEADER_RE.match(uncommented, index)
        if not match:
            index += 1
            continue
        end = find_bibtex_entry_end(
            uncommented, match.end() - 1, match.group(2)
        )
        if end is None:
            index = match.end()
            continue
        entry_type = match.group(1).lower()
        parts = split_bibtex_items(uncommented[match.end():end])
        index = end + 1
        if entry_type in ignored or not parts:
            continue
        key = parts[0].strip()
        if not key:
            continue
        fields: dict[str, str] = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip().casefold()
            if name:
                fields[name] = _clean_bib_value(value)
        author = fields.get("author", "")
        year = fields.get("year", "")
        if not year:
            date = fields.get("date", "")
            if date:
                year = date[:4]
        entries[key] = {
            "type": entry_type,
            "author": _first_author_surname(author),
            "year": year,
            "title": fields.get("title", ""),
        }
    return entries


__all__ = [
    "find_bibtex_entry_end",
    "find_bibtex_keys",
    "parse_bibtex_entries",
    "split_bibtex_items",
]
