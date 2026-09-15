"""Dependency-free BibTeX entry scanning shared by core and the UI."""

from __future__ import annotations

import re

_ENTRY_HEADER_RE = re.compile(r"@([A-Za-z][\w-]*)\s*([{(])")


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
    uncommented = re.sub(r"(?<!\\)%[^\r\n]*", "", text or "")
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


__all__ = [
    "find_bibtex_entry_end",
    "find_bibtex_keys",
    "split_bibtex_items",
]
