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
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget
    from ui.main_window import MainWindow

_ACTIVE_REPO_WORKERS: set = set()


class _GitRepoCheckWorker(QThread):
    """Verifica se una directory è in un repository git senza bloccare la GUI."""

    done = pyqtSignal(str, bool)

    def __init__(self, directory):
        super().__init__(None)
        self._directory = directory
        _ACTIVE_REPO_WORKERS.add(self)
        self.finished.connect(
            lambda w=self: _ACTIVE_REPO_WORKERS.discard(w)
        )

    def run(self) -> None:
        self.done.emit(str(self._directory), _is_git_repo(self._directory))


class _GitDiffWorker(QThread):
    """Esegue 'git diff HEAD' in un thread separato per non bloccare la UI."""

    done = pyqtSignal(object, object, object)   # (added, modified, deleted) set[int]

    def __init__(self, file_path):
        super().__init__(None)
        self._file_path  = file_path
        self._cancelled  = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        diff = _run_git_diff(self._file_path)
        if self._cancelled or diff is None:
            return
        if not diff.strip():
            self.done.emit(set(), set(), set())
        else:
            added, modified, deleted = _parse_diff(diff)
            if not self._cancelled:
                self.done.emit(added, modified, deleted)


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


_REPO_CACHE: dict[str, bool] = {}


def _is_git_repo(directory) -> bool:
    """True se `directory` è dentro un repository git (esito memoizzato).

    Evita di avviare un thread e un subprocess `git` a ogni pausa di
    digitazione per file che non sono in un repository.
    """
    key = str(directory)
    cached = _REPO_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            cwd=key,
            timeout=3,
        )
        inside = result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        inside = False
    _REPO_CACHE[key] = inside
    return inside


def _run_git_diff(file_path) -> str | None:
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

    def __init__(self, main_window: MainWindow):
        super().__init__(main_window)
        self._mw = main_window
        self._active_editor: EditorWidget | None = None
        self._worker: _GitDiffWorker | None = None
        self._old_workers: list = []
        self._repo_worker: _GitRepoCheckWorker | None = None

        from config.settings import Settings
        self._enabled = Settings.instance().get("editor/git_gutter", True)

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

    def set_enabled(self, enabled: bool) -> None:
        """Attiva o disattiva il Git Gutter a caldo."""
        self._enabled = enabled
        if not enabled:
            self._timer.stop()
            self._cancel_worker()
            for ed in self._mw._tab_manager.all_editors():
                if hasattr(ed, "update_git_gutter"):
                    ed.update_git_gutter(set(), set(), set())
        else:
            self._refresh()

    def _on_editor_changed(self, editor: EditorWidget | None) -> None:
        if self._active_editor:
            try:
                self._active_editor.textChanged.disconnect(self._schedule)
            except Exception:
                pass
        self._cancel_worker()
        self._active_editor = editor
        if editor:
            editor.textChanged.connect(self._schedule)
            self._refresh()

    def _schedule(self) -> None:
        if self._enabled:
            self._timer.start()

    def _cancel_worker(self) -> None:
        # Elimina worker precedenti non più in esecuzione
        self._old_workers[:] = [
            w for w in self._old_workers if w.isRunning()
        ]
        if self._worker is not None:
            self._worker.cancel()
            self._old_workers.append(self._worker)
            self._worker = None

    def _refresh(self) -> None:
        if not self._enabled:
            return
        editor = self._active_editor
        if not editor or not editor.file_path:
            return

        parent = editor.file_path.parent
        cached = _REPO_CACHE.get(str(parent))
        if cached is False:
            # Fuori da un repository git: nessun diff da mostrare, nessun
            # thread/subprocess da avviare a ogni modifica.
            self._cancel_worker()
            try:
                editor.update_git_gutter(set(), set(), set())
            except Exception:
                pass
            return
        if cached is None:
            # Primo controllo: non lanciare `git` sul thread GUI. Il diff
            # partirà quando il worker avrà popolato la cache.
            self._cancel_worker()
            if self._repo_worker is None or not self._repo_worker.isRunning():
                self._repo_worker = _GitRepoCheckWorker(parent)
                self._repo_worker.done.connect(self._on_repo_checked)
                self._repo_worker.finished.connect(
                    self._repo_worker.deleteLater)
                self._repo_worker.finished.connect(
                    lambda: setattr(self, "_repo_worker", None))
                self._repo_worker.start()
            return

        self._cancel_worker()
        worker = _GitDiffWorker(editor.file_path)
        worker.done.connect(lambda a, m, d, ed=editor: self._on_diff_done(a, m, d, ed))
        self._worker = worker
        self._old_workers.append(worker)
        worker.start()

    def _on_repo_checked(self, directory: str, inside: bool) -> None:
        self._repo_worker = None
        editor = self._active_editor
        if not editor or not editor.file_path:
            return
        try:
            if str(editor.file_path.parent) != directory:
                return
        except Exception:
            return
        if inside:
            self._refresh()
        else:
            try:
                editor.update_git_gutter(set(), set(), set())
            except Exception:
                pass

    def _on_diff_done(self, added: set, modified: set, deleted: set,
                      editor: EditorWidget) -> None:
        if editor is not self._active_editor:
            return
        self._worker = None
        try:
            editor.update_git_gutter(added, modified, deleted)
        except Exception:
            pass
