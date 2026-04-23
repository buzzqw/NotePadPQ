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

import re
from typing import Optional, List, Dict, TYPE_CHECKING
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QTimer, QSortFilterProxyModel, pyqtSignal
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QFont, QIcon, QKeySequence, QAction
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeView, QLineEdit, QPushButton, QLabel,
    QComboBox, QMenu, QAbstractItemView,
)

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


# ─── Parser per linguaggio ────────────────────────────────────────────────────

class _Parser:
    """Base class per i parser di linguaggio."""

    def parse(self, text: str) -> List[FuncSymbol]:
        raise NotImplementedError


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
    _CMDS = [
        (r"\\chapter\*?\{([^}]+)\}",          "chapter", "📖"),
        (r"\\section\*?\{([^}]+)\}",          "section", "§"),
        (r"\\subsection\*?\{([^}]+)\}",       "subsection", "  §"),
        (r"\\subsubsection\*?\{([^}]+)\}",    "subsubsection", "    §"),
        (r"\\newcommand\{\\(\w+)\}",           "command", "⌘"),
        (r"\\newenvironment\{(\w+)\}",         "environment", "⬜"),
    ]

    def parse(self, text: str) -> List[FuncSymbol]:
        results = []
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, kind, icon in self._CMDS:
                m = re.search(pattern, line)
                if m:
                    results.append(FuncSymbol(
                        name=m.group(1), kind=kind, line=lineno,
                        signature=line.strip()[:80], icon=icon
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
                level = len(m.group(1))
                title = m.group(2).strip()
                
                # Icone diverse in base all'importanza del titolo
                icons = ["📖", "●", "○", "·", "▸", "▹"]
                icon = icons[level - 1] if level <= len(icons) else "·"
                
                results.append(FuncSymbol(
                    name=f"{'  ' * (level - 1)}{title}", 
                    kind="header", 
                    line=lineno,
                    signature=line.strip()[:80], 
                    icon=icon
                ))
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


def _get_parser(editor: "EditorWidget") -> Optional[_Parser]:
    """Individua il parser giusto per l'editor."""
    lang = ""
    
    # 1. Prova a dedurlo dall'estensione del file
    if getattr(editor, "file_path", None):
        ext = editor.file_path.suffix.lstrip(".").lower()
        lang = _LANG_ALIASES.get(ext, ext)
        
    # 2. Se l'estensione non basta (es. file nuovo), chiedi al Lexer
    if not lang or lang not in _PARSERS:
        try:
            lexer = editor.lexer()
            if lexer:
                # Scintilla potrebbe chiamarlo 'tex', 'markdown', ecc.
                lex_name = lexer.language().lower().replace(" ", "")
                lang = _LANG_ALIASES.get(lex_name, lex_name)
        except Exception:
            pass
            
    return _PARSERS.get(lang)


# ─── Pannello ─────────────────────────────────────────────────────────────────

class _FunctionListPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw     = main_window
        self._editor: Optional["EditorWidget"] = None
        self._symbols: List[FuncSymbol] = []

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._refresh)

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
        self._filter.setPlaceholderText("Filtra funzioni…")
        self._filter.setFixedHeight(24)
        self._filter.textChanged.connect(self._apply_filter)
        top.addWidget(self._filter, 1)

        self._sort_btn = QPushButton("A↓")
        self._sort_btn.setFixedSize(32, 24)
        self._sort_btn.setToolTip("Ordina A-Z / per riga")
        self._sort_btn.setCheckable(True)
        self._sort_btn.toggled.connect(self._toggle_sort)
        top.addWidget(self._sort_btn)

        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedSize(28, 24)
        btn_refresh.setToolTip("Aggiorna")
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
        self._editor = editor
        if editor:
            editor.textChanged.connect(self._on_text_changed)
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


    def _on_text_changed(self) -> None:
        if self.isVisible():
            self._timer.start()
        else:
            self._needs_refresh = True

    def _refresh(self) -> None:
        self._model.clear()
        editor = self._editor
        if not editor:
            self._info.setText("Nessun editor")
            return

        parser = _get_parser(editor)
        if not parser:
            self._info.setText("Linguaggio non supportato")
            item = QStandardItem("(nessun parser disponibile)")
            item.setEnabled(False)
            self._model.appendRow(item)
            return

        text = editor.get_content() if hasattr(editor, "get_content") else editor.text()
        self._symbols = parser.parse(text)

        if not self._symbols:
            self._info.setText("Nessuna funzione trovata")
            return

        # Raggruppa per kind
        groups: Dict[str, QStandardItem] = {}
        _KIND_ORDER = ["class", "function", "method", "section",
                       "chapter", "subsection", "subsubsection",
                       "command", "environment", "procedure", "other"]

        for sym in self._symbols:
            kind = sym.kind
            if kind not in groups:
                kind_label = kind.capitalize() + "i" if not kind.endswith("e") else kind.capitalize() + "i"
                group_item = QStandardItem(f"— {kind.upper()} —")
                group_item.setEnabled(False)
                group_item.setData("group", Qt.ItemDataRole.UserRole)
                font = group_item.font()
                font.setBold(True)
                group_item.setFont(font)
                group_item.setForeground(QColor("#888"))
                self._model.appendRow(group_item)
                groups[kind] = group_item

            icon = sym.icon or "·"
            item = QStandardItem(f"{icon}  {sym.name}  ({sym.line})")
            item.setData(sym.line, Qt.ItemDataRole.UserRole)
            item.setToolTip(sym.signature)
            item.setEditable(False)
            groups[kind].appendRow(item)

        self._tree.expandAll()
        self._apply_filter(self._filter.text())

        count = len(self._symbols)
        lang  = editor.file_path.suffix if editor.file_path else ""
        self._info.setText(f"{count} simboli trovati  {lang}")

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

        menu = QMenu(self)
        if isinstance(line, int):
            menu.addAction("Vai alla riga",
                           lambda: self._editor and self._editor.go_to_line(line))
            menu.addAction("Copia nome",
                           lambda: self._copy_name(item))
        menu.addSeparator()
        menu.addAction("Aggiorna lista", self._refresh)
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

    dock = QDockWidget("𝑓  Function List", main_window)
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
        act = QAction("𝑓  Function List", main_window)
        act.setShortcut(QKeySequence("Ctrl+Shift+F"))
        act.setCheckable(True)
        act.toggled.connect(dock.setVisible)
        dock.visibilityChanged.connect(act.setChecked)
        view_menu.addAction(act)

    main_window._function_list_dock  = dock
    main_window._function_list_panel = panel
    return panel
