"""
ui/git_blame_inline.py — Git Blame Inline
NotePadPQ

Mostra autore e messaggio del commit per la riga del cursore
come QScintilla annotation (testo in un box sotto la riga).
Usa `git blame -L N,N --porcelain` — veloce anche su repo grandi.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QTimer, QThread, pyqtSignal

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


class _BlameWorker(QThread):
    """Esegue 'git blame' in un thread separato per non bloccare la UI."""

    done = pyqtSignal(str)   # testo formattato (vuoto se non disponibile)

    def __init__(self, path: Path, lineno: int):
        super().__init__(None)
        self._path    = path
        self._lineno  = lineno
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        text = GitBlameManager._run_blame(self._path, self._lineno)
        if not self._cancelled:
            self.done.emit(text)


class GitBlameManager:

    def __init__(self, main_window: "MainWindow"):
        self._mw = main_window
        self._editor: Optional["EditorWidget"] = None
        self._enabled = False
        self._cache: dict[tuple, str] = {}
        self._last_line = -1

        self._blame_worker: Optional[_BlameWorker] = None
        self._old_blame_workers: list = []

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._update)

        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )

    # ── Abilitazione ─────────────────────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._cancel_blame_worker()
            self._clear()
        elif self._editor:
            self._timer.start()

    # ── Gestione editor ──────────────────────────────────────────────────────

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        if self._editor:
            try:
                self._editor.cursor_changed.disconnect(self._on_cursor)
                self._editor.textChanged.disconnect(self._on_text_changed)
            except (RuntimeError, TypeError):
                pass
        self._cancel_blame_worker()
        self._clear()
        self._editor = editor
        self._last_line = -1
        if editor and self._enabled:
            editor.cursor_changed.connect(self._on_cursor)
            editor.textChanged.connect(self._on_text_changed)

    def _on_cursor(self, _line: int, _col: int) -> None:
        if self._enabled:
            self._timer.start()

    def _on_text_changed(self) -> None:
        if self._editor and self._editor.file_path:
            p = str(self._editor.file_path)
            self._cache = {k: v for k, v in self._cache.items() if k[0] != p}

    # ── Aggiornamento blame ───────────────────────────────────────────────────

    def _cancel_blame_worker(self) -> None:
        if self._blame_worker is not None:
            self._blame_worker.cancel()
            old = self._blame_worker
            self._old_blame_workers.append(old)
            def _cleanup(w=old):
                try:
                    self._old_blame_workers.remove(w)
                except ValueError:
                    pass
            old.finished.connect(_cleanup)
            self._blame_worker = None

    def _update(self) -> None:
        if not self._enabled or not self._editor:
            return
        editor = self._editor
        path = getattr(editor, "file_path", None)
        if not path or not path.exists():
            return

        line0, _ = editor.getCursorPosition()
        line1 = line0 + 1

        if line1 == self._last_line:
            return
        self._clear()
        self._last_line = line1

        key = (str(path), line1)
        text = self._cache.get(key)
        if text is not None:
            if text:
                self._annotate(editor, line0, text)
            return

        # Non in cache: avvia worker asincrono
        self._cancel_blame_worker()
        worker = _BlameWorker(path, line1)
        worker.done.connect(
            lambda txt, k=key, ln0=line0, ln1=line1, ed=editor:
                self._on_blame_done(txt, k, ln0, ln1, ed)
        )
        self._blame_worker = worker
        self._old_blame_workers.append(worker)
        def _cleanup(w=worker):
            try:
                self._old_blame_workers.remove(w)
            except ValueError:
                pass
        worker.finished.connect(_cleanup)
        worker.start()

    def _on_blame_done(self, text: str, key: tuple, line0: int,
                       line1: int, editor: "EditorWidget") -> None:
        self._cache[key] = text
        self._blame_worker = None
        if editor is not self._editor:
            return
        if line1 != self._last_line:
            return
        if text:
            try:
                self._annotate(editor, line0, text)
            except Exception:
                pass

    # ── Annotation ───────────────────────────────────────────────────────────

    def _clear(self) -> None:
        if not self._editor:
            return
        try:
            self._editor.clearAnnotations(-1)
        except AttributeError:
            try:
                self._editor.SendScintilla(2547)  # SCI_ANNOTATIONCLEARALL
            except Exception:
                pass

    def _annotate(self, editor: "EditorWidget", line0: int, text: str) -> None:
        try:
            from PyQt6.Qsci import QsciScintilla
            editor.setAnnotationDisplay(
                QsciScintilla.AnnotationDisplay.AnnotationBoxed
            )
            editor.annotate(line0, f"  {text}  ", 0)
        except Exception:
            pass

    # ── Git blame ─────────────────────────────────────────────────────────────

    @staticmethod
    def _run_blame(path: Path, lineno: int) -> str:
        try:
            res = subprocess.run(
                ["git", "blame", "-L", f"{lineno},{lineno}",
                 "--porcelain", "--", path.name],
                cwd=str(path.parent),
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=5,
            )
            if res.returncode != 0:
                return ""
            return GitBlameManager._parse(res.stdout)
        except Exception:
            return ""

    @staticmethod
    def _parse(output: str) -> str:
        author = ""
        summary = ""
        ts = 0
        for line in output.splitlines():
            if line.startswith("author ") and not line.startswith("author-"):
                author = line[7:].strip()
            elif line.startswith("summary "):
                summary = line[8:].strip()
            elif line.startswith("author-time "):
                try:
                    ts = int(line[12:])
                except ValueError:
                    pass

        if not author or "Not Committed Yet" in author:
            return ""

        age = GitBlameManager._age(ts)
        out = author
        if age:
            out += f", {age}"
        if summary:
            out += f" • {summary[:70]}"
        return out

    @staticmethod
    def _age(ts: int) -> str:
        if not ts:
            return ""
        try:
            delta = datetime.now(timezone.utc) - datetime.fromtimestamp(ts, timezone.utc)
            d = delta.days
            if d > 365:  return f"{d // 365} anni fa"
            if d > 30:   return f"{d // 30} mesi fa"
            if d > 1:    return f"{d} giorni fa"
            if d == 1:   return "ieri"
            s = delta.seconds
            if s > 3600: return f"{s // 3600} ore fa"
            if s > 60:   return f"{s // 60} min fa"
            return "adesso"
        except Exception:
            return ""


def install(main_window: "MainWindow") -> GitBlameManager:
    from config.settings import Settings
    mgr = GitBlameManager(main_window)
    mgr.set_enabled(Settings.instance().get("editor/git_blame_inline", False))
    main_window._git_blame_mgr = mgr
    return mgr
