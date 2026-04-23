"""
plugins/ftp_browser_plugin.py — Plugin FTP Browser
NotePadPQ

Pannello dock con navigazione FTP/SFTP stile Notepad++ NppFTP.
Supporta FTP (ftplib) e SFTP (paramiko se installato).
Permette di aprire file remoti direttamente in un tab, salvarli
e sfogliare la struttura ad albero del server.

Dipendenze:
    FTP:  ftplib (stdlib)
    SFTP: paramiko (opzionale)  → pip install paramiko

Installazione automatica di paramiko se mancante (su richiesta utente).
"""

from __future__ import annotations

import os
import io
import threading
from pathlib import Path, PurePosixPath
from typing import Optional, List, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget,
    QTreeWidgetItem, QPushButton, QLabel, QLineEdit, QSpinBox,
    QComboBox, QDialog, QFormLayout, QDialogButtonBox,
    QMessageBox, QApplication, QProgressDialog, QMenu, QInputDialog,
    QCheckBox,
)
from PyQt6.QtGui import QIcon

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Modello connessione ──────────────────────────────────────────────────────

class FtpProfile:
    """Dati di una connessione FTP/SFTP."""

    def __init__(self, name="", host="", port=21, user="anonymous",
                 password="", protocol="FTP", remote_dir="/"):
        self.name       = name
        self.host       = host
        self.port       = port
        self.user       = user
        self.password   = password
        self.protocol   = protocol   # "FTP" o "SFTP"
        self.remote_dir = remote_dir

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "FtpProfile":
        p = cls()
        for k, v in d.items():
            setattr(p, k, v)
        return p


# ─── Dialog configurazione profilo ────────────────────────────────────────────

class _ProfileDialog(QDialog):

    def __init__(self, profile: Optional[FtpProfile] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Profilo FTP/SFTP")
        self.resize(400, 280)
        self._profile = profile or FtpProfile()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name     = QLineEdit(self._profile.name)
        self._host     = QLineEdit(self._profile.host)
        self._port     = QSpinBox(); self._port.setRange(1, 65535)
        self._port.setValue(self._profile.port)
        self._user     = QLineEdit(self._profile.user)
        self._password = QLineEdit(self._profile.password)
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._protocol = QComboBox()
        self._protocol.addItems(["FTP", "SFTP"])
        self._protocol.setCurrentText(self._profile.protocol)
        self._remote   = QLineEdit(self._profile.remote_dir)

        form.addRow("Nome profilo:", self._name)
        form.addRow("Host:", self._host)
        form.addRow("Porta:", self._port)
        form.addRow("Utente:", self._user)
        form.addRow("Password:", self._password)
        form.addRow("Protocollo:", self._protocol)
        form.addRow("Directory remota:", self._remote)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._protocol.currentTextChanged.connect(self._on_protocol_changed)
        self._on_protocol_changed(self._protocol.currentText())

    def _on_protocol_changed(self, proto: str) -> None:
        default_port = 21 if proto == "FTP" else 22
        if self._port.value() in (21, 22):
            self._port.setValue(default_port)

    def _on_accept(self) -> None:
        if not self._host.text().strip():
            QMessageBox.warning(self, "Errore", "Inserire l'host.")
            return
        self._profile.name     = self._name.text().strip() or self._host.text()
        self._profile.host     = self._host.text().strip()
        self._profile.port     = self._port.value()
        self._profile.user     = self._user.text()
        self._profile.password = self._password.text()
        self._profile.protocol = self._protocol.currentText()
        self._profile.remote_dir = self._remote.text() or "/"
        self.accept()

    def result_profile(self) -> FtpProfile:
        return self._profile


# ─── Pannello FTP ─────────────────────────────────────────────────────────────

class _FtpPanel(QWidget):
    """Widget principale del pannello FTP Browser."""

    file_open_requested = pyqtSignal(str, bytes)  # remote_path, content

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw        = main_window
        self._profiles: List[FtpProfile] = []
        self._conn      = None    # ftplib.FTP o paramiko.SFTPClient
        self._current_profile: Optional[FtpProfile] = None
        self._current_dir = "/"

        self._load_profiles()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Barra superiore: selettore profilo + connetti/disconnetti
        top = QHBoxLayout()
        self._profile_combo = QComboBox()
        self._profile_combo.setSizePolicy(
            self._profile_combo.sizePolicy().horizontalPolicy(),
            self._profile_combo.sizePolicy().verticalPolicy()
        )
        self._populate_combo()
        top.addWidget(self._profile_combo, 1)

        self._btn_connect = QPushButton("Connetti")
        self._btn_connect.setFixedWidth(80)
        self._btn_connect.clicked.connect(self._connect)
        top.addWidget(self._btn_connect)

        btn_add  = QPushButton("＋")
        btn_add.setFixedWidth(28)
        btn_add.setToolTip("Nuovo profilo")
        btn_add.clicked.connect(self._add_profile)
        top.addWidget(btn_add)

        btn_edit = QPushButton("✎")
        btn_edit.setFixedWidth(28)
        btn_edit.setToolTip("Modifica profilo")
        btn_edit.clicked.connect(self._edit_profile)
        top.addWidget(btn_edit)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(28)
        btn_del.setToolTip("Elimina profilo")
        btn_del.clicked.connect(self._delete_profile)
        top.addWidget(btn_del)

        layout.addLayout(top)

        # Percorso corrente
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("📁"))
        self._path_label = QLabel("/")
        self._path_label.setStyleSheet("font-family: monospace; font-size: 11px;")
        path_row.addWidget(self._path_label, 1)
        btn_up = QPushButton("↑")
        btn_up.setFixedWidth(28)
        btn_up.setToolTip("Directory padre")
        btn_up.clicked.connect(self._go_up)
        path_row.addWidget(btn_up)
        layout.addLayout(path_row)

        # Albero file
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Nome", "Dimensione", "Data"])
        self._tree.header().resizeSection(0, 200)
        self._tree.header().resizeSection(1, 80)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree, 1)

        # Barra di stato
        self._status = QLabel("Non connesso")
        self._status.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self._status)

    def _populate_combo(self) -> None:
        self._profile_combo.clear()
        for p in self._profiles:
            self._profile_combo.addItem(f"{p.protocol} · {p.name} ({p.host})")
        if not self._profiles:
            self._profile_combo.addItem("— Nessun profilo —")

    # ── Profili ───────────────────────────────────────────────────────────────

    def _profiles_path(self) -> Path:
        from core.platform import get_data_dir
        return get_data_dir() / "ftp_profiles.json"

    def _load_profiles(self) -> None:
        import json
        try:
            import keyring
            has_keyring = True
        except ImportError:
            has_keyring = False

        p = self._profiles_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._profiles = []
                for d in data:
                    prof = FtpProfile.from_dict(d)
                    # Recupera la password dal portachiavi di sistema
                    if has_keyring and not prof.password:
                        try:
                            stored_pw = keyring.get_password("NotePadPQ_FTP", prof.name)
                            if stored_pw:
                                prof.password = stored_pw
                        except Exception:
                            pass
                    self._profiles.append(prof)
            except Exception:
                self._profiles = []

    def _save_profiles(self) -> None:
        import json
        try:
            import keyring
            has_keyring = True
        except ImportError:
            has_keyring = False

        save_list = []
        for p in self._profiles:
            d = p.to_dict()
            if has_keyring and p.password:
                # Salva nel portachiavi di sistema crittografato
                try:
                    keyring.set_password("NotePadPQ_FTP", p.name, p.password)
                    d["password"] = ""  # Svuota la password dal JSON!
                except Exception as e:
                    print(f"Errore salvataggio nel portachiavi: {e}")
            elif not has_keyring:
                # Se keyring non è installato, non salvare la password per sicurezza
                d["password"] = ""
            save_list.append(d)

        try:
            self._profiles_path().write_text(
                json.dumps(save_list, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _add_profile(self) -> None:
        dlg = _ProfileDialog(parent=self)
        if dlg.exec():
            self._profiles.append(dlg.result_profile())
            self._save_profiles()
            self._populate_combo()
            self._profile_combo.setCurrentIndex(len(self._profiles) - 1)

    def _edit_profile(self) -> None:
        idx = self._profile_combo.currentIndex()
        if 0 <= idx < len(self._profiles):
            old_name = self._profiles[idx].name
            dlg = _ProfileDialog(self._profiles[idx], parent=self)
            if dlg.exec():
                new_profile = dlg.result_profile()
                # Se il nome del profilo è cambiato, elimina la vecchia password dal portachiavi
                if old_name != new_profile.name:
                    try:
                        import keyring
                        keyring.delete_password("NotePadPQ_FTP", old_name)
                    except Exception:
                        pass
                
                self._profiles[idx] = new_profile
                self._save_profiles()
                self._populate_combo()
                self._profile_combo.setCurrentIndex(idx)

    def _delete_profile(self) -> None:
        idx = self._profile_combo.currentIndex()
        if 0 <= idx < len(self._profiles):
            p_to_delete = self._profiles[idx]
            reply = QMessageBox.question(
                self, "Elimina profilo",
                f"Eliminare il profilo «{p_to_delete.name}»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                # Elimina la password dal portachiavi di sistema
                try:
                    import keyring
                    keyring.delete_password("NotePadPQ_FTP", p_to_delete.name)
                except Exception:
                    pass
                    
                self._profiles.pop(idx)
                self._save_profiles()
                self._populate_combo()

    def _delete_profile(self) -> None:
        idx = self._profile_combo.currentIndex()
        if 0 <= idx < len(self._profiles):
            reply = QMessageBox.question(
                self, "Elimina profilo",
                f"Eliminare il profilo «{self._profiles[idx].name}»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._profiles.pop(idx)
                self._save_profiles()
                self._populate_combo()

    # ── Connessione ───────────────────────────────────────────────────────────

    def _connect(self) -> None:
        if self._conn is not None:
            self._disconnect()
            return

        idx = self._profile_combo.currentIndex()
        if idx < 0 or idx >= len(self._profiles):
            QMessageBox.warning(self, "FTP Browser", "Seleziona un profilo.")
            return

        profile = self._profiles[idx]
        self._current_profile = profile
        self._status.setText(f"Connessione a {profile.host}…")
        QApplication.processEvents()

        try:
            if profile.protocol == "SFTP":
                self._conn = self._connect_sftp(profile)
            else:
                self._conn = self._connect_ftp(profile)

            self._btn_connect.setText("Disconnetti")
            self._status.setText(f"✓ Connesso a {profile.host}")
            self._list_directory(profile.remote_dir)
        except Exception as e:
            self._conn = None
            self._status.setText("Errore connessione")
            QMessageBox.critical(self, "FTP Browser", f"Connessione fallita:\n{e}")

    def _connect_ftp(self, profile: FtpProfile):
        import ftplib
        ftp = ftplib.FTP()
        ftp.connect(profile.host, profile.port, timeout=15)
        ftp.login(profile.user, profile.password)
        return ("ftp", ftp)

    def _connect_sftp(self, profile: FtpProfile):
        try:
            import paramiko
        except ImportError:
            raise RuntimeError(
                "paramiko non installato.\n"
                "Esegui: pip install paramiko"
            )
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            profile.host, port=profile.port,
            username=profile.user, password=profile.password,
            timeout=15
        )
        sftp = ssh.open_sftp()
        return ("sftp", sftp, ssh)

    def _disconnect(self) -> None:
        if self._conn:
            try:
                kind = self._conn[0]
                if kind == "ftp":
                    self._conn[1].quit()
                elif kind == "sftp":
                    self._conn[1].close()
                    self._conn[2].close()
            except Exception:
                pass
        self._conn = None
        self._btn_connect.setText("Connetti")
        self._status.setText("Disconnesso")
        self._tree.clear()

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _list_directory(self, path: str) -> None:
        self._current_dir = path
        self._path_label.setText(path)
        self._tree.clear()
        self._status.setText(f"Elenco {path}…")
        QApplication.processEvents()

        try:
            entries = self._fetch_listing(path)
        except Exception as e:
            self._status.setText("Errore lettura directory")
            QMessageBox.warning(self, "FTP Browser", str(e))
            return

        for name, size, date, is_dir in sorted(
                entries, key=lambda x: (not x[3], x[0].lower())
        ):
            item = QTreeWidgetItem([
                ("📁 " if is_dir else "📄 ") + name,
                "" if is_dir else self._fmt_size(size),
                date,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, (path, name, is_dir))
            self._tree.addTopLevelItem(item)

        count = len(entries)
        self._status.setText(f"{count} elementi in {path}")

    def _fetch_listing(self, path: str) -> list:
        """Restituisce [(name, size, date, is_dir), ...]"""
        if not self._conn:
            return []
        kind = self._conn[0]

        if kind == "ftp":
            ftp = self._conn[1]
            ftp.cwd(path)
            entries = []
            lines = []
            ftp.retrlines("LIST", lines.append)
            for line in lines:
                parts = line.split(None, 8)
                if len(parts) < 9:
                    continue
                is_dir = parts[0].startswith("d")
                size   = int(parts[4]) if not is_dir else 0
                date   = " ".join(parts[5:8])
                name   = parts[8]
                if name in (".", ".."):
                    continue
                entries.append((name, size, date, is_dir))
            return entries

        elif kind == "sftp":
            sftp = self._conn[1]
            entries = []
            for attr in sftp.listdir_attr(path):
                import stat
                is_dir = stat.S_ISDIR(attr.st_mode)
                size   = attr.st_size or 0
                import datetime
                date   = datetime.datetime.fromtimestamp(
                    attr.st_mtime or 0
                ).strftime("%Y-%m-%d %H:%M")
                entries.append((attr.filename, size, date, is_dir))
            return entries

        return []

    def _go_up(self) -> None:
        parent = str(PurePosixPath(self._current_dir).parent)
        if parent != self._current_dir:
            self._list_directory(parent)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        parent_dir, name, is_dir = data
        full_path = str(PurePosixPath(parent_dir) / name)
        if is_dir:
            self._list_directory(full_path)
        else:
            self._download_and_open(full_path)

    def _download_and_open(self, remote_path: str) -> None:
        """Scarica il file remoto e lo apre in un tab."""
        self._status.setText(f"Download {remote_path}…")
        QApplication.processEvents()
        try:
            content = self._fetch_file(remote_path)
            self._open_in_editor(remote_path, content)
            self._status.setText(f"✓ Aperto: {remote_path}")
        except Exception as e:
            self._status.setText("Errore download")
            QMessageBox.warning(self, "FTP Browser", f"Download fallito:\n{e}")

    def _fetch_file(self, remote_path: str) -> bytes:
        kind = self._conn[0]
        buf = io.BytesIO()
        if kind == "ftp":
            self._conn[1].retrbinary(f"RETR {remote_path}", buf.write)
        elif kind == "sftp":
            self._conn[1].getfo(remote_path, buf)
        return buf.getvalue()

    def _open_in_editor(self, remote_path: str, raw: bytes) -> None:
        """Apre i byte del file remoto in un nuovo tab dell'editor."""
        from core.file_manager import FileManager
        from editor.editor_widget import LineEnding
        from pathlib import PurePosixPath
        from PyQt6.QtCore import QTimer

        # Rilevamento encoding
        encoding, bom_len = FileManager._detect_bom(raw)
        if not encoding:
            encoding = FileManager._chardet_detect(raw[:8192]) or "UTF-8"
        try:
            text = raw[bom_len:].decode(encoding, errors="replace")
        except Exception:
            text = raw.decode("latin-1", errors="replace")

        le = LineEnding.detect(text)

        # Crea tab con path virtuale (non esiste su disco locale)
        tab = self._mw._tab_manager.new_tab(path=None)
        
        # Metadati: origine remota
        tab._ftp_remote_path   = remote_path
        tab._ftp_profile       = self._current_profile
        tab._ftp_panel_ref     = self
        
        tab.load_content(text, encoding.upper(), le)

        # --- FIX FORZATURA NOMI E TITOLI PULITA ---
        name = PurePosixPath(remote_path).name
        proto = self._current_profile.protocol.lower()
        host = self._current_profile.host
        full_uri = f"{proto}://{host}{remote_path}"

        tm = self._mw._tab_manager

        def force_titles(*args):
            if tab not in tm._containers:
                return
            
            # 1. Aggiorna la linguetta del tab
            idx = tm.indexOf(tm._containers[tab])
            if idx >= 0:
                mod_tab = "* " if tab.is_modified() else ""
                tm.setTabText(idx, f"{mod_tab}{name}")

            # 2. Aggiorna il titolo della finestra in alto
            if tm.current_editor() == tab:
                mod_win = " *" if tab.is_modified() else ""
                self._mw.setWindowTitle(f"{full_uri}{mod_win} — {self._mw.APP_NAME}")

        QTimer.singleShot(10, force_titles)
        tab.modified_changed.connect(lambda mod: QTimer.singleShot(10, force_titles))
        tm.current_editor_changed.connect(lambda ed: QTimer.singleShot(10, force_titles) if ed == tab else None)

    # ── Context menu ──────────────────────────────────────────────────────────

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        parent_dir, name, is_dir = data
        full_path = str(PurePosixPath(parent_dir) / name)

        menu = QMenu(self)
        if not is_dir:
            menu.addAction("Apri", lambda: self._download_and_open(full_path))
        menu.addAction("Rinomina", lambda: self._rename(full_path, name))
        menu.addAction("Elimina", lambda: self._delete(full_path, name))
        menu.addSeparator()
        menu.addAction("Nuova cartella", self._mkdir)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _rename(self, path: str, old_name: str) -> None:
        new_name, ok = QInputDialog.getText(
            self, "Rinomina", "Nuovo nome:", text=old_name
        )
        if not ok or not new_name.strip() or new_name == old_name:
            return
        new_path = str(PurePosixPath(path).parent / new_name)
        try:
            kind = self._conn[0]
            if kind == "ftp":
                self._conn[1].rename(path, new_path)
            elif kind == "sftp":
                self._conn[1].rename(path, new_path)
            self._list_directory(self._current_dir)
        except Exception as e:
            QMessageBox.warning(self, "FTP Browser", f"Rinomina fallita:\n{e}")

    def _delete(self, path: str, name: str) -> None:
        reply = QMessageBox.question(
            self, "Elimina", f"Eliminare «{name}» dal server?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            kind = self._conn[0]
            if kind == "ftp":
                try:
                    self._conn[1].delete(path)
                except Exception:
                    self._conn[1].rmd(path)
            elif kind == "sftp":
                self._conn[1].remove(path)
            self._list_directory(self._current_dir)
        except Exception as e:
            QMessageBox.warning(self, "FTP Browser", f"Eliminazione fallita:\n{e}")

    def _mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuova cartella", "Nome:")
        if not ok or not name.strip():
            return
        new_path = str(PurePosixPath(self._current_dir) / name)
        try:
            kind = self._conn[0]
            if kind == "ftp":
                self._conn[1].mkd(new_path)
            elif kind == "sftp":
                self._conn[1].mkdir(new_path)
            self._list_directory(self._current_dir)
        except Exception as e:
            QMessageBox.warning(self, "FTP Browser", f"Creazione fallita:\n{e}")

    # ── Upload file corrente ──────────────────────────────────────────────────

    def upload_current(self) -> None:
        """Carica il file corrente dell'editor sul server (se proveniente da FTP)."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return

        remote_path = getattr(editor, "_ftp_remote_path", None)
        if not remote_path:
            QMessageBox.information(
                self, "FTP Browser",
                "Il file corrente non è stato aperto tramite FTP Browser."
            )
            return

        # Le connessioni FTP/SFTP cadono spesso per inattività.
        # Se siamo disconnessi, proviamo a riconnetterci silenziosamente.
        if self._conn is None:
            profile = getattr(editor, "_ftp_profile", None)
            if profile:
                self._current_profile = profile
                self._status.setText(f"Riconnessione a {profile.host}…")
                QApplication.processEvents()
                try:
                    if profile.protocol == "SFTP":
                        self._conn = self._connect_sftp(profile)
                    else:
                        self._conn = self._connect_ftp(profile)
                    self._btn_connect.setText("Disconnetti")
                except Exception as e:
                    QMessageBox.warning(self, "FTP Browser", f"Riconnessione fallita:\n{e}")
                    return

        content = editor.get_content()
        raw = content.encode(editor.encoding, errors="replace")
        # ... (codice precedente del caricamento sftp/ftp) ...
        try:
            kind = self._conn[0]
            buf = io.BytesIO(raw)
            if kind == "ftp":
                self._conn[1].storbinary(f"STOR {remote_path}", buf)
            elif kind == "sftp":
                self._conn[1].putfo(buf, remote_path)
                
            self._status.setText(f"✓ Salvato online: {remote_path}")
            
            # --- FIX DEFINITIVO: Segna come salvato e aggiorna l'interfaccia ---
            # setModified(False) è il comando standard di Scintilla:
            # toglie l'asterisco e avvisa MainWindow di aggiornare il titolo.
            editor.setModified(False)
            self._mw._on_editor_changed(editor)
            
        except Exception as e:
            QMessageBox.warning(self, "FTP Browser", f"Upload fallito:\n{e}")
            self._conn = None

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 ** 2:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 ** 3:
            return f"{size / 1024 ** 2:.1f} MB"
        return f"{size / 1024 ** 3:.1f} GB"


# ─── Plugin ───────────────────────────────────────────────────────────────────

class FtpBrowserPlugin(BasePlugin):

    NAME        = "FTP Browser"
    VERSION     = "1.0"
    DESCRIPTION = "Pannello di navigazione e trasferimento file FTP/SFTP."
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._panel = _FtpPanel(main_window)

        self._dock = QDockWidget("🌐  FTP Browser", main_window)
        self._dock.setObjectName("FtpBrowserDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(260)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._dock)
        self._dock.hide()

        self.add_menu_action(main_window, "plugins",
                             "🌐 FTP Browser",
                             lambda: self._dock.setVisible(not self._dock.isVisible()))
        self.add_menu_action(main_window, "plugins",
                             "↑ Carica file corrente (FTP)",
                             self._panel.upload_current)
        main_window._menus["plugins"].menuAction().setVisible(True)

    def on_unload(self) -> None:
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()
