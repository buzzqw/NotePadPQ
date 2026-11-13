"""Find in Files: le scorciatoie (prefiltro, righe candidate) devono dare
esattamente i risultati del vecchio loop riga per riga."""

from __future__ import annotations

import random
import re

import pytest

from core.text_search import literal_search_source
from ui.find_replace import (
    _MAX_FIND_ENTRIES_PER_FILE,
    _FindInFilesWorker,
    _search_text,
    _whole_text_prefilter,
)


def _reference(text: str, pattern: re.Pattern):
    """Il loop originale di _FindInFilesWorker.run."""
    count = 0
    hits = []
    for i, line in enumerate(text.split("\n")):
        found = list(pattern.finditer(line))
        if found:
            count += len(found)
            if len(hits) < _MAX_FIND_ENTRIES_PER_FILE:
                hits.append((i, line, found[0].start(), found[0].end()))
    return count, hits


WORDS = ["alfa", "Beta", "città", "cafe\u0301", "l'uomo", "l’uomo", "a  b", "--", "…",
         "x", "", "foo bar", "\\section", "{", "}", "\t"]

REGEXES = [r"\w+", r"^a", r"a$", r"\s+", r"b\s*a", r"(?i)alfa", r"(?<!l)'", r"x(?!y)",
           r"\Aalfa", r"alfa\Z", r"^$", r"[^a]+", r"(?:Beta|città)", r"\bx\b", r"\\section\{",
           r"a|", r".", r"(?P<w>alfa)(?P=w)?", r"\d*"]


def _random_text(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randrange(0, 40)):
        lines.append(" ".join(rng.choice(WORDS) for _ in range(rng.randrange(0, 6))))
    newline = rng.choice(["\n", "\r\n"])
    return newline.join(lines) + rng.choice(["", newline])


@pytest.mark.parametrize("seed", range(30))
def test_literal_and_regex_searches_match_the_line_loop(seed):
    rng = random.Random(seed)
    for _ in range(40):
        text = _random_text(rng)
        if rng.random() < 0.5:
            query = rng.choice([w for w in WORDS if w]) if rng.random() < 0.8 else "alfa\nBeta"
            source = literal_search_source(query)
            literal = "\n" not in query
        else:
            source = rng.choice(REGEXES)
            literal = False
        flags = rng.choice([0, re.IGNORECASE])
        pattern = re.compile(source, flags)
        prefilter = _whole_text_prefilter(source, flags)
        assert _search_text(text, pattern, prefilter, literal) == _reference(text, pattern), (
            source, text)


def test_prefilter_is_disabled_for_line_sensitive_constructs():
    assert _whole_text_prefilter(r"\Aalfa", 0) is None
    assert _whole_text_prefilter(r"alfa\Z", 0) is None
    assert _whole_text_prefilter(r"x(?!y)", 0) is None
    assert _whole_text_prefilter(r"(?<=a)b", 0) is None
    assert _whole_text_prefilter(r"(?i)alfa", 0) is None
    assert _whole_text_prefilter(r"(?:a|b)(?P<n>c)(?P=n)", 0) is not None
    assert _whole_text_prefilter(r"^alfa$", 0).flags & re.MULTILINE


def test_chunked_search_matches_the_line_loop(monkeypatch):
    """Blocchi minuscoli: i confini cadono ovunque, i risultati no."""
    import ui.find_replace as fr

    monkeypatch.setattr(fr, "_SEARCH_CHUNK_CHARS", 7)
    original = fr._line_chunks
    monkeypatch.setattr(fr, "_line_chunks", lambda text, size=7: original(text, size))
    rng = random.Random(99)
    for _ in range(400):
        text = _random_text(rng)
        source = rng.choice(REGEXES + [literal_search_source(w) for w in WORDS if w])
        literal = source not in REGEXES
        pattern = re.compile(source, re.IGNORECASE)
        prefilter = _whole_text_prefilter(source, re.IGNORECASE)
        assert _search_text(text, pattern, prefilter, literal) == _reference(text, pattern), (
            source, text)


def test_entries_are_capped_but_all_matches_are_counted():
    text = "alfa\n" * (_MAX_FIND_ENTRIES_PER_FILE + 50)
    pattern = re.compile("alfa")
    count, hits = _search_text(text, pattern, _whole_text_prefilter("alfa", 0), True)
    assert count == _MAX_FIND_ENTRIES_PER_FILE + 50
    assert len(hits) == _MAX_FIND_ENTRIES_PER_FILE


def test_worker_reports_the_same_files_and_lines(tmp_path, qtbot):
    (tmp_path / "a.txt").write_text("niente\nqui c'è alfa\nalfa alfa\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nessun risultato\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.tex").write_bytes(b"\\section{Alfa}\r\nfine\r\n")
    worker = _FindInFilesWorker(str(tmp_path), [], "alfa", False, False, True)
    results = {}
    worker.file_done.connect(
        lambda rel, _abs, count, entries: results.__setitem__(
            rel, (count, [(e.line_num, e.line_text, e.col_start, e.col_end) for e in entries])))
    worker.run()
    assert results == {
        "a.txt": (3, [(2, "qui c'è alfa", 8, 12), (3, "alfa alfa", 0, 4)]),
        str(sub.relative_to(tmp_path) / "c.tex"): (1, [(1, "\\section{Alfa}\r", 9, 13)]),
    }
