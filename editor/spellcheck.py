"""Motori di controllo ortografico e tokenizzazione consapevole del LaTeX.

Il modulo isola due responsabilità che prima erano sparse tra
``editor_widget`` e ``spell_check_dialog``:

* :func:`iter_spell_words` estrae dal testo solo le parole che ha senso
  controllare, saltando comandi, environment, opzioni, percorsi, URL, commenti
  e blocchi matematici.  Ogni parola è restituita con gli offset originali nel
  testo, così le sottolineature restano allineate.
* :func:`get_spell_checker` sceglie il motore migliore disponibile:
  Hunspell (binario di sistema), poi ``spylls`` (Hunspell puro Python), poi
  ``pyspellchecker`` come fallback storico.

I dizionari Hunspell vengono cercati in ``$NOTEPADPQ_HUNSPELL_DIR``, nella
cartella ``hunspell`` della directory dati dell'applicazione e nei percorsi
standard del sistema.  Se non c'è un dizionario per la lingua richiesta si
torna automaticamente a ``pyspellchecker``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

from core.latex_parser import read_latex_group

# ─── Tokenizzazione ──────────────────────────────────────────────────────────

# Un solo match per parole, numeri, spazi e caratteri speciali: evita di
# iterare carattere per carattere sui documenti grandi.
_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+|\s+|[\\$]|[^\s\w]", re.UNICODE)
_URL_RE = re.compile(
    r"(?:(?:https?|ftp|file)://|www\.)\S+"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    re.IGNORECASE,
)
# Percorsi relativi/assoluti: "inc/Images/mappa.pdf".
# Solo lo slash: il backslash è la sintassi dei comandi LaTeX.
_PATH_RE = re.compile(r"(?:[^\s/]+/)+[\w.-]+", re.UNICODE)

# Comandi di accento LaTeX: base + segno combinante, poi normalizzato in NFC.
_ACCENT_MARKS = {
    "'": "\u0301",  # acuto
    "`": "\u0300",  # grave
    "^": "\u0302",  # circonflesso
    '"': "\u0308",  # dieresi
    "~": "\u0303",  # tilde
    "=": "\u0304",  # macron
    ".": "\u0307",  # punto sovrapposto
    "u": "\u0306",  # breve
    "v": "\u030c",  # caron
    "H": "\u030b",  # doppio acuto
    "c": "\u0327",  # cedilla
    "k": "\u0328",  # ogonek
    "r": "\u030a",  # anello
    "b": "\u0331",  # linea sotto
    "d": "\u0323",  # punto sotto
}

# Environment il cui contenuto non è prosa: si salta fino a \end{...}.
_OPAQUE_ENVIRONMENTS = frozenset({
    "verbatim", "verbatim*", "Verbatim", "Verbatim*", "BVerbatim",
    "lstlisting", "minted", "comment", "filecontents", "filecontents*",
    "alltt", "math", "displaymath", "equation", "equation*", "align",
    "align*", "alignat", "alignat*", "flalign", "flalign*", "gather",
    "gather*", "multline", "multline*", "eqnarray", "eqnarray*", "split",
    "cases", "array", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix",
    "smallmatrix", "tikzpicture", "pgfpicture", "pspicture", "axis",
})

_VERBATIM_COMMANDS = frozenset({"verb", "Verb", "lstinline", "mintinline"})

# Numero di argomenti obbligatori da saltare per i comandi i cui argomenti
# sono chiavi, percorsi, colori, lunghezze o nomi: controllarli produrrebbe
# solo falsi positivi.  Gli argomenti opzionali ``[...]`` sono sempre saltati.
_SKIP_ARG_COUNT: dict[str, int] = {}


def _register_skip(count: int, *names: str) -> None:
    for name in names:
        _SKIP_ARG_COUNT[name] = count


# Riferimenti, etichette, citazioni.
_register_skip(
    1, "label", "ref", "eqref", "pageref", "autoref", "nameref", "vref",
    "vpageref", "cpageref", "labelcref", "namecref", "nameCref", "namecrefs",
    "lcnamecref", "fullref", "cref", "Cref", "crefrange", "Crefrange",
    "cite", "citep", "citet", "citealp", "citeauthor", "citeyear",
    "citeyearpar", "parencite", "textcite", "autocite", "footcite",
    "smartcite", "supercite", "nocite", "bibitem", "newlabel",
)
# Pacchetti, classi e file esterni.
_register_skip(
    1, "usepackage", "RequirePackage", "documentclass", "PassOptionsToPackage",
    "PassOptionsToClass", "input", "include", "includeonly", "includegraphics",
    "includepdf", "lstinputlisting", "bibliography", "bibliographystyle",
    "addbibresource", "bibinput",
)
_register_skip(2, "inputminted")
# Colori: il testo eventualmente seguente resta controllabile.
_register_skip(2, "colorlet")
_register_skip(3, "definecolor")
_register_skip(1, "color", "pagecolor", "textcolor", "colorbox")
_register_skip(2, "fcolorbox")
# colortbl / xcolor: nomi di colore dentro le celle.
_register_skip(1, "cellcolor", "rowcolor", "columncolor", "arrayrulecolor")
_register_skip(3, "rowcolors")
# Ipertesti: \hypertarget{chiave}{testo} (il testo resta controllato).
_register_skip(1, "hypertarget")
_register_skip(1, "captionof")
# Link: \href{url}{testo} e \textcolor{colore}{testo} saltano solo il primo.
_register_skip(1, "url", "nolinkurl", "path", "href", "hyperlink")
# Lunghezze, contatori e definizioni.
_register_skip(2, "setlength", "addtolength", "setcounter", "addtocounter")
_register_skip(1, "newcounter", "hyphenation", "index", "glossary")
_register_skip(
    2, "newcommand", "renewcommand", "providecommand", "DeclareRobustCommand",
    "DeclareMathOperator", "newtheorem",
)
_register_skip(3, "newenvironment", "renewenvironment")
_register_skip(3, "newacronym")
_register_skip(2, "newglossaryentry")
# Grafica, layout e chiavi di configurazione.
_register_skip(
    1, "graphicspath", "geometry", "hypersetup", "lstset", "tikzset",
    "usetikzlibrary", "pgfplotsset", "sisetup", "captionsetup", "ctexset",
    "setmainfont", "setsansfont", "setmonofont",
)
_register_skip(2, "newcolumntype", "fontsize", "setkomafont",
               "addtokomafont", "KOMAoption")
_register_skip(5, "titleformat")
# Unità e matematica dentro testo (mhchem, siunitx, amsmath).
_register_skip(1, "num", "unit", "ang", "ensuremath", "ce", "chemfig",
               "bm", "mathbb", "mathcal", "mathrm", "mathbf", "mathit",
               "mathsf", "mathtt", "mathfrak", "boldsymbol", "pmb")
_register_skip(2, "SI", "qty")
# Tabelle e box.
_register_skip(2, "multicolumn", "multirow")
_register_skip(1, "cline", "cmidrule", "hhline", "parbox", "raisebox",
               "scalebox", "rotatebox")
_register_skip(2, "resizebox", "rule")
# Acronimi e glossario.
_register_skip(
    1, "gls", "glspl", "Gls", "Glss", "Glspl", "acrshort", "acrlong",
    "acrfull", "acrpl", "Acrshort", "Acrlong", "Acrfull",
)


def _skip_space(text: str, index: int) -> int:
    length = len(text)
    while index < length and text[index].isspace():
        index += 1
    return index


def _skip_optional_args(text: str, index: int) -> int:
    """Salta uno o più argomenti opzionali ``[...]`` dopo un comando."""
    length = len(text)
    while True:
        start = _skip_space(text, index)
        if start >= length or text[start] != "[":
            return start
        group = read_latex_group(text, start, "[")
        if group is None:
            return length
        index = group[1] + 1


def _skip_to_end_environment(text: str, start: int, name: str) -> int:
    pattern = re.compile(r"\\end\s*\{\s*" + re.escape(name) + r"\s*\}")
    match = pattern.search(text, start)
    return match.end() if match else len(text)


def _skip_environment(text: str, index: int, command: str) -> int:
    """Salta ``\\begin{env}`` (o ``\\end{env}``) e gli argomenti opzionali."""
    length = len(text)
    index = _skip_space(text, index)
    if index >= length or text[index] != "{":
        return index
    group = read_latex_group(text, index)
    if group is None:
        return length
    name = text[group[0]:group[1]].strip()
    index = group[1] + 1
    if command == "end":
        return index
    index = _skip_optional_args(text, index)
    if name in _OPAQUE_ENVIRONMENTS:
        return _skip_to_end_environment(text, index, name)
    return index


def _skip_verbatim_command(text: str, index: int, name: str) -> int:
    length = len(text)
    index = _skip_space(text, index)
    if index < length and text[index] == "*":
        index = _skip_space(text, index + 1)
    if name == "mintinline":
        index = _skip_optional_args(text, index)
        index = _skip_space(text, index)
        group = read_latex_group(text, index) if index < length and text[index] == "{" else None
        if group is not None:
            index = group[1] + 1
        index = _skip_space(text, index)
    elif name == "lstinline":
        index = _skip_optional_args(text, index)
        index = _skip_space(text, index)
    if index >= length:
        return length
    delimiter = text[index]
    if delimiter == "{":
        # \lstinline{codice}: delimitatore a graffe, non un carattere singolo.
        group = read_latex_group(text, index)
        return length if group is None else group[1] + 1
    end = text.find(delimiter, index + 1)
    return length if end < 0 else end + 1


def _skip_backslash(text: str, index: int) -> int:
    """Salta un comando LaTeX e gli argomenti che non contengono prosa."""
    length = len(text)
    position = index + 1
    if position >= length:
        return length
    char = text[position]

    if char.isalpha() or char == "@":
        end = position
        while end < length and (text[end].isalpha() or text[end] == "@"):
            end += 1
        name = text[position:end]
        if name in _VERBATIM_COMMANDS:
            return _skip_verbatim_command(text, end, name)
        if name in ("begin", "end"):
            return _skip_environment(text, end, name)

        # Forme con asterisco: \section*, \vspace*, \newtheorem*.
        starred = _skip_space(text, end)
        if starred < length and text[starred] == "*":
            end = starred + 1

        end = _skip_optional_args(text, end)
        skipped = 0
        skip_count = _SKIP_ARG_COUNT.get(name, 0)
        while skipped < skip_count:
            argument = _skip_space(text, end)
            if argument < length and text[argument] == "[":
                end = _skip_optional_args(text, argument)
                continue
            if argument >= length or text[argument] != "{":
                break
            group = read_latex_group(text, argument)
            if group is None:
                return length
            end = group[1] + 1
            skipped += 1
        if skip_count:
            # Opzioni finali, es. \newtheorem{thm}{Teorema}[section].
            end = _skip_optional_args(text, end)
        return end

    if char == "(":
        end = text.find("\\)", position + 1)
        return length if end < 0 else end + 2
    if char == "[":
        end = text.find("\\]", position + 1)
        return length if end < 0 else end + 2
    # ``\\`` (a capo), ``\%``, ``\'`` e simili: due caratteri.
    return position + 1


def _skip_math(text: str, index: int) -> int:
    """Salta un blocco matematico delimitato da ``$`` o ``$$``."""
    length = len(text)
    if text.startswith("$$", index):
        end = text.find("$$", index + 2)
        return length if end < 0 else end + 2
    position = index + 1
    while position < length:
        if text[position] == "\\":
            position += 2
            continue
        if text[position] == "$":
            return position + 1
        position += 1
    return length


def _read_accent(text: str, index: int) -> tuple[str, int] | None:
    """Legge ``\\'e`` o ``\\'{e}`` e restituisce (lettera accentata, fine)."""
    if index + 1 >= len(text) or text[index] != "\\":
        return None
    mark = _ACCENT_MARKS.get(text[index + 1])
    if mark is None:
        return None
    position = index + 2
    if position >= len(text):
        return None
    if text[position] == "{":
        group = read_latex_group(text, position)
        if group is None:
            return None
        content = text[group[0]:group[1]]
        if len(content) != 1 or not content.isalpha():
            return None
        return unicodedata.normalize("NFC", content + mark), group[1] + 1
    if text[position].isalpha():
        return unicodedata.normalize("NFC", text[position] + mark), position + 1
    return None


def _read_word(text: str, start: int) -> tuple[str, int]:
    """Legge una parola, ricomponendo eventuali accenti in sintassi LaTeX."""
    parts: list[str] = []
    length = len(text)
    position = start
    while position < length:
        match = _TOKEN_RE.match(text, position)
        if match is not None and match.group(0)[0].isalpha():
            parts.append(match.group(0))
            position = match.end()
            continue
        accent = _read_accent(text, position)
        if accent is None:
            break
        letter, position = accent
        parts.append(letter)
    return "".join(parts), position


def iter_spell_words(text: str) -> Iterator[tuple[int, int, str]]:
    """Restituisce ``(start, end, parola)`` per le parole da controllare.

    Gli offset si riferiscono sempre al testo originale, anche quando gli
    accenti LaTeX vengono ricomposti e i commenti saltati.
    """
    if not text:
        return
    source = text
    length = len(source)
    index = 0
    while index < length:
        match = _TOKEN_RE.match(source, index)
        if match is None:
            index += 1
            continue
        token = match.group(0)
        first = token[0]

        if first == "\\":
            index = _skip_backslash(source, index)
            continue
        if first == "$":
            index = _skip_math(source, index)
            continue
        if first == "%":
            newline = source.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if not first.isalpha():
            index = match.end()
            continue

        start = match.start()
        url = _URL_RE.match(source, start)
        if url is not None:
            index = url.end()
            continue
        path = _PATH_RE.match(source, start)
        if path is not None:
            index = path.end()
            continue

        word, end = _read_word(source, start)
        if not word:
            index = max(match.end(), start + 1)
            continue

        # Elisione italiana/francese: "dell'articolo" → si controlla solo
        # "articolo".  Una virgoletta di chiusura ('' o ’) non è elisione.
        if (end < length and source[end] in "'’"
                and end + 1 < length and source[end + 1].isalpha()):
            index = end + 1
            continue

        if len(word) > 2:
            yield start, end, unicodedata.normalize("NFC", word)
        index = end


# ─── Backend ─────────────────────────────────────────────────────────────────


class SpellBackend:
    """Interfaccia minima usata da editor e dialog."""

    name = "base"

    def unknown(self, words: Iterable[str]) -> set[str]:
        raise NotImplementedError

    def candidates(self, word: str) -> set[str]:
        raise NotImplementedError


_LANGUAGE_VARIANTS: dict[str, tuple[str, ...]] = {
    "it": ("it_IT", "it_CH", "it"),
    "en": ("en_US", "en_GB", "en"),
    "de": ("de_DE", "de_AT", "de_CH", "de"),
    "fr": ("fr_FR", "fr"),
    "es": ("es_ES", "es"),
    "pt": ("pt_PT", "pt_BR", "pt"),
    "pl": ("pl_PL", "pl"),
    "nl": ("nl_NL", "nl"),
    "ru": ("ru_RU", "ru"),
}


def _dictionary_roots() -> list[Path]:
    roots: list[Path] = []
    env_dir = os.environ.get("NOTEPADPQ_HUNSPELL_DIR")
    if env_dir:
        roots.extend(Path(part).expanduser() for part in env_dir.split(os.pathsep) if part)
    try:
        from core.platform import get_data_dir

        roots.append(get_data_dir() / "hunspell")
    except Exception:
        pass

    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "NotePadPQ" / "hunspell")
    else:
        roots.extend([
            Path("/usr/share/hunspell"),
            Path("/usr/share/myspell"),
            Path("/usr/share/myspell/dicts"),
            Path("/usr/local/share/hunspell"),
            Path.home() / ".local" / "share" / "hunspell",
            Path.home() / "Library" / "Spelling",
            Path("/Library/Spelling"),
        ])
    return roots


def _dictionary_prefix(lang: str) -> Path | None:
    """Restituisce il prefisso di un dizionario Hunspell per ``lang``."""
    variants = _LANGUAGE_VARIANTS.get((lang or "").lower(), (lang,))
    for root in _dictionary_roots():
        for variant in variants:
            dictionary = root / f"{variant}.dic"
            affix = root / f"{variant}.aff"
            if dictionary.is_file() and affix.is_file():
                return dictionary.with_suffix("")
    return None


class HunspellBinaryBackend(SpellBackend):
    """Hunspell tramite il binario di sistema, invocato in batch."""

    name = "hunspell"

    def __init__(self, executable: str, prefix: Path):
        self._executable = executable
        self._prefix = str(prefix)
        self._correct: dict[str, bool] = {}
        self._lock = threading.Lock()

    def _run(self, arguments: list[str], stdin: str) -> str:
        process = subprocess.run(
            [self._executable, "-i", "utf-8", "-d", self._prefix, *arguments],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        return process.stdout

    def unknown(self, words: Iterable[str]) -> set[str]:
        requested = [word for word in words if word]
        if not requested:
            return set()
        with self._lock:
            pending = list(dict.fromkeys(
                word for word in requested if word not in self._correct
            ))
            if pending:
                if len(self._correct) > 50_000:
                    self._correct.clear()
                try:
                    output = self._run(["-l"], "\n".join(pending))
                except (OSError, subprocess.SubprocessError):
                    # Motore non più disponibile: meglio non bloccare l'editor.
                    return set()
                reported = set(output.splitlines())
                for word in pending:
                    self._correct[word] = word not in reported
            return {word for word in requested if not self._correct.get(word, False)}

    def candidates(self, word: str) -> set[str]:
        try:
            with self._lock:
                output = self._run(["-a"], word + "\n")
        except (OSError, subprocess.SubprocessError):
            return set()
        suggestions: set[str] = set()
        for line in output.splitlines():
            if line.startswith("&"):
                payload = line.split(":", 1)
                if len(payload) == 2:
                    suggestions.update(
                        item.strip() for item in payload[1].split(",") if item.strip()
                    )
            elif line.startswith("#"):
                break
        return suggestions


class SpyllsBackend(SpellBackend):
    """Hunspell puro Python, usato quando il binario non è disponibile."""

    name = "spylls"

    def __init__(self, prefix: Path):
        from spylls.hunspell import Dictionary

        self._dictionary = Dictionary.from_files(str(prefix))

    def unknown(self, words: Iterable[str]) -> set[str]:
        return {word for word in words if word and not self._dictionary.lookup(word)}

    def candidates(self, word: str) -> set[str]:
        try:
            return set(self._dictionary.suggest(word))
        except Exception:
            return set()


class PyspellcheckerBackend(SpellBackend):
    """Fallback storico: lista di frequenza senza morfologia."""

    name = "pyspellchecker"

    def __init__(self, lang: str):
        from spellchecker import SpellChecker

        self._checker = SpellChecker(language=lang)

    def unknown(self, words: Iterable[str]) -> set[str]:
        requested = [word for word in words if word]
        if not requested:
            return set()
        # pyspellchecker restituisce le parole in minuscolo: si conserva la
        # grafia originale per far combaciare gli offset dell'editor.
        misspelled = self._checker.unknown({word.lower() for word in requested})
        return {word for word in requested if word.lower() in misspelled}

    def candidates(self, word: str) -> set[str]:
        return set(self._checker.candidates(word) or set())


_CHECKERS: dict[str, SpellBackend] = {}


def get_spell_checker(lang: str) -> SpellBackend:
    """Restituisce (e memorizza) il motore migliore per la lingua richiesta."""
    key = (lang or "it").lower()
    checker = _CHECKERS.get(key)
    if checker is not None:
        return checker

    prefix = _dictionary_prefix(key)
    executable = shutil.which("hunspell")
    if prefix is not None and executable:
        checker = HunspellBinaryBackend(executable, prefix)
    elif prefix is not None:
        try:
            checker = SpyllsBackend(prefix)
        except ImportError:
            checker = None
        except Exception:
            checker = None

    if checker is None:
        checker = PyspellcheckerBackend(key)

    _CHECKERS[key] = checker
    return checker
