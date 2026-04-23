"""
config/themes.py — Motore temi
NotePadPQ

Gestisce il caricamento, l'applicazione e la personalizzazione dei temi.
Un tema definisce colori per ogni token sintattico + colori UI (margini,
selezione, caret, ecc.) + font predefinito.

I temi sono file JSON in <data_dir>/themes/ oppure built-in nel codice.
Il tema attivo viene applicato a tutti i tab aperti.

Uso:
    from config.themes import ThemeManager
    tm = ThemeManager.instance()
    tm.apply_theme("Dark", editor)
    tm.set_active("Monokai")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# ─── Struttura tema ───────────────────────────────────────────────────────────

# Chiavi UI standard (non dipendenti dal lexer)
UI_KEYS = [
    "editor_bg",        # sfondo editor
    "editor_fg",        # testo default
    "margin_bg",        # sfondo margine numeri riga
    "margin_fg",        # testo margine
    "caret_line_bg",    # sfondo riga cursore
    "caret_fg",         # colore cursore
    "selection_bg",     # sfondo selezione
    "selection_fg",     # testo selezione (None = lascia il colore token)
    "brace_match_bg",   # sfondo parentesi corrispondente
    "brace_match_fg",   # testo parentesi corrispondente
    "brace_bad_bg",     # sfondo parentesi senza coppia
    "brace_bad_fg",
    "find_indicator",   # colore indicatore find
    "whitespace_fg",    # colore spazi visibili
    "fold_fg",          # colore simboli folding
    "fold_bg",
]

# ─── Temi built-in ────────────────────────────────────────────────────────────

BUILTIN_THEMES: dict[str, dict] = {

    "Dark": {
        "meta": {
            "name": "Dark",
            "author": "NotePadPQ",
            "version": "1.0",
            "dark": True,
        },
        "ui": {
            "editor_bg":      "#1e1e1e",
            "editor_fg":      "#d4d4d4",
            "margin_bg":      "#1e1e1e",
            "margin_fg":      "#858585",
            "caret_line_bg":  "#2a2d2e",
            "caret_fg":       "#aeafad",
            "selection_bg":   "#264f78",
            "selection_fg":   None,
            "brace_match_bg": "#0d6a0d",
            "brace_match_fg": "#ffffff",
            "brace_bad_bg":   "#6a0000",
            "brace_bad_fg":   "#ffffff",
            "find_indicator": "#ffa500",
            "whitespace_fg":  "#3b3b3b",
            "fold_fg":        "#c5c5c5",
            "fold_bg":        "#37373d",
        },
        "font": {
            "family": None,   # None = usa il font preferito dalla piattaforma
            "size": 11,
        },
        "tokens": {
            # token generici (usati da tutti i lexer)
            "default":        {"fg": "#d4d4d4", "bg": "#1e1e1e"},
            "comment":        {"fg": "#6a9955", "italic": True},
            "comment_block":  {"fg": "#6a9955", "italic": True},
            "keyword":        {"fg": "#569cd6", "bold": True},
            "keyword2":       {"fg": "#c586c0"},
            "string":         {"fg": "#ce9178"},
            "string2":        {"fg": "#ce9178"},
            "string_raw":     {"fg": "#ce9178"},
            "number":         {"fg": "#b5cea8"},
            "operator":       {"fg": "#d4d4d4"},
            "identifier":     {"fg": "#9cdcfe"},
            "function":       {"fg": "#dcdcaa"},
            "class_name":     {"fg": "#4ec9b0"},
            "builtin":        {"fg": "#4fc1ff"},
            "decorator":      {"fg": "#c586c0"},
            "preprocessor":   {"fg": "#c586c0"},
            "regex":          {"fg": "#d16969"},
            "constant":       {"fg": "#4fc1ff"},
            "type":           {"fg": "#4ec9b0"},
            "label":          {"fg": "#c8c8c8"},
            "error":          {"fg": "#f44747", "bg": "#3a0000"},
            "unclosed_string":{"fg": "#ce9178", "bg": "#3a1a00"},
            # HTML/XML specifici
            "tag":            {"fg": "#569cd6"},
            "attribute":      {"fg": "#9cdcfe"},
            "attribute_value":{"fg": "#ce9178"},
            "entity":         {"fg": "#4ec9b0"},
            # LaTeX specifici
            "command":        {"fg": "#569cd6", "bold": True},
            "math":           {"fg": "#d7ba7d"},
            "math_command":   {"fg": "#4ec9b0"},
            "environment":    {"fg": "#c586c0"},
            "special_char":   {"fg": "#d4d4d4"},
        }
    },

    "Light": {
        "meta": {
            "name": "Light",
            "author": "NotePadPQ",
            "version": "1.0",
            "dark": False,
        },
        "ui": {
            "editor_bg":      "#ffffff",
            "editor_fg":      "#000000",
            "margin_bg":      "#f0f0f0",
            "margin_fg":      "#808080",
            "caret_line_bg":  "#fffbdd",
            "caret_fg":       "#000000",
            "selection_bg":   "#3399ff",
            "selection_fg":   "#ffffff",
            "brace_match_bg": "#c2e0c2",
            "brace_match_fg": "#000000",
            "brace_bad_bg":   "#ffc0c0",
            "brace_bad_fg":   "#000000",
            "find_indicator": "#ff8c00",
            "whitespace_fg":  "#d0d0d0",
            "fold_fg":        "#808080",
            "fold_bg":        "#e8e8e8",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#000000", "bg": "#ffffff"},
            "comment":        {"fg": "#008000", "italic": True},
            "comment_block":  {"fg": "#008000", "italic": True},
            "keyword":        {"fg": "#0000ff", "bold": True},
            "keyword2":       {"fg": "#af00db"},
            "string":         {"fg": "#a31515"},
            "string2":        {"fg": "#a31515"},
            "string_raw":     {"fg": "#a31515"},
            "number":         {"fg": "#098658"},
            "operator":       {"fg": "#000000"},
            "identifier":     {"fg": "#001080"},
            "function":       {"fg": "#795e26"},
            "class_name":     {"fg": "#267f99"},
            "builtin":        {"fg": "#0070c1"},
            "decorator":      {"fg": "#af00db"},
            "preprocessor":   {"fg": "#af00db"},
            "regex":          {"fg": "#811f3f"},
            "constant":       {"fg": "#0070c1"},
            "type":           {"fg": "#267f99"},
            "label":          {"fg": "#444444"},
            "error":          {"fg": "#ff0000", "bg": "#fff0f0"},
            "unclosed_string":{"fg": "#a31515", "bg": "#fff4e0"},
            "tag":            {"fg": "#800000"},
            "attribute":      {"fg": "#ff0000"},
            "attribute_value":{"fg": "#0000ff"},
            "entity":         {"fg": "#ff0000"},
            "command":        {"fg": "#0000ff", "bold": True},
            "math":           {"fg": "#795e26"},
            "math_command":   {"fg": "#267f99"},
            "environment":    {"fg": "#af00db"},
            "special_char":   {"fg": "#000000"},
        }
    },

    "Monokai": {
        "meta": {"name": "Monokai", "author": "NotePadPQ", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#272822",
            "editor_fg":      "#f8f8f2",
            "margin_bg":      "#1e1f1c",
            "margin_fg":      "#90908a",
            "caret_line_bg":  "#3e3d32",
            "caret_fg":       "#f8f8f0",
            "selection_bg":   "#49483e",
            "selection_fg":   None,
            "brace_match_bg": "#a6e22e",
            "brace_match_fg": "#272822",
            "brace_bad_bg":   "#f92672",
            "brace_bad_fg":   "#272822",
            "find_indicator": "#e6db74",
            "whitespace_fg":  "#3b3a32",
            "fold_fg":        "#75715e",
            "fold_bg":        "#272822",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#f8f8f2", "bg": "#272822"},
            "comment":        {"fg": "#75715e", "italic": True},
            "comment_block":  {"fg": "#75715e", "italic": True},
            "keyword":        {"fg": "#f92672", "bold": True},
            "keyword2":       {"fg": "#66d9e8"},
            "string":         {"fg": "#e6db74"},
            "string2":        {"fg": "#e6db74"},
            "string_raw":     {"fg": "#e6db74"},
            "number":         {"fg": "#ae81ff"},
            "operator":       {"fg": "#f92672"},
            "identifier":     {"fg": "#f8f8f2"},
            "function":       {"fg": "#a6e22e"},
            "class_name":     {"fg": "#a6e22e"},
            "builtin":        {"fg": "#66d9e8"},
            "decorator":      {"fg": "#a6e22e"},
            "preprocessor":   {"fg": "#f92672"},
            "regex":          {"fg": "#ae81ff"},
            "constant":       {"fg": "#ae81ff"},
            "type":           {"fg": "#66d9e8"},
            "label":          {"fg": "#f8f8f2"},
            "error":          {"fg": "#f8f8f2", "bg": "#f92672"},
            "unclosed_string":{"fg": "#e6db74", "bg": "#4a3a00"},
            "tag":            {"fg": "#f92672"},
            "attribute":      {"fg": "#a6e22e"},
            "attribute_value":{"fg": "#e6db74"},
            "entity":         {"fg": "#ae81ff"},
            "command":        {"fg": "#f92672", "bold": True},
            "math":           {"fg": "#ae81ff"},
            "math_command":   {"fg": "#66d9e8"},
            "environment":    {"fg": "#a6e22e"},
            "special_char":   {"fg": "#ae81ff"},
        }
    },

    "Nord": {
        "meta": {"name": "Nord", "author": "NotePadPQ", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#2e3440",
            "editor_fg":      "#d8dee9",
            "margin_bg":      "#2e3440",
            "margin_fg":      "#4c566a",
            "caret_line_bg":  "#3b4252",
            "caret_fg":       "#d8dee9",
            "selection_bg":   "#434c5e",
            "selection_fg":   None,
            "brace_match_bg": "#a3be8c",
            "brace_match_fg": "#2e3440",
            "brace_bad_bg":   "#bf616a",
            "brace_bad_fg":   "#eceff4",
            "find_indicator": "#ebcb8b",
            "whitespace_fg":  "#3b4252",
            "fold_fg":        "#4c566a",
            "fold_bg":        "#2e3440",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#d8dee9", "bg": "#2e3440"},
            "comment":        {"fg": "#616e88", "italic": True},
            "comment_block":  {"fg": "#616e88", "italic": True},
            "keyword":        {"fg": "#81a1c1", "bold": True},
            "keyword2":       {"fg": "#b48ead"},
            "string":         {"fg": "#a3be8c"},
            "string2":        {"fg": "#a3be8c"},
            "string_raw":     {"fg": "#a3be8c"},
            "number":         {"fg": "#b48ead"},
            "operator":       {"fg": "#81a1c1"},
            "identifier":     {"fg": "#d8dee9"},
            "function":       {"fg": "#88c0d0"},
            "class_name":     {"fg": "#8fbcbb"},
            "builtin":        {"fg": "#81a1c1"},
            "decorator":      {"fg": "#d08770"},
            "preprocessor":   {"fg": "#5e81ac"},
            "regex":          {"fg": "#ebcb8b"},
            "constant":       {"fg": "#b48ead"},
            "type":           {"fg": "#8fbcbb"},
            "label":          {"fg": "#d8dee9"},
            "error":          {"fg": "#eceff4", "bg": "#bf616a"},
            "unclosed_string":{"fg": "#a3be8c", "bg": "#3b3028"},
            "tag":            {"fg": "#81a1c1"},
            "attribute":      {"fg": "#8fbcbb"},
            "attribute_value":{"fg": "#a3be8c"},
            "entity":         {"fg": "#d08770"},
            "command":        {"fg": "#81a1c1", "bold": True},
            "math":           {"fg": "#ebcb8b"},
            "math_command":   {"fg": "#88c0d0"},
            "environment":    {"fg": "#b48ead"},
            "special_char":   {"fg": "#d8dee9"},
        }
    },

    "Dracula": {
        "meta": {"name": "Dracula", "author": "NotePadPQ", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#282a36",
            "editor_fg":      "#f8f8f2",
            "margin_bg":      "#21222c",
            "margin_fg":      "#6272a4",
            "caret_line_bg":  "#44475a",
            "caret_fg":       "#f8f8f2",
            "selection_bg":   "#44475a",
            "selection_fg":   None,
            "brace_match_bg": "#50fa7b",
            "brace_match_fg": "#282a36",
            "brace_bad_bg":   "#ff5555",
            "brace_bad_fg":   "#f8f8f2",
            "find_indicator": "#f1fa8c",
            "whitespace_fg":  "#44475a",
            "fold_fg":        "#6272a4",
            "fold_bg":        "#282a36",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#f8f8f2", "bg": "#282a36"},
            "comment":        {"fg": "#6272a4", "italic": True},
            "comment_block":  {"fg": "#6272a4", "italic": True},
            "keyword":        {"fg": "#ff79c6", "bold": True},
            "keyword2":       {"fg": "#8be9fd"},
            "string":         {"fg": "#f1fa8c"},
            "string2":        {"fg": "#f1fa8c"},
            "string_raw":     {"fg": "#f1fa8c"},
            "number":         {"fg": "#bd93f9"},
            "operator":       {"fg": "#ff79c6"},
            "identifier":     {"fg": "#f8f8f2"},
            "function":       {"fg": "#50fa7b"},
            "class_name":     {"fg": "#8be9fd"},
            "builtin":        {"fg": "#8be9fd"},
            "decorator":      {"fg": "#50fa7b"},
            "preprocessor":   {"fg": "#ff79c6"},
            "regex":          {"fg": "#bd93f9"},
            "constant":       {"fg": "#bd93f9"},
            "type":           {"fg": "#8be9fd"},
            "label":          {"fg": "#f8f8f2"},
            "error":          {"fg": "#f8f8f2", "bg": "#ff5555"},
            "unclosed_string":{"fg": "#f1fa8c", "bg": "#3a3500"},
            "tag":            {"fg": "#ff79c6"},
            "attribute":      {"fg": "#50fa7b"},
            "attribute_value":{"fg": "#f1fa8c"},
            "entity":         {"fg": "#bd93f9"},
            "command":        {"fg": "#ff79c6", "bold": True},
            "math":           {"fg": "#bd93f9"},
            "math_command":   {"fg": "#8be9fd"},
            "environment":    {"fg": "#50fa7b"},
            "special_char":   {"fg": "#f8f8f2"},
        }
    },

    "Solarized Dark": {
        "meta": {"name": "Solarized Dark", "author": "NotePadPQ", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#002b36",
            "editor_fg":      "#839496",
            "margin_bg":      "#073642",
            "margin_fg":      "#586e75",
            "caret_line_bg":  "#073642",
            "caret_fg":       "#839496",
            "selection_bg":   "#073642",
            "selection_fg":   "#93a1a1",
            "brace_match_bg": "#859900",
            "brace_match_fg": "#002b36",
            "brace_bad_bg":   "#dc322f",
            "brace_bad_fg":   "#fdf6e3",
            "find_indicator": "#b58900",
            "whitespace_fg":  "#073642",
            "fold_fg":        "#586e75",
            "fold_bg":        "#002b36",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#839496", "bg": "#002b36"},
            "comment":        {"fg": "#586e75", "italic": True},
            "comment_block":  {"fg": "#586e75", "italic": True},
            "keyword":        {"fg": "#859900", "bold": True},
            "keyword2":       {"fg": "#2aa198"},
            "string":         {"fg": "#2aa198"},
            "string2":        {"fg": "#2aa198"},
            "string_raw":     {"fg": "#2aa198"},
            "number":         {"fg": "#d33682"},
            "operator":       {"fg": "#657b83"},
            "identifier":     {"fg": "#268bd2"},
            "function":       {"fg": "#268bd2"},
            "class_name":     {"fg": "#b58900"},
            "builtin":        {"fg": "#cb4b16"},
            "decorator":      {"fg": "#6c71c4"},
            "preprocessor":   {"fg": "#cb4b16"},
            "regex":          {"fg": "#dc322f"},
            "constant":       {"fg": "#d33682"},
            "type":           {"fg": "#b58900"},
            "label":          {"fg": "#839496"},
            "error":          {"fg": "#fdf6e3", "bg": "#dc322f"},
            "unclosed_string":{"fg": "#2aa198", "bg": "#001f27"},
            "tag":            {"fg": "#268bd2"},
            "attribute":      {"fg": "#93a1a1"},
            "attribute_value":{"fg": "#2aa198"},
            "entity":         {"fg": "#cb4b16"},
            "command":        {"fg": "#268bd2", "bold": True},
            "math":           {"fg": "#d33682"},
            "math_command":   {"fg": "#2aa198"},
            "environment":    {"fg": "#859900"},
            "special_char":   {"fg": "#839496"},
        }
    },

    "One Dark": {
        "meta": {"name": "One Dark", "author": "NotePadPQ", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#282c34",
            "editor_fg":      "#abb2bf",
            "margin_bg":      "#21252b",
            "margin_fg":      "#495162",
            "caret_line_bg":  "#2c313c",
            "caret_fg":       "#528bff",
            "selection_bg":   "#3e4451",
            "selection_fg":   None,
            "brace_match_bg": "#98c379",
            "brace_match_fg": "#282c34",
            "brace_bad_bg":   "#e06c75",
            "brace_bad_fg":   "#282c34",
            "find_indicator": "#e5c07b",
            "whitespace_fg":  "#3b4048",
            "fold_fg":        "#495162",
            "fold_bg":        "#282c34",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#abb2bf", "bg": "#282c34"},
            "comment":        {"fg": "#5c6370", "italic": True},
            "comment_block":  {"fg": "#5c6370", "italic": True},
            "keyword":        {"fg": "#c678dd", "bold": True},
            "keyword2":       {"fg": "#56b6c2"},
            "string":         {"fg": "#98c379"},
            "string2":        {"fg": "#98c379"},
            "string_raw":     {"fg": "#98c379"},
            "number":         {"fg": "#d19a66"},
            "operator":       {"fg": "#56b6c2"},
            "identifier":     {"fg": "#e06c75"},
            "function":       {"fg": "#61afef"},
            "class_name":     {"fg": "#e5c07b"},
            "builtin":        {"fg": "#56b6c2"},
            "decorator":      {"fg": "#61afef"},
            "preprocessor":   {"fg": "#c678dd"},
            "regex":          {"fg": "#98c379"},
            "constant":       {"fg": "#d19a66"},
            "type":           {"fg": "#e5c07b"},
            "label":          {"fg": "#abb2bf"},
            "error":          {"fg": "#282c34", "bg": "#e06c75"},
            "unclosed_string":{"fg": "#98c379", "bg": "#2a3820"},
            "tag":            {"fg": "#e06c75"},
            "attribute":      {"fg": "#d19a66"},
            "attribute_value":{"fg": "#98c379"},
            "entity":         {"fg": "#56b6c2"},
            "command":        {"fg": "#c678dd", "bold": True},
            "math":           {"fg": "#d19a66"},
            "math_command":   {"fg": "#56b6c2"},
            "environment":    {"fg": "#61afef"},
            "special_char":   {"fg": "#abb2bf"},
        }
    },

    "Matrix": {
        "meta": {"name": "Matrix", "author": "NotePadPQ", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#000000",
            "editor_fg":      "#00ff41",
            "margin_bg":      "#0a0a0a",
            "margin_fg":      "#007a1f",
            "caret_line_bg":  "#001a00",
            "caret_fg":       "#00ff41",
            "selection_bg":   "#003300",
            "selection_fg":   "#00ff41",
            "brace_match_bg": "#004d00",
            "brace_match_fg": "#00ff41",
            "brace_bad_bg":   "#330000",
            "brace_bad_fg":   "#ff0000",
            "find_indicator": "#00ff41",
            "whitespace_fg":  "#003300",
            "fold_fg":        "#00cc33",
            "fold_bg":        "#001100",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#00ff41", "bg": "#000000"},
            "comment":        {"fg": "#007a1f", "italic": True},
            "comment_block":  {"fg": "#007a1f", "italic": True},
            "keyword":        {"fg": "#00ff41", "bold": True},
            "keyword2":       {"fg": "#39ff14"},
            "string":         {"fg": "#00cc33"},
            "string2":        {"fg": "#00cc33"},
            "string_raw":     {"fg": "#00cc33"},
            "number":         {"fg": "#00ff99"},
            "operator":       {"fg": "#00ff41"},
            "identifier":     {"fg": "#00e639"},
            "function":       {"fg": "#39ff14", "bold": True},
            "class_name":     {"fg": "#00ffaa"},
            "builtin":        {"fg": "#00ff99"},
            "decorator":      {"fg": "#39ff14"},
            "preprocessor":   {"fg": "#39ff14"},
            "regex":          {"fg": "#00ff99"},
            "constant":       {"fg": "#00ffaa"},
            "type":           {"fg": "#00ffaa"},
            "label":          {"fg": "#00cc33"},
            "error":          {"fg": "#ff0000", "bg": "#1a0000"},
            "unclosed_string":{"fg": "#00cc33", "bg": "#001a00"},
            "tag":            {"fg": "#00ff41", "bold": True},
            "attribute":      {"fg": "#00e639"},
            "attribute_value":{"fg": "#00cc33"},
            "entity":         {"fg": "#00ffaa"},
            "command":        {"fg": "#00ff41", "bold": True},
            "math":           {"fg": "#00ff99"},
            "math_command":   {"fg": "#00ffaa"},
            "environment":    {"fg": "#39ff14"},
            "special_char":   {"fg": "#00ff41"},
        }
    },
    
    
    "Catppuccin Mocha": {
        "meta": {"name": "Catppuccin Mocha", "author": "Catppuccin Org", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg": "#1e1e2e", "editor_fg": "#cdd6f4",
            "margin_bg": "#181825", "margin_fg": "#6c7086",
            "caret_line_bg": "#313244", "caret_fg": "#cdd6f4",
            "selection_bg": "#585b70", "selection_fg": None,
            "brace_match_bg": "#585b70", "brace_match_fg": "#f38ba8",
            "brace_bad_bg":   "#f38ba8", "brace_bad_fg": "#1e1e2e",
            "find_indicator": "#f9e2af",
            "whitespace_fg":  "#313244",
            "fold_fg":        "#6c7086", "fold_bg": "#1e1e2e",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#cdd6f4", "bg": "#1e1e2e"},
            "comment":        {"fg": "#6c7086", "italic": True},
            "comment_block":  {"fg": "#6c7086", "italic": True},
            "keyword":        {"fg": "#cba6f7", "bold": True},
            "keyword2":       {"fg": "#f38ba8"},
            "string":         {"fg": "#a6e3a1"},
            "string2":        {"fg": "#a6e3a1"},
            "string_raw":     {"fg": "#94e2d5"},
            "number":         {"fg": "#fab387"},
            "operator":       {"fg": "#89dceb"},
            "identifier":     {"fg": "#cdd6f4"},
            "function":       {"fg": "#89b4fa"},
            "class_name":     {"fg": "#f9e2af"},
            "builtin":        {"fg": "#89dceb"},
            "decorator":      {"fg": "#f5c2e7"},
            "preprocessor":   {"fg": "#f5c2e7"},
            "regex":          {"fg": "#f38ba8"},
            "constant":       {"fg": "#fab387"},
            "type":           {"fg": "#f9e2af"},
            "label":          {"fg": "#cdd6f4"},
            "error":          {"fg": "#1e1e2e", "bg": "#f38ba8"},
            "unclosed_string":{"fg": "#a6e3a1", "bg": "#1a2820"},
            "tag":            {"fg": "#f38ba8"},
            "attribute":      {"fg": "#89b4fa"},
            "attribute_value":{"fg": "#a6e3a1"},
            "entity":         {"fg": "#fab387"},
            "command":        {"fg": "#cba6f7", "bold": True},
            "math":           {"fg": "#f5e0dc"},
            "math_command":   {"fg": "#f38ba8", "italic": True},
            "environment":    {"fg": "#f9e2af"},
            "special_char":   {"fg": "#cdd6f4"},
        }
    },

    "Gruvbox Dark": {
        "meta": {"name": "Gruvbox Dark", "author": "Pavel Pertsev", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg": "#282828", "editor_fg": "#ebdbb2",
            "margin_bg": "#1d2021", "margin_fg": "#928374",
            "caret_line_bg": "#3c3836", "caret_fg": "#ebdbb2",
            "selection_bg": "#504945", "selection_fg": None,
            "brace_match_bg": "#504945", "brace_match_fg": "#fb4934",
            "brace_bad_bg":   "#cc241d", "brace_bad_fg": "#ebdbb2",
            "find_indicator": "#fabd2f",
            "whitespace_fg":  "#3c3836",
            "fold_fg":        "#928374", "fold_bg": "#282828",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#ebdbb2", "bg": "#282828"},
            "comment":        {"fg": "#928374", "italic": True},
            "comment_block":  {"fg": "#928374", "italic": True},
            "keyword":        {"fg": "#fb4934", "bold": True},
            "keyword2":       {"fg": "#fe8019"},
            "string":         {"fg": "#b8bb26"},
            "string2":        {"fg": "#b8bb26"},
            "string_raw":     {"fg": "#8ec07c"},
            "number":         {"fg": "#d3869b"},
            "operator":       {"fg": "#8ec07c"},
            "identifier":     {"fg": "#ebdbb2"},
            "function":       {"fg": "#b8bb26"},
            "class_name":     {"fg": "#fabd2f"},
            "builtin":        {"fg": "#83a598"},
            "decorator":      {"fg": "#d3869b"},
            "preprocessor":   {"fg": "#8ec07c"},
            "regex":          {"fg": "#d3869b"},
            "constant":       {"fg": "#d3869b"},
            "type":           {"fg": "#fabd2f"},
            "label":          {"fg": "#ebdbb2"},
            "error":          {"fg": "#ebdbb2", "bg": "#cc241d"},
            "unclosed_string":{"fg": "#b8bb26", "bg": "#1e1b10"},
            "tag":            {"fg": "#fb4934"},
            "attribute":      {"fg": "#fabd2f"},
            "attribute_value":{"fg": "#b8bb26"},
            "entity":         {"fg": "#fe8019"},
            "command":        {"fg": "#fb4934", "bold": True},
            "math":           {"fg": "#d5c4a1"},
            "math_command":   {"fg": "#83a598", "italic": True},
            "environment":    {"fg": "#fabd2f"},
            "special_char":   {"fg": "#ebdbb2"},
        }
    },

    "SynthWave '84": {
        "meta": {"name": "SynthWave '84", "author": "Robb Owen", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg": "#262335", "editor_fg": "#ffffff",
            "margin_bg": "#1f1d2b", "margin_fg": "#848bbd",
            "caret_line_bg": "#34294f", "caret_fg": "#ff7edb",
            "selection_bg": "#3c2d59", "selection_fg": None,
            "brace_match_bg": "#3c2d59", "brace_match_fg": "#f92aad",
            "brace_bad_bg":   "#f92aad", "brace_bad_fg": "#ffffff",
            "find_indicator": "#fefe62",
            "whitespace_fg":  "#34294f",
            "fold_fg":        "#848bbd", "fold_bg": "#1f1d2b",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#ffffff", "bg": "#262335"},
            "comment":        {"fg": "#848bbd", "italic": True},
            "comment_block":  {"fg": "#848bbd", "italic": True},
            "keyword":        {"fg": "#f92aad", "bold": True},
            "keyword2":       {"fg": "#ff7edb"},
            "string":         {"fg": "#ff8b39"},
            "string2":        {"fg": "#ff8b39"},
            "string_raw":     {"fg": "#36f9f6"},
            "number":         {"fg": "#f97e72"},
            "operator":       {"fg": "#f92aad"},
            "identifier":     {"fg": "#ffffff"},
            "function":       {"fg": "#36f9f6"},
            "class_name":     {"fg": "#fefe62"},
            "builtin":        {"fg": "#36f9f6"},
            "decorator":      {"fg": "#ff7edb"},
            "preprocessor":   {"fg": "#f92aad"},
            "regex":          {"fg": "#f97e72"},
            "constant":       {"fg": "#fefe62"},
            "type":           {"fg": "#fefe62"},
            "label":          {"fg": "#ffffff"},
            "error":          {"fg": "#ffffff", "bg": "#f92aad"},
            "unclosed_string":{"fg": "#ff8b39", "bg": "#2a1f00"},
            "tag":            {"fg": "#f92aad"},
            "attribute":      {"fg": "#fefe62"},
            "attribute_value":{"fg": "#ff8b39"},
            "entity":         {"fg": "#36f9f6"},
            "command":        {"fg": "#f92aad", "bold": True},
            "math":           {"fg": "#e0edff"},
            "math_command":   {"fg": "#ff7edb", "italic": True},
            "environment":    {"fg": "#fefe62"},
            "special_char":   {"fg": "#ffffff"},
        }
    },

    "Solarized Light": {
        "meta": {"name": "Solarized Light", "author": "NotePadPQ", "version": "1.0", "dark": False},
        "ui": {
            "editor_bg":      "#fdf6e3", "editor_fg":      "#657b83",
            "margin_bg":      "#eee8d5", "margin_fg":      "#93a1a1",
            "caret_line_bg":  "#eee8d5", "caret_fg":       "#586e75",
            "selection_bg":   "#eee8d5", "selection_fg":   "#586e75",
            "brace_match_bg": "#859900", "brace_match_fg": "#fdf6e3",
            "brace_bad_bg":   "#dc322f", "brace_bad_fg":   "#fdf6e3",
            "find_indicator": "#b58900",
            "whitespace_fg":  "#eee8d5",
            "fold_fg":        "#93a1a1", "fold_bg": "#fdf6e3",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#657b83", "bg": "#fdf6e3"},
            "comment":        {"fg": "#93a1a1", "italic": True},
            "comment_block":  {"fg": "#93a1a1", "italic": True},
            "keyword":        {"fg": "#859900", "bold": True},
            "keyword2":       {"fg": "#2aa198"},
            "string":         {"fg": "#2aa198"},
            "string2":        {"fg": "#2aa198"},
            "string_raw":     {"fg": "#2aa198"},
            "number":         {"fg": "#d33682"},
            "operator":       {"fg": "#657b83"},
            "identifier":     {"fg": "#268bd2"},
            "function":       {"fg": "#268bd2"},
            "class_name":     {"fg": "#b58900"},
            "builtin":        {"fg": "#cb4b16"},
            "decorator":      {"fg": "#6c71c4"},
            "preprocessor":   {"fg": "#cb4b16"},
            "regex":          {"fg": "#dc322f"},
            "constant":       {"fg": "#d33682"},
            "type":           {"fg": "#b58900"},
            "label":          {"fg": "#657b83"},
            "error":          {"fg": "#fdf6e3", "bg": "#dc322f"},
            "unclosed_string":{"fg": "#2aa198", "bg": "#fdf0e0"},
            "tag":            {"fg": "#268bd2"},
            "attribute":      {"fg": "#657b83"},
            "attribute_value":{"fg": "#2aa198"},
            "entity":         {"fg": "#cb4b16"},
            "command":        {"fg": "#268bd2", "bold": True},
            "math":           {"fg": "#d33682"},
            "math_command":   {"fg": "#2aa198"},
            "environment":    {"fg": "#859900"},
            "special_char":   {"fg": "#657b83"},
        }
    },

    "Tokyo Night": {
        "meta": {"name": "Tokyo Night", "author": "enkia", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#1a1b26", "editor_fg":      "#a9b1d6",
            "margin_bg":      "#16161e", "margin_fg":      "#3b3d57",
            "caret_line_bg":  "#1f2335", "caret_fg":       "#c0caf5",
            "selection_bg":   "#283457", "selection_fg":   None,
            "brace_match_bg": "#414868", "brace_match_fg": "#f7768e",
            "brace_bad_bg":   "#f7768e", "brace_bad_fg":   "#1a1b26",
            "find_indicator": "#e0af68",
            "whitespace_fg":  "#1f2335",
            "fold_fg":        "#3b3d57", "fold_bg": "#1a1b26",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#a9b1d6", "bg": "#1a1b26"},
            "comment":        {"fg": "#565f89", "italic": True},
            "comment_block":  {"fg": "#565f89", "italic": True},
            "keyword":        {"fg": "#bb9af7", "bold": True},
            "keyword2":       {"fg": "#7dcfff"},
            "string":         {"fg": "#9ece6a"},
            "string2":        {"fg": "#9ece6a"},
            "string_raw":     {"fg": "#73daca"},
            "number":         {"fg": "#ff9e64"},
            "operator":       {"fg": "#89ddff"},
            "identifier":     {"fg": "#c0caf5"},
            "function":       {"fg": "#7aa2f7"},
            "class_name":     {"fg": "#e0af68"},
            "builtin":        {"fg": "#7dcfff"},
            "decorator":      {"fg": "#7aa2f7"},
            "preprocessor":   {"fg": "#bb9af7"},
            "regex":          {"fg": "#73daca"},
            "constant":       {"fg": "#ff9e64"},
            "type":           {"fg": "#e0af68"},
            "label":          {"fg": "#a9b1d6"},
            "error":          {"fg": "#1a1b26", "bg": "#f7768e"},
            "unclosed_string":{"fg": "#9ece6a", "bg": "#1a2010"},
            "tag":            {"fg": "#f7768e"},
            "attribute":      {"fg": "#e0af68"},
            "attribute_value":{"fg": "#9ece6a"},
            "entity":         {"fg": "#ff9e64"},
            "command":        {"fg": "#bb9af7", "bold": True},
            "math":           {"fg": "#e0af68"},
            "math_command":   {"fg": "#73daca", "italic": True},
            "environment":    {"fg": "#7aa2f7"},
            "special_char":   {"fg": "#89ddff"},
        }
    },

    "GitHub Light": {
        "meta": {"name": "GitHub Light", "author": "NotePadPQ", "version": "1.0", "dark": False},
        "ui": {
            "editor_bg":      "#ffffff", "editor_fg":      "#24292f",
            "margin_bg":      "#f6f8fa", "margin_fg":      "#8c959f",
            "caret_line_bg":  "#f6f8fa", "caret_fg":       "#24292f",
            "selection_bg":   "#0550ae", "selection_fg":   "#ffffff",
            "brace_match_bg": "#dafbe1", "brace_match_fg": "#24292f",
            "brace_bad_bg":   "#ffebe9", "brace_bad_fg":   "#24292f",
            "find_indicator": "#fb8500",
            "whitespace_fg":  "#e8ebef",
            "fold_fg":        "#8c959f", "fold_bg": "#f6f8fa",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#24292f", "bg": "#ffffff"},
            "comment":        {"fg": "#6e7781", "italic": True},
            "comment_block":  {"fg": "#6e7781", "italic": True},
            "keyword":        {"fg": "#cf222e", "bold": True},
            "keyword2":       {"fg": "#0550ae"},
            "string":         {"fg": "#0a3069"},
            "string2":        {"fg": "#0a3069"},
            "string_raw":     {"fg": "#0550ae"},
            "number":         {"fg": "#0550ae"},
            "operator":       {"fg": "#24292f"},
            "identifier":     {"fg": "#24292f"},
            "function":       {"fg": "#8250df"},
            "class_name":     {"fg": "#953800"},
            "builtin":        {"fg": "#0550ae"},
            "decorator":      {"fg": "#8250df"},
            "preprocessor":   {"fg": "#cf222e"},
            "regex":          {"fg": "#116329"},
            "constant":       {"fg": "#0550ae"},
            "type":           {"fg": "#953800"},
            "label":          {"fg": "#24292f"},
            "error":          {"fg": "#ffffff", "bg": "#cf222e"},
            "unclosed_string":{"fg": "#0a3069", "bg": "#fff8e1"},
            "tag":            {"fg": "#116329"},
            "attribute":      {"fg": "#0550ae"},
            "attribute_value":{"fg": "#0a3069"},
            "entity":         {"fg": "#953800"},
            "command":        {"fg": "#8250df", "bold": True},
            "math":           {"fg": "#0550ae"},
            "math_command":   {"fg": "#116329"},
            "environment":    {"fg": "#953800"},
            "special_char":   {"fg": "#24292f"},
        }
    },

    "Ayu Dark": {
        "meta": {"name": "Ayu Dark", "author": "dempfi", "version": "1.0", "dark": True},
        "ui": {
            "editor_bg":      "#0d1017", "editor_fg":      "#bfbdb6",
            "margin_bg":      "#0d1017", "margin_fg":      "#3d4354",
            "caret_line_bg":  "#131721", "caret_fg":       "#ffb454",
            "selection_bg":   "#273747", "selection_fg":   None,
            "brace_match_bg": "#253340", "brace_match_fg": "#ffb454",
            "brace_bad_bg":   "#f26d78", "brace_bad_fg":   "#0d1017",
            "find_indicator": "#ffb454",
            "whitespace_fg":  "#1a1f29",
            "fold_fg":        "#3d4354", "fold_bg": "#0d1017",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":        {"fg": "#bfbdb6", "bg": "#0d1017"},
            "comment":        {"fg": "#5c6773", "italic": True},
            "comment_block":  {"fg": "#5c6773", "italic": True},
            "keyword":        {"fg": "#ff8f40", "bold": True},
            "keyword2":       {"fg": "#39bae6"},
            "string":         {"fg": "#aad94c"},
            "string2":        {"fg": "#aad94c"},
            "string_raw":     {"fg": "#95e6cb"},
            "number":         {"fg": "#d2a6ff"},
            "operator":       {"fg": "#f29668"},
            "identifier":     {"fg": "#bfbdb6"},
            "function":       {"fg": "#ffb454"},
            "class_name":     {"fg": "#59c2ff"},
            "builtin":        {"fg": "#39bae6"},
            "decorator":      {"fg": "#ffb454"},
            "preprocessor":   {"fg": "#ff8f40"},
            "regex":          {"fg": "#95e6cb"},
            "constant":       {"fg": "#d2a6ff"},
            "type":           {"fg": "#59c2ff"},
            "label":          {"fg": "#bfbdb6"},
            "error":          {"fg": "#0d1017", "bg": "#f26d78"},
            "unclosed_string":{"fg": "#aad94c", "bg": "#0d1a00"},
            "tag":            {"fg": "#59c2ff"},
            "attribute":      {"fg": "#ffb454"},
            "attribute_value":{"fg": "#aad94c"},
            "entity":         {"fg": "#f29668"},
            "command":        {"fg": "#ff8f40", "bold": True},
            "math":           {"fg": "#d2a6ff"},
            "math_command":   {"fg": "#95e6cb", "italic": True},
            "environment":    {"fg": "#59c2ff"},
            "special_char":   {"fg": "#bfbdb6"},
        }
    },


    "Plain Dark": {
        "meta": {
            "name": "Plain Dark",
            "author": "NotePadPQ",
            "version": "1.0",
            "dark": True,
            "description": "Testo monocromatico su sfondo scuro — nessuna distinzione sintattica",
        },
        "ui": {
            "editor_bg":      "#1e1e1e",
            "editor_fg":      "#cccccc",
            "margin_bg":      "#1e1e1e",
            "margin_fg":      "#555555",
            "caret_line_bg":  "#2a2a2a",
            "caret_fg":       "#cccccc",
            "selection_bg":   "#3a5a78",
            "selection_fg":   None,
            "brace_match_bg": "#2a4a2a",
            "brace_match_fg": "#cccccc",
            "brace_bad_bg":   "#4a1a1a",
            "brace_bad_fg":   "#cccccc",
            "find_indicator": "#888800",
            "whitespace_fg":  "#333333",
            "fold_fg":        "#555555",
            "fold_bg":        "#1e1e1e",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":         {"fg": "#cccccc", "bg": "#1e1e1e"},
            "comment":         {"fg": "#cccccc"},
            "comment_block":   {"fg": "#cccccc"},
            "keyword":         {"fg": "#cccccc"},
            "keyword2":        {"fg": "#cccccc"},
            "string":          {"fg": "#cccccc"},
            "string2":         {"fg": "#cccccc"},
            "string_raw":      {"fg": "#cccccc"},
            "number":          {"fg": "#cccccc"},
            "operator":        {"fg": "#cccccc"},
            "identifier":      {"fg": "#cccccc"},
            "function":        {"fg": "#cccccc"},
            "class_name":      {"fg": "#cccccc"},
            "builtin":         {"fg": "#cccccc"},
            "decorator":       {"fg": "#cccccc"},
            "preprocessor":    {"fg": "#cccccc"},
            "regex":           {"fg": "#cccccc"},
            "constant":        {"fg": "#cccccc"},
            "type":            {"fg": "#cccccc"},
            "label":           {"fg": "#cccccc"},
            "error":           {"fg": "#ff6060", "bg": "#3a0000"},
            "unclosed_string": {"fg": "#cccccc", "bg": "#3a2000"},
            "tag":             {"fg": "#cccccc"},
            "attribute":       {"fg": "#cccccc"},
            "attribute_value": {"fg": "#cccccc"},
            "entity":          {"fg": "#cccccc"},
            "command":         {"fg": "#cccccc"},
            "math":            {"fg": "#cccccc"},
            "math_command":    {"fg": "#cccccc"},
            "environment":     {"fg": "#cccccc"},
            "special_char":    {"fg": "#cccccc"},
        }
    },

    "Plain Light": {
        "meta": {
            "name": "Plain Light",
            "author": "NotePadPQ",
            "version": "1.0",
            "dark": False,
            "description": "Testo monocromatico su sfondo chiaro — nessuna distinzione sintattica",
        },
        "ui": {
            "editor_bg":      "#ffffff",
            "editor_fg":      "#222222",
            "margin_bg":      "#f5f5f5",
            "margin_fg":      "#999999",
            "caret_line_bg":  "#f0f0f0",
            "caret_fg":       "#222222",
            "selection_bg":   "#b0cce0",
            "selection_fg":   "#000000",
            "brace_match_bg": "#d0e8d0",
            "brace_match_fg": "#222222",
            "brace_bad_bg":   "#f0c0c0",
            "brace_bad_fg":   "#222222",
            "find_indicator": "#cc8800",
            "whitespace_fg":  "#cccccc",
            "fold_fg":        "#aaaaaa",
            "fold_bg":        "#f5f5f5",
        },
        "font": {"family": None, "size": 11},
        "tokens": {
            "default":         {"fg": "#222222", "bg": "#ffffff"},
            "comment":         {"fg": "#222222"},
            "comment_block":   {"fg": "#222222"},
            "keyword":         {"fg": "#222222"},
            "keyword2":        {"fg": "#222222"},
            "string":          {"fg": "#222222"},
            "string2":         {"fg": "#222222"},
            "string_raw":      {"fg": "#222222"},
            "number":          {"fg": "#222222"},
            "operator":        {"fg": "#222222"},
            "identifier":      {"fg": "#222222"},
            "function":        {"fg": "#222222"},
            "class_name":      {"fg": "#222222"},
            "builtin":         {"fg": "#222222"},
            "decorator":       {"fg": "#222222"},
            "preprocessor":    {"fg": "#222222"},
            "regex":           {"fg": "#222222"},
            "constant":        {"fg": "#222222"},
            "type":            {"fg": "#222222"},
            "label":           {"fg": "#222222"},
            "error":           {"fg": "#cc0000", "bg": "#ffe8e8"},
            "unclosed_string": {"fg": "#222222", "bg": "#fff4e0"},
            "tag":             {"fg": "#222222"},
            "attribute":       {"fg": "#222222"},
            "attribute_value": {"fg": "#222222"},
            "entity":          {"fg": "#222222"},
            "command":         {"fg": "#222222"},
            "math":            {"fg": "#222222"},
            "math_command":    {"fg": "#222222"},
            "environment":     {"fg": "#222222"},
            "special_char":    {"fg": "#222222"},
        }
    },

}

# ─── ThemeManager ─────────────────────────────────────────────────────────────

class ThemeManager(QObject):
    """
    Singleton. Gestisce caricamento, applicazione e personalizzazione temi.
    """

    theme_changed = pyqtSignal(str)   # nome tema

    _instance: Optional["ThemeManager"] = None

    def __init__(self):
        super().__init__()
        self._active_name: str = "Dark"
        self._themes: dict[str, dict] = dict(BUILTIN_THEMES)
        self._user_themes_dir: Optional[Path] = None
        self._load_user_themes()

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Caricamento ───────────────────────────────────────────────────────────

    def _load_user_themes(self) -> None:
        """Carica i temi JSON dalla directory utente."""
        try:
            from core.platform import get_data_dir
            self._user_themes_dir = get_data_dir() / "themes"
            self._user_themes_dir.mkdir(parents=True, exist_ok=True)
            for f in self._user_themes_dir.glob("*.json"):
                try:
                    theme = json.loads(f.read_text(encoding="utf-8"))
                    name = theme.get("meta", {}).get("name", f.stem)
                    self._themes[name] = theme
                except Exception as e:
                    print(f"[themes] Errore caricamento {f}: {e}")
        except Exception:
            pass

    def available_themes(self) -> list[str]:
        """Restituisce la lista di nomi tema ordinata (built-in prima)."""
        builtin = list(BUILTIN_THEMES.keys())
        user = [k for k in self._themes if k not in BUILTIN_THEMES]
        return builtin + sorted(user)

    def get_theme(self, name: str) -> Optional[dict]:
        return self._themes.get(name)

    def is_dark(self, name: str = "") -> bool:
        n = name or self._active_name
        return self._themes.get(n, {}).get("meta", {}).get("dark", True)

    # ── Tema attivo ───────────────────────────────────────────────────────────

    def active_name(self) -> str:
        return self._active_name

    def set_active(self, name: str) -> bool:
        if name not in self._themes:
            return False
        self._active_name = name
        self.theme_changed.emit(name)
        return True

    # ── Applicazione ──────────────────────────────────────────────────────────

    def apply_to_editor(self, editor: "EditorWidget",
                        theme_name: str = "") -> None:
        """
        Applica un tema a un EditorWidget.
        Se theme_name è vuoto, usa il tema attivo.
        """
        name = theme_name or self._active_name
        theme = self._themes.get(name)
        if not theme:
            return

        ui     = theme.get("ui", {})
        tokens = theme.get("tokens", {})
        font_d = theme.get("font", {})

        # ── Font ──
        from core.platform import get_preferred_monospace_font
        family = font_d.get("family") or get_preferred_monospace_font()
        size   = font_d.get("size", 11)
        editor.set_font_family(family, size)

        # ── Colori UI ──
        def c(key, fallback="#000000"):
            v = ui.get(key)
            return QColor(v) if v else None

        bg = c("editor_bg", "#1e1e1e")
        fg = c("editor_fg", "#d4d4d4")
        if bg and fg:
            editor.setPaper(bg)
            editor.setColor(fg)

        if c("caret_line_bg"):
            editor.setCaretLineBackgroundColor(c("caret_line_bg"))
        if c("caret_fg"):
            editor.setCaretForegroundColor(c("caret_fg"))
        if c("margin_bg"):
            editor.setMarginsBackgroundColor(c("margin_bg"))
        if c("margin_fg"):
            editor.setMarginsForegroundColor(c("margin_fg"))
        if c("selection_bg"):
            editor.setSelectionBackgroundColor(c("selection_bg"))
        sel_fg = c("selection_fg")
        if sel_fg:
            editor.setSelectionForegroundColor(sel_fg)
        if c("brace_match_bg"):
            editor.setMatchedBraceBackgroundColor(c("brace_match_bg"))
        if c("brace_match_fg"):
            editor.setMatchedBraceForegroundColor(c("brace_match_fg"))
        if c("brace_bad_bg"):
            editor.setUnmatchedBraceBackgroundColor(c("brace_bad_bg"))
        if c("brace_bad_fg"):
            editor.setUnmatchedBraceForegroundColor(c("brace_bad_fg"))
        if c("whitespace_fg"):
            editor.setWhitespaceForegroundColor(c("whitespace_fg"))
        if c("fold_fg"):
            editor.setFoldMarginColors(c("fold_bg") or bg, c("fold_fg"))

        # ── Lexer tokens ──
        lexer = editor.lexer()
        if lexer:
            self._apply_tokens_to_lexer(lexer, tokens, family, size, bg, fg)

    def _apply_tokens_to_lexer(self, lexer, tokens: dict,
                                font_family: str, font_size: int,
                                editor_bg: QColor, editor_fg: QColor) -> None:
        """
        Applica i colori dei token al lexer corrente.
        Usa mappature precise stile-numero → chiave-token per ogni tipo di lexer.
        """
        from PyQt6.Qsci import (
            QsciLexerPython, QsciLexerCPP, QsciLexerJavaScript,
            QsciLexerBash, QsciLexerTeX, QsciLexerHTML, QsciLexerXML,
            QsciLexerCSS, QsciLexerSQL, QsciLexerJSON, QsciLexerYAML,
            QsciLexerMarkdown, QsciLexerRuby, QsciLexerLua,
            QsciLexerJava, QsciLexerCSharp,
        )

        # Font base
        base_font = QFont(font_family, font_size)
        base_font.setFixedPitch(True)
        lexer.setDefaultFont(base_font)
        lexer.setDefaultPaper(editor_bg)
        lexer.setDefaultColor(editor_fg)

        # Prima passo: imposta sfondo e font uniformi per tutti gli stili
        default_tok = tokens.get("default", {})
        def_fg = QColor(default_tok.get("fg", editor_fg.name()))
        def_bg = QColor(default_tok.get("bg", editor_bg.name()))
        for style_num in range(128):
            try:
                f = QFont(font_family, font_size)
                f.setFixedPitch(True)
                lexer.setColor(def_fg, style_num)
                lexer.setPaper(def_bg, style_num)
                lexer.setFont(f, style_num)
            except Exception:
                break

        # Secondo passo: applica i colori specifici per tipo di lexer
        def _apply(style_map: dict) -> None:
            """style_map: {stile_num: chiave_token}"""
            for style_num, tok_key in style_map.items():
                tok = tokens.get(tok_key, {})
                if not tok:
                    continue
                fg = QColor(tok["fg"]) if "fg" in tok else def_fg
                bg = QColor(tok.get("bg", def_bg.name()))
                f  = QFont(font_family, font_size)
                f.setFixedPitch(True)
                if tok.get("bold"):
                    f.setBold(True)
                if tok.get("italic"):
                    f.setItalic(True)
                try:
                    lexer.setColor(fg, style_num)
                    lexer.setPaper(bg, style_num)
                    lexer.setFont(f, style_num)
                except Exception:
                    pass

        # ── Python ────────────────────────────────────────────────────────────
        if isinstance(lexer, QsciLexerPython):
            _apply({
                0:  "default",
                1:  "comment",
                2:  "number",
                3:  "string",
                4:  "string",
                5:  "keyword",
                6:  "string",
                7:  "string",
                8:  "class_name",
                9:  "function",
                10: "operator",
                11: "identifier",
                12: "comment_block",
                13: "string_raw",
                14: "string_raw",
                15: "decorator",
                16: "string",
                17: "string",
                18: "string",
                19: "string",
            })

        # ── C / C++ / C# / Java (tutti ereditano da QsciLexerCPP) ─────────────
        elif isinstance(lexer, (QsciLexerCPP, QsciLexerCSharp, QsciLexerJava)):
            _apply({
                0:  "default",
                1:  "comment",
                2:  "comment",
                3:  "comment_block",
                4:  "number",
                5:  "keyword",
                6:  "string",
                7:  "string",
                8:  "string",
                9:  "preprocessor",
                10: "operator",
                11: "identifier",
                12: "unclosed_string",
                13: "keyword2",
                14: "comment_block",
                15: "regex",
                16: "comment",
                17: "comment",
                18: "string2",
                19: "string_raw",
                20: "string2",
            })

        # ── JavaScript (eredita da CPP ma ha regex prominent) ─────────────────
        elif isinstance(lexer, QsciLexerJavaScript):
            _apply({
                0:  "default",
                1:  "comment",
                2:  "comment",
                3:  "comment_block",
                4:  "number",
                5:  "keyword",
                6:  "string",
                7:  "string",
                8:  "string",
                9:  "preprocessor",
                10: "operator",
                11: "identifier",
                12: "unclosed_string",
                13: "keyword2",
                14: "comment_block",
                15: "regex",
            })

        # ── Bash / Shell ──────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerBash):
            _apply({
                0:  "default",
                1:  "error",
                2:  "comment",
                3:  "number",
                4:  "keyword",
                5:  "string",
                6:  "string2",
                7:  "operator",
                8:  "identifier",
                9:  "string",
                10: "string",
                11: "string",
                12: "string",
                13: "string",
            })

        # ── LaTeX / TeX ───────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerTeX):
            _apply({
                0: "default",
                1: "special_char",
                2: "command",
                3: "math",
                4: "command",
                5: "string",
            })

        # ── HTML / XML ────────────────────────────────────────────────────────
        elif isinstance(lexer, (QsciLexerHTML, QsciLexerXML)):
            _apply({
                0:  "default",
                1:  "tag",
                2:  "tag",
                3:  "attribute",
                4:  "attribute",
                5:  "attribute_value",
                6:  "attribute_value",
                7:  "attribute_value",
                8:  "attribute_value",
                9:  "comment",
                10: "entity",
                11: "tag",
                17: "string",        # script default
                62: "comment",       # server-side
                63: "default",
            })

        # ── CSS ───────────────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerCSS):
            _apply({
                0:  "default",
                1:  "tag",
                2:  "class_name",
                3:  "keyword",
                4:  "keyword2",
                5:  "attribute",
                6:  "string",
                7:  "string2",
                8:  "operator",
                9:  "identifier",
                10: "comment",
                11: "number",
                12: "attribute_value",
                13: "regex",
            })

        # ── SQL ───────────────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerSQL):
            _apply({
                0:  "default",
                1:  "comment",
                2:  "comment",
                3:  "comment_block",
                4:  "number",
                5:  "keyword",
                6:  "string",
                7:  "string2",
                8:  "operator",
                9:  "identifier",
                10: "comment",
                11: "keyword2",
                13: "keyword",
                14: "type",
            })

        # ── JSON ──────────────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerJSON):
            _apply({
                0:  "default",
                1:  "number",
                2:  "string",
                3:  "unclosed_string",
                4:  "attribute",     # property name
                5:  "operator",
                6:  "keyword",       # keywords (true/false/null)
                7:  "error",
                8:  "comment",
                9:  "comment",
            })

        # ── YAML ──────────────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerYAML):
            _apply({
                0:  "default",
                1:  "comment",
                2:  "identifier",    # identifier
                3:  "keyword",       # keyword
                4:  "number",
                5:  "string",
                6:  "string2",
                7:  "error",
                8:  "operator",
                9:  "attribute",
                10: "attribute",
            })

        # ── Markdown ──────────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerMarkdown):
            _apply({
                0:  "default",
                1:  "comment",      # special char
                2:  "keyword",      # strong ** **
                3:  "string",       # emphasis * *
                4:  "string2",      # code `
                5:  "tag",          # header #
                6:  "tag",          # header ##
                7:  "tag",          # header ###-######
                8:  "identifier",   # hrule
                9:  "string",       # link
                10: "attribute",    # link description
                11: "number",       # image
                12: "keyword2",     # code block
            })

        # ── Ruby ──────────────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerRuby):
            _apply({
                0:  "default",
                1:  "error",
                2:  "comment",
                3:  "preprocessor",
                4:  "number",
                5:  "string",       # here-doc
                6:  "string",       # here-doc end
                7:  "string2",
                8:  "string",
                9:  "string",       # multi-line string
                10: "string_raw",   # %q
                11: "string",       # %Q
                12: "string",       # %w
                13: "regex",
                14: "operator",
                15: "identifier",
                16: "class_name",
                17: "function",
                18: "keyword",
                19: "builtin",
                20: "keyword2",
                21: "decorator",    # symbol
            })

        # ── Lua ───────────────────────────────────────────────────────────────
        elif isinstance(lexer, QsciLexerLua):
            _apply({
                0:  "default",
                1:  "comment",
                2:  "comment_block",
                3:  "comment_block",
                4:  "number",
                5:  "keyword",
                6:  "string",
                7:  "string2",
                8:  "string",       # literal string
                9:  "preprocessor",
                10: "operator",
                11: "identifier",
                12: "keyword2",
                13: "builtin",
            })

    # ── Salvataggio tema custom ───────────────────────────────────────────────

    def save_user_theme(self, theme: dict) -> bool:
        """Salva un tema personalizzato nella directory utente."""
        name = theme.get("meta", {}).get("name", "Custom")
        if not self._user_themes_dir:
            return False
        try:
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-")
            path = self._user_themes_dir / f"{safe_name}.json"
            path.write_text(
                json.dumps(theme, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            self._themes[name] = theme
            return True
        except Exception as e:
            print(f"[themes] Errore salvataggio: {e}")
            return False

    def delete_user_theme(self, name: str) -> bool:
        """Elimina un tema utente (non può eliminare i built-in)."""
        if name in BUILTIN_THEMES:
            return False
        try:
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-")
            path = self._user_themes_dir / f"{safe_name}.json"
            if path.exists():
                path.unlink()
            self._themes.pop(name, None)
            return True
        except Exception:
            return False

    def export_theme(self, name: str, dest_path: Path) -> bool:
        """Esporta un tema in un file JSON esterno."""
        theme = self._themes.get(name)
        if not theme:
            return False
        try:
            dest_path.write_text(
                json.dumps(theme, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            return True
        except Exception:
            return False

    def import_theme(self, path: Path) -> Optional[str]:
        """
        Importa un tema da file JSON esterno.
        Restituisce il nome del tema importato o None in caso di errore.
        """
        try:
            theme = json.loads(path.read_text(encoding="utf-8"))
            name = theme.get("meta", {}).get("name", path.stem)
            theme["meta"]["name"] = name
            if self.save_user_theme(theme):
                return name
        except Exception as e:
            print(f"[themes] Errore importazione: {e}")
        return None

    def clone_theme(self, source_name: str, new_name: str) -> Optional[dict]:
        """
        Clona un tema (built-in o utente) come base per un tema custom.
        Restituisce il nuovo tema (non ancora salvato).
        """
        import copy
        source = self._themes.get(source_name)
        if not source:
            return None
        clone = copy.deepcopy(source)
        clone["meta"]["name"] = new_name
        clone["meta"]["author"] = "Utente"
        return clone


# ─── Test standalone ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from PyQt6.Qsci import QsciLexerPython

    app = QApplication(sys.argv)
    tm = ThemeManager.instance()

    print(f"Temi disponibili: {tm.available_themes()}")
    print(f"Tema attivo: {tm.active_name()}")

    for name in tm.available_themes():
        theme = tm.get_theme(name)
        dark  = tm.is_dark(name)
        ntok  = len(theme.get("tokens", {}))
        print(f"  {name:<20} dark={dark}  token={ntok}")

    # Test clone e salvataggio
    clone = tm.clone_theme("Dark", "Il mio Dark")
    if clone:
        clone["tokens"]["keyword"]["fg"] = "#ff0000"
        saved = tm.save_user_theme(clone)
        print(f"\nClone 'Il mio Dark' salvato: {saved}")
        print(f"Temi dopo salvataggio: {tm.available_themes()}")
