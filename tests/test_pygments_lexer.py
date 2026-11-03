"""Lo styling incrementale Pygments deve coincidere con una tokenizzazione
completa del documento, anche dopo modifiche in punti arbitrari."""

from __future__ import annotations

import random

import pytest
from PyQt6.Qsci import QsciScintilla

from editor import pygments_lexer
from editor.pygments_lexer import (
    NATIVE_LANGUAGES,
    S_COMMENT,
    S_DEFAULT,
    S_STRING,
    PygmentsLexer,
    _token_to_style,
)

GO_SOURCE = '''package main

import (
\t"fmt"
\t"strings"
)

/* Commento
   multiriga con "virgolette" e `backtick` */
type Point struct {
\tX, Y int // coordinate
}

// Somma restituisce la somma.
func Somma(a, b int) int {
\ts := `raw
string su più righe`
\t_ = s
\treturn a + b * 0x1F
}

func main() {
\tfmt.Println(strings.Repeat("è€", 3), 'x', 3.14)
}
'''


def _reference_styles(lexer: PygmentsLexer, text: str) -> list[int]:
    """Stile per byte ottenuto tokenizzando l'intero documento da zero."""
    if lexer._native_enabled:
        data = text.encode("utf-8")
        return list(pygments_lexer._code_native.style(lexer._alias, data, len(data)))
    styles: list[int] = []
    for _index, ttype, value in lexer._pygments_lexer.get_tokens_unprocessed(text):
        styles.extend([_token_to_style(ttype)] * len(value.encode("utf-8")))
    return styles[:len(text.encode("utf-8"))]


def _editor_styles(editor: QsciScintilla) -> list[int]:
    total = editor.SendScintilla(editor.SCI_GETLENGTH)
    return [editor.SendScintilla(editor.SCI_GETSTYLEAT, i) for i in range(total)]


def _make_editor(qtbot, alias: str, text: str, native: bool = False):
    """Editor con PygmentsLexer; ``native`` sceglie lo scanner C++."""
    editor = QsciScintilla()
    qtbot.addWidget(editor)
    editor.setUtf8(True)
    lexer = PygmentsLexer(alias, alias, editor)
    lexer._native_enabled = native and alias in NATIVE_LANGUAGES
    editor.setLexer(lexer)
    editor.setText(text)
    editor.SendScintilla(editor.SCI_COLOURISE, 0, -1)
    return editor, lexer


def _restyle(editor, end: int = -1) -> None:
    """Ristila come fa Scintilla durante l'uso: da endStyled, non da zero.

    ``SCI_COLOURISE(0, ...)`` chiederebbe esplicitamente di ripartire
    dall'inizio e non eserciterebbe la ripartenza incrementale.
    """
    total = editor.SendScintilla(editor.SCI_GETLENGTH)
    end = total if end < 0 else min(end, total)
    start = editor.SendScintilla(editor.SCI_GETENDSTYLED)
    if start < end:
        editor.SendScintilla(editor.SCI_COLOURISE, start, end)


def _assert_matches_reference(editor, lexer):
    text = editor.text()
    assert _editor_styles(editor) == _reference_styles(lexer, text)


def test_full_document_matches_reference(qtbot):
    editor, lexer = _make_editor(qtbot, "go", GO_SOURCE * 20)
    _assert_matches_reference(editor, lexer)


def test_random_edits_restyle_like_a_full_relex(qtbot):
    editor, lexer = _make_editor(qtbot, "go", GO_SOURCE * 40)
    rng = random.Random(7)
    snippets = ["x", " ", "\n", '"', "`", "/*", "*/", "// c\n", "é", "{\n}\n"]
    for _ in range(60):
        total = editor.SendScintilla(editor.SCI_GETLENGTH)
        pos = rng.randrange(total)
        # Le posizioni Scintilla sono in byte: allinea a un inizio carattere.
        pos = editor.SendScintilla(editor.SCI_POSITIONBEFORE,
                                   editor.SendScintilla(editor.SCI_POSITIONAFTER, pos))
        if rng.random() < 0.3 and pos + 3 < total:
            end = editor.SendScintilla(editor.SCI_POSITIONAFTER, pos)
            editor.SendScintilla(editor.SCI_DELETERANGE, pos, end - pos)
        else:
            data = rng.choice(snippets).encode("utf-8")
            editor.SendScintilla(editor.SCI_INSERTTEXT, pos, data)
        # Prima solo la finestra visibile intorno alla modifica, come al paint.
        _restyle(editor, pos + 300)
    _restyle(editor)
    _assert_matches_reference(editor, lexer)


def test_windowed_styling_matches_reference(qtbot):
    """Scintilla stila a finestre (area visibile): il risultato non cambia."""
    text = GO_SOURCE * 30
    editor, lexer = _make_editor(qtbot, "go", "")
    editor.setText(text)
    total = editor.SendScintilla(editor.SCI_GETLENGTH)
    for end in range(400, total + 400, 400):
        _restyle(editor, end)
    _assert_matches_reference(editor, lexer)


def test_opening_a_block_comment_restyles_following_lines(qtbot):
    editor, _lexer = _make_editor(qtbot, "go", "a := 1\nb := 2\n/* x */\nc := 3\n")
    editor.SendScintilla(editor.SCI_INSERTTEXT, 0, b"/* ")
    _restyle(editor)
    b_pos = editor.text().encode().index(b"b :=")
    assert editor.SendScintilla(editor.SCI_GETSTYLEAT, b_pos) == S_COMMENT


def test_crlf_line_endings_keep_styles_aligned(qtbot):
    text = 'x := "s"\r\n' * 200
    editor, lexer = _make_editor(qtbot, "go", text)
    data = editor.text().encode()
    last_quote = data.rindex(b'"s"')
    assert editor.SendScintilla(editor.SCI_GETSTYLEAT, last_quote + 1) == S_STRING
    assert editor.SendScintilla(editor.SCI_GETSTYLEAT, last_quote + 4) == S_DEFAULT
    _assert_matches_reference(editor, lexer)


def test_php_restart_inside_code_block_stays_in_php_mode(qtbot):
    html = "<html><body>\n" + "<p>testo</p>\n" * 50
    php = "<?php\n" + "".join(f"$v{i} = 'stringa {i}';\n" for i in range(200)) + "?>\n"
    editor, lexer = _make_editor(qtbot, "php", html + php + "</body></html>\n")
    pos = editor.text().encode().index(b"$v150")
    editor.SendScintilla(editor.SCI_INSERTTEXT, pos, b" ")
    _restyle(editor)
    string_pos = editor.text().encode().index(b"'stringa 150'")
    assert editor.SendScintilla(editor.SCI_GETSTYLEAT, string_pos) == S_STRING
    _assert_matches_reference(editor, lexer)


@pytest.mark.parametrize("alias", ["rust", "kotlin", "swift", "scala", "dart", "toml"])
def test_other_languages_survive_edits(qtbot, alias):
    sample = {
        "rust": 'fn main() {\n    let s = r#"raw\n"#;\n    /* a /* b */ c */\n}\n',
        "kotlin": 'fun main() {\n    val s = """multi\nline"""\n}\n',
        "swift": 'let s = """\nmulti\n"""\nfunc f() {}\n',
        "scala": 'object A {\n  val s = """x\ny"""\n}\n',
        "dart": "void main() {\n  var s = '''x\ny''';\n}\n",
        "toml": '[table]\nkey = """\nmulti\n"""\nn = 1\n',
    }[alias]
    editor, lexer = _make_editor(qtbot, alias, sample * 50)
    mid = len(editor.text().encode()) // 2
    editor.SendScintilla(editor.SCI_INSERTTEXT, mid, b"\n")
    _restyle(editor)
    _assert_matches_reference(editor, lexer)


def test_edit_after_a_multiline_comment_restarts_before_it(qtbot):
    """Una modifica dentro un commento multiriga deve ripartire da prima."""
    text = "a := 1\n" * 50 + "/*\n" + "dentro\n" * 50 + "*/\nb := 2\n"
    editor, lexer = _make_editor(qtbot, "go", text)
    pos = editor.text().encode().index(b"dentro\n" * 3) + 7 * 30
    editor.SendScintilla(editor.SCI_INSERTTEXT, pos, b"x")
    _restyle(editor)
    _assert_matches_reference(editor, lexer)


@pytest.mark.parametrize("alias, line", [
    ("rust", "let a = 1; // c\n"),
    ("scala", "val a = 1 // c\n"),
])
def test_line_comment_newline_is_a_safe_restart(qtbot, alias, line):
    """Rust/Scala includono il newline nel token del commento di riga."""
    editor, lexer = _make_editor(qtbot, alias, line * 2000)
    restart = lexer._restart_position(editor, len(editor.text().encode()) // 2)
    assert restart > len(editor.text().encode()) // 2 - 200


# ── Scanner nativo (core._code_native) ───────────────────────────────────────

needs_native = pytest.mark.skipif(not NATIVE_LANGUAGES, reason="native scanner not compiled")

NATIVE_SAMPLES = {
    "go": GO_SOURCE,
    "rust": (
        "use std::fmt;\n/// Doc comment.\n#[derive(Debug)]\n#[cfg(feature = \"x\")]\n"
        "struct P<'a> { x: &'a str, v: Vec<u8> }\n"
        "fn get(a: u32) -> Option<u32> {\n    let s = r#\"raw \"q\" \n\"#;\n"
        "    /* a /* nested */ b */\n    println!(\"{}\", a + 1_000u32);\n"
        "    let c = 'x'; let l: &'static str = \"s\";\n    Some(a as u32)\n}\n"
        "mod tests { }\n"
    ),
    "kotlin": (
        "package org.example.app\nimport kotlin.math.max\n@Ann class P(val x: Int) : Base() {\n"
        "    private val s = \"v $x ${max(x, 1) + 1}\"\n"
        "    fun Base.`quoted name`(a: Int): String = \"\"\"multi\n$a line\"\"\"\n"
        "    /* commento\n multiriga */ val n = 10L\n}\n"
    ),
    "swift": (
        "import Foundation\n@MainActor class P: NSObject {\n"
        "  func get(_ a: Int) -> String { let s = \"v \\(a + 1)\"; return s }\n"
        "  #if DEBUG\n  var n = 0x1F\n  #endif\n  let m = \"\"\"\n  multi \\(n)\n  \"\"\"\n}\n"
    ),
    "scala": (
        "package a\nimport scala.collection.{immutable, mutable}\n"
        "@ann case class P(x: Int) extends B {\n  def get(a: Int): String = s\"v $a ${a + 1}\"\n"
        "  val n = 10L; val c = 'c'; val l = xs :+ 1\n  val t = \"\"\"x\ny\"\"\"\n}\n"
    ),
    "dart": (
        "import 'package:a/b.dart';\n/// Doc.\n@override\nclass P extends B {\n"
        "  int get(int a) { var s = \"v $a ${a + 1}\"; return 0x1F; }\n"
        "  final r = r'raw $x';\n  final m = \'\'\'\nmulti $s\n\'\'\';\n}\n"
    ),
}


@needs_native
@pytest.mark.parametrize("alias", sorted(NATIVE_SAMPLES))
def test_native_incremental_edits_match_a_full_native_scan(qtbot, alias):
    editor, lexer = _make_editor(qtbot, alias, NATIVE_SAMPLES[alias] * 40, native=True)
    assert lexer._native_enabled
    rng = random.Random(alias)
    for _ in range(40):
        total = editor.SendScintilla(editor.SCI_GETLENGTH)
        pos = editor.SendScintilla(editor.SCI_POSITIONBEFORE,
                                   editor.SendScintilla(editor.SCI_POSITIONAFTER,
                                                        rng.randrange(total)))
        editor.SendScintilla(editor.SCI_INSERTTEXT, pos,
                             rng.choice(['"', "/*", "*/", "\n", "x", "'", "${", "}"]).encode())
        _restyle(editor, pos + 300)
    _restyle(editor)
    _assert_matches_reference(editor, lexer)


@needs_native
@pytest.mark.parametrize("alias", sorted(NATIVE_SAMPLES))
def test_native_scanner_keeps_pygments_colours(alias):
    """Lo scanner nativo deve dare (quasi) gli stessi colori di Pygments.

    Misurato su sorgenti reali: Go 100%, Rust 99%, Kotlin 99%, Swift 99%,
    Scala 99%, Dart 98%. Qui una soglia prudente sui campioni sintetici.
    """
    from pygments.lexers import get_lexer_by_name

    from editor.pygments_lexer import S_COMMENT_LINE, S_ESCAPE

    text = NATIVE_SAMPLES[alias]
    data = text.encode()
    normal = {S_COMMENT_LINE: S_COMMENT, S_ESCAPE: S_STRING}
    reference: list[int] = []
    for _i, ttype, value in get_lexer_by_name(alias).get_tokens_unprocessed(text):
        style = _token_to_style(ttype)
        reference.extend([normal.get(style, style)] * len(value.encode()))
    native = pygments_lexer._code_native.style(alias, data, len(data))
    pairs = [(r, n) for b, r, n in zip(data, reference, native) if b not in b" \t\n"]
    agreement = sum(r == n for r, n in pairs) / len(pairs)
    assert agreement >= 0.9, f"{alias}: {agreement:.1%}"


@needs_native
def test_native_scanner_releases_the_gil_and_validates_input():
    with pytest.raises(ValueError):
        pygments_lexer._code_native.style("cobol", b"x", 1)
    assert pygments_lexer._code_native.style("go", b"", 0) == b""
    # span oltre la fine del testo: tronca senza leggere fuori dal buffer
    assert len(pygments_lexer._code_native.style("go", b"a := 1", 100)) == 6


def test_without_native_extension_pygments_is_used(qtbot, monkeypatch):
    """Senza estensione compilata l'editor funziona come prima, con Pygments."""
    monkeypatch.setattr(pygments_lexer, "NATIVE_LANGUAGES", frozenset())
    monkeypatch.setattr(pygments_lexer, "_code_native", None)
    editor = QsciScintilla()
    qtbot.addWidget(editor)
    editor.setUtf8(True)
    lexer = PygmentsLexer("go", "Go", editor)
    assert not lexer._native_enabled
    editor.setLexer(lexer)
    editor.setText(GO_SOURCE)
    editor.SendScintilla(editor.SCI_COLOURISE, 0, -1)
    _assert_matches_reference(editor, lexer)
