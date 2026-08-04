"""
ui/include_list.py — Pannello Include List
NotePadPQ

Pannello dock che elenca tutti i comandi include del file corrente
(LaTeX: \\includegraphics, \\include, \\input, \\subfile, \\bibliography;
 Markdown: immagini e link locali).

Per ogni include mostra:
  - icona stato (✓ trovato / ⚠ non trovato / ? non verificabile)
  - tipo di comando  •  argomento  •  numero di riga

Opzionale: confronto con una cartella di riferimento per evidenziare
file presenti nella cartella ma non referenziati nel documento.

Uso da main.py:
    from ui.include_list import install as install_include_list
    install_include_list(win)
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, TYPE_CHECKING

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel, QColor, QIcon, QKeySequence, QAction
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeView, QLabel, QPushButton, QLineEdit,
    QAbstractItemView, QFileDialog, QMenu,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


# ─── Struttura dati ───────────────────────────────────────────────────────────

STATUS_FOUND   = "found"
STATUS_MISSING = "missing"
STATUS_UNKNOWN = "unknown"   # nessuna base dir disponibile

STATUS_ICON = {
    STATUS_FOUND:   "✓",
    STATUS_MISSING: "⚠",
    STATUS_UNKNOWN: "?",
}
STATUS_COLOR = {
    STATUS_FOUND:   "#4caf50",
    STATUS_MISSING: "#f44336",
    STATUS_UNKNOWN: "#888888",
}

# Estensioni cercate automaticamente quando manca estensione nell'include
_IMG_EXTS   = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg",
               ".bmp", ".gif", ".tiff", ".tif", ".webp")

# Estensioni che Qt sa renderizzare direttamente in un tooltip HTML
# (PDF/EPS/TIFF non sono supportati dal motore di rich text di QToolTip)
_IMG_PREVIEW_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".svg"}
_TEX_EXTS   = (".tex",)
_BIB_EXTS   = (".bib",)

# Estensioni considerate "rilevanti" per il confronto con la cartella
_RELEVANT_BY_KIND = {
    "latex": {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg",
              ".bmp", ".gif", ".tiff", ".tif", ".webp",
              ".tex", ".bib", ".cls", ".sty"},
    "markdown": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                 ".bmp", ".tiff", ".md", ".markdown"},
}


@dataclass
class IncludeEntry:
    kind:     str    # "includegraphics", "include", "input", "subfile", "bibliography", "md_image", "md_link"
    arg:      str    # argomento grezzo (nome file / path)
    line:     int    # 1-based
    status:   str = STATUS_UNKNOWN
    resolved: Optional[Path] = None   # path effettivo trovato su disco


# ─── Parser ───────────────────────────────────────────────────────────────────

def _resolve_file(arg: str, base_dir: Path,
                  search_exts: tuple[str, ...]) -> Optional[Path]:
    """Cerca il file: prima as-is, poi aggiungendo le estensioni in search_exts."""
    if not base_dir:
        return None
    p = (base_dir / arg).resolve()
    if p.exists():
        return p
    for ext in search_exts:
        q = Path(str(p) + ext)
        if q.exists():
            return q
        # anche solo il nome senza directory intermedie già nell'arg
        q2 = base_dir / (arg + ext)
        if q2.resolve().exists():
            return q2.resolve()
    return None


def _determine_status(entry: IncludeEntry, base_dir: Optional[Path],
                      search_exts: tuple[str, ...]) -> None:
    if not base_dir:
        entry.status = STATUS_UNKNOWN
        return
    p = _resolve_file(entry.arg, base_dir, search_exts)
    if p is not None:
        entry.status   = STATUS_FOUND
        entry.resolved = p
    else:
        entry.status = STATUS_MISSING


# Pattern LaTeX: (regex, kind, search_exts)
_LATEX_PATTERNS: list[tuple[re.Pattern, str, tuple]] = [
    # \includegraphics[opts]{file}
    (re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"), "includegraphics", _IMG_EXTS),
    # \include{file}  \input{file}  \subfile{file}
    (re.compile(r"\\include\{([^}]+)\}"),   "include",   _TEX_EXTS),
    (re.compile(r"\\input\{([^}]+)\}"),     "input",     _TEX_EXTS),
    (re.compile(r"\\subfile\{([^}]+)\}"),   "subfile",   _TEX_EXTS),
    # \bibliography{file}  (può contenere più file separati da virgola)
    (re.compile(r"\\bibliography\{([^}]+)\}"), "bibliography", _BIB_EXTS),
    # \import{prefix}{file}
    (re.compile(r"\\import\{([^}]*)\}\{([^}]+)\}"), "import", _TEX_EXTS),
]


def parse_latex(text: str, base_dir: Optional[Path]) -> List[IncludeEntry]:
    entries: List[IncludeEntry] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        for pattern, kind, exts in _LATEX_PATTERNS:
            for m in pattern.finditer(line):
                if kind == "import":
                    prefix = m.group(1).strip().rstrip("/")
                    fname  = m.group(2).strip()
                    arg    = (prefix + "/" + fname) if prefix else fname
                elif kind == "bibliography":
                    # può essere "file1,file2" — espandi
                    for bib in m.group(1).split(","):
                        bib = bib.strip()
                        if not bib:
                            continue
                        e = IncludeEntry(kind="bibliography", arg=bib, line=lineno)
                        _determine_status(e, base_dir, _BIB_EXTS)
                        entries.append(e)
                    continue
                else:
                    arg = m.group(1).strip()
                e = IncludeEntry(kind=kind, arg=arg, line=lineno)
                _determine_status(e, base_dir, exts)
                entries.append(e)
    return entries


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MD_LINK  = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")


def parse_markdown(text: str, base_dir: Optional[Path]) -> List[IncludeEntry]:
    entries: List[IncludeEntry] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        # immagini
        for m in _MD_IMAGE.finditer(line):
            href = m.group(2).strip()
            if href.startswith(("http://", "https://", "ftp://", "#", "mailto:")):
                continue
            e = IncludeEntry(kind="md_image", arg=href, line=lineno)
            _determine_status(e, base_dir, ())
            entries.append(e)
        # link locali
        for m in _MD_LINK.finditer(line):
            href = m.group(2).strip()
            if href.startswith(("http://", "https://", "ftp://", "#", "mailto:")):
                continue
            e = IncludeEntry(kind="md_link", arg=href, line=lineno)
            _determine_status(e, base_dir, ())
            entries.append(e)
    return entries


def _not_included(entries: List[IncludeEntry],
                  ref_dir: Path,
                  lang: str) -> List[Path]:
    """File nella ref_dir con estensioni rilevanti che non compaiono tra gli include."""
    rel_exts = _RELEVANT_BY_KIND.get(lang, set())
    if not rel_exts or not ref_dir.is_dir():
        return []

    resolved: Set[Path] = set()
    for e in entries:
        if e.resolved:
            resolved.add(e.resolved)

    missing: List[Path] = []
    for p in sorted(ref_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in rel_exts:
            if p not in resolved:
                missing.append(p)
    return missing


# ─── Worker ───────────────────────────────────────────────────────────────────

class _ScanWorker(QThread):
    done = pyqtSignal(list, list, int)   # entries, not_included, generation

    def __init__(self, text: str, lang: str,
                 base_dir: Optional[Path], ref_dir: Optional[Path],
                 generation: int):
        super().__init__(None)
        self._text       = text
        self._lang       = lang
        self._base_dir   = base_dir
        self._ref_dir    = ref_dir
        self._generation = generation
        self._cancelled  = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        if self._lang == "latex":
            entries = parse_latex(self._text, self._base_dir)
        elif self._lang == "markdown":
            entries = parse_markdown(self._text, self._base_dir)
        else:
            entries = []

        not_inc: List[Path] = []
        if not self._cancelled and self._ref_dir and entries is not None:
            not_inc = _not_included(entries, self._ref_dir, self._lang)

        if not self._cancelled:
            self.done.emit(entries, not_inc, self._generation)


# ─── Pannello ─────────────────────────────────────────────────────────────────

_KIND_LABEL = {
    "includegraphics": "\\includegraphics",
    "include":         "\\include",
    "input":           "\\input",
    "subfile":         "\\subfile",
    "bibliography":    "\\bibliography",
    "import":          "\\import",
    "md_image":        "![image]",
    "md_link":         "[link]",
}

_GROUP_ORDER = [
    "includegraphics", "include", "input", "subfile",
    "import", "bibliography", "md_image", "md_link",
]


class _IncludeListPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw            = main_window
        self._editor: Optional["EditorWidget"] = None
        self._entries: List[IncludeEntry]  = []
        self._not_inc: List[Path]          = []
        self._lang: str                    = ""
        self._ref_dir: Optional[Path]      = None
        self._scan_worker: Optional[_ScanWorker] = None
        self._old_workers: list            = []
        self._scan_gen: int                = 0
        self._needs_refresh: bool          = True

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(800)
        self._timer.timeout.connect(self._refresh)

        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Barra cartella riferimento
        folder_row = QHBoxLayout()
        self._folder_label = QLabel(tr("include_list.no_ref_folder",
                                       default="Nessuna cartella"))
        self._folder_label.setStyleSheet("font-size: 11px; color: #888;")
        self._folder_label.setWordWrap(False)
        self._folder_label.setMaximumWidth(220)
        folder_row.addWidget(self._folder_label, 1)

        btn_folder = QPushButton("📁")
        btn_folder.setFixedSize(28, 24)
        btn_folder.setToolTip(tr("include_list.tooltip_set_folder",
                                 default="Imposta cartella di confronto"))
        btn_folder.clicked.connect(self._choose_ref_folder)
        folder_row.addWidget(btn_folder)

        btn_clear = QPushButton("✕")
        btn_clear.setFixedSize(22, 24)
        btn_clear.setToolTip(tr("include_list.tooltip_clear_folder",
                                default="Rimuovi cartella"))
        btn_clear.clicked.connect(self._clear_ref_folder)
        folder_row.addWidget(btn_clear)

        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedSize(24, 24)
        btn_refresh.setToolTip(tr("include_list.tooltip_refresh",
                                  default="Aggiorna"))
        btn_refresh.clicked.connect(self._refresh)
        folder_row.addWidget(btn_refresh)
        layout.addLayout(folder_row)

        # Filtro
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("include_list.placeholder_filter",
                                           default="Filtra…"))
        self._filter.setFixedHeight(24)
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        # Albero
        self._model = QStandardItemModel(self)
        self._tree  = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.clicked.connect(self._on_clicked)
        self._tree.doubleClicked.connect(self._on_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._tree, 1)

        # Barra info
        self._info = QLabel("")
        self._info.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self._info)

    # ── Cartella riferimento ──────────────────────────────────────────────────

    def _ref_dir_key(self) -> str:
        if self._editor and self._editor.file_path:
            h = str(self._editor.file_path)
        else:
            h = "__global__"
        return f"include_list/ref_folder/{h}"

    def _load_ref_dir(self) -> None:
        from config.settings import Settings
        val = Settings.instance().get(self._ref_dir_key())
        if val and Path(val).is_dir():
            self._ref_dir = Path(val)
        else:
            self._ref_dir = None
        self._update_folder_label()

    def _save_ref_dir(self) -> None:
        from config.settings import Settings
        Settings.instance().set(self._ref_dir_key(),
                                str(self._ref_dir) if self._ref_dir else "")

    def _update_folder_label(self) -> None:
        if self._ref_dir:
            self._folder_label.setText(self._ref_dir.name)
            self._folder_label.setToolTip(str(self._ref_dir))
            self._folder_label.setStyleSheet("font-size: 11px;")
        else:
            self._folder_label.setText(tr("include_list.no_ref_folder",
                                          default="Nessuna cartella"))
            self._folder_label.setToolTip("")
            self._folder_label.setStyleSheet("font-size: 11px; color: #888;")

    def _choose_ref_folder(self) -> None:
        start = str(self._ref_dir) if self._ref_dir else (
            str(self._editor.file_path.parent)
            if self._editor and self._editor.file_path else ""
        )
        chosen = QFileDialog.getExistingDirectory(self,
            tr("include_list.choose_folder", default="Scegli cartella di confronto"),
            start)
        if chosen:
            self._ref_dir = Path(chosen)
            self._save_ref_dir()
            self._update_folder_label()
            self._schedule_refresh()

    def _clear_ref_folder(self) -> None:
        self._ref_dir = None
        self._save_ref_dir()
        self._update_folder_label()
        self._schedule_refresh()

    # ── Aggiornamento ─────────────────────────────────────────────────────────

    def _detect_lang(self, editor: "EditorWidget") -> str:
        if editor.file_path:
            ext = editor.file_path.suffix.lower()
            if ext in (".tex", ".sty", ".cls", ".ltx"):
                return "latex"
            if ext in (".md", ".markdown"):
                return "markdown"
        # fallback: chiede al lexer
        try:
            lex = editor.lexer()
            if lex:
                name = lex.language().lower()
                if "latex" in name or "tex" in name:
                    return "latex"
                if "markdown" in name or "mark" in name:
                    return "markdown"
        except Exception:
            pass
        return ""

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        if self._editor:
            try:
                self._editor.textChanged.disconnect(self._on_text_changed)
            except Exception:
                pass
        self._editor = editor
        self._load_ref_dir()
        if editor:
            editor.textChanged.connect(self._on_text_changed)
        if self.isVisible():
            self._needs_refresh = False
            self._timer.start()
        else:
            self._needs_refresh = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self._timer.start()

    def _on_text_changed(self) -> None:
        if self.isVisible():
            self._timer.start()
        else:
            self._needs_refresh = True

    def _schedule_refresh(self) -> None:
        if self.isVisible():
            self._timer.start()
        else:
            self._needs_refresh = True

    def _cancel_worker(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            old = self._scan_worker
            self._old_workers.append(old)
            def _cleanup(w=old):
                try:
                    self._old_workers.remove(w)
                except ValueError:
                    pass
            old.finished.connect(_cleanup)
            self._scan_worker = None

    def _refresh(self) -> None:
        editor = self._editor
        if not editor:
            self._model.clear()
            self._info.setText(tr("include_list.no_editor", default="Nessun editor aperto"))
            self.setMaximumHeight(120)
            return

        lang = self._detect_lang(editor)
        if not lang:
            self._model.clear()
            item = QStandardItem(tr("include_list.unsupported",
                                    default="(solo LaTeX e Markdown)"))
            item.setEnabled(False)
            self._model.appendRow(item)
            self._info.setText("")
            # Niente da mostrare per questo tipo di file: non serve occupare
            # metà del dock a destra con un albero vuoto, meglio cedere lo
            # spazio ai pannelli affiancati (es. AI Assistant).
            self.setMaximumHeight(120)
            return

        self._lang = lang
        self.setMaximumHeight(16777215)
        base_dir   = editor.file_path.parent if editor.file_path else None
        text       = editor.get_content() if hasattr(editor, "get_content") else editor.text()

        self._cancel_worker()
        self._scan_gen += 1
        gen    = self._scan_gen
        worker = _ScanWorker(text, lang, base_dir, self._ref_dir, gen)
        worker.done.connect(self._on_scan_done)
        self._scan_worker = worker
        self._old_workers.append(worker)
        def _cleanup(w=worker):
            try:
                self._old_workers.remove(w)
            except ValueError:
                pass
        worker.finished.connect(_cleanup)
        worker.start()

    def _on_scan_done(self, entries: list, not_inc: list, gen: int) -> None:
        if gen != self._scan_gen:
            return
        self._scan_worker = None
        self._entries  = entries
        self._not_inc  = not_inc
        self._rebuild_model()

    # ── Modello ───────────────────────────────────────────────────────────────

    def _rebuild_model(self) -> None:
        self._model.clear()

        entries  = self._entries
        not_inc  = self._not_inc

        if not entries and not not_inc:
            item = QStandardItem(tr("include_list.no_includes",
                                    default="Nessun include trovato"))
            item.setEnabled(False)
            self._model.appendRow(item)
            self._info.setText("")
            return

        # Raggruppa per kind seguendo _GROUP_ORDER
        groups: dict[str, list[IncludeEntry]] = {}
        for e in entries:
            groups.setdefault(e.kind, []).append(e)

        for kind in _GROUP_ORDER:
            if kind not in groups:
                continue
            grp_items = groups.pop(kind)
            label     = _KIND_LABEL.get(kind, kind)
            found_cnt = sum(1 for e in grp_items if e.status == STATUS_FOUND)
            miss_cnt  = sum(1 for e in grp_items if e.status == STATUS_MISSING)
            suffix    = f"  ({len(grp_items)})"
            if miss_cnt:
                suffix += f"  ⚠{miss_cnt}"
            g = QStandardItem(f"{label}{suffix}")
            g.setEditable(False)
            g.setEnabled(True)
            g.setData("group", Qt.ItemDataRole.UserRole)
            font = g.font(); font.setBold(True); g.setFont(font)
            for e in grp_items:
                g.appendRow(self._make_entry_item(e))
            self._model.appendRow(g)

        # Eventuali kind non in _GROUP_ORDER
        for kind, grp_items in groups.items():
            label = _KIND_LABEL.get(kind, kind)
            g = QStandardItem(f"{label}  ({len(grp_items)})")
            g.setEditable(False)
            g.setData("group", Qt.ItemDataRole.UserRole)
            font = g.font(); font.setBold(True); g.setFont(font)
            for e in grp_items:
                g.appendRow(self._make_entry_item(e))
            self._model.appendRow(g)

        # Sezione "non inclusi dalla cartella"
        if not_inc:
            g = QStandardItem(f"━━ {tr('include_list.not_included', default='Non inclusi dalla cartella')}  ({len(not_inc)})")
            g.setEditable(False)
            g.setData("group_orphan", Qt.ItemDataRole.UserRole)
            font = g.font(); font.setBold(True); g.setFont(font)
            g.setForeground(QColor("#f0a040"))
            for p in not_inc:
                it = QStandardItem(f"📄  {p.name}")
                it.setData(str(p), Qt.ItemDataRole.UserRole + 1)   # path completo
                it.setToolTip(str(p))
                it.setEditable(False)
                g.appendRow(it)
            self._model.appendRow(g)

        self._tree.expandAll()
        self._apply_filter(self._filter.text())

        found = sum(1 for e in entries if e.status == STATUS_FOUND)
        miss  = sum(1 for e in entries if e.status == STATUS_MISSING)
        parts = [f"{len(entries)} include"]
        if miss:
            parts.append(f"⚠ {miss} mancanti")
        if not_inc:
            parts.append(f"📄 {len(not_inc)} non usati")
        self._info.setText("  ".join(parts))

    def _make_entry_item(self, e: IncludeEntry) -> QStandardItem:
        icon   = STATUS_ICON[e.status]
        color  = STATUS_COLOR[e.status]
        text   = f"{icon}  {e.arg}  (riga {e.line})"
        item   = QStandardItem(text)
        item.setData(e.line, Qt.ItemDataRole.UserRole)
        item.setData(e.status, Qt.ItemDataRole.UserRole + 2)
        item.setForeground(QColor(color))
        item.setToolTip(self._tooltip_for(e))
        item.setEditable(False)
        return item

    def _tooltip_for(self, e: IncludeEntry) -> str:
        path_text = str(e.resolved) if e.resolved else e.arg
        is_image = (
            e.kind in ("includegraphics", "md_image")
            and e.resolved is not None
            and e.resolved.suffix.lower() in _IMG_PREVIEW_EXTS
        )
        if not is_image:
            return path_text
        url = QUrl.fromLocalFile(str(e.resolved)).toString()
        return (
            f'<img src="{url}" width="320"><br>'
            f'<span>{html.escape(path_text)}</span>'
        )

    # ── Filtro ────────────────────────────────────────────────────────────────

    def _apply_filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self._model.rowCount()):
            grp = self._model.item(i)
            if grp is None:
                continue
            grp_visible = False
            for j in range(grp.rowCount()):
                child = grp.child(j)
                if child is None:
                    continue
                match = not text or text in child.text().lower()
                idx   = self._model.indexFromItem(child)
                self._tree.setRowHidden(idx.row(), idx.parent(), not match)
                if match:
                    grp_visible = True
            grp_idx = self._model.indexFromItem(grp)
            self._tree.setRowHidden(grp_idx.row(), grp_idx.parent(),
                                    not grp_visible and bool(text))

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _on_clicked(self, index) -> None:
        item = self._model.itemFromIndex(index)
        if not item:
            return
        line = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(line, int) and self._editor:
            self._editor.go_to_line(line)
            self._editor.setFocus()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        item = self._model.itemFromIndex(index)
        if not item:
            return
        line  = item.data(Qt.ItemDataRole.UserRole)
        fpath = item.data(Qt.ItemDataRole.UserRole + 1)   # solo per orfani

        menu = QMenu(self)

        # Voce "Vai alla riga" per gli include già nel documento
        if isinstance(line, int) and self._editor:
            menu.addAction(
                tr("include_list.ctx_goto", default="Vai alla riga"),
                lambda: self._editor.go_to_line(line)
            )

        # Voci per i file orfani (presenti in cartella ma non inclusi)
        if fpath:
            p = Path(fpath)
            ext = p.suffix.lower()

            if self._lang == "latex":
                if ext in set(_IMG_EXTS):
                    menu.addAction(
                        tr("include_list.ctx_insert_image",
                           default="Inserisci immagine…"),
                        lambda fp=p: self._insert_latex_image(fp)
                    )
                elif ext in set(_TEX_EXTS):
                    sub = menu.addMenu(tr("include_list.ctx_insert_tex",
                                         default="Inserisci file…"))
                    sub.addAction(
                        r"\include{…}",
                        lambda fp=p: self._insert_latex_tex(fp, "include")
                    )
                    sub.addAction(
                        r"\input{…}",
                        lambda fp=p: self._insert_latex_tex(fp, "input")
                    )
                elif ext in set(_BIB_EXTS):
                    menu.addAction(
                        tr("include_list.ctx_insert_bib",
                           default="Inserisci \\bibliography{…}"),
                        lambda fp=p: self._insert_latex_bib(fp)
                    )
                else:
                    menu.addAction(
                        tr("include_list.ctx_open", default="Apri file"),
                        lambda fp=fpath: self._mw.open_files([fp])
                    )

            elif self._lang == "markdown":
                if ext in set(_IMG_EXTS):
                    menu.addAction(
                        tr("include_list.ctx_insert_image",
                           default="Inserisci immagine"),
                        lambda fp=p: self._insert_md_image(fp)
                    )
                else:
                    menu.addAction(
                        tr("include_list.ctx_insert_link",
                           default="Inserisci link"),
                        lambda fp=p: self._insert_md_link(fp)
                    )
            else:
                menu.addAction(
                    tr("include_list.ctx_open", default="Apri file"),
                    lambda fp=fpath: self._mw.open_files([fp])
                )

        menu.addSeparator()
        menu.addAction(tr("include_list.ctx_refresh", default="Aggiorna"),
                       self._refresh)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ── Inserimento ───────────────────────────────────────────────────────────

    def _rel_path(self, fpath: Path) -> str:
        """Percorso relativo alla dir del documento, o assoluto come fallback."""
        if self._editor and self._editor.file_path:
            try:
                return str(fpath.relative_to(self._editor.file_path.parent))
            except ValueError:
                pass
        return str(fpath)

    def _insert_at_cursor(self, code: str) -> None:
        editor = self._editor
        if not editor or not code:
            return
        if editor.hasSelectedText():
            editor.replaceSelectedText(code)
        else:
            editor.insert(code)
        editor.setFocus()

    def _insert_latex_image(self, fpath: Path) -> None:
        editor = self._editor
        if not editor:
            return
        base_dir = editor.file_path.parent if editor.file_path else None
        rel = self._rel_path(fpath)

        from PyQt6.QtWidgets import QDialog
        from ui.latex_insert_image_dialog import LatexInsertImageDialog
        dlg = LatexInsertImageDialog(parent=self._mw, base_dir=base_dir)
        dlg.set_image_file(rel)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        code = dlg.get_latex_code()
        if not code:
            return
        # Assicura graphicx nel preambolo
        toolbar = getattr(self._mw, "_lang_toolbar", None)
        if toolbar and hasattr(toolbar, "_ensure_latex_package"):
            toolbar._ensure_latex_package(editor, "graphicx")
        self._insert_at_cursor(code)

    def _insert_latex_tex(self, fpath: Path, cmd: str) -> None:
        # Usa lo stem se l'estensione è .tex (LaTeX la cerca da solo)
        arg = self._rel_path(fpath)
        if arg.endswith(".tex"):
            arg = arg[:-4]
        self._insert_at_cursor(f"\\{cmd}{{{arg}}}\n")

    def _insert_latex_bib(self, fpath: Path) -> None:
        arg = fpath.stem   # \bibliography vuole solo il nome senza estensione
        self._insert_at_cursor(f"\\bibliography{{{arg}}}\n")

    def _insert_md_image(self, fpath: Path) -> None:
        rel = self._rel_path(fpath)
        alt = fpath.stem
        self._insert_at_cursor(f"![{alt}]({rel})")

    def _insert_md_link(self, fpath: Path) -> None:
        rel = self._rel_path(fpath)
        self._insert_at_cursor(f"[{fpath.name}]({rel})")


# ─── Installazione ────────────────────────────────────────────────────────────

def install(main_window: "MainWindow") -> _IncludeListPanel:
    panel = _IncludeListPanel(main_window)

    dock = QDockWidget(
        "🔗  " + tr("action.view_include_list", default="Include List"),
        main_window
    )
    dock.setObjectName("IncludeListDock")
    dock.setWidget(panel)
    dock.setMinimumWidth(220)
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
        act = QAction(
            tr("action.view_include_list", default="Include List"),
            main_window
        )
        act.setShortcut(QKeySequence("Ctrl+Shift+I"))
        act.setCheckable(True)
        act.toggled.connect(dock.setVisible)

        def _sync(visible, a=act):
            a.blockSignals(True)
            a.setChecked(visible)
            a.blockSignals(False)
        dock.visibilityChanged.connect(_sync)
        view_menu.addAction(act)
        main_window._actions["view_include_list"] = act

        try:
            from pathlib import Path as _P
            from PyQt6.QtGui import QPalette, QPixmap
            icon_path = _P(__file__).parent.parent / "icons" / "lucide" / "list-checks.svg"
            if icon_path.exists():
                wtext = main_window.palette().color(QPalette.ColorRole.WindowText).name()
                svg = icon_path.read_bytes().replace(b"currentColor", wtext.encode())
                pm = QPixmap()
                if pm.loadFromData(svg, "SVG") and not pm.isNull():
                    act.setIcon(QIcon(pm))
        except Exception:
            pass

    main_window._include_list_dock  = dock
    main_window._include_list_panel = panel

    current = main_window._tab_manager.current_editor()
    panel._on_editor_changed(current)

    return panel
