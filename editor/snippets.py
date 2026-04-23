"""
editor/snippets.py — Gestione snippet
NotePadPQ

Snippet espandibili con trigger: digitare il trigger + Tab espande il template.
Supporta variabili: ${1}, ${2}, ... (tab-stop), ${0} (posizione finale),
${FILENAME}, ${DATE}, ${CLIPBOARD}.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from core.platform import get_data_dir

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# ─── Snippet built-in per linguaggio ─────────────────────────────────────────

BUILTIN_SNIPPETS: dict[str, dict[str, dict]] = {

    "python": {
        "def": {
            "trigger": "def",
            "description": "Definizione funzione",
            "body": "def ${1:nome}(${2:args}):\n    ${0:pass}",
        },
        "class": {
            "trigger": "class",
            "description": "Definizione classe",
            "body": "class ${1:Nome}(${2:object}):\n    def __init__(self):\n        ${0:pass}",
        },
        "if": {
            "trigger": "if",
            "description": "Blocco if",
            "body": "if ${1:condizione}:\n    ${0:pass}",
        },
        "ifmain": {
            "trigger": "ifmain",
            "description": "if __name__ == '__main__'",
            "body": "if __name__ == \"__main__\":\n    ${0:main()}",
        },
        "for": {
            "trigger": "for",
            "description": "Ciclo for",
            "body": "for ${1:item} in ${2:iterable}:\n    ${0:pass}",
        },
        "try": {
            "trigger": "try",
            "description": "Blocco try/except",
            "body": "try:\n    ${1:pass}\nexcept ${2:Exception} as e:\n    ${0:print(e)}",
        },
        "with": {
            "trigger": "with",
            "description": "Context manager",
            "body": "with ${1:open('${2:file}')} as ${3:f}:\n    ${0:pass}",
        },
        "prop": {
            "trigger": "prop",
            "description": "Property",
            "body": "@property\ndef ${1:nome}(self):\n    return self._${1:nome}\n\n@${1:nome}.setter\ndef ${1:nome}(self, value):\n    self._${1:nome} = value",
        },
        "dataclass": {
            "trigger": "dc",
            "description": "Dataclass",
            "body": "from dataclasses import dataclass, field\n\n@dataclass\nclass ${1:Nome}:\n    ${2:campo}: ${3:str} = ${0:''}",
        },
    },

    "latex": {
        "begin": {
            "trigger": "beg",
            "description": "\\begin{} ... \\end{}",
            "body": "\\begin{${1:environment}}\n    ${0}\n\\end{${1:environment}}",
        },
        "figure": {
            "trigger": "fig",
            "description": "Ambiente figure",
            "body": "\\begin{figure}[${1:htbp}]\n    \\centering\n    \\includegraphics[width=${2:\\textwidth}]{${3:file}}\n    \\caption{${4:Caption}}\n    \\label{fig:${5:label}}\n\\end{figure}",
        },
        "table": {
            "trigger": "tab",
            "description": "Ambiente table con tabular",
            "body": "\\begin{table}[${1:htbp}]\n    \\centering\n    \\caption{${2:Caption}}\n    \\label{tab:${3:label}}\n    \\begin{tabular}{${4:ll}}\n        \\toprule\n        ${5:Col1} & ${0:Col2} \\\\\\\\\n        \\midrule\n        & \\\\\\\\\n        \\bottomrule\n    \\end{tabular}\n\\end{table}",
        },
        "equation": {
            "trigger": "eq",
            "description": "Ambiente equation",
            "body": "\\begin{equation}\n    ${1:formula}\n    \\label{eq:${2:label}}\n\\end{equation}",
        },
        "align": {
            "trigger": "al",
            "description": "Ambiente align",
            "body": "\\begin{align}\n    ${1:formula} &= ${0} \\\\\\\\\n\\end{align}",
        },
        "section": {
            "trigger": "sec",
            "description": "\\section{}",
            "body": "\\section{${1:Titolo}}\n\\label{sec:${2:label}}\n\n${0}",
        },
        "itemize": {
            "trigger": "it",
            "description": "Ambiente itemize",
            "body": "\\begin{itemize}\n    \\item ${1:primo}\n    \\item ${0:secondo}\n\\end{itemize}",
        },
        "enumerate": {
            "trigger": "en",
            "description": "Ambiente enumerate",
            "body": "\\begin{enumerate}\n    \\item ${1:primo}\n    \\item ${0:secondo}\n\\end{enumerate}",
        },
        "ref": {
            "trigger": "ref",
            "description": "\\ref{}",
            "body": "\\ref{${1:label}}",
        },
        "cite": {
            "trigger": "ci",
            "description": "\\cite{}",
            "body": "\\cite{${1:chiave}}",
        },
        "textbf": {
            "trigger": "bf",
            "description": "Testo in grassetto",
            "body": "\\textbf{${1:testo}}${0}",
        },
        "textit": {
            "trigger": "it2",
            "description": "Testo in corsivo",
            "body": "\\textit{${1:testo}}${0}",
        },
        "frac": {
            "trigger": "fr",
            "description": "Frazione",
            "body": "\\frac{${1:num}}{${2:den}}${0}",
        },
    },

    "html": {
        "html5": {
            "trigger": "html5",
            "description": "Template HTML5 base",
            "body": "<!DOCTYPE html>\n<html lang=\"${1:it}\">\n<head>\n    <meta charset=\"UTF-8\">\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n    <title>${2:Titolo}</title>\n</head>\n<body>\n    ${0}\n</body>\n</html>",
        },
        "div": {
            "trigger": "div",
            "description": "<div class=\"\">",
            "body": "<div class=\"${1:classe}\">\n    ${0}\n</div>",
        },
        "link": {
            "trigger": "a",
            "description": "<a href=\"\">",
            "body": "<a href=\"${1:#}\">${0:testo}</a>",
        },
        "img": {
            "trigger": "img",
            "description": "<img>",
            "body": "<img src=\"${1:url}\" alt=\"${2:descrizione}\">",
        },
    },

    "bash": {
        "shebang": {
            "trigger": "sheb",
            "description": "Shebang bash",
            "body": "#!/bin/bash\nset -euo pipefail\n\n${0}",
        },
        "function": {
            "trigger": "fn",
            "description": "Funzione bash",
            "body": "${1:nome}() {\n    ${0}\n}",
        },
        "if": {
            "trigger": "if",
            "description": "Blocco if",
            "body": "if [[ ${1:condizione} ]]; then\n    ${0}\nfi",
        },
        "for": {
            "trigger": "for",
            "description": "Ciclo for",
            "body": "for ${1:item} in ${2:lista}; do\n    ${0}\ndone",
        },
    },

    "javascript": {
        "fn": {
            "trigger": "fn",
            "description": "Funzione arrow",
            "body": "const ${1:nome} = (${2:args}) => {\n    ${0}\n};",
        },
        "afn": {
            "trigger": "afn",
            "description": "Funzione async",
            "body": "const ${1:nome} = async (${2:args}) => {\n    try {\n        ${0}\n    } catch (error) {\n        console.error(error);\n    }\n};",
        },
        "class": {
            "trigger": "cls",
            "description": "Classe ES6",
            "body": "class ${1:Nome} {\n    constructor(${2:args}) {\n        ${0}\n    }\n}",
        },
        "fetch": {
            "trigger": "fetch",
            "description": "fetch API",
            "body": "const response = await fetch('${1:url}');\nconst data = await response.json();\n${0}",
        },
    },
}


# ─── SnippetManager ───────────────────────────────────────────────────────────

class SnippetManager(QObject):
    """
    Singleton. Gestisce snippet built-in e utente.
    """

    _instance: Optional["SnippetManager"] = None

    def __init__(self):
        super().__init__()
        self._snippets: dict[str, dict[str, dict]] = {}
        # Carica built-in
        for lang, snips in BUILTIN_SNIPPETS.items():
            self._snippets[lang] = dict(snips)
        # Carica utente
        self._load_user_snippets()

    @classmethod
    def instance(cls) -> "SnippetManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _snippets_dir(self) -> Path:
        p = get_data_dir() / "snippets"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _load_user_snippets(self) -> None:
        for f in self._snippets_dir().glob("*.json"):
            lang = f.stem.lower()
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if lang not in self._snippets:
                    self._snippets[lang] = {}
                self._snippets[lang].update(data)
            except Exception:
                pass

    def get_triggers(self, language: str) -> dict[str, str]:
        """Restituisce {trigger: description} per il linguaggio."""
        lang = language.lower()
        snips = self._snippets.get(lang, {})
        return {
            s["trigger"]: s.get("description", s["trigger"])
            for s in snips.values()
            if "trigger" in s
        }

    def expand(self, editor: "EditorWidget", language: str) -> bool:
        """
        Prova ad espandere il trigger prima del cursore.
        Restituisce True se uno snippet è stato espanso.
        """
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)[:col]

        # Trova il trigger: ultima "parola" prima del cursore
        m = re.search(r'\b(\w+)$', line_text)
        if not m:
            return False

        trigger = m.group(1)
        lang    = language.lower()
        snips   = self._snippets.get(lang, {})

        snippet = None
        for s in snips.values():
            if s.get("trigger") == trigger:
                snippet = s
                break

        if not snippet:
            return False

        body = snippet.get("body", "")
        body = self._expand_variables(body, editor)

        # Rimuove il trigger e inserisce il corpo dello snippet
        # Seleziona il trigger
        trigger_start = col - len(trigger)
        editor.setSelection(line, trigger_start, line, col)
        editor.replaceSelectedText("")

        # Inserisce il corpo (semplificato: senza gestione tab-stop interattivi)
        # Rimuove le annotazioni ${N:default} lasciando solo il testo default
        expanded = re.sub(r'\$\{(\d+):([^}]*)\}', r'\2', body)
        expanded = re.sub(r'\$\{(\d+)\}', '', expanded)
        expanded = re.sub(r'\$0', '', expanded)
        editor.insert(expanded)
        return True

    def _expand_variables(self, body: str, editor: "EditorWidget") -> str:
        """Sostituisce le variabili di sistema nel corpo dello snippet."""
        path = editor.file_path
        replacements = {
            "${FILENAME}": path.name if path else "",
            "${BASENAME}": path.stem if path else "",
            "${DIR}":      str(path.parent) if path else "",
            "${DATE}":     datetime.now().strftime("%Y-%m-%d"),
            "${DATETIME}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "${CLIPBOARD}": QApplication.clipboard().text(),
        }
        for var, val in replacements.items():
            body = body.replace(var, val)
        return body

    def save_user_snippet(self, language: str, name: str, snippet: dict) -> None:
        lang = language.lower()
        if lang not in self._snippets:
            self._snippets[lang] = {}
        self._snippets[lang][name] = snippet
        path = self._snippets_dir() / f"{lang}.json"
        user_snips = {
            k: v for k, v in self._snippets[lang].items()
            if k not in BUILTIN_SNIPPETS.get(lang, {})
        }
        path.write_text(
            json.dumps(user_snips, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
