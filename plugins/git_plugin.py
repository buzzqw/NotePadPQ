"""
plugins/git_plugin.py — Plugin integrazione Git / GitHub / GitLab
NotePadPQ

Funzionalità:
  - Pannello dock "Git" con status, log, diff, branch corrente
  - Azioni rapide: commit, push, pull, checkout, stash
  - Decoratori di riga nell'editor (aggiunto/modificato/eliminato)
  - Apertura URL su GitHub/GitLab per il file corrente
  - Supporto remote: GitHub e GitLab (apertura PR, blame, raw)

Dipendenze:
  - git (CLI, deve essere nel PATH)
  - Nessuna libreria Python aggiuntiva richiesta
    (usa subprocess per chiamare git)

Opzionale:
  - PyGithub   → pip install PyGithub   (azioni GitHub API)
  - python-gitlab → pip install python-gitlab (azioni GitLab API)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QPushButton, QLabel,
    QLineEdit, QComboBox, QSplitter, QMenu, QInputDialog,
    QMessageBox, QApplication, QCheckBox, QListWidget, QListWidgetItem,
    QFormLayout, QGroupBox, QDialog, QDialogButtonBox, QPlainTextEdit,
)
from PyQt6.QtGui import QColor, QFont

from plugins.base_plugin import BasePlugin

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


# ─── Helper Git CLI ───────────────────────────────────────────────────────────

class GitRunner:
    """Esegue comandi git in una directory specifica."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir

    def run(self, *args, check=False) -> Tuple[int, str, str]:
        """Esegue git con gli argomenti dati. Restituisce (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            return -1, "", "git non trovato nel PATH"
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout comando git"
        except Exception as e:
            return -1, "", str(e)

    def is_repo(self) -> bool:
        rc, _, _ = self.run("rev-parse", "--is-inside-work-tree")
        return rc == 0

    def current_branch(self) -> str:
        rc, out, _ = self.run("branch", "--show-current")
        return out if rc == 0 else "?"

    def status(self) -> List[Tuple[str, str]]:
        """Restituisce [(status_code, filepath), ...]"""
        rc, out, _ = self.run("status", "--porcelain")
        if rc != 0 or not out:
            return []
        result = []
        for line in out.splitlines():
            if len(line) >= 3:
                xy   = line[:2].strip()
                path = line[3:].strip()
                result.append((xy, path))
        return result

    def log(self, n: int = 50) -> List[dict]:
        """Restituisce gli ultimi N commit come lista di dict."""
        fmt = "%H%x1f%h%x1f%an%x1f%ae%x1f%ai%x1f%s"
        rc, out, _ = self.run("log", f"-{n}", f"--pretty=format:{fmt}")
        if rc != 0 or not out:
            return []
        commits = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) >= 6:
                commits.append({
                    "hash":    parts[0],
                    "short":   parts[1],
                    "author":  parts[2],
                    "email":   parts[3],
                    "date":    parts[4][:16],
                    "subject": parts[5],
                })
        return commits

    def diff(self, path: Optional[str] = None, staged: bool = False) -> str:
        args = ["diff"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
        rc, out, _ = self.run(*args)
        return out if rc == 0 else ""

    def diff_file_lines(self, path: str) -> dict:
        """
        Restituisce un dict {line_number: 'A'|'M'|'D'} per decorare l'editor.
        """
        result = {}
        rc, out, _ = self.run("diff", "--unified=0", "--", path)
        if rc != 0 or not out:
            return result
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

    def branches(self) -> List[str]:
        rc, out, _ = self.run("branch", "-a", "--format=%(refname:short)")
        return out.splitlines() if rc == 0 else []

    def remotes(self) -> dict:
        rc, out, _ = self.run("remote", "-v")
        result = {}
        if rc == 0:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and "(fetch)" in line:
                    result[parts[0]] = parts[1]
        return result

    def add(self, path: str = ".") -> bool:
        rc, _, err = self.run("add", path)
        return rc == 0

    def commit(self, message: str) -> Tuple[bool, str]:
        rc, out, err = self.run("commit", "-m", message)
        return rc == 0, out or err

    def push(self, remote="origin", branch="") -> Tuple[bool, str]:
        args = ["push", remote]
        if branch:
            args.append(branch)
        rc, out, err = self.run(*args)
        return rc == 0, out or err

    def pull(self, remote="origin") -> Tuple[bool, str]:
        rc, out, err = self.run("pull", remote)
        return rc == 0, out or err

    def stash(self, message="") -> bool:
        args = ["stash", "push"]
        if message:
            args += ["-m", message]
        rc, _, _ = self.run(*args)
        return rc == 0

    def stash_pop(self) -> bool:
        rc, _, _ = self.run("stash", "pop")
        return rc == 0

    def checkout(self, branch: str, create=False) -> Tuple[bool, str]:
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        rc, out, err = self.run(*args)
        return rc == 0, out or err

    def get_config(self, key: str, global_: bool = False) -> str:
        args = ["config"]
        if global_:
            args.append("--global")
        args.append(key)
        rc, out, _ = self.run(*args)
        return out if rc == 0 else ""

    def set_config(self, key: str, value: str, global_: bool = False) -> bool:
        args = ["config"]
        if global_:
            args.append("--global")
        args += [key, value]
        rc, _, _ = self.run(*args)
        return rc == 0


# ─── Token storage ───────────────────────────────────────────────────────────────

def _save_token(service: str, token: str) -> None:
    try:
        import keyring
        keyring.set_password("notepadpq_git", service, token)
        return
    except Exception:
        pass
    cfg = Path.home() / ".config" / "notepadpq" / "git_tokens.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
        except Exception:
            pass
    data[service] = token
    cfg.write_text(json.dumps(data, indent=2))


def _load_token(service: str) -> str:
    try:
        import keyring
        t = keyring.get_password("notepadpq_git", service)
        if t:
            return t
    except Exception:
        pass
    cfg = Path.home() / ".config" / "notepadpq" / "git_tokens.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
            return data.get(service, "")
        except Exception:
            pass
    return ""


# ─── Dialog credenziali ───────────────────────────────────────────────────────────

class _CredentialsDialog(QDialog):
    def __init__(self, git=None, parent=None):
        super().__init__(parent)
        self._git = git
        self.setWindowTitle("Git — Utente & Token")
        self.setMinimumWidth(500)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        grp_id = QGroupBox("Identità Git")
        fl = QFormLayout(grp_id)
        self._name_local   = QLineEdit()
        self._email_local  = QLineEdit()
        self._name_global  = QLineEdit()
        self._email_global = QLineEdit()
        fl.addRow("Nome (repo corrente):",  self._name_local)
        fl.addRow("Email (repo corrente):", self._email_local)
        fl.addRow("Nome (globale):",        self._name_global)
        fl.addRow("Email (globale):",       self._email_global)
        layout.addWidget(grp_id)

        grp_gh = QGroupBox("GitHub — Personal Access Token")
        gl = QFormLayout(grp_gh)
        self._gh_token = QLineEdit()
        self._gh_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._gh_token.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxxxxx")
        btn_gh = QPushButton("👁"); btn_gh.setFixedWidth(32); btn_gh.setCheckable(True)
        btn_gh.toggled.connect(lambda v: self._gh_token.setEchoMode(
            QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        r1 = QHBoxLayout(); r1.addWidget(self._gh_token); r1.addWidget(btn_gh)
        gl.addRow("Token:", r1)
        gl.addRow(QLabel("<small>github.com/settings/tokens → scope: repo, workflow</small>"))
        layout.addWidget(grp_gh)

        grp_gl = QGroupBox("GitLab — Personal Access Token")
        gll = QFormLayout(grp_gl)
        self._gl_url   = QLineEdit(); self._gl_url.setPlaceholderText("https://gitlab.com")
        self._gl_token = QLineEdit(); self._gl_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._gl_token.setPlaceholderText("glpat-xxxxxxxxxxxxxxxxxxxx")
        btn_gl = QPushButton("👁"); btn_gl.setFixedWidth(32); btn_gl.setCheckable(True)
        btn_gl.toggled.connect(lambda v: self._gl_token.setEchoMode(
            QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        r2 = QHBoxLayout(); r2.addWidget(self._gl_token); r2.addWidget(btn_gl)
        gll.addRow("URL GitLab:", self._gl_url)
        gll.addRow("Token:", r2)
        gll.addRow(QLabel("<small>gitlab.com/-/user_settings/personal_access_tokens → scope: api, read/write_repository</small>"))
        layout.addWidget(grp_gl)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_values(self) -> None:
        if self._git:
            self._name_local.setText(self._git.get_config("user.name"))
            self._email_local.setText(self._git.get_config("user.email"))
            self._name_global.setText(self._git.get_config("user.name", global_=True))
            self._email_global.setText(self._git.get_config("user.email", global_=True))
        self._gh_token.setText(_load_token("github"))
        self._gl_token.setText(_load_token("gitlab"))
        self._gl_url.setText(_load_token("gitlab_url") or "https://gitlab.com")

    def _save(self) -> None:
        if self._git:
            if v := self._name_local.text().strip():  self._git.set_config("user.name", v)
            if v := self._email_local.text().strip(): self._git.set_config("user.email", v)
            if v := self._name_global.text().strip():  self._git.set_config("user.name", v, global_=True)
            if v := self._email_global.text().strip(): self._git.set_config("user.email", v, global_=True)
        if v := self._gh_token.text().strip(): _save_token("github", v)
        if v := self._gl_token.text().strip(): _save_token("gitlab", v)
        if v := self._gl_url.text().strip():   _save_token("gitlab_url", v)
        QMessageBox.information(self, "Git", "Configurazione salvata.")
        self.accept()


# ─── Pannello Git ─────────────────────────────────────────────────────────────

class _GitPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw   = main_window
        self._git: Optional[GitRunner] = None
        self._repo_dir: Optional[Path] = None
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start(5000)  # aggiorna ogni 5s

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header: repo + branch + refresh
        hdr = QHBoxLayout()
        self._repo_label   = QLabel("Nessun repository")
        self._repo_label.setStyleSheet("font-size: 11px;")
        self._branch_label = QLabel("")
        self._branch_label.setStyleSheet(
            "font-size: 11px; color: #7ec8e3; font-weight: bold;"
        )
        btn_refresh = QPushButton("🔄")
        btn_refresh.setFixedSize(26, 26)
        btn_refresh.setToolTip("Aggiorna (F5)")
        btn_refresh.clicked.connect(self.refresh)
        hdr.addWidget(self._repo_label, 1)
        hdr.addWidget(self._branch_label)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        # Azioni rapide
        acts = QHBoxLayout()
        for label, tip, slot in [
            ("↓ Pull",
             "git pull — Scarica e integra le modifiche dal remote.\n"
             "Mantiene il repo locale sincronizzato con il server.",
             self._pull),
            ("↑ Push",
             "git push — Carica i commit locali sul remote.\n"
             "Richiede almeno un remote configurato (es. origin).",
             self._push),
            ("✓ Commit",
             "git add . + git commit — Apre un dialog per scegliere\n"
             "i file da includere e scrivere il messaggio di commit.",
             self._commit),
            ("≡ Stash",
             "Sì → git stash push  (salva le modifiche non committate)\n"
             "No → git stash pop   (ripristina le modifiche salvate)",
             self._stash),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setFixedHeight(26)
            btn.clicked.connect(slot)
            acts.addWidget(btn)
        layout.addLayout(acts)

        # Tabs: Status / Log / Diff / Branch
        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.TabPosition.South)

        # ── Tab Status ──
        status_w = QWidget()
        sl = QVBoxLayout(status_w)
        sl.setContentsMargins(0, 0, 0, 0)
        self._status_tree = QTreeWidget()
        self._status_tree.setHeaderLabels(["", "File"])
        self._status_tree.header().resizeSection(0, 30)
        self._status_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._status_tree.customContextMenuRequested.connect(self._status_context_menu)
        sl.addWidget(self._status_tree)
        tabs.addTab(status_w, "Status")

        # ── Tab Log ──
        log_w = QWidget()
        ll = QVBoxLayout(log_w)
        ll.setContentsMargins(0, 0, 0, 0)
        self._log_list = QTreeWidget()
        self._log_list.setHeaderLabels(["Hash", "Data", "Autore", "Messaggio"])
        self._log_list.header().resizeSection(0, 60)
        self._log_list.header().resizeSection(1, 120)
        self._log_list.header().resizeSection(2, 100)
        self._log_list.itemClicked.connect(self._on_log_click)
        ll.addWidget(self._log_list)
        tabs.addTab(log_w, "Log")

        # ── Tab Diff ──
        diff_w = QWidget()
        dl = QVBoxLayout(diff_w)
        dl.setContentsMargins(0, 0, 0, 0)
        diff_top = QHBoxLayout()
        self._diff_staged_cb = QCheckBox("Staged")
        diff_top.addWidget(self._diff_staged_cb)
        btn_refresh_diff = QPushButton("Aggiorna diff")
        btn_refresh_diff.clicked.connect(self._show_diff)
        diff_top.addWidget(btn_refresh_diff)
        diff_top.addStretch()
        dl.addLayout(diff_top)
        self._diff_view = QTextEdit()
        self._diff_view.setReadOnly(True)
        self._diff_view.setFont(QFont("Monospace", 10))
        dl.addWidget(self._diff_view)
        tabs.addTab(diff_w, "Diff")

        # ── Tab Branch ──
        branch_w = QWidget()
        bl = QVBoxLayout(branch_w)
        bl.setContentsMargins(0, 0, 0, 0)
        self._branch_list = QListWidget()
        self._branch_list.itemDoubleClicked.connect(self._checkout_branch)
        bl.addWidget(self._branch_list)
        branch_acts = QHBoxLayout()
        btn_new_br = QPushButton("Nuova branch")
        btn_new_br.clicked.connect(self._new_branch)
        branch_acts.addWidget(btn_new_br)
        branch_acts.addStretch()
        bl.addLayout(branch_acts)
        tabs.addTab(branch_w, "Branch")

        # ── Tab Config ──
        config_w = QWidget()
        cfl = QVBoxLayout(config_w)
        cfl.setContentsMargins(4,4,4,4)
        self._cfg_name_lbl  = QLabel("Nome: —")
        self._cfg_email_lbl = QLabel("Email: —")
        self._cfg_name_lbl.setStyleSheet("font-size:11px")
        self._cfg_email_lbl.setStyleSheet("font-size:11px")
        cfl.addWidget(self._cfg_name_lbl)
        cfl.addWidget(self._cfg_email_lbl)
        btn_creds = QPushButton("⚙  Configura utente & token…")
        btn_creds.clicked.connect(self._open_credentials)
        cfl.addWidget(btn_creds)
        cfl.addWidget(QLabel("git config locale:"))
        self._cfg_view = QPlainTextEdit()
        self._cfg_view.setReadOnly(True)
        self._cfg_view.setFont(QFont("Monospace", 9))
        cfl.addWidget(self._cfg_view, 1)
        cfl.addStretch()
        tabs.addTab(config_w, "Config")

        layout.addWidget(tabs, 1)

        # Log operazioni
        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setMaximumHeight(80)
        self._log_output.setFont(QFont("Monospace", 9))
        layout.addWidget(self._log_output)

    # ── Rilevamento repo ──────────────────────────────────────────────────────

    def set_editor(self, editor: Optional["EditorWidget"]) -> None:
        """Aggiorna il repo in base al file aperto nell'editor."""
        if editor is None or editor.file_path is None:
            return
        repo_dir = self._find_repo(editor.file_path)
        if repo_dir and repo_dir != self._repo_dir:
            self._repo_dir  = repo_dir
            self._git       = GitRunner(repo_dir)
            self._repo_label.setText(f"📁 {repo_dir.name}")
            self.refresh()

    def _find_repo(self, path: Path) -> Optional[Path]:
        """Risale la gerarchia finché trova una .git directory."""
        current = path.parent if path.is_file() else path
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        if not self._git:
            return
        self._branch_label.setText(f"⎇ {self._git.current_branch()}")
        self._refresh_status()
        self._refresh_log()
        self._refresh_branches()
        self._refresh_config()

    def _auto_refresh(self) -> None:
        """Refresh periodico silenzioso."""
        if self._git:
            self._refresh_status()

    def _refresh_status(self) -> None:
        self._status_tree.clear()
        if not self._git:
            return
        _ICONS = {
            "M": ("✎", "#f0b429"),
            "A": ("＋", "#56bd5b"),
            "D": ("－", "#e06c75"),
            "?": ("?", "#888"),
            "R": ("➜", "#61afef"),
        }
        for xy, filepath in self._git.status():
            icon, color = _ICONS.get(xy[0], ("·", "#aaa"))
            item = QTreeWidgetItem([icon, filepath])
            item.setForeground(0, QColor(color))
            item.setData(0, Qt.ItemDataRole.UserRole, filepath)
            self._status_tree.addTopLevelItem(item)

    def _refresh_log(self) -> None:
        self._log_list.clear()
        if not self._git:
            return
        for c in self._git.log(60):
            item = QTreeWidgetItem([c["short"], c["date"], c["author"], c["subject"]])
            item.setData(0, Qt.ItemDataRole.UserRole, c["hash"])
            self._log_list.addTopLevelItem(item)

    def _refresh_branches(self) -> None:
        self._branch_list.clear()
        if not self._git:
            return
        current = self._git.current_branch()
        for br in self._git.branches():
            item = QListWidgetItem(("★ " if br == current else "  ") + br)
            if br == current:
                item.setForeground(QColor("#7ec8e3"))
            self._branch_list.addItem(item)

    # ── Azioni rapide ─────────────────────────────────────────────────────────

    def _pull(self) -> None:
        if not self._git:
            return
        ok, msg = self._git.pull()
        self._log(msg, ok)
        if ok:
            self.refresh()

    def _push(self) -> None:
        if not self._git:
            return
        ok, msg = self._git.push()
        self._log(msg, ok)

    def _commit(self) -> None:
        if not self._git:
            return
        msg, ok = QInputDialog.getText(
            self, "Commit", "Messaggio di commit:"
        )
        if not ok or not msg.strip():
            return
        self._git.add(".")
        success, out = self._git.commit(msg.strip())
        self._log(out, success)
        if success:
            self.refresh()

    def _stash(self) -> None:
        if not self._git:
            return
        reply = QMessageBox.question(
            self, "Stash",
            "Stash (salva) le modifiche correnti?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No |
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._git.stash()
            self.refresh()
        elif reply == QMessageBox.StandardButton.No:
            self._git.stash_pop()
            self.refresh()

    def _checkout_branch(self, item: QListWidgetItem) -> None:
        br = item.text().strip().lstrip("★ ").strip()
        ok, msg = self._git.checkout(br)
        self._log(msg, ok)
        if ok:
            self.refresh()

    def _new_branch(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuova branch", "Nome branch:")
        if ok and name.strip():
            success, msg = self._git.checkout(name.strip(), create=True)
            self._log(msg, success)
            if success:
                self.refresh()

    # ── Diff ─────────────────────────────────────────────────────────────────

    def _show_diff(self) -> None:
        if not self._git:
            return
        editor = self._mw._tab_manager.current_editor()
        path = None
        if editor and editor.file_path and self._repo_dir:
            try:
                path = str(editor.file_path.relative_to(self._repo_dir))
            except ValueError:
                pass
        diff_text = self._git.diff(path, staged=self._diff_staged_cb.isChecked())
        self._diff_view.setPlainText(diff_text or "(nessuna differenza)")
        self._colorize_diff()

    def _colorize_diff(self) -> None:
        """Colora il testo diff: + verde, - rosso, @@ blu."""
        cursor = self._diff_view.textCursor()
        from PyQt6.QtGui import QTextCharFormat, QTextCursor
        doc = self._diff_view.document()
        block = doc.begin()
        while block.isValid():
            text = block.text()
            fmt = QTextCharFormat()
            if text.startswith("+") and not text.startswith("+++"):
                fmt.setForeground(QColor("#56bd5b"))
            elif text.startswith("-") and not text.startswith("---"):
                fmt.setForeground(QColor("#e06c75"))
            elif text.startswith("@@"):
                fmt.setForeground(QColor("#61afef"))
            if fmt.isValid():
                cursor.setPosition(block.position())
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                cursor.setCharFormat(fmt)
            block = block.next()

    def _on_log_click(self, item: QTreeWidgetItem, col: int) -> None:
        sha = item.data(0, Qt.ItemDataRole.UserRole)
        if sha and self._git:
            rc, out, _ = self._git.run("show", "--stat", sha)
            self._log_output.setPlainText(out[:2000])

    # ── Context menu status ───────────────────────────────────────────────────

    def _status_context_menu(self, pos) -> None:
        item = self._status_tree.itemAt(pos)
        if not item:
            return
        filepath = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("git add",      lambda: self._stage(filepath))
        menu.addAction("git reset HEAD", lambda: self._unstage(filepath))
        menu.addAction("git checkout --", lambda: self._discard(filepath))
        menu.addSeparator()
        menu.addAction("Apri nell'editor",
                       lambda: self._open_file(filepath))
        menu.addAction("Apri su GitHub/GitLab",
                       lambda: self._open_remote_url(filepath))
        menu.exec(self._status_tree.viewport().mapToGlobal(pos))

    def _stage(self, filepath: str) -> None:
        if self._git:
            self._git.add(filepath)
            self._refresh_status()

    def _unstage(self, filepath: str) -> None:
        if self._git:
            self._git.run("reset", "HEAD", "--", filepath)
            self._refresh_status()

    def _discard(self, filepath: str) -> None:
        reply = QMessageBox.question(
            self, "Discard",
            f"Annullare le modifiche a «{filepath}»? (non recuperabile)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes and self._git:
            self._git.run("checkout", "--", filepath)
            self._refresh_status()

    def _open_file(self, filepath: str) -> None:
        if self._repo_dir:
            full = self._repo_dir / filepath
            if full.exists():
                self._mw.open_files([full])

    def _open_remote_url(self, filepath: str) -> None:
        """Apre il file sul remote GitHub/GitLab nel browser."""
        if not self._git:
            return
        remotes = self._git.remotes()
        remote_url = remotes.get("origin", "")
        branch = self._git.current_branch()

        # Converti URL SSH → HTTPS
        m = re.match(r"git@(github\.com|gitlab\.com):(.+?)(?:\.git)?$", remote_url)
        if m:
            host, path = m.group(1), m.group(2)
            url = f"https://{host}/{path}/blob/{branch}/{filepath}"
        elif remote_url.startswith("https://"):
            base = remote_url.rstrip(".git")
            url = f"{base}/blob/{branch}/{filepath}"
        else:
            QMessageBox.information(self, "Git", f"Remote: {remote_url}")
            return

        from core.platform import open_url_in_browser
        open_url_in_browser(url)

    # ── Decoratori riga nell'editor ───────────────────────────────────────────

    def apply_diff_decorators(self, editor: "EditorWidget") -> None:
        """
        Aggiunge indicatori colorati nei margini dell'editor
        per le righe aggiunte (verde), modificate (arancione) e
        eliminate (rosso) rispetto all'ultimo commit.
        """
        if not self._git or not editor.file_path or not self._repo_dir:
            return
        try:
            rel = str(editor.file_path.relative_to(self._repo_dir))
        except ValueError:
            return

        changes = self._git.diff_file_lines(rel)

        # Usa gli indicatori QScintilla (0=aggiunto, 1=modificato, 2=eliminato)
        _COLORS = {"A": "#56bd5b", "M": "#f0b429", "D": "#e06c75"}
        for i, color_str in enumerate(["#56bd5b", "#f0b429", "#e06c75"]):
            editor.indicatorDefine(
                editor.IndicatorStyle.BoxIndicator, i
            )
            editor.setIndicatorForegroundColor(QColor(color_str), i)

        editor.markerDeleteAll(-1)
        for line_no, kind in changes.items():
            marker_num = {"A": 0, "M": 1, "D": 2}.get(kind, 0)
            # 0-based in Scintilla
            editor.markerAdd(line_no - 1, marker_num)

    # ── Configurazione ────────────────────────────────────────────────────────

    def _open_credentials(self) -> None:
        dlg = _CredentialsDialog(self._git, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_config()

    def _refresh_config(self) -> None:
        if not self._git:
            return
        name  = self._git.get_config("user.name")
        email = self._git.get_config("user.email")
        self._cfg_name_lbl.setText(f"Nome: {name or '(non impostato)'}")
        self._cfg_email_lbl.setText(f"Email: {email or '(non impostata)'}")
        rc, out, _ = self._git.run("config", "--local", "--list")
        self._cfg_view.setPlainText(out if rc == 0 else "(nessuna config locale)")

    # ── Utility ───────────────────────────────────────────────────────────────

    def _log(self, msg: str, success: bool = True) -> None:
        prefix = "✓" if success else "✗"
        color  = "#56bd5b" if success else "#e06c75"
        self._log_output.append(
            f'<span style="color:{color}">{prefix}</span> {msg}'
        )


# ─── Plugin ───────────────────────────────────────────────────────────────────

class GitPlugin(BasePlugin):

    NAME        = "Git Integration"
    VERSION     = "1.0"
    DESCRIPTION = "Pannello Git con status, log, diff, commit, push/pull e integrazione GitHub/GitLab."
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._panel = _GitPanel(main_window)
        self._last_editor = None

        self._dock = QDockWidget("⎇  Git", main_window)
        self._dock.setObjectName("GitDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(300)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._dock)
        self._dock.hide()

        # Quando il dock diventa visibile, aggiorna subito con l'editor corrente
        self._dock.visibilityChanged.connect(self._on_dock_visibility)

        # Una sola voce nel menu Plugin
        self.add_menu_action(main_window, "plugins",
                             "⎇  Git",
                             lambda: self._dock.setVisible(not self._dock.isVisible()))
        main_window._menus["plugins"].menuAction().setVisible(True)

    def _on_dock_visibility(self, visible: bool) -> None:
        if visible and hasattr(self, "_panel") and self._last_editor is not None:
            self._panel.set_editor(self._last_editor)

    def on_editor_changed(self, editor) -> None:
        if hasattr(self, "_panel"):
            self._last_editor = editor
            if self._dock.isVisible():
                self._panel.set_editor(editor)

    def on_file_opened(self, path) -> None:
        if hasattr(self, "_panel"):
            editor = self._mw._tab_manager.current_editor()
            if editor:
                self._last_editor = editor
                if self._dock.isVisible():
                    self._panel.set_editor(editor)

    def on_unload(self) -> None:
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()
