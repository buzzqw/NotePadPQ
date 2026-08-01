"""
plugins/compare_plugin.py — Plugin Compare & Merge (v2.1)
NotePadPQ

Novità v2.1:
- Editing inline nei pannelli diff (stile Meld)
- Syntax highlighting automatico via Pygments + tema attivo
- Scroll sync proporzionale (funziona con conteggi righe diversi)
- Nessun padding di allineamento: ogni pannello mostra le proprie righe reali
- Aggiornamento differito dopo modifica (800ms debounce)
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List, Tuple, Deque
from collections import deque
import difflib
import re
from pathlib import Path

from PyQt6.QtCore import Qt, QRect, QSize, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QPlainTextEdit, QPushButton, QLabel, QComboBox,
    QDialogButtonBox, QFileDialog, QWidget, QCheckBox, QMessageBox,
    QApplication
)
from PyQt6.QtGui import (
    QColor, QTextCharFormat, QFont, QTextCursor,
    QPainter, QPen, QKeySequence, QShortcut
)

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# ─── Colori ───────────────────────────────────────────────────────────────────
_COLOR_ADD       = QColor("#e6ffed")
_COLOR_DEL       = QColor("#ffeef0")
_COLOR_CHG       = QColor("#fffdef")
_COLOR_ACTIVE    = QColor("#d1e9ff")
_COLOR_NONE      = QColor("#ffffff")  # opaco, match con stylesheet pannello
_COLOR_TEXT      = QColor("#24292e")
_COLOR_LINE_NUM  = QColor("#959da5")
_COLOR_LN_BG     = QColor("#f6f8fa")
_COLOR_CHAR_ADD  = QColor("#acf2bd")
_COLOR_CHAR_DEL  = QColor("#fdb8c0")
_COLOR_CONFLICT  = QColor("#ffe0e0")


class LineNumberWidget(QWidget):
    """Widget che disegna i numeri di riga allineati al QPlainTextEdit."""

    def __init__(self, editor: QPlainTextEdit):
        super().__init__(editor)
        self._editor = editor
        self._editor.blockCountChanged.connect(self._update_width)
        self._editor.updateRequest.connect(self.update)
        self._char_width = self.fontMetrics().horizontalAdvance("9")
        self.setFont(QFont("Monospace", 10))

    def sizeHint(self) -> QSize:
        return QSize(self._needed_width(), 0)

    def _needed_width(self) -> int:
        digits = max(1, len(str(self._editor.blockCount())))
        return self._char_width * (digits + 2) + 8

    def _update_width(self, _=None) -> None:
        self.setFixedWidth(self._needed_width())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect(), _COLOR_LN_BG)
        block = self._editor.firstVisibleBlock()
        block_num = block.blockNumber()
        top = int(self._editor.blockBoundingGeometry(block).translated(
            self._editor.contentOffset()).top())
        bottom = top + int(self._editor.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                n = str(block_num + 1)
                painter.setPen(QPen(_COLOR_LINE_NUM))
                painter.drawText(
                    QRect(0, top, self.width() - 4,
                          self.fontMetrics().height()),
                    Qt.AlignmentFlag.AlignRight, n
                )
            block = block.next()
            top = bottom
            bottom = top + int(self._editor.blockBoundingRect(block).height())
            block_num += 1
        painter.end()


# ─── Syntax highlighting (inline, non distruttivo per gli sfondi diff) ────────

_SYNTAX_CACHE: dict[str, tuple] = {}  # lang_name -> (token_map, formats_dict)


def _get_syntax_formats(lang_name: str, theme_tokens: dict,
                        default_fg: QColor) -> dict:
    """Restituisce un dict token_key → QTextCharFormat (solo foreground/style)."""
    if lang_name in _SYNTAX_CACHE:
        return _SYNTAX_CACHE[lang_name][1]
    try:
        from pygments.token import (
            Keyword, Name, String, Number, Operator, Comment, Error
        )
    except ImportError:
        _SYNTAX_CACHE[lang_name] = ({}, {})
        return {}

    token_map = {
        Keyword.Type: "keyword2",
        Keyword: "keyword",
        Comment.Preproc: "preprocessor",
        Comment.PreprocFile: "preprocessor",
        Comment.Special: "comment",
        Comment: "comment",
        String.Doc: "comment_block",
        String.Escape: "string_raw",
        String: "string",
        Number: "number",
        Name.Class: "class_name",
        Name.Function: "function",
        Name.Decorator: "decorator",
        Name.Namespace: "keyword",
        Name.Builtin: "identifier",
        Name: "identifier",
        Operator: "operator",
        Error: "error",
    }

    formats = {}
    for tok_key in set(token_map.values()):
        tok_def = theme_tokens.get(tok_key, {}) if theme_tokens else {}
        fmt = QTextCharFormat()
        fg_val = tok_def.get("fg", default_fg.name()) if isinstance(tok_def, dict) else default_fg.name()
        fmt.setForeground(QColor(fg_val))
        if tok_def.get("bold"):
            fmt.setFontWeight(700)
        if tok_def.get("italic"):
            fmt.setFontItalic(True)
        formats[tok_key] = fmt
    _SYNTAX_CACHE[lang_name] = (token_map, formats)
    return formats


def _apply_syntax_to_cursor(cursor: QTextCursor, text: str,
                            start_pos: int, lang_name: str,
                            theme_tokens: dict, default_fg: QColor) -> None:
    """Applica syntax highlighting (solo foreground/style) al testo appena inserito,
    preservando lo sfondo diff esistente."""
    if not lang_name or not text:
        return
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name
        lexer = get_lexer_by_name(lang_name, ensurenl=False, stripall=False)
    except Exception:
        return

    formats = _get_syntax_formats(lang_name, theme_tokens, default_fg)
    token_map = _SYNTAX_CACHE.get(lang_name, ({}, {}))[0]
    if not formats:
        return

    try:
        tokens = list(lex(text, lexer))
    except Exception:
        return

    pos = 0
    for ttype, value in tokens:
        length = len(value)
        if length == 0:
            continue
        tok_key = "default"
        for token_cls, key in token_map.items():
            if ttype in token_cls:
                tok_key = key
                break
        fmt = formats.get(tok_key)
        if fmt:
            doc = cursor.document()
            abs_start = start_pos + pos
            cur = QTextCursor(doc)
            cur.setPosition(abs_start)
            cur.setPosition(abs_start + length, QTextCursor.MoveMode.KeepAnchor)
            cur.mergeCharFormat(fmt)
        pos += length


class DiffPanel(QWidget):
    """Pannello combinato: numeri di riga + vista diff editabile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._editor = QPlainTextEdit()
        mono = QFont("Monospace", 10)
        self._editor.setFont(mono)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._editor.setStyleSheet("background-color: white; color: #24292e;")
        self._editor.textChanged.connect(self._on_text_changed)

        self._line_nums = LineNumberWidget(self._editor)

        layout.addWidget(self._line_nums)
        layout.addWidget(self._editor)

    def _on_text_changed(self) -> None:
        pass

    def editor(self) -> QPlainTextEdit:
        return self._editor

    def set_plain_text(self, text: str) -> None:
        self._editor.setPlainText(text)

    def clear(self) -> None:
        self._editor.clear()

    def document(self):
        return self._editor.document()

    def verticalScrollBar(self):
        return self._editor.verticalScrollBar()

    def set_read_only(self, ro: bool) -> None:
        self._editor.setReadOnly(ro)


class CompareDialog(QDialog):
    """Finestra di confronto e merge side-by-side (v2.1) — stile Meld."""

    def __init__(self, main_window: "MainWindow", text_a: str = "",
                 text_b: str = "", label_a: str = "A", label_b: str = "B",
                 text_base: str = ""):
        super().__init__(main_window)
        self._mw = main_window
        self.setWindowTitle("Compare & Merge Files")
        self.resize(1200, 780)

        self._lines_a: List[str] = []
        self._lines_b: List[str] = []
        self._lines_base: List[str] = []
        self._opcodes: List[Tuple] = []
        self._opcodes_base_a: List[Tuple] = []
        self._opcodes_base_b: List[Tuple] = []
        self._diff_blocks: List[int] = []
        self._diff_idx = -1
        self._source_data: dict[int, str] = {}
        self._source_names: dict[int, str] = {}
        self._next_id = 0
        self._undo_stack: Deque[Tuple[List[str], List[str]]] = deque(maxlen=50)
        self._three_way = False
        self._refreshing = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._auto_refresh)

        self._theme_colors = self._get_theme_colors()
        self._lang_a = ""
        self._lang_b = ""

        self._build_ui()
        self._populate_sources()

        if text_a or text_b:
            if text_a:
                sid = self._add_text(text_a, label_a)
                self._src_a.addItem(label_a, sid)
            if text_b:
                sid = self._add_text(text_b, label_b)
                self._src_b.addItem(label_b, sid)
            if text_a:
                self._src_a.setCurrentIndex(self._src_a.count() - 1)
            if text_b:
                self._src_b.setCurrentIndex(self._src_b.count() - 1)
            if text_base:
                sid = self._add_text(text_base, "Base")
                self._src_base.addItem("Base", sid)
                self._src_base.setCurrentIndex(self._src_base.count() - 1)
                self._three_way = True
                self._three_way_cb.setChecked(True)
                self._toggle_three_way()
            self._run_compare()

    # ── Tema ───────────────────────────────────────────────────────────────────

    def _get_theme_colors(self) -> dict:
        try:
            from config.themes import ThemeManager
            tm = ThemeManager.instance()
            theme = tm.get_theme(tm._active_name) or {}
            tokens = theme.get("tokens", {})
            ui = theme.get("ui", {})
            return {
                "tokens": tokens,
                "fg": QColor(ui.get("editor_fg", "#24292e")),
                "bg": QColor(ui.get("editor_bg", "#ffffff")),
            }
        except Exception:
            return {"tokens": {}, "fg": QColor("#24292e"), "bg": QColor("#ffffff")}

    def _detect_language(self, name: str) -> str:
        ext = Path(name).suffix.lower() if name else ""
        ext_map = {
            ".py": "python", ".pyw": "python",
            ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".h": "c",
            ".hpp": "cpp", ".cs": "csharp",
            ".java": "java", ".js": "javascript", ".ts": "typescript",
            ".html": "html", ".htm": "html", ".xml": "xml",
            ".css": "css", ".scss": "scss",
            ".json": "json", ".yaml": "yaml", ".yml": "yaml",
            ".sql": "sql", ".sh": "bash", ".bash": "bash",
            ".md": "markdown", ".rst": "rst",
            ".rb": "ruby", ".lua": "lua", ".php": "php",
            ".go": "go", ".rs": "rust", ".swift": "swift",
            ".kt": "kotlin", ".tex": "latex",
            ".toml": "toml", ".ini": "ini", ".cfg": "ini",
            ".diff": "diff", ".patch": "diff",
        }
        return ext_map.get(ext, "")

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- Toolbar Selezione ---
        top = QHBoxLayout()
        top.addWidget(QLabel("A:"))
        self._src_a = QComboBox()
        self._src_a.setMinimumWidth(200)
        top.addWidget(self._src_a)

        self._btn_file_a = QPushButton("📂")
        self._btn_file_a.setFixedWidth(30)
        self._btn_file_a.setToolTip(tr("plugin.compare.pick_file"))
        self._btn_file_a.clicked.connect(lambda: self._pick_file("a"))
        top.addWidget(self._btn_file_a)

        self._btn_clip_a = QPushButton("📋")
        self._btn_clip_a.setFixedWidth(30)
        self._btn_clip_a.setToolTip(tr("plugin.compare.paste_clipboard"))
        self._btn_clip_a.clicked.connect(lambda: self._paste_clipboard("a"))
        top.addWidget(self._btn_clip_a)

        btn_swap = QPushButton("⇄")
        btn_swap.setFixedWidth(30)
        btn_swap.setToolTip(tr("plugin.compare.swap"))
        btn_swap.clicked.connect(self._swap_sources)
        top.addWidget(btn_swap)

        top.addWidget(QLabel(" B:"))
        self._src_b = QComboBox()
        self._src_b.setMinimumWidth(200)
        top.addWidget(self._src_b)

        self._btn_file_b = QPushButton("📂")
        self._btn_file_b.setFixedWidth(30)
        self._btn_file_b.setToolTip(tr("plugin.compare.pick_file"))
        self._btn_file_b.clicked.connect(lambda: self._pick_file("b"))
        top.addWidget(self._btn_file_b)

        self._btn_clip_b = QPushButton("📋")
        self._btn_clip_b.setFixedWidth(30)
        self._btn_clip_b.setToolTip(tr("plugin.compare.paste_clipboard"))
        self._btn_clip_b.clicked.connect(lambda: self._paste_clipboard("b"))
        top.addWidget(self._btn_clip_b)

        top.addWidget(QLabel("  " + tr("plugin.compare.ignore_ws") + ":"))
        self._ws_mode = QComboBox()
        self._ws_mode.addItems([
            tr("plugin.compare.ws_none"),
            tr("plugin.compare.ws_trailing"),
            tr("plugin.compare.ws_all"),
        ])
        self._ws_mode.setCurrentIndex(0)
        top.addWidget(self._ws_mode)

        self._three_way_cb = QCheckBox(tr("plugin.compare.three_way"))
        self._three_way_cb.toggled.connect(self._toggle_three_way)
        top.addWidget(self._three_way_cb)

        btn_compare = QPushButton(tr("plugin.compare.run"))
        btn_compare.setStyleSheet("font-weight: bold; padding: 0 10px;")
        btn_compare.clicked.connect(self._run_compare)
        top.addWidget(btn_compare)
        layout.addLayout(top)

        # --- Toolbar Selezione Base (solo modalità 3 vie) ---
        self._base_row = QWidget()
        base_row = QHBoxLayout(self._base_row)
        base_row.setContentsMargins(0, 0, 0, 0)
        base_row.addWidget(QLabel(tr("plugin.compare.base") + ":"))
        self._src_base = QComboBox()
        self._src_base.setMinimumWidth(200)
        base_row.addWidget(self._src_base)

        self._btn_file_base = QPushButton("📂")
        self._btn_file_base.setFixedWidth(30)
        self._btn_file_base.setToolTip(tr("plugin.compare.pick_file"))
        self._btn_file_base.clicked.connect(lambda: self._pick_file("base"))
        base_row.addWidget(self._btn_file_base)

        self._btn_clip_base = QPushButton("📋")
        self._btn_clip_base.setFixedWidth(30)
        self._btn_clip_base.setToolTip(tr("plugin.compare.paste_clipboard"))
        self._btn_clip_base.clicked.connect(lambda: self._paste_clipboard("base"))
        base_row.addWidget(self._btn_clip_base)

        base_row.addStretch()
        self._base_row.setVisible(False)
        layout.addWidget(self._base_row)

        # --- Toolbar Navigazione e Merge ---
        nav = QHBoxLayout()
        self._diff_label = QLabel(tr("plugin.compare.differences") + ": 0")
        nav.addWidget(self._diff_label)

        self._stats_label = QLabel("")
        nav.addWidget(self._stats_label)
        nav.addSpacing(10)

        self._btn_prev = QPushButton("▲ " + tr("plugin.compare.prev"))
        self._btn_next = QPushButton(tr("plugin.compare.next") + " ▼")
        self._btn_prev.clicked.connect(self._prev_diff)
        self._btn_next.clicked.connect(self._next_diff)
        nav.addWidget(self._btn_prev)
        nav.addWidget(self._btn_next)

        nav.addSpacing(20)
        self._btn_to_left = QPushButton(tr("plugin.compare.copy_left"))
        self._btn_to_right = QPushButton(tr("plugin.compare.copy_right"))
        self._btn_to_left.setStyleSheet(
            "background-color: #f0fff0; border: 1px solid #c0e0c0;")
        self._btn_to_right.setStyleSheet(
            "background-color: #f0fff0; border: 1px solid #c0e0c0;")
        self._btn_to_left.clicked.connect(lambda: self._merge_action("left"))
        self._btn_to_right.clicked.connect(lambda: self._merge_action("right"))
        nav.addWidget(self._btn_to_left)
        nav.addWidget(self._btn_to_right)

        self._btn_undo = QPushButton(tr("plugin.compare.undo"))
        self._btn_undo.clicked.connect(self._undo_merge)
        self._btn_undo.setEnabled(False)
        nav.addWidget(self._btn_undo)

        self._btn_refresh = QPushButton("⟳ " + tr("plugin.compare.refresh"))
        self._btn_refresh.clicked.connect(self._run_compare)
        nav.addWidget(self._btn_refresh)

        nav.addStretch()
        layout.addLayout(nav)

        # --- Area di visualizzazione ---
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._panel_a = DiffPanel()
        self._panel_b = DiffPanel()
        self._panel_base = DiffPanel()
        self._panel_base.setVisible(False)

        self._panel_a.editor().textChanged.connect(
            lambda: self._on_panel_edited("a"))
        self._panel_b.editor().textChanged.connect(
            lambda: self._on_panel_edited("b"))

        self._splitter.addWidget(self._panel_a)
        self._splitter.addWidget(self._panel_b)
        self._splitter.addWidget(self._panel_base)
        self._splitter.setSizes([550, 550, 0])

        layout.addWidget(self._splitter, 1)

        # Scroll sync proporzionale
        self._scrolling = False

        def _sync_prop(src, dst):
            if self._scrolling:
                return
            src_max = src.verticalScrollBar().maximum()
            dst_max = dst.verticalScrollBar().maximum()
            if src_max <= 0 or dst_max <= 0:
                return
            ratio = src.verticalScrollBar().value() / src_max
            self._scrolling = True
            dst.verticalScrollBar().setValue(int(ratio * dst_max))
            self._scrolling = False

        v_a = self._panel_a
        v_b = self._panel_b
        v_a.verticalScrollBar().valueChanged.connect(lambda v: _sync_prop(v_a, v_b))
        v_b.verticalScrollBar().valueChanged.connect(lambda v: _sync_prop(v_b, v_a))

        # --- Footer ---
        footer = QHBoxLayout()

        self._edit_mode_cb = QCheckBox(tr("plugin.compare.edit_mode"))
        self._edit_mode_cb.setChecked(True)
        self._edit_mode_cb.toggled.connect(self._toggle_edit_mode)
        footer.addWidget(self._edit_mode_cb)

        self._btn_save_a = QPushButton(tr("plugin.compare.save_a"))
        self._btn_save_a.clicked.connect(lambda: self._save_to_file("a"))
        footer.addWidget(self._btn_save_a)

        self._btn_save_b = QPushButton(tr("plugin.compare.save_b"))
        self._btn_save_b.clicked.connect(lambda: self._save_to_file("b"))
        footer.addWidget(self._btn_save_b)

        btn_apply = QPushButton(tr("plugin.compare.apply"))
        btn_apply.setFixedHeight(35)
        btn_apply.clicked.connect(self._apply_to_editors)
        footer.addWidget(btn_apply)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.accept)
        footer.addStretch()
        footer.addWidget(btns)
        layout.addLayout(footer)

        # --- Shortcuts ---
        QShortcut(QKeySequence(Qt.Modifier.ALT | Qt.Key.Key_Left),
                  self, activated=lambda: self._merge_action("left"))
        QShortcut(QKeySequence(Qt.Modifier.ALT | Qt.Key.Key_Right),
                  self, activated=lambda: self._merge_action("right"))
        QShortcut(QKeySequence(Qt.Modifier.ALT | Qt.Key.Key_Up),
                  self, activated=self._prev_diff)
        QShortcut(QKeySequence(Qt.Modifier.ALT | Qt.Key.Key_Down),
                  self, activated=self._next_diff)
        QShortcut(QKeySequence.StandardKey.Undo, self,
                  activated=self._undo_merge)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self,
                  activated=self._run_compare)

    # ── Edit mode ─────────────────────────────────────────────────────────────

    def _toggle_edit_mode(self, enabled: bool) -> None:
        self._panel_a.set_read_only(not enabled)
        self._panel_b.set_read_only(not enabled)

    def _on_panel_edited(self, side: str) -> None:
        if self._refreshing:
            return
        self._debounce_timer.start(800)

    def _auto_refresh(self) -> None:
        text_a = self._panel_a.editor().toPlainText()
        text_b = self._panel_b.editor().toPlainText()
        sid_a = self._current_id("a")
        sid_b = self._current_id("b")
        if sid_a >= 0:
            self._source_data[sid_a] = text_a
        if sid_b >= 0:
            self._source_data[sid_b] = text_b
        cursor_a = self._panel_a.editor().textCursor()
        cursor_b = self._panel_b.editor().textCursor()
        pos_a = cursor_a.position()
        pos_b = cursor_b.position()
        self._run_compare()
        c = self._panel_a.editor().textCursor()
        c.setPosition(min(pos_a, len(self._panel_a.editor().toPlainText())))
        self._panel_a.editor().setTextCursor(c)
        c = self._panel_b.editor().textCursor()
        c.setPosition(min(pos_b, len(self._panel_b.editor().toPlainText())))
        self._panel_b.editor().setTextCursor(c)

    # ── Gestione sorgenti ─────────────────────────────────────────────────────

    def _add_text(self, text: str, name: str) -> int:
        sid = self._next_id
        self._next_id += 1
        self._source_data[sid] = text
        self._source_names[sid] = name
        return sid

    def _populate_sources(self) -> None:
        editors = self._mw._tab_manager.all_editors()
        self._src_a.clear()
        self._src_b.clear()
        self._src_base.clear()
        for i, ed in enumerate(editors):
            name = ed.file_path.name if ed.file_path else f"(Tab {i+1})"
            sid = self._add_text(ed.get_content(), name)
            self._src_a.addItem(name, sid)
            self._src_b.addItem(name, sid)
            self._src_base.addItem(name, sid)
        if self._src_b.count() > 1:
            self._src_b.setCurrentIndex(1)

    def _combo_for_side(self, side: str) -> QComboBox:
        return {"a": self._src_a, "b": self._src_b,
                "base": self._src_base}[side]

    def _pick_file(self, side: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("plugin.compare.open_file"), "",
            tr("plugin.compare.all_files"))
        if path:
            p = Path(path)
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                QMessageBox.warning(self, tr("plugin.compare.error"),
                                    tr("plugin.compare.read_error", error=str(e)))
                return
            name = f"[File] {p.name}"
            sid = self._add_text(text, name)
            combo = self._combo_for_side(side)
            combo.addItem(name, sid)
            combo.setCurrentIndex(combo.count() - 1)

    def _paste_clipboard(self, side: str) -> None:
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if not text:
            QMessageBox.information(self, tr("plugin.compare.clipboard_empty_title"),
                                    tr("plugin.compare.clipboard_empty"))
            return
        name = tr("plugin.compare.clipboard_name")
        sid = self._add_text(text, name)
        combo = self._combo_for_side(side)
        existing = combo.findText(name)
        if existing >= 0:
            combo.setItemData(existing, sid)
            combo.setCurrentIndex(existing)
        else:
            combo.addItem(name, sid)
            combo.setCurrentIndex(combo.count() - 1)

    def _swap_sources(self) -> None:
        idx_a = self._src_a.currentIndex()
        idx_b = self._src_b.currentIndex()
        self._src_a.setCurrentIndex(idx_b)
        self._src_b.setCurrentIndex(idx_a)

    def _toggle_three_way(self) -> None:
        self._three_way = self._three_way_cb.isChecked()
        self._panel_base.setVisible(self._three_way)
        self._base_row.setVisible(self._three_way)
        if self._three_way:
            sizes = self._splitter.sizes()
            total = sum(sizes)
            third = total // 3
            self._splitter.setSizes([third, third, third])
        else:
            sizes = self._splitter.sizes()
            total = sum(sizes)
            half = total // 2
            self._splitter.setSizes([half, half, 0])

    def _current_id(self, side: str) -> int:
        data = self._combo_for_side(side).currentData()
        return data if data is not None else -1

    # ── Algoritmo di diff ─────────────────────────────────────────────────────

    def _preprocess_lines(self, lines: List[str]) -> List[str]:
        mode = self._ws_mode.currentIndex()
        if mode == 0:
            return lines
        if mode == 1:
            return [l.rstrip('\n').rstrip('\r') for l in lines]
        if mode == 2:
            return [re.sub(r'\s+', '', l) for l in lines]
        return lines

    def _run_compare(self) -> None:
        self._debounce_timer.stop()
        sid_a = self._current_id("a")
        sid_b = self._current_id("b")
        text_a = self._source_data.get(sid_a, "")
        text_b = self._source_data.get(sid_b, "")

        self._lines_a = text_a.splitlines(keepends=True)
        self._lines_b = text_b.splitlines(keepends=True)

        cmp_a = self._preprocess_lines(self._lines_a)
        cmp_b = self._preprocess_lines(self._lines_b)

        matcher = difflib.SequenceMatcher(None, cmp_a, cmp_b, autojunk=False)
        self._opcodes = matcher.get_opcodes()
        self._diff_blocks = [i for i, op in enumerate(self._opcodes)
                             if op[0] != 'equal']

        if self._three_way:
            text_base = self._source_data.get(self._current_id("base"), "")
            self._lines_base = text_base.splitlines(keepends=True)
            cmp_base = self._preprocess_lines(self._lines_base)
            m1 = difflib.SequenceMatcher(None, cmp_base, cmp_a, autojunk=False)
            self._opcodes_base_a = m1.get_opcodes()
            m2 = difflib.SequenceMatcher(None, cmp_base, cmp_b, autojunk=False)
            self._opcodes_base_b = m2.get_opcodes()

        if not self._diff_blocks:
            self._diff_idx = -1
        elif self._diff_idx >= len(self._diff_blocks):
            self._diff_idx = 0
        elif self._diff_idx < 0 and self._diff_blocks:
            self._diff_idx = 0

        self._undo_stack.clear()
        self._btn_undo.setEnabled(False)

        self._apply_syntax_names()
        self._render_diff()
        self._update_ui_state()
        stats = self._compute_stats()
        self._stats_label.setText(
            f"  +{stats['added']}  -{stats['deleted']}  ~{stats['changed']}")

    def _apply_syntax_names(self) -> None:
        """Prepara i nomi dei linguaggi per il syntax highlighting inline."""
        name_a = self._source_names.get(self._current_id("a"), "")
        name_b = self._source_names.get(self._current_id("b"), "")
        self._lang_a = self._detect_language(name_a)
        self._lang_b = self._detect_language(name_b)

    def _compute_stats(self) -> dict:
        added = deleted = changed = 0
        for tag, i1, i2, j1, j2 in self._opcodes:
            if tag == "insert":
                added += j2 - j1
            elif tag == "delete":
                deleted += i2 - i1
            elif tag == "replace":
                added += (j2 - j1)
                deleted += (i2 - i1)
                changed += min(i2 - i1, j2 - j1)
        return {"added": added, "deleted": deleted, "changed": changed}

    # ── Rendering (senza padding, ogni pannello mostra le proprie righe) ─────

    def _render_diff(self) -> None:
        self._refreshing = True
        self._panel_a.clear()
        self._panel_b.clear()
        if self._three_way:
            self._panel_base.clear()
            self._render_three_way()
        else:
            self._render_two_way()
        self._apply_inline_syntax()
        self._refreshing = False

    def _apply_inline_syntax(self) -> None:
        """Applica syntax highlighting dopo il rendering diff, preservando sfondi."""
        tc = self._theme_colors
        if self._lang_a:
            _apply_syntax_to_cursor(
                self._panel_a.editor().textCursor(),
                self._panel_a.editor().toPlainText(), 0,
                self._lang_a, tc["tokens"], tc["fg"])
        if self._lang_b:
            _apply_syntax_to_cursor(
                self._panel_b.editor().textCursor(),
                self._panel_b.editor().toPlainText(), 0,
                self._lang_b, tc["tokens"], tc["fg"])

    def _render_two_way(self) -> None:
        cursor_a = self._panel_a.editor().textCursor()
        cursor_b = self._panel_b.editor().textCursor()

        active_opcode_idx = (self._diff_blocks[self._diff_idx]
                             if (self._diff_idx >= 0 and self._diff_blocks)
                             else -1)

        for idx, (tag, i1, i2, j1, j2) in enumerate(self._opcodes):
            is_active = (idx == active_opcode_idx)
            chunk_a = "".join(self._lines_a[i1:i2])
            chunk_b = "".join(self._lines_b[j1:j2])

            if tag == "equal":
                _append_plain(cursor_a, chunk_a, _COLOR_NONE)
                _append_plain(cursor_b, chunk_b, _COLOR_NONE)
            elif tag == "replace":
                bg = _COLOR_ACTIVE if is_active else _COLOR_CHG
                _append_char_diff(cursor_a, chunk_a, chunk_b,
                                  _COLOR_CHAR_DEL, _COLOR_CHAR_ADD, bg)
                _append_char_diff(cursor_b, chunk_b, chunk_a,
                                  _COLOR_CHAR_ADD, _COLOR_CHAR_DEL, bg)
            elif tag == "delete":
                bg = _COLOR_ACTIVE if is_active else _COLOR_DEL
                _append_plain(cursor_a, chunk_a, bg)
            elif tag == "insert":
                bg = _COLOR_ACTIVE if is_active else _COLOR_ADD
                _append_plain(cursor_b, chunk_b, bg)

    def _render_three_way(self) -> None:
        cursor_a = self._panel_a.editor().textCursor()
        cursor_b = self._panel_b.editor().textCursor()
        cursor_base = self._panel_base.editor().textCursor()

        a_changed = set()
        b_changed = set()
        for tag, i1, i2, _, _ in self._opcodes_base_a:
            if tag != "equal":
                for ln in range(i1, i2):
                    a_changed.add(ln)
        for tag, i1, i2, _, _ in self._opcodes_base_b:
            if tag != "equal":
                for ln in range(i1, i2):
                    b_changed.add(ln)
        conflict_lines = a_changed & b_changed

        for tag, i1, i2, _, _ in self._opcodes_base_a:
            is_conflict = any(ln in conflict_lines
                              for ln in range(i1, max(i1, i2)))
            if tag == "equal":
                bg = _COLOR_NONE
            elif is_conflict:
                bg = _COLOR_CONFLICT
            else:
                bg = QColor("#ffeeee")
            _append_plain(cursor_base, "".join(self._lines_base[i1:i2]), bg)

        for tag, i1, i2, j1, j2 in self._opcodes_base_a:
            is_conflict = any(ln in conflict_lines
                              for ln in range(i1, max(i1, i2)))
            if tag == "equal":
                _append_plain(cursor_a, "".join(self._lines_base[i1:i2]),
                              _COLOR_NONE)
            elif tag == "replace":
                bg_c = _COLOR_CONFLICT if is_conflict else _COLOR_CHG
                _append_char_diff(cursor_a,
                    "".join(self._lines_base[i1:i2]),
                    "".join(self._lines_a[j1:j2]),
                    _COLOR_CHAR_DEL, _COLOR_CHAR_ADD, bg_c)
            elif tag == "delete":
                _append_plain(cursor_a, "".join(self._lines_base[i1:i2]),
                              _COLOR_CONFLICT if is_conflict else _COLOR_DEL)
            elif tag == "insert":
                _append_plain(cursor_a, "".join(self._lines_a[j1:j2]),
                              _COLOR_CONFLICT if is_conflict else _COLOR_ADD)

        for tag, i1, i2, j1, j2 in self._opcodes_base_b:
            is_conflict = any(ln in conflict_lines
                              for ln in range(i1, max(i1, i2)))
            if tag == "equal":
                _append_plain(cursor_b, "".join(self._lines_base[i1:i2]),
                              _COLOR_NONE)
            elif tag == "replace":
                bg_c = _COLOR_CONFLICT if is_conflict else _COLOR_CHG
                _append_char_diff(cursor_b,
                    "".join(self._lines_base[i1:i2]),
                    "".join(self._lines_b[j1:j2]),
                    _COLOR_CHAR_DEL, _COLOR_CHAR_ADD, bg_c)
            elif tag == "delete":
                _append_plain(cursor_b, "".join(self._lines_base[i1:i2]),
                              _COLOR_CONFLICT if is_conflict else _COLOR_DEL)
            elif tag == "insert":
                _append_plain(cursor_b, "".join(self._lines_b[j1:j2]),
                              _COLOR_CONFLICT if is_conflict else _COLOR_ADD)

    # ── Navigazione e Merge ───────────────────────────────────────────────────

    def _update_ui_state(self) -> None:
        valid = (self._diff_idx >= 0 and
                 self._diff_idx < len(self._diff_blocks))
        self._btn_to_right.setEnabled(valid)
        self._btn_to_left.setEnabled(valid)
        if valid and self._diff_blocks:
            self._diff_label.setText(
                tr("plugin.compare.differences") +
                f": {len(self._diff_blocks)}  [{self._diff_idx + 1}/{len(self._diff_blocks)}]")
        elif not self._diff_blocks:
            self._diff_label.setText(tr("plugin.compare.no_differences"))

    def _goto_diff(self, idx: int) -> None:
        if not self._diff_blocks:
            return
        old_idx = self._diff_idx
        self._diff_idx = idx % len(self._diff_blocks)
        opcode_idx = self._diff_blocks[self._diff_idx]
        _, i1, _, _, _ = self._opcodes[opcode_idx]
        self._render_diff()
        if self._panel_a.document().blockCount() > 0:
            block = self._panel_a.document().findBlockByLineNumber(
                min(i1, self._panel_a.document().blockCount() - 1))
            cursor = QTextCursor(block)
            self._panel_a.editor().setTextCursor(cursor)
            self._panel_a.editor().ensureCursorVisible()
        self._update_ui_state()

    def _prev_diff(self) -> None:
        if not self._diff_blocks:
            return
        if self._diff_idx <= 0:
            QApplication.beep()
        self._goto_diff(self._diff_idx - 1)

    def _next_diff(self) -> None:
        if not self._diff_blocks:
            return
        if self._diff_idx >= len(self._diff_blocks) - 1:
            QApplication.beep()
        self._goto_diff(self._diff_idx + 1)

    def _merge_action(self, direction: str) -> None:
        if self._diff_idx < 0:
            return
        opcode_idx = self._diff_blocks[self._diff_idx]
        tag, i1, i2, j1, j2 = self._opcodes[opcode_idx]

        self._undo_stack.append((list(self._lines_a), list(self._lines_b)))
        self._btn_undo.setEnabled(True)

        if direction == "right":
            self._lines_b[j1:j2] = self._lines_a[i1:i2]
        else:
            self._lines_a[i1:i2] = self._lines_b[j1:j2]

        sid_a = self._current_id("a")
        sid_b = self._current_id("b")
        self._source_data[sid_a] = "".join(self._lines_a)
        self._source_data[sid_b] = "".join(self._lines_b)

        old_idx = self._diff_idx
        self._run_compare()
        if self._diff_blocks:
            self._goto_diff(min(old_idx, len(self._diff_blocks) - 1))
        else:
            self._diff_idx = -1
            self._render_diff()
            self._update_ui_state()

    def _undo_merge(self) -> None:
        if not self._undo_stack:
            return
        self._lines_a, self._lines_b = self._undo_stack.pop()
        self._btn_undo.setEnabled(len(self._undo_stack) > 0)
        sid_a = self._current_id("a")
        sid_b = self._current_id("b")
        self._source_data[sid_a] = "".join(self._lines_a)
        self._source_data[sid_b] = "".join(self._lines_b)
        self._run_compare()

    # ── Azioni finali ─────────────────────────────────────────────────────────

    def _save_to_file(self, side: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("plugin.compare.save_file"), "",
            tr("plugin.compare.all_files"))
        if not path:
            return
        sid = self._current_id(side)
        text = self._source_data.get(sid, "")
        try:
            Path(path).write_text(text, encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, tr("plugin.compare.error"),
                                tr("plugin.compare.write_error", error=str(e)))

    def _apply_to_editors(self) -> None:
        editors = self._mw._tab_manager.all_editors()
        applied = 0
        for i, ed in enumerate(editors):
            name = ed.file_path.name if ed.file_path else f"(Tab {i+1})"
            for sid, sname in self._source_names.items():
                if sname == name:
                    text = self._source_data.get(sid, "")
                    ed.load_content(text)
                    applied += 1
                    break
        QMessageBox.information(self, tr("plugin.compare.merge_done_title"),
                                tr("plugin.compare.merge_done", count=applied))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _append_plain(cursor: QTextCursor, text: str, bg: QColor,
                  underline_color: QColor = None) -> None:
    fmt = QTextCharFormat()
    fmt.setBackground(bg)
    fmt.setForeground(_COLOR_TEXT)
    if underline_color is not None and underline_color != QColor("transparent"):
        fmt.setUnderlineColor(underline_color)
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
    cursor.insertText(text, fmt)


def _append_char_diff(cursor: QTextCursor, text: str,
                      other: str, self_style: QColor,
                      other_style: QColor, block_bg: QColor) -> None:
    matcher = difflib.SequenceMatcher(None, text, other, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            _append_plain(cursor, text[i1:i2], block_bg)
        elif tag == "replace":
            if text[i1:i2]:
                _append_plain(cursor, text[i1:i2], block_bg,
                              underline_color=self_style)
            if other[j1:j2]:
                _append_plain(cursor, other[j1:j2], block_bg,
                              underline_color=other_style)
        elif tag == "delete":
            _append_plain(cursor, text[i1:i2], block_bg,
                          underline_color=self_style)
        elif tag == "insert":
            pass


# ─── Plugin ───────────────────────────────────────────────────────────────────

class ComparePlugin(BasePlugin):
    """Entry point del plugin per NotePadPQ."""

    NAME = "Compare & Merge"
    VERSION = "2.1"
    DESCRIPTION = "Meld-style compare & merge with inline editing, syntax highlighting, char-level diff, undo, and three-way merge."
    AUTHOR = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self.add_menu_action(
            main_window, "plugins",
            tr("plugin.compare.menu"),
            self._open_compare,
            shortcut="F9",
            icon_key="plugin_compare"
        )

    def _open_compare(self) -> None:
        dlg = CompareDialog(self._mw)
        dlg.exec()

    @staticmethod
    def compare_texts(text_a: str, text_b: str,
                      label_a: str = "A", label_b: str = "B",
                      text_base: str = "") -> None:
        from plugins.plugin_manager import PluginManager
        pm = PluginManager.instance()
        mw = pm._main_window
        if mw:
            dlg = CompareDialog(mw, text_a=text_a, text_b=text_b,
                                label_a=label_a, label_b=label_b,
                                text_base=text_base)
            dlg.exec()
