"""
editor/lexers.py — Mapping estensioni → lexer QScintilla
NotePadPQ

Gestisce:
- Mapping estensione file → lexer QScintilla
- Configurazione token per ogni lexer (via apply_theme_tokens)
- Funzioni per impostare il lexer su un EditorWidget
- Rilevamento linguaggio da contenuto (shebang, DOCTYPE, ecc.)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtGui import QColor, QFont
from PyQt6.Qsci import (
    QsciScintilla, QsciLexer,
    QsciLexerPython, QsciLexerCPP, QsciLexerJavaScript,
    QsciLexerHTML, QsciLexerCSS, QsciLexerXML,
    QsciLexerSQL, QsciLexerBash, QsciLexerMakefile,
    QsciLexerDiff, QsciLexerProperties, QsciLexerJSON,
    QsciLexerYAML, QsciLexerLua, QsciLexerRuby,
    QsciLexerTeX, QsciLexerMarkdown,
    QsciLexerBatch, QsciLexerCMake, QsciLexerCSharp,
    QsciLexerJava, QsciLexerPerl, QsciLexerPascal,
    QsciLexerFortran, QsciLexerVerilog, QsciLexerVHDL,
    QsciLexerPostScript, QsciLexerSpice,
)

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# ─── Mapping estensione → (classe lexer, nome linguaggio) ────────────────────

_EXT_MAP: dict[str, tuple[type, str]] = {
    # Python
    ".py":    (QsciLexerPython,     "Python"),
    ".pyw":   (QsciLexerPython,     "Python"),
    ".pyi":   (QsciLexerPython,     "Python"),
    # C / C++
    ".c":     (QsciLexerCPP,        "C/C++"),
    ".h":     (QsciLexerCPP,        "C/C++"),
    ".cpp":   (QsciLexerCPP,        "C/C++"),
    ".cxx":   (QsciLexerCPP,        "C/C++"),
    ".cc":    (QsciLexerCPP,        "C/C++"),
    ".hpp":   (QsciLexerCPP,        "C/C++"),
    ".hxx":   (QsciLexerCPP,        "C/C++"),
    # C#
    ".cs":    (QsciLexerCSharp,     "C#"),
    # Java
    ".java":  (QsciLexerJava,       "Java"),
    # JavaScript / TypeScript
    ".js":    (QsciLexerJavaScript, "JavaScript"),
    ".mjs":   (QsciLexerJavaScript, "JavaScript"),
    ".cjs":   (QsciLexerJavaScript, "JavaScript"),
    ".ts":    (QsciLexerJavaScript, "TypeScript"),
    ".tsx":   (QsciLexerJavaScript, "TypeScript"),
    ".jsx":   (QsciLexerJavaScript, "JavaScript"),
    # Web
    ".html":  (QsciLexerHTML,       "HTML"),
    ".htm":   (QsciLexerHTML,       "HTML"),
    ".xhtml": (QsciLexerHTML,       "HTML"),
    ".css":   (QsciLexerCSS,        "CSS"),
    ".xml":   (QsciLexerXML,        "XML"),
    ".svg":   (QsciLexerXML,        "XML"),
    ".xsl":   (QsciLexerXML,        "XML"),
    ".xslt":  (QsciLexerXML,        "XML"),
    # Data
    ".json":  (QsciLexerJSON,       "JSON"),
    ".yaml":  (QsciLexerYAML,       "YAML"),
    ".yml":   (QsciLexerYAML,       "YAML"),
    ".toml":  (QsciLexerProperties, "TOML"),
    ".ini":   (QsciLexerProperties, "INI"),
    ".cfg":   (QsciLexerProperties, "INI"),
    ".conf":  (QsciLexerProperties, "Config"),
    # Database
    ".sql":   (QsciLexerSQL,        "SQL"),
    # Shell
    ".sh":    (QsciLexerBash,       "Bash"),
    ".bash":  (QsciLexerBash,       "Bash"),
    ".zsh":   (QsciLexerBash,       "Bash"),
    ".fish":  (QsciLexerBash,       "Bash"),
    ".ksh":   (QsciLexerBash,       "Bash"),
    ".bat":   (QsciLexerBatch,      "Batch"),
    ".cmd":   (QsciLexerBatch,      "Batch"),
    # Build
    ".mk":    (QsciLexerMakefile,   "Makefile"),
    ".cmake": (QsciLexerCMake,      "CMake"),
    # LaTeX
    ".tex":   (QsciLexerTeX,        "LaTeX"),
    ".sty":   (QsciLexerTeX,        "LaTeX"),
    ".cls":   (QsciLexerTeX,        "LaTeX"),
    ".bib":   (QsciLexerTeX,        "BibTeX"),
    ".dtx":   (QsciLexerTeX,        "LaTeX"),
    # Markdown
    ".md":    (QsciLexerMarkdown,   "Markdown"),
    ".markdown": (QsciLexerMarkdown,"Markdown"),
    ".rst":   (None,                "reStructuredText"),
    # Script
    ".lua":   (QsciLexerLua,        "Lua"),
    ".rb":    (QsciLexerRuby,       "Ruby"),
    ".pl":    (QsciLexerPerl,       "Perl"),
    ".pm":    (QsciLexerPerl,       "Perl"),
    # Diff
    ".diff":  (QsciLexerDiff,       "Diff"),
    ".patch": (QsciLexerDiff,       "Diff"),
    # Pascal / Delphi
    ".pas":   (QsciLexerPascal,     "Pascal"),
    ".dpr":   (QsciLexerPascal,     "Pascal"),
    # Fortran
    ".f90":   (QsciLexerFortran,    "Fortran"),
    ".f95":   (QsciLexerFortran,    "Fortran"),
    ".f":     (QsciLexerFortran,    "Fortran"),
    # Hardware
    ".v":     (QsciLexerVerilog,    "Verilog"),
    ".sv":    (QsciLexerVerilog,    "SystemVerilog"),
    ".vhd":   (QsciLexerVHDL,      "VHDL"),
    ".vhdl":  (QsciLexerVHDL,      "VHDL"),
    # Altro
    ".ps":    (QsciLexerPostScript, "PostScript"),
    ".cir":   (QsciLexerSpice,     "SPICE"),
    ".sp":    (QsciLexerSpice,     "SPICE"),
}

# Mapping nome linguaggio → estensione canonica (per set_lexer_by_name)
_NAME_TO_EXT: dict[str, str] = {
    "python":        ".py",
    "c/c++":         ".cpp",
    "c#":            ".cs",
    "java":          ".java",
    "javascript":    ".js",
    "typescript":    ".ts",
    "html":          ".html",
    "css":           ".css",
    "xml":           ".xml",
    "json":          ".json",
    "yaml":          ".yaml",
    "sql":           ".sql",
    "bash/shell":    ".sh",
    "bash":          ".sh",
    "batch":         ".bat",
    "makefile":      ".mk",
    "cmake":         ".cmake",
    "latex":         ".tex",
    "markdown":      ".md",
    "lua":           ".lua",
    "ruby":          ".rb",
    "perl":          ".pl",
    "diff":          ".diff",
    "ini/config":    ".ini",
    "testo normale": "",
}

# ─── Funzioni pubbliche ───────────────────────────────────────────────────────

def set_lexer_by_extension(editor: "EditorWidget", ext: str) -> bool:
    """
    Imposta il lexer sull'editor in base all'estensione file.
    Restituisce True se il lexer è stato impostato.
    """
    ext = ext.lower()
    entry = _EXT_MAP.get(ext)
    if entry is None:
        # Filenames speciali senza estensione
        return False
    lexer_class, lang_name = entry
    return _apply_lexer(editor, lexer_class, lang_name)


def set_lexer_by_path(editor: "EditorWidget", path: Path) -> bool:
    """
    Imposta il lexer in base al percorso file.
    Prova estensione, poi filename speciali, poi shebang/content.
    """
    # Estensione
    ext = path.suffix.lower()
    if ext and set_lexer_by_extension(editor, ext):
        return True

    # Filename speciali senza estensione
    name = path.name.lower()
    special = {
        "makefile":    (".mk",  QsciLexerMakefile, "Makefile"),
        "dockerfile":  (".sh",  QsciLexerBash,     "Dockerfile"),
        "cmakelists.txt": (".cmake", QsciLexerCMake, "CMake"),
        ".gitignore":  (".sh",  QsciLexerBash,     "gitignore"),
        ".env":        (".ini", QsciLexerProperties, "Env"),
        "requirements.txt": (".ini", QsciLexerProperties, "Requirements"),
    }
    if name in special:
        _, cls, lang = special[name]
        return _apply_lexer(editor, cls, lang)

    # Shebang / content detection
    try:
        content = editor.text()[:200] if editor.text() else ""
        detected = _detect_from_content(content)
        if detected:
            return set_lexer_by_extension(editor, detected)
    except Exception:
        pass

    return False


def set_lexer_by_name(editor: "EditorWidget", lang_name: str) -> bool:
    """Imposta il lexer per nome linguaggio (dal menu Documento)."""
    key = lang_name.lower()
    ext = _NAME_TO_EXT.get(key)
    if ext is None:
        return False
    if not ext:
        # Testo normale: rimuove il lexer
        editor.setLexer(None)
        editor._current_language = ""
        return True
    return set_lexer_by_extension(editor, ext)


def get_language_name(editor: "EditorWidget") -> str:
    """Restituisce il nome del linguaggio dell'editor corrente."""
    # Usa il nome salvato da _apply_lexer (es. "LaTeX"), più preciso di lexer.language()
    # che può restituire nomi interni diversi (es. QsciLexerTeX → "TeX").
    stored = getattr(editor, "_current_language", None)
    if stored:
        return stored
    lexer = editor.lexer()
    if lexer is None:
        return "Text"
    return lexer.language() or "Text"


def get_comment_chars(language: str) -> tuple[str, str]:
    """
    Restituisce (commento_riga, commento_blocco_apri, commento_blocco_chiudi)
    per il linguaggio dato. Usato da text_tools per commenta/decommenta.
    """
    lc = language.lower()
    line_comments = {
        "python":     "#",
        "bash":       "#",
        "ruby":       "#",
        "perl":       "#",
        "lua":        "--",
        "sql":        "--",
        "haskell":    "--",
        "c/c++":      "//",
        "c#":         "//",
        "java":       "//",
        "javascript": "//",
        "typescript": "//",
        "go":         "//",
        "rust":       "//",
        "swift":      "//",
        "kotlin":     "//",
        "latex":      "%",
        "matlab":     "%",
        "batch":      "REM ",
        "vbscript":   "'",
        "ini":        ";",
        "properties": "#",
    }
    block_comments = {
        "c/c++":      ("/*", "*/"),
        "c#":         ("/*", "*/"),
        "java":       ("/*", "*/"),
        "javascript": ("/*", "*/"),
        "typescript": ("/*", "*/"),
        "css":        ("/*", "*/"),
        "html":       ("<!--", "-->"),
        "xml":        ("<!--", "-->"),
        "lua":        ("--[[", "]]"),
        "python":     ('"""', '"""'),
    }
    return (
        line_comments.get(lc, "#"),
        block_comments.get(lc, ("#", ""))
    )

# ─── Helpers interni ──────────────────────────────────────────────────────────

def _apply_lexer(editor: "EditorWidget",
                 lexer_class: Optional[type],
                 lang_name: str) -> bool:
    """Instanzia e applica il lexer all'editor."""
    if lexer_class is None:
        editor.setLexer(None)
        editor._current_language = lang_name
        return False

    font = editor.font()
    lexer = lexer_class(editor)
    lexer.setDefaultFont(font)
    lexer.setFont(font)

    # Configurazione specifica per linguaggio
    _configure_lexer(lexer, lang_name)

    editor.setLexer(lexer)
    # Memorizza il nome linguaggio sull'editor per _update_file_type_menu
    editor._current_language = lang_name

    # Forza il refresh dell'highlighting di Scintilla
    editor.SendScintilla(editor.SCI_COLOURISE, 0, -1)

    # Applica il tema corrente al nuovo lexer.
    # Il QTimer garantisce che Scintilla abbia terminato di inizializzare
    # il lexer prima che vengano impostati i colori dei token.
    try:
        from config.themes import ThemeManager
        from PyQt6.QtCore import QTimer
        tm = ThemeManager.instance()
        # Applica subito i colori UI (sfondo, margini, caret...)
        tm.apply_to_editor(editor)
        # Riapplica dopo 50ms per essere sicuri che i token siano pronti
        QTimer.singleShot(50, lambda: tm.apply_to_editor(editor))
    except Exception:
        pass

    # Imposta il linguaggio nell'autocompletamento
    try:
        ac = getattr(editor, "_autocomplete", None)
        if ac:
            ac.set_language(lang_name.lower())
    except Exception:
        pass

    # Attiva il supporto LaTeX avanzato (auto-end, completamento contestuale)
    if lang_name in ("LaTeX", "BibTeX"):
        try:
            from editor.latex_support import LaTeXSupport
            LaTeXSupport.activate(editor)
        except Exception:
            pass
        # Collega il rebuild dell'API alle modifiche del documento
        try:
            ac = getattr(editor, "_autocomplete", None)
            if ac:
                try:
                    editor.textChanged.disconnect(ac.on_document_changed)
                except Exception:
                    pass
                editor.textChanged.connect(ac.on_document_changed)
        except Exception:
            pass
        # Avvia il checker sintattico in tempo reale
        try:
            from editor.latex_checker import LaTeXChecker
            old_checker = getattr(editor, "_latex_checker", None)
            if old_checker:
                old_checker.stop()
            checker = LaTeXChecker(editor, parent=editor)
            checker.start()
            editor._latex_checker = checker
        except Exception:
            pass

    return True


def _configure_lexer(lexer: QsciLexer, lang_name: str) -> None:
    """Configurazione specifica per tipo di lexer."""
    if isinstance(lexer, QsciLexerPython):
        lexer.setIndentationWarning(
            QsciLexerPython.IndentationWarning.Inconsistent
        )
        lexer.setFoldCompact(False)
        lexer.setFoldQuotes(True)
        lexer.setFoldComments(True)
        lexer.setStringsOverNewlineAllowed(False)

    elif isinstance(lexer, QsciLexerCPP):
        lexer.setFoldComments(True)
        lexer.setFoldCompact(False)
        lexer.setFoldAtElse(True)
        lexer.setDollarsAllowed(False)

    elif isinstance(lexer, (QsciLexerHTML, QsciLexerXML)):
        lexer.setFoldCompact(False)
        lexer.setFoldPreprocessor(True)

    elif isinstance(lexer, QsciLexerCSS):
        lexer.setFoldComments(True)
        lexer.setFoldCompact(False)

    elif isinstance(lexer, QsciLexerSQL):
        lexer.setFoldComments(True)
        lexer.setFoldCompact(False)

    elif isinstance(lexer, QsciLexerBash):
        lexer.setFoldComments(True)
        lexer.setFoldCompact(False)

    elif isinstance(lexer, QsciLexerTeX):
        lexer.setFoldComments(True)

    elif isinstance(lexer, QsciLexerJSON):
        lexer.setFoldCompact(False)

    elif isinstance(lexer, QsciLexerYAML):
        pass  # nessuna config extra necessaria


def _detect_from_content(content: str) -> str:
    """Rilevamento linguaggio da shebang o content type."""
    if not content:
        return ""
    first_line = content.split("\n")[0].strip()

    if first_line.startswith("#!"):
        # join all tokens so "#!/usr/bin/env python3" is fully matched
        shebang = " ".join(first_line[2:].split()) if len(first_line) > 2 else ""
        if "python" in shebang:
            return ".py"
        if "bash" in shebang or "sh" in shebang:
            return ".sh"
        if "ruby" in shebang:
            return ".rb"
        if "perl" in shebang:
            return ".pl"
        if "lua" in shebang:
            return ".lua"
        if "node" in shebang:
            return ".js"

    if content.strip().startswith("<!DOCTYPE html") or \
       content.strip().startswith("<html"):
        return ".html"
    if content.strip().startswith("<?xml"):
        return ".xml"
    if content.strip().startswith("{") or content.strip().startswith("["):
        try:
            import json
            json.loads(content)
            return ".json"
        except Exception:
            pass
    if "\\documentclass" in content or "\\begin{document}" in content:
        return ".tex"
    if content.strip().startswith("---"):
        return ".yaml"
    if "SELECT " in content.upper() and "FROM " in content.upper():
        return ".sql"

    return ""
