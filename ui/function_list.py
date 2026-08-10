"""
ui/function_list.py — Pannello Function List
NotePadPQ

Pannello dock con la lista di funzioni, classi e metodi del file corrente,
stile Notepad++ "Function List". Diverso da SymbolPanel (struttura documento):
  - Function List: solo funzioni/metodi, aggiornamento in tempo reale,
    navigazione rapida, ricerca filtro, ordinamento
  - SymbolPanel: struttura gerarchica completa (anche variabili, header, ecc.)

I due pannelli coesistono e sono complementari.

Linguaggi supportati con parser dedicato:
    Python, JavaScript/TypeScript, C/C++, Java, C#, Go, Rust,
    PHP, Ruby, Bash, SQL (stored procedures), LaTeX (sezioni)

Uso da MainWindow:
    FunctionListPanel.install(main_window)
    → aggiunge dock + voce menu Visualizza
"""

from __future__ import annotations

import bisect
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path as _Path
from typing import Optional, List, Dict, TYPE_CHECKING
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QTimer, QThread, QSortFilterProxyModel, pyqtSignal
from PyQt6.QtGui import (
    QStandardItemModel, QStandardItem, QColor, QFont, QIcon, QKeySequence,
    QAction, QPalette,
)
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeView, QLineEdit, QPushButton, QLabel,
    QComboBox, QMenu, QAbstractItemView,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


# ─── Struttura simbolo ────────────────────────────────────────────────────────

@dataclass
class FuncSymbol:
    name:      str
    kind:      str      # "function", "method", "class", "section", ecc.
    line:      int      # 1-based
    signature: str = ""
    parent:    str = ""
    icon:      str = ""   # emoji usata come icona
    level:     int = 0    # livello gerarchia (1=top) per MD/LaTeX; 0 = nessuna gerarchia
    file_path: Optional[_Path] = None


# ─── Parser per linguaggio ────────────────────────────────────────────────────

class _Parser(ABC):
    """Base class astratta per i parser di linguaggio."""

    @abstractmethod
    def parse(self, text: str) -> List[FuncSymbol]:
        ...


class _PythonParser(_Parser):
    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        lines   = text.splitlines()
        class_stack: list[str] = []
        indent_stack: list[int] = []

        for lineno, line in enumerate(lines, 1):
            stripped = line.lstrip()
            indent   = len(line) - len(stripped)

            # Aggiorna lo stack delle classi in base all'indentazione
            while indent_stack and indent <= indent_stack[-1]:
                indent_stack.pop()
                if class_stack:
                    class_stack.pop()

            m = re.match(r"^class\s+(\w+)\s*(?:\([^)]*\))?:", stripped)
            if m:
                name = m.group(1)
                class_stack.append(name)
                indent_stack.append(indent)
                results.append(FuncSymbol(
                    name=name, kind="class", line=lineno,
                    signature=f"class {name}", icon="🔷"
                ))
                continue

            m = re.match(r"^(async\s+)?def\s+(\w+)\s*(\([^)]*\))?", stripped)
            if m:
                is_async = bool(m.group(1))
                name     = m.group(2)
                sig      = m.group(3) or "()"
                prefix   = "async " if is_async else ""
                parent   = class_stack[-1] if class_stack else ""
                kind     = "method" if parent else "function"
                icon     = "⚙" if kind == "method" else "𝑓"
                results.append(FuncSymbol(
                    name=name, kind=kind, line=lineno,
                    signature=f"{prefix}def {name}{sig}",
                    parent=parent, icon=icon
                ))

        return results


class _JSParser(_Parser):
    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        lines   = text.splitlines()
        patterns = [
            (r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(\([^)]*\))",
             "function", "𝑓"),
            (r"^(?:export\s+)?class\s+(\w+)",
             "class", "🔷"),
            (r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
             "function", "𝑓"),
            (r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function",
             "function", "𝑓"),
            (r"^\s+(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{",
             "method", "⚙"),
        ]
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            for pattern, kind, icon in patterns:
                m = re.match(pattern, stripped)
                if m:
                    name = m.group(1)
                    sig  = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                    results.append(FuncSymbol(
                        name=name, kind=kind, line=lineno,
                        signature=f"{name}({sig})", icon=icon
                    ))
                    break
        return results


class _CppParser(_Parser):
    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        lines   = text.splitlines()
        patterns = [
            (r"^(?:class|struct)\s+(\w+)", "class", "🔷"),
            (r"^(?:[\w:*&<>]+\s+)+(\w+)\s*\(([^)]*)\)\s*(?:const\s*)?(?:\{|;|:)",
             "function", "𝑓"),
        ]
        for lineno, line in enumerate(lines, 1):
            for pattern, kind, icon in patterns:
                m = re.match(pattern, line.strip())
                if m:
                    name = m.group(1)
                    results.append(FuncSymbol(
                        name=name, kind=kind, line=lineno,
                        signature=line.strip()[:80], icon=icon
                    ))
                    break
        return results


class _JavaParser(_Parser):
    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        lines   = text.splitlines()
        for lineno, line in enumerate(lines, 1):
            s = line.strip()
            m = re.match(
                r"(?:public|private|protected|static|final|abstract|"
                r"synchronized|native|default)[\w\s<>[\],]*\s+(\w+)\s*\(([^)]*)\)",
                s
            )
            if m:
                name = m.group(1)
                if name not in ("if", "while", "for", "switch", "catch"):
                    results.append(FuncSymbol(
                        name=name, kind="method", line=lineno,
                        signature=s[:80], icon="⚙"
                    ))
                continue
            m = re.match(r"(?:public|private|protected)?\s*class\s+(\w+)", s)
            if m:
                results.append(FuncSymbol(
                    name=m.group(1), kind="class", line=lineno,
                    signature=s[:80], icon="🔷"
                ))
        return results


class _BashParser(_Parser):
    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        for lineno, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            m = re.match(r"^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?", s)
            if m and not s.startswith("#"):
                results.append(FuncSymbol(
                    name=m.group(1), kind="function", line=lineno,
                    signature=s[:60], icon="𝑓"
                ))
        return results


class _LaTeXParser(_Parser):
    # (pattern, kind, icon, level)  level=0 → mostrato flat in gruppo separato
    # Le varianti starred e non-starred sono pattern mutuamente esclusivi:
    # \\section\s*\{ non matcha \\section*{ perché * non è whitespace.
    _CMDS = [
        (r"\\part\s*\{([^}]+)\}",              "part",           "📚", 1),
        (r"\\part\*\s*\{([^}]+)\}",            "part*",          "📚", 1),
        (r"\\chapter\s*\{([^}]+)\}",           "chapter",        "📖", 2),
        (r"\\chapter\*\s*\{([^}]+)\}",         "chapter*",       "📖", 2),
        (r"\\section\s*\{([^}]+)\}",           "section",        "§",  3),
        (r"\\section\*\s*\{([^}]+)\}",         "section*",       "§",  3),
        (r"\\subsection\s*\{([^}]+)\}",        "subsection",     "§",  4),
        (r"\\subsection\*\s*\{([^}]+)\}",      "subsection*",    "§",  4),
        (r"\\subsubsection\s*\{([^}]+)\}",     "subsubsection",  "§",  5),
        (r"\\subsubsection\*\s*\{([^}]+)\}",   "subsubsection*", "§",  5),
        (r"\\newcommand\{\\(\w+)\}",            "command",        "⌘",  0),
        (r"\\newenvironment\{(\w+)\}",          "environment",    "⬜", 0),
    ]

    def parse(self, text: str) -> List[FuncSymbol]:
        from config.settings import Settings as _S
        hidden = set(
            k.strip() for k in
            (_S.instance().get("function_list/latex_hidden_kinds") or "").split(",")
            if k.strip()
        )
        results = []
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, kind, icon, lv in self._CMDS:
                if kind in hidden:
                    continue
                m = re.search(pattern, line)
                if m:
                    results.append(FuncSymbol(
                        name=m.group(1), kind=kind, line=lineno,
                        signature=line.strip()[:80], icon=icon, level=lv,
                    ))
                    break
        return results


class _SqlParser(_Parser):
    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        for lineno, line in enumerate(text.splitlines(), 1):
            s = line.strip().upper()
            m = re.match(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION|TRIGGER|VIEW)\s+(\w+)",
                s
            )
            if m:
                results.append(FuncSymbol(
                    name=m.group(1).lower(), kind="procedure", line=lineno,
                    signature=line.strip()[:80], icon="🗄"
                ))
        return results
        
        
        
class _MarkdownParser(_Parser):
    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        for lineno, line in enumerate(text.splitlines(), 1):
            m = re.match(r"^(#{1,6})\s+(.*)", line)
            if m:
                lv = len(m.group(1))
                title = m.group(2).strip()
                icons = ["📖", "●", "○", "·", "▸", "▹"]
                icon = icons[lv - 1] if lv <= len(icons) else "·"
                results.append(FuncSymbol(
                    name=title,
                    kind="header",
                    line=lineno,
                    signature=line.strip()[:80],
                    icon=icon,
                    level=lv,
                ))
        return results

class _JsonParser(_Parser):
    """Parser configurabile da file JSON."""

    def __init__(self, definition: dict):
        self._language: str = definition.get("language", "")
        self._hierarchical: bool = definition.get("hierarchical", False)
        self._compiled: list[dict] = []
        for p in definition.get("patterns", []):
            try:
                self._compiled.append({
                    "regex":      re.compile(p["regex"]),
                    "kind":       p.get("kind", "symbol"),
                    "name_group": p.get("name_group", 1),
                    "icon":       p.get("icon", "·"),
                    "level":      p.get("level", 0),
                })
            except re.error:
                pass

    def parse(self, text: str) -> List[FuncSymbol]:
        from config.settings import Settings as _S
        try:
            hidden_all = json.loads(
                _S.instance().get("function_list/hidden_kinds") or "{}"
            )
            hidden: set[str] = set(hidden_all.get(self._language, []))
        except Exception:
            hidden = set()

        results = []
        for lineno, line in enumerate(text.splitlines(), 1):
            for p in self._compiled:
                if p["kind"] in hidden:
                    continue
                m = p["regex"].search(line)
                if m:
                    try:
                        name = m.group(p["name_group"])
                    except IndexError:
                        name = m.group(0)
                    results.append(FuncSymbol(
                        name=name.strip(),
                        kind=p["kind"],
                        line=lineno,
                        signature=line.strip()[:80],
                        icon=p["icon"],
                        level=p["level"],
                    ))
                    break
        return results


# Mapping linguaggio → parser
_PARSERS: Dict[str, _Parser] = {
    "python":     _PythonParser(),
    "javascript": _JSParser(),
    "typescript": _JSParser(),
    "c/c++":      _CppParser(),
    "c":          _CppParser(),
    "cpp":        _CppParser(),
    "java":       _JavaParser(),
    "bash":       _BashParser(),
    "latex":      _LaTeXParser(),
    "sql":        _SqlParser(),
    "markdown":   _MarkdownParser(), # <--- Aggiunto!
}

# Alias
_LANG_ALIASES = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "jsx": "javascript", "tsx": "typescript",
    "h": "c/c++", "hpp": "c/c++", "cpp": "c/c++", "cc": "c/c++",
    "rb": "python",  
    "sh": "bash", "bash": "bash",
    "tex": "latex", "sty": "latex",
    "md": "markdown", "markdown": "markdown", # <--- Aggiunto!
}


# Preset JSON caricati da config/function_list/
_JSON_PRESETS: dict[str, _JsonParser] = {}
_JSON_PRESET_DEFS: list[dict] = []   # raw definitions per UI Preferenze


def _load_json_presets() -> None:
    global _JSON_PRESETS, _JSON_PRESET_DEFS
    _JSON_PRESETS.clear()
    _JSON_PRESET_DEFS.clear()
    preset_dir = _Path(__file__).parent.parent / "config" / "function_list"
    if not preset_dir.exists():
        return
    for f in sorted(preset_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            lang = data.get("language", "").strip()
            if not lang:
                continue
            _JSON_PRESETS[lang] = _JsonParser(data)
            _JSON_PRESET_DEFS.append(data)
            # Registra le estensioni negli alias
            for ext in data.get("extensions", []):
                ext = ext.lstrip(".").lower()
                if ext and ext not in _LANG_ALIASES:
                    _LANG_ALIASES[ext] = lang
        except Exception:
            pass


_load_json_presets()


def reload_presets() -> None:
    """Ricarica i preset JSON (chiamato da Preferenze dopo modifica)."""
    _load_json_presets()


def _get_parser(editor: "EditorWidget") -> Optional[_Parser]:
    """Individua il parser giusto per l'editor."""
    lang = ""

    # 1. Prova a dedurlo dall'estensione del file
    if getattr(editor, "file_path", None):
        ext = editor.file_path.suffix.lstrip(".").lower()
        lang = _LANG_ALIASES.get(ext, ext)

    # 2. Se l'estensione non basta, chiedi al Lexer
    if not lang or (lang not in _PARSERS and lang not in _JSON_PRESETS):
        try:
            lexer = editor.lexer()
            if lexer:
                lex_name = lexer.language().lower().replace(" ", "")
                lang = _LANG_ALIASES.get(lex_name, lex_name)
                # Prova anche i lexer_names dei preset JSON
                if lang not in _PARSERS and lang not in _JSON_PRESETS:
                    for data in _JSON_PRESET_DEFS:
                        if lex_name in [ln.lower() for ln in data.get("lexer_names", [])]:
                            lang = data["language"]
                            break
        except Exception:
            pass

    # 3. Controlla se il preset JSON è abilitato
    from config.settings import Settings as _S
    disabled = set(
        k.strip() for k in
        (_S.instance().get("function_list/disabled_presets") or "").split(",")
        if k.strip()
    )
    if lang in _JSON_PRESETS and lang not in disabled:
        return _JSON_PRESETS[lang]

    # 4. Fallback al parser built-in
    return _PARSERS.get(lang)


# ─── Worker asincrono parse ───────────────────────────────────────────────────

class _ParseWorker(QThread):
    """Esegue parser.parse(text) in background per non bloccare la UI."""

    done = pyqtSignal(list, int, bool)  # (symbols, generation, is_hierarchical)

    def __init__(self, parser: "_Parser", text: str, generation: int,
                 is_hierarchical: bool):
        super().__init__(None)
        self._parser        = parser
        self._text          = text
        self._generation    = generation
        self._is_hier       = is_hierarchical
        self._cancelled     = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        symbols = self._parser.parse(self._text)
        if not self._cancelled:
            self.done.emit(symbols, self._generation, self._is_hier)


class _MultiFileParser(_Parser):
    """Adatta un parser esistente aggiungendo l'origine a ogni simbolo."""

    def __init__(self, parser: _Parser, sources: list[tuple[_Path, str]]):
        self._parser = parser
        self._sources = sources

    def parse(self, _text: str) -> List[FuncSymbol]:
        symbols: list[FuncSymbol] = []
        for path, text in self._sources:
            for symbol in self._parser.parse(text):
                symbol.file_path = path
                symbols.append(symbol)
        return symbols


# ─── Pannello ─────────────────────────────────────────────────────────────────

class _FunctionListPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw     = main_window
        self._editor: Optional["EditorWidget"] = None
        self._symbols: List[FuncSymbol] = []
        self._needs_refresh = True
        self._parse_worker: "_ParseWorker | None" = None
        self._old_parse_workers: list = []
        self._parse_gen: int = 0

        # Simbolo "corrente": riga in cui si trova il cursore nell'editor,
        # evidenziata nell'albero. Lista (line, item) ordinata per riga per
        # ricerca O(log n) con bisect, ricostruita a ogni refresh del parser.
        self._line_items: list[tuple[int, QStandardItem]] = []
        self._current_hl_item: Optional[QStandardItem] = None

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._refresh)

        # Debounce per l'evidenziazione della funzione corrente: il cursore
        # si sposta molto più spesso del testo, quindi usiamo un intervallo
        # breve ma comunque "lazy" per non ricalcolare a ogni singolo evento.
        self._hl_timer = QTimer(self)
        self._hl_timer.setSingleShot(True)
        self._hl_timer.setInterval(150)
        self._hl_timer.timeout.connect(self._update_highlight)

        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Barra superiore
        top = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("function_list.placeholder_filter"))
        self._filter.setFixedHeight(24)
        self._filter.textChanged.connect(self._apply_filter)
        top.addWidget(self._filter, 1)

        self._sort_btn = QPushButton("A↓")
        self._sort_btn.setFixedSize(32, 24)
        self._sort_btn.setToolTip(tr("tooltip.funclist_sort"))
        self._sort_btn.setCheckable(True)
        self._sort_btn.toggled.connect(self._toggle_sort)
        top.addWidget(self._sort_btn)

        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedSize(28, 24)
        btn_refresh.setToolTip(tr("tooltip.funclist_refresh"))
        btn_refresh.clicked.connect(self._refresh)
        top.addWidget(btn_refresh)
        layout.addLayout(top)

        # Modello + proxy per filtro/ordinamento
        self._model = QStandardItemModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)
        self._proxy.setRecursiveFilteringEnabled(True)

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.clicked.connect(self._on_clicked)
        self._tree.doubleClicked.connect(self._on_double_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._tree, 1)

        # Info barra
        self._info = QLabel("")
        self._info.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self._info)

    # ── Aggiornamento ─────────────────────────────────────────────────────────

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        if self._editor:
            try:
                self._editor.textChanged.disconnect(self._on_text_changed)
            except Exception:
                pass
            try:
                self._editor.cursorPositionChanged.disconnect(self._on_cursor_moved)
            except Exception:
                pass
        self._editor = editor
        if editor:
            editor.textChanged.connect(self._on_text_changed)
            editor.cursorPositionChanged.connect(self._on_cursor_moved)
        self._set_highlight(None)
        # Se visibile aggiorna subito, altrimenti segna flag
        if self.isVisible():
            self._needs_refresh = False
            self._timer.start()
        else:
            self._needs_refresh = True

    def showEvent(self, event) -> None:
        # Quando il pannello diventa visibile, aggiorna se c'e' un refresh pendente
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self._timer.start()
        else:
            self._hl_timer.start()

    def _on_text_changed(self) -> None:
        if self.isVisible():
            self._timer.start()
        else:
            self._needs_refresh = True

    def _on_cursor_moved(self, line: int, index: int) -> None:
        # Costo quasi nullo se il pannello e' nascosto: nessun timer, nessun
        # lavoro finche' l'utente non lo riapre.
        if self.isVisible():
            self._hl_timer.start()

    def _set_highlight(self, item: Optional[QStandardItem]) -> None:
        """Applica/rimuove lo sfondo di evidenziazione, senza toccare selezione o focus."""
        if self._current_hl_item is item:
            return
        if self._current_hl_item is not None:
            try:
                self._current_hl_item.setData(None, Qt.ItemDataRole.BackgroundRole)
                font = self._current_hl_item.font(); font.setBold(False)
                self._current_hl_item.setFont(font)
            except RuntimeError:
                pass  # item appartenente a un modello già svuotato/ricostruito
        self._current_hl_item = item
        if item is not None:
            color = QColor(self._tree.palette().color(
                QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight
            ))
            color.setAlpha(70)
            item.setBackground(color)
            font = item.font(); font.setBold(True)
            item.setFont(font)

    def _update_highlight(self) -> None:
        if not self.isVisible() or not self._editor or not self._line_items:
            self._set_highlight(None)
            return
        current_line = self._editor.getCursorPosition()[0] + 1  # 1-based, come FuncSymbol.line
        lines = [ln for ln, _ in self._line_items]
        idx = bisect.bisect_right(lines, current_line) - 1
        if idx < 0:
            self._set_highlight(None)
            return
        item = self._line_items[idx][1]
        self._set_highlight(item)
        src_index = item.index()
        self._tree.scrollTo(self._proxy.mapFromSource(src_index),
                             QAbstractItemView.ScrollHint.EnsureVisible)

    # Parser che usano la vista gerarchica per level
    _HIERARCHICAL_PARSERS = (_MarkdownParser, _LaTeXParser)

    def _make_sym_item(self, sym: FuncSymbol) -> QStandardItem:
        prefix = f"{sym.file_path.name}: " if sym.file_path else ""
        item = QStandardItem(f"{sym.icon}  {prefix}{sym.name}  ({sym.line})")
        item.setData(sym.line, Qt.ItemDataRole.UserRole)
        if sym.file_path:
            item.setData(str(sym.file_path), Qt.ItemDataRole.UserRole + 1)
        item.setToolTip(sym.signature)
        item.setEditable(False)
        current_path = getattr(self._editor, "file_path", None)
        if (sym.file_path is None or current_path is None
                or sym.file_path.resolve() == current_path.resolve()):
            self._line_items.append((sym.line, item))
        return item

    def _make_group_header(self, label: str) -> QStandardItem:
        g = QStandardItem(f"— {label.upper()} —")
        g.setEnabled(False)
        g.setData("group", Qt.ItemDataRole.UserRole)
        font = g.font(); font.setBold(True); g.setFont(font)
        g.setForeground(QColor("#888"))
        return g

    def _build_hierarchical(self, symbols: List[FuncSymbol]) -> None:
        """Costruisce albero annidato per linguaggi con livelli (MD, LaTeX)."""
        stack: list[tuple[int, QStandardItem]] = []  # (level, item)
        flat: List[FuncSymbol] = []   # simboli senza gerarchia (level=0)
        previous_file = None

        for sym in symbols:
            if sym.file_path != previous_file:
                stack.clear()
                previous_file = sym.file_path
            if sym.level == 0:
                flat.append(sym)
                continue
            item = self._make_sym_item(sym)
            while stack and stack[-1][0] >= sym.level:
                stack.pop()
            if stack:
                stack[-1][1].appendRow(item)
            else:
                self._model.appendRow(item)
            stack.append((sym.level, item))

        if flat:
            grp = self._make_group_header("Comandi / Ambienti")
            self._model.appendRow(grp)
            for sym in flat:
                grp.appendRow(self._make_sym_item(sym))

    def _build_grouped(self, symbols: List[FuncSymbol]) -> None:
        """Raggruppa simboli per kind (comportamento originale)."""
        groups: Dict[str, QStandardItem] = {}
        for sym in symbols:
            kind = sym.kind
            if kind not in groups:
                g = self._make_group_header(kind)
                self._model.appendRow(g)
                groups[kind] = g
            groups[kind].appendRow(self._make_sym_item(sym))

    def _cancel_parse_worker(self) -> None:
        if self._parse_worker is not None:
            self._parse_worker.cancel()
            old = self._parse_worker
            self._old_parse_workers.append(old)
            def _cleanup(w=old):
                try:
                    self._old_parse_workers.remove(w)
                except ValueError:
                    pass
            old.finished.connect(_cleanup)
            self._parse_worker = None

    def _refresh(self) -> None:
        editor = self._editor
        if not editor:
            self._model.clear()
            self._info.setText(tr("function_list.no_editor"))
            return

        parser = _get_parser(editor)
        if not parser:
            self._model.clear()
            self._info.setText("Linguaggio non supportato")
            item = QStandardItem("(nessun parser disponibile)")
            item.setEnabled(False)
            self._model.appendRow(item)
            return

        text = editor.get_content() if hasattr(editor, "get_content") else editor.text()
        is_hier = (isinstance(parser, _JsonParser) and parser._hierarchical) \
                  or isinstance(parser, self._HIERARCHICAL_PARSERS)
        if isinstance(parser, _LaTeXParser) and getattr(editor, "file_path", None):
            try:
                from core.latex_project import LatexProjectContext
                context = LatexProjectContext(editor.file_path, text)
                sources: list[tuple[_Path, str]] = []
                seen: set[_Path] = set()
                for source in context.included_files():
                    source = source.resolve()
                    if source in seen:
                        continue
                    seen.add(source)
                    source_text = text if source == editor.file_path.resolve() else source.read_text(
                        encoding="utf-8", errors="replace")
                    sources.append((source, source_text))
                if sources:
                    parser = _MultiFileParser(parser, sources)
                    text = ""
            except (OSError, RuntimeError, ValueError):
                pass
        self._cancel_parse_worker()
        self._parse_gen += 1
        gen = self._parse_gen
        worker = _ParseWorker(parser, text, gen, is_hier)
        worker.done.connect(self._on_parse_done)
        self._parse_worker = worker
        self._old_parse_workers.append(worker)
        def _cleanup(w=worker):
            try:
                self._old_parse_workers.remove(w)
            except ValueError:
                pass
        worker.finished.connect(_cleanup)
        worker.start()

    def _on_parse_done(self, symbols: list, gen: int, is_hier: bool) -> None:
        if gen != self._parse_gen:
            return
        self._parse_worker = None
        self._symbols = symbols
        self._model.clear()
        self._line_items = []
        self._current_hl_item = None  # il vecchio item apparteneva al modello appena svuotato

        if not symbols:
            self._info.setText(tr("function_list.no_functions"))
            return

        if is_hier:
            self._build_hierarchical(symbols)
        else:
            self._build_grouped(symbols)
        self._line_items.sort(key=lambda t: t[0])

        self._tree.expandAll()
        self._apply_filter(self._filter.text())
        self._update_highlight()

        editor = self._editor
        count = len(symbols)
        lang  = editor.file_path.suffix if editor and editor.file_path else ""
        self._info.setText(tr("function_list.symbols_found", count=count, lang=lang))

    # ── Filtro e ordinamento ──────────────────────────────────────────────────

    def _apply_filter(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)
        if text:
            self._tree.expandAll()

    def _toggle_sort(self, checked: bool) -> None:
        if checked:
            self._proxy.setSortRole(Qt.ItemDataRole.DisplayRole)
            self._proxy.sort(0, Qt.SortOrder.AscendingOrder)
            self._sort_btn.setText("1↓")
        else:
            # Ripristina ordine naturale (per numero di riga)
            self._proxy.setSortRole(Qt.ItemDataRole.UserRole)
            self._proxy.sort(0, Qt.SortOrder.AscendingOrder)
            self._sort_btn.setText("A↓")

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _on_clicked(self, index) -> None:
        src_index = self._proxy.mapToSource(index)
        item = self._model.itemFromIndex(src_index)
        if not item:
            return
        line = item.data(Qt.ItemDataRole.UserRole)
        file_ref = item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(file_ref, str) and self._editor:
            target = _Path(file_ref)
            current = getattr(self._editor, "file_path", None)
            if current is None or target.resolve() != current.resolve():
                try:
                    self._mw.open_files([target])
                    self._editor = self._mw._tab_manager.current_editor()
                except Exception:
                    return
        if isinstance(line, int) and self._editor:
            self._editor.go_to_line(line)
            self._editor.setFocus()

    def _on_double_clicked(self, index) -> None:
        self._on_clicked(index)
        if self._editor:
            self._editor.setFocus()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        src = self._proxy.mapToSource(index)
        item = self._model.itemFromIndex(src)
        line = item.data(Qt.ItemDataRole.UserRole) if item else None
        file_ref = item.data(Qt.ItemDataRole.UserRole + 1) if item else None

        menu = QMenu(self)
        if isinstance(line, int):
            menu.addAction(tr("function_list.goto_line", default="Vai alla riga"),
                           lambda idx=index: self._on_clicked(idx))
            menu.addAction(tr("function_list.copy_name"),
                           lambda: self._copy_name(item))
        menu.addSeparator()
        menu.addAction(tr("function_list.refresh", default="Aggiorna lista"), self._refresh)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _copy_name(self, item: QStandardItem) -> None:
        if item:
            text = item.text().split("(")[0].strip().lstrip("𝑓⚙🔷§📖⌘⬜🗄· ")
            QApplication.clipboard().setText(text)


# ─── Installazione ────────────────────────────────────────────────────────────

def install(main_window: "MainWindow") -> _FunctionListPanel:
    """
    Crea il pannello Function List come dock e lo aggiunge alla MainWindow.
    Aggiunge anche la voce nel menu Visualizza.
    Chiamare da MainWindow._setup_dock_panels() o dopo win.show().
    """
    panel = _FunctionListPanel(main_window)

    dock = QDockWidget("𝑓  " + tr("action.view_function_list", default="Function List"), main_window)
    dock.setObjectName("FunctionListDock")
    dock.setWidget(panel)
    dock.setMinimumWidth(200)
    dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable |
        QDockWidget.DockWidgetFeature.DockWidgetClosable |
        QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )
    main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.hide()

    # Voce menu Visualizza
    view_menu = main_window._menus.get("view")
    if view_menu:
        act = QAction(tr("action.view_function_list", default="Function List"), main_window)
        act.setShortcut(QKeySequence("Ctrl+Shift+F"))
        act.setCheckable(True)
        act.setIconVisibleInMenu(True)
        act.toggled.connect(dock.setVisible)
        def _sync_fl(visible, a=act):
            a.blockSignals(True)
            a.setChecked(visible)
            a.blockSignals(False)
        dock.visibilityChanged.connect(_sync_fl)
        view_menu.addAction(act)
        main_window._actions["function_list"] = act

        # Applica subito l'icona con il colore testo corrente (evita timing fragile)
        try:
            from pathlib import Path
            from PyQt6.QtGui import QPalette, QPixmap
            icon_path = Path(__file__).parent.parent / "icons" / "lucide" / "list-tree.svg"
            if not icon_path.exists():
                icon_path = Path(__file__).parent.parent / "icons" / "lucide" / "list-tree.svg"
            if icon_path.exists():
                wtext = main_window.palette().color(QPalette.ColorRole.WindowText).name()
                svg = icon_path.read_bytes().replace(b"currentColor", wtext.encode())
                pm = QPixmap()
                if pm.loadFromData(svg, "SVG") and not pm.isNull():
                    act.setIcon(QIcon(pm))
        except Exception:
            pass

    main_window._function_list_dock  = dock
    main_window._function_list_panel = panel

    # Il pannello viene installato dopo che i file di sessione sono già aperti,
    # quindi current_editor_changed non verrà emesso per i tab già presenti.
    # Forziamo un _on_editor_changed iniziale così _editor è impostato e il
    # refresh partirà non appena il dock diventa visibile (via showEvent).
    current = main_window._tab_manager.current_editor()
    panel._on_editor_changed(current)

    return panel
