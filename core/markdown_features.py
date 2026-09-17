"""Pure Markdown productivity helpers.

This module deliberately has no Qt dependency.  It contains the small,
deterministic transformations used by the Markdown toolbar and by workspace
link navigation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_ATX_RE = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.+?)\s*$")
_SETEXT_RE = re.compile(r"^\s*(=+|-+)\s*$")
_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
_MERMAID_RE = re.compile(
    r"(?P<fence>^\s*```+\s*mermaid\s*$)(?P<body>.*?)(?P<close>^\s*```+\s*$)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class MarkdownHeading:
    level: int
    title: str
    line: int
    slug: str


@dataclass(frozen=True)
class WikiLink:
    target: str
    label: str
    start: int
    end: int


@dataclass(frozen=True)
class TocResult:
    text: str
    cursor: int
    heading_count: int
    updated: bool


@dataclass(frozen=True)
class MermaidBlock:
    start: int
    end: int
    body: str


def _strip_inline_markdown(value: str) -> str:
    value = re.sub(r"!?(?:\[([^\]]+)\])(?:\([^)]*\)|\[[^]]*\])", r"\1", value)
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return " ".join(value.split()).strip("# ")


def _slugify(value: str) -> str:
    value = _strip_inline_markdown(value).casefold()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[-\s]+", "-", value).strip("-")
    return value or "section"


def extract_headings(text: str) -> list[MarkdownHeading]:
    """Extract ATX and setext headings, ignoring fenced code blocks."""
    lines = text.splitlines()
    result: list[MarkdownHeading] = []
    used_slugs: dict[str, int] = {}
    fence_char: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char = marker[0]
            elif marker[0] == fence_char:
                fence_char = None
            i += 1
            continue
        if fence_char is not None:
            i += 1
            continue

        match = _ATX_RE.match(line)
        if match:
            level = len(match.group(1))
            title = _strip_inline_markdown(re.sub(r"\s+#+\s*$", "", match.group(2)))
        elif (
            line.strip()
            and i + 1 < len(lines)
            and _SETEXT_RE.match(lines[i + 1])
            and not line.lstrip().startswith(("- ", "* ", "+ ", "> "))
        ):
            level = 1 if lines[i + 1].lstrip().startswith("=") else 2
            title = _strip_inline_markdown(line)
            i += 1
        else:
            i += 1
            continue

        if title:
            base = _slugify(title)
            count = used_slugs.get(base, 0)
            used_slugs[base] = count + 1
            slug = base if count == 0 else f"{base}-{count}"
            result.append(MarkdownHeading(level, title, i + 1, slug))
        i += 1
    return result


def generate_toc(text: str, min_level: int = 1, max_level: int = 3) -> str:
    """Return a GitHub-compatible nested Markdown TOC without markers."""
    min_level = max(1, min(6, min_level))
    max_level = max(min_level, min(6, max_level))
    headings = [h for h in extract_headings(text) if min_level <= h.level <= max_level]
    if not headings:
        return ""
    base = min(h.level for h in headings)
    return "\n".join(
        f"{'  ' * max(0, h.level - base)}- [{h.title}](#{h.slug})"
        for h in headings
    )


def insert_or_update_toc(
    text: str,
    cursor: int | None = None,
    min_level: int = 1,
    max_level: int = 3,
) -> TocResult:
    """Insert or replace a ``<!-- TOC -->`` block."""
    start_marker = "<!-- TOC -->"
    end_marker = "<!-- /TOC -->"
    block = f"{start_marker}\n{generate_toc(text, min_level, max_level)}\n{end_marker}"
    pattern = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker),
        re.DOTALL,
    )
    match = pattern.search(text)
    if match:
        new_text = text[:match.start()] + block + text[match.end():]
        new_cursor = match.start() + len(block)
        return TocResult(new_text, new_cursor, len(extract_headings(text)), True)

    position = len(text) if cursor is None else max(0, min(len(text), cursor))
    prefix = "" if position == 0 or text[:position].endswith("\n") else "\n"
    suffix = "" if position == len(text) or text[position:].startswith("\n") else "\n"
    inserted = prefix + block + suffix
    new_text = text[:position] + inserted + text[position:]
    return TocResult(new_text, position + len(inserted), len(extract_headings(text)), False)


def extract_wikilinks(text: str) -> list[WikiLink]:
    """Return ``[[target]]`` and ``[[target|display]]`` occurrences."""
    return [
        WikiLink(
            target=part.split("|", 1)[0].strip(),
            label=(part.split("|", 1)[1].strip() if "|" in part else part.strip()),
            start=match.start(),
            end=match.end(),
        )
        for match in _WIKILINK_RE.finditer(text)
        for part in [match.group(1)]
        if part.split("|", 1)[0].strip()
    ]


def expand_wikilinks_for_preview(text: str) -> str:
    """Convert wikilinks to safe Markdown links for the HTML preview.

    Fenced code blocks are left untouched so examples of ``[[target]]`` remain
    code.  The custom URI is handled by :class:`PreviewPanel` and never written
    back to the source document.
    """
    lines: list[str] = []
    fence_char: str | None = None
    for line in text.splitlines(keepends=True):
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char = marker[0]
            elif marker[0] == fence_char:
                fence_char = None
            lines.append(line)
            continue
        if fence_char is not None:
            lines.append(line)
            continue

        def replace(match: re.Match[str]) -> str:
            part = match.group(1)
            target, separator, label = part.partition("|")
            target = target.strip()
            label = label.strip() if separator else target
            if not target:
                return match.group(0)
            return f"[{label}](npq-wikilink:{quote(target, safe='')})"

        lines.append(_WIKILINK_RE.sub(replace, line))
    return "".join(lines)


def wikilink_at(text: str, position: int) -> WikiLink | None:
    for link in extract_wikilinks(text):
        if link.start <= position <= link.end:
            return link
    return None


def resolve_wikilink_target(
    target: str,
    current_file: Path | None,
    workspace_root: Path | None = None,
) -> Path | None:
    """Resolve a wikilink using the current folder, workspace, then filename."""
    clean = target.strip().split("#", 1)[0].strip()
    if not clean:
        return None
    candidates: list[Path] = []
    roots = [p for p in (current_file.parent if current_file else None, workspace_root) if p]
    raw = Path(clean)
    for root in roots:
        candidates.append(root / raw)
        if raw.suffix == "":
            candidates.extend((root / f"{clean}{ext}") for ext in (".md", ".markdown"))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue

    root = workspace_root or (current_file.parent if current_file else None)
    if root and root.is_dir():
        wanted = raw.name.casefold()
        wanted_stem = raw.stem.casefold()
        try:
            for candidate in root.rglob("*"):
                if not candidate.is_file() or candidate.suffix.casefold() not in {".md", ".markdown"}:
                    continue
                if ".git" in candidate.parts or "node_modules" in candidate.parts:
                    continue
                if candidate.name.casefold() == wanted or candidate.stem.casefold() == wanted_stem:
                    return candidate.resolve()
        except OSError:
            pass
    return None


def find_backlinks(
    files: Iterable[Path], target: Path, workspace_root: Path | None = None
) -> list[Path]:
    """Find Markdown files containing a wikilink resolving to ``target``."""
    target_resolved = target.resolve()
    result: list[Path] = []
    for path in files:
        try:
            if path.resolve() == target_resolved or path.suffix.casefold() not in {".md", ".markdown"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for link in extract_wikilinks(text):
                root = workspace_root or target.parent
                if resolve_wikilink_target(link.target, path, root) == target_resolved:
                    result.append(path)
                    break
        except OSError:
            continue
    return result


def is_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https", "ftp"} and bool(parsed.netloc)


def is_image_url(value: str) -> bool:
    if not is_url(value):
        return False
    path = urlparse(value.strip()).path.casefold()
    return path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tif", ".tiff"))


def smart_paste_markdown(clipboard: str, selected: str = "") -> str | None:
    """Return a Markdown replacement for a URL paste, or ``None``."""
    value = clipboard.strip()
    if selected and is_url(value):
        return f"[{selected}](<{value}>)" if ")" in value else f"[{selected}]({value})"
    if not selected and is_image_url(value):
        return f"![]({value})"
    return None


MERMAID_TEMPLATES: dict[str, str] = {
    "flowchart": "```mermaid\nflowchart TD\n    A[Start] --> B[End]\n```",
    "sequence": "```mermaid\nsequenceDiagram\n    Alice->>Bob: Hello Bob\n    Bob-->>Alice: Hello Alice\n```",
    "class": "```mermaid\nclassDiagram\n    class NotePadPQ\n    NotePadPQ : +open_file()\n```",
    "state": "```mermaid\nstateDiagram-v2\n    [*] --> Draft\n    Draft --> Published\n```",
    "er": "```mermaid\nerDiagram\n    DOCUMENT ||--o{ LINK : contains\n```",
    "gantt": "```mermaid\ngantt\n    title Project\n    dateFormat YYYY-MM-DD\n    section Work\n    Task :done, task1, 2026-01-01, 3d\n```",
}


def extract_mermaid_blocks(text: str) -> list[MermaidBlock]:
    return [MermaidBlock(m.start(), m.end(), m.group("body").strip()) for m in _MERMAID_RE.finditer(text)]


def validate_mermaid(text: str) -> list[str]:
    """Perform lightweight offline validation before the preview renderer runs."""
    errors: list[str] = []
    known = {v.splitlines()[1].strip().split()[0].casefold() for v in MERMAID_TEMPLATES.values()}
    for index, block in enumerate(extract_mermaid_blocks(text), start=1):
        first = next((line.strip() for line in block.body.splitlines() if line.strip() and not line.strip().startswith("%%")), "")
        if not first:
            errors.append(f"Blocco Mermaid {index}: contenuto vuoto")
        elif first.split()[0].casefold() not in known and not first.casefold().startswith(("mindmap", "pie", "gitgraph", "timeline", "journey")):
            errors.append(f"Blocco Mermaid {index}: tipo di diagramma non riconosciuto ({first.split()[0]})")
    if text.lower().count("```mermaid") != len(extract_mermaid_blocks(text)):
        errors.append("È presente almeno un blocco Mermaid non chiuso")
    return errors
