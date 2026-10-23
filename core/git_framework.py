"""
core/git_framework.py — Backend Git unificato con operazioni asincrone via QThread.
Condiviso da git_plugin, git_gutter, e git_blame_inline per evitare duplicazione.
NotePadPQ
"""
from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot


class _GitThread(QThread):
    """QThread che esegue un comando git e restituisce il risultato via segnale."""

    result_ready = pyqtSignal(int, str, str)

    def __init__(self, repo_dir: Path, args: list[str], timeout: int = 30):
        super().__init__()
        self._repo_dir = repo_dir
        self._args = args
        self._timeout = timeout
        self._cancelled = False
        self._process = None
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        """Terminate a running command and suppress a result callback."""
        with self._lock:
            self._cancelled = True
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self) -> None:
        if self.cancelled:
            return
        process = None
        try:
            process = subprocess.Popen(
                ["git"] + self._args,
                cwd=str(self._repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            with self._lock:
                self._process = process
                cancelled = self._cancelled
            if cancelled:
                process.terminate()
            out, err = process.communicate(timeout=self._timeout)
            if self.cancelled:
                return
            # Do not strip: porcelain status uses significant leading spaces
            # for the index/worktree columns, and diff context lines start
            # with a space too.
            self.result_ready.emit(process.returncode, out, err)
        except FileNotFoundError:
            if not self.cancelled:
                self.result_ready.emit(-1, "", "git not found in PATH")
        except subprocess.TimeoutExpired:
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
                process.communicate()
            if not self.cancelled:
                self.result_ready.emit(-1, "", "Timeout")
        except Exception as e:
            if not self.cancelled:
                self.result_ready.emit(-1, "", str(e))
        finally:
            with self._lock:
                self._process = None


class _GitResultHandler(QObject):
    """Delivers worker results in the thread that owns the GitFramework."""

    def __init__(self, framework, thread: _GitThread,
                 callback: Callable[[int, str, str], None]):
        super().__init__()
        self._framework = framework
        self._thread = thread
        self._callback = callback

    @pyqtSlot(int, str, str)
    def deliver(self, rc: int, out: str, err: str) -> None:
        if not self._thread.cancelled:
            self._callback(rc, out, err)

    @pyqtSlot()
    def cleanup(self) -> None:
        self._framework._workers.discard(self._thread)
        self._framework._handlers.pop(self._thread, None)
        self._thread.deleteLater()
        self.deleteLater()


class GitFramework:
    """Backend git unificato con operazioni su QThread.

    Uso:
        gf = GitFramework(Path("/progetto"))
        gf.status_async(callback)
        files = gf.status()  # sincrono per chiamanti non-UI
    """

    _TIMEOUT_SHORT = 5
    _TIMEOUT_LONG = 120

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir
        # Keep QThreads and their queued-result receivers alive until finished.
        self._workers: set[_GitThread] = set()
        self._handlers: dict[_GitThread, _GitResultHandler] = {}

    def _run_async(self, args: list[str], callback: Callable[[int, str, str], None],
                   timeout: int = 30) -> _GitThread:
        t = _GitThread(self.repo_dir, args, timeout)
        handler = _GitResultHandler(self, t, callback)
        self._workers.add(t)
        self._handlers[t] = handler
        t.result_ready.connect(handler.deliver)
        t.finished.connect(handler.cleanup)
        t.start()
        return t

    def cancel_all(self) -> None:
        """Cancel outstanding asynchronous commands and suppress their callbacks."""
        for worker in tuple(self._workers):
            worker.cancel()

    def _run_sync(self, args: list[str], timeout: int = 30,
                  strip_output: bool = True) -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            if strip_output:
                return result.returncode, result.stdout.strip(), result.stderr.strip()
            return result.returncode, result.stdout, result.stderr
        except FileNotFoundError:
            return -1, "", "git not found in PATH"
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except Exception as e:
            return -1, "", str(e)

    # ── Query sincrone (per chiamanti non-UI) ─────────────────────────────────

    def is_repo(self) -> bool:
        rc, _, _ = self._run_sync(["rev-parse", "--is-inside-work-tree"], self._TIMEOUT_SHORT)
        return rc == 0

    def current_branch(self) -> str:
        rc, out, _ = self._run_sync(["branch", "--show-current"], self._TIMEOUT_SHORT)
        return out if rc == 0 else "?"

    def status(self) -> list[tuple[str, str]]:
        rc, out, _ = self._run_sync(
            ["status", "--porcelain"], self._TIMEOUT_SHORT, strip_output=False)
        return self._parse_status(out) if rc == 0 else []

    @staticmethod
    def _parse_status(out: str) -> list[tuple[str, str]]:
        result = []
        for line in out.splitlines():
            if len(line) >= 3:
                xy = line[:2].strip()
                path = line[3:].strip()
                result.append((xy, path))
        return result

    def status_async(self, callback: Callable[[list[tuple[str, str]]], None]) -> _GitThread:
        """Fetch repository status without blocking the UI thread."""
        def _cb(rc, out, _err):
            callback(self._parse_status(out) if rc == 0 else [])
        return self._run_async(["status", "--porcelain"], _cb, self._TIMEOUT_SHORT)

    @staticmethod
    def _parse_status_detailed(out: str) -> list[tuple[str, str, str]]:
        """Parse porcelain output as ``(index_status, worktree_status, path)``.

        Unlike :meth:`_parse_status`, this keeps the two status columns apart so
        the UI can tell whether a file is already staged.
        """
        result = []
        for line in out.splitlines():
            if len(line) < 3:
                continue
            index_status, worktree_status = line[0], line[1]
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path:
                result.append((index_status, worktree_status, path))
        return result

    def status_detailed_async(
        self, callback: Callable[[list[tuple[str, str, str]]], None]
    ) -> _GitThread:
        """Fetch status preserving the staged/worktree distinction."""
        def _cb(rc, out, _err):
            callback(self._parse_status_detailed(out) if rc == 0 else [])
        return self._run_async(["status", "--porcelain"], _cb, self._TIMEOUT_SHORT)

    def log(self, n: int = 50) -> list[dict]:
        fmt = "%H\x1f%h\x1f%an\x1f%ae\x1f%ai\x1f%s"
        rc, out, _ = self._run_sync(
            ["log", f"-{n}", f"--pretty=format:{fmt}"], self._TIMEOUT_SHORT)
        return self._parse_log(out) if rc == 0 else []

    @staticmethod
    def _parse_log(out: str) -> list[dict]:
        commits = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) >= 6:
                commits.append({
                    "hash": parts[0], "short": parts[1],
                    "author": parts[2], "email": parts[3],
                    "date": parts[4][:16], "subject": parts[5],
                })
        return commits

    def log_async(self, n: int, callback: Callable[[list[dict]], None]) -> _GitThread:
        """Fetch commit history without blocking the UI thread."""
        fmt = "%H\x1f%h\x1f%an\x1f%ae\x1f%ai\x1f%s"

        def _cb(rc, out, _err):
            callback(self._parse_log(out) if rc == 0 else [])
        return self._run_async(
            ["log", f"-{n}", f"--pretty=format:{fmt}"], _cb, self._TIMEOUT_SHORT)

    def branches(self) -> list[str]:
        rc, out, _ = self._run_sync(
            ["branch", "-a", "--format=%(refname:short)"], self._TIMEOUT_SHORT)
        return out.splitlines() if rc == 0 else []

    def remotes(self) -> dict:
        rc, out, _ = self._run_sync(["remote", "-v"], self._TIMEOUT_SHORT)
        result = {}
        if rc == 0:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and "(fetch)" in line:
                    result[parts[0]] = parts[1]
        return result

    def diff(self, path: str | None = None, staged: bool = False) -> str:
        args = self._diff_args(path, staged)
        rc, out, _ = self._run_sync(
            args, self._TIMEOUT_SHORT, strip_output=False)
        return out if rc == 0 else ""

    def changed_files_vs_remote(self) -> list[str]:
        """Files that differ from the upstream branch (or from HEAD).

        ``@{upstream}`` uses the local remote-tracking ref, so no network
        access is needed.  When the branch has no upstream, the fallback to
        ``HEAD`` still returns tracked modifications only: untracked files
        are deliberately not included.
        """
        rc, out, _ = self._run_sync(
            ["diff", "--name-only", "@{upstream}"], self._TIMEOUT_SHORT)
        if rc != 0:
            rc, out, _ = self._run_sync(
                ["diff", "--name-only", "HEAD"], self._TIMEOUT_SHORT)
        if rc != 0:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    @staticmethod
    def _diff_args(path: str | None, staged: bool) -> list[str]:
        args = ["diff"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
        return args

    def diff_async(self, path: str | None, staged: bool,
                   callback: Callable[[str], None]) -> _GitThread:
        """Fetch a file or repository diff without blocking the UI thread."""
        def _cb(rc, out, _err):
            callback(out if rc == 0 else "")
        return self._run_async(self._diff_args(path, staged), _cb, self._TIMEOUT_SHORT)

    def diff_file_lines(self, file_path: str) -> dict:
        rc, out, _ = self._run_sync(
            ["diff", "--unified=0", "--", file_path], self._TIMEOUT_SHORT)
        return self._parse_diff_file_lines(out) if rc == 0 else {}

    @staticmethod
    def _parse_diff_file_lines(out: str) -> dict:
        result = {}
        current_line = 0
        for line in out.splitlines():
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                current_line = int(m.group(1))
                continue
            if line.startswith("+") and not line.startswith("+++"):
                result[current_line] = "A"
                current_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                result[current_line] = "D"
            else:
                current_line += 1
        return result

    def diff_file_lines_async(self, file_path: str,
                              callback: Callable[[dict], None]) -> _GitThread:
        """Fetch gutter markers without blocking editor interaction."""
        def _cb(rc, out, _err):
            callback(self._parse_diff_file_lines(out) if rc == 0 else {})
        return self._run_async(
            ["diff", "--unified=0", "--", file_path], _cb, self._TIMEOUT_SHORT)

    def show_async(self, sha: str, callback: Callable[[str], None]) -> _GitThread:
        """Fetch commit details without blocking the log view."""
        def _cb(rc, out, _err):
            callback(out if rc == 0 else "")
        return self._run_async(["show", "--stat", sha], _cb, self._TIMEOUT_SHORT)

    def stash_list(self) -> list[str]:
        rc, out, _ = self._run_sync(
            ["stash", "list", "--pretty=format:%h %ai %s"], self._TIMEOUT_SHORT)
        return out.splitlines() if rc == 0 else []

    def get_config(self, key: str, global_: bool = False) -> str:
        args = ["config"]
        if global_:
            args.append("--global")
        args.append(key)
        rc, out, _ = self._run_sync(args, self._TIMEOUT_SHORT)
        return out if rc == 0 else ""

    def set_config(self, key: str, value: str, global_: bool = False) -> bool:
        args = ["config"]
        if global_:
            args.append("--global")
        args += [key, value]
        rc, _, _ = self._run_sync(args, self._TIMEOUT_SHORT)
        return rc == 0

    # ── Operazioni potenzialmente lunghe (asincrone) ──────────────────────────

    def pull_async(self, remote: str = "origin",
                   callback: Callable[[bool, str], None] = None):
        def _cb(rc, out, err):
            ok = rc == 0
            msg = (out or err).strip()
            if callback:
                callback(ok, msg)
        self._run_async(["pull", remote], _cb, self._TIMEOUT_LONG)

    def push_async(self, remote: str = "origin", branch: str = "",
                   callback: Callable[[bool, str], None] = None):
        args = ["push", remote]
        if branch:
            args.append(branch)
        def _cb(rc, out, err):
            ok = rc == 0
            msg = (out or err).strip()
            if callback:
                callback(ok, msg)
        self._run_async(args, _cb, self._TIMEOUT_LONG)

    def stage_files(self, files: list[str]) -> bool:
        """Stage solo i file specificati (NON tutto con `git add .`)."""
        if not files:
            return True
        rc, _, _ = self._run_sync(["add"] + files, self._TIMEOUT_SHORT)
        return rc == 0

    def stage_all(self) -> bool:
        """Stage every change, including deletions and untracked files."""
        rc, _, _ = self._run_sync(["add", "-A"], self._TIMEOUT_SHORT)
        return rc == 0

    def unstage_all(self) -> bool:
        """Move every staged change back to the worktree."""
        rc, _, _ = self._run_sync(["reset"], self._TIMEOUT_SHORT)
        return rc == 0

    def unstage_file(self, path: str) -> bool:
        rc, _, _ = self._run_sync(["reset", "HEAD", "--", path], self._TIMEOUT_SHORT)
        return rc == 0

    def discard_file(self, path: str) -> bool:
        rc, _, _ = self._run_sync(["checkout", "--", path], self._TIMEOUT_SHORT)
        return rc == 0

    def commit_async(self, message: str, files: list[str] | None = None,
                     callback: Callable[[bool, str], None] = None):
        """Commit. Se files è specificato, committa solo quelli.

        Usa un pathspec esplicito: eventuali altri file già in stage non
        finiscono nel commit quando l'utente li ha deselezionati.
        """
        args = ["commit", "-m", message]
        if files:
            if not self.stage_files(list(files)):
                if callback:
                    callback(False, "Stage fallito")
                return
            args += ["--"] + list(files)
        def _cb(rc, out, err):
            ok = rc == 0
            msg = (out or err).strip()
            if callback:
                callback(ok, msg)
        self._run_async(args, _cb, self._TIMEOUT_SHORT)

    def stash_push_async(self, message: str = "",
                         callback: Callable[[bool, str], None] = None):
        args = ["stash", "push"]
        if message:
            args += ["-m", message]
        def _cb(rc, out, err):
            ok = rc == 0
            msg = (out or err).strip()
            if callback:
                callback(ok, msg)
        self._run_async(args, _cb, self._TIMEOUT_SHORT)

    def stash_pop_async(self, index: int = 0,
                        callback: Callable[[bool, str], None] = None):
        args = ["stash", "pop"]
        if index > 0:
            args = ["stash", "pop", f"stash@{{{index}}}"]
        def _cb(rc, out, err):
            ok = rc == 0
            msg = (out or err).strip()
            if callback:
                callback(ok, msg)
        self._run_async(args, _cb, self._TIMEOUT_SHORT)

    def checkout_async(self, branch: str, create: bool = False,
                       callback: Callable[[bool, str], None] = None):
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        def _cb(rc, out, err):
            ok = rc == 0
            msg = (out or err).strip()
            if callback:
                callback(ok, msg)
        self._run_async(args, _cb, self._TIMEOUT_SHORT)

    def fetch_async(self, remote: str = "origin",
                    callback: Callable[[bool, str], None] = None):
        def _cb(rc, out, err):
            ok = rc == 0
            msg = (out or err).strip()
            if callback:
                callback(ok, msg)
        self._run_async(["fetch", remote], _cb, self._TIMEOUT_LONG)
