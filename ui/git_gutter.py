"""
ui/git_gutter.py — Git Gutter
NotePadPQ

Mostra nel margine dell'editor le righe aggiunte/modificate/rimosse
rispetto all'HEAD di git, stile VS Code / Atom:
  verde  → riga aggiunta
  arancio → riga modificata
  rosso  → riga rimossa

Uso:
    from ui.git_gutter import GitGutter
    gutter = GitGutter(main_window)
    # si aggancia automaticamente a tutti gli editor tramite tab_manager
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QTimer, QObject

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


def _parse_diff(diff_output: str) -> tuple[set[int], set[int], set[int]]:
    """
    Analizza l'output di 'git diff HEAD' (formato unified) e restituisce
    tre set di indici riga 0-based: (aggiunte, modificate, rimosse).
    """
    added: set[int] = set()
    modified: set[int] = set()
    deleted: set[int] = set()

    current_new = 0
    pending_del: list[int] = []

    for line in diff_output.splitlines():
        if line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                current_new = int(m.group(1)) - 1  # 0-based
            pending_del = []
        elif line.startswith("+++") or line.startswith("---"):
            continue
        elif line.startswith("+"):
            if pending_del:
                modified.add(current_new)
                pending_del.pop()
            else:
                added.add(current_new)
            current_new += 1
        elif line.startswith("-"):
            pending_del.append(current_new)
        else:
            # riga di contesto: svuota le cancellazioni pendenti
            if pending_del:
                for dl in pending_del:
                    deleted.add(dl)
                pending_del = []
            current_new += 1

    for dl in pending_del:
        deleted.add(dl)

    return added, modified, deleted


def _run_git_diff(file_path) -> Optional[str]:
    """Esegue 'git diff HEAD -- <file>' e restituisce l'output o None."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", str(file_path)],
            capture_output=True,
            text=True,
            cwd=str(file_path.parent),
            timeout=3,
        )
        if result.returncode not in (0, 1):
            return None
        return result.stdout
    except Exception:
        return None


class GitGutter(QObject):
    """
    Aggiorna il git gutter di tutti gli editor aperti.
    Si aggancia al tab_manager e ascolta i cambiamenti di testo
    con un debounce di 800ms per non eseguire 'git diff' ad ogni tasto.
    """

    DELAY_MS = 800

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._active_editor: Optional["EditorWidget"] = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS)
        self._timer.timeout.connect(self._refresh)

        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )
        ed = main_window._tab_manager.current_editor()
        if ed:
            self._on_editor_changed(ed)

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        if self._active_editor:
            try:
                self._active_editor.textChanged.disconnect(self._schedule)
            except Exception:
                pass
        self._active_editor = editor
        if editor:
            editor.textChanged.connect(self._schedule)
            self._refresh()

    def _schedule(self) -> None:
        self._timer.start()

    def _refresh(self) -> None:
        editor = self._active_editor
        if not editor or not editor.file_path:
            return
        diff = _run_git_diff(editor.file_path)
        if diff is None:
            return
        if not diff.strip():
            editor.update_git_gutter(set(), set(), set())
        else:
            added, modified, deleted = _parse_diff(diff)
            editor.update_git_gutter(added, modified, deleted)
