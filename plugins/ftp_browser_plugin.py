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

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QThread
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget,
    QTreeWidgetItem, QPushButton, QLabel, QLineEdit, QSpinBox,
    QComboBox, QDialog, QFormLayout, QDialogButtonBox,
    QMessageBox, QApplication, QProgressDialog, QMenu, QInputDialog,
    QCheckBox, QTextEdit, QSplitter, QTabWidget,
)
from PyQt6.QtGui import QIcon, QFont, QColor, QTextCursor, QKeyEvent

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Modello connessione ──────────────────────────────────────────────────────

class FtpProfile:
    """Dati di una connessione FTP/SFTP/SSH/SMB."""

    def __init__(self, name="", host="", port=21, user="anonymous",
                 password="", protocol="FTP", remote_dir="/",
                 domain="", smb_share=""):
        self.name       = name
        self.host       = host
        self.port       = port
        self.user       = user
        self.password   = password
        self.protocol   = protocol   # "FTP", "SFTP", "SSH" o "SMB"
        self.remote_dir = remote_dir
        self.domain     = domain      # per SMB/AD
        self.smb_share  = smb_share   # nome share SMB (es. "documents")

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
        self._protocol.addItems(["FTP", "SFTP", "SSH", "SMB"])
        self._protocol.setCurrentText(self._profile.protocol)
        self._remote   = QLineEdit(self._profile.remote_dir)

        self._domain    = QLineEdit(getattr(self._profile, "domain", ""))
        self._domain.setPlaceholderText("WORKGROUP  oppure  DOMINIO.LOCAL")
        self._smb_share = QLineEdit(getattr(self._profile, "smb_share", ""))
        self._smb_share.setPlaceholderText("es. documents  oppure  homes")

        form.addRow("Nome profilo:", self._name)
        form.addRow("Host:", self._host)
        form.addRow("Porta:", self._port)
        form.addRow("Utente:", self._user)
        form.addRow("Password:", self._password)
        form.addRow("Protocollo:", self._protocol)
        form.addRow("Directory remota:", self._remote)
        self._row_domain    = form.addRow("Dominio/Workgroup:", self._domain)
        self._row_smb_share = form.addRow("Share SMB:", self._smb_share)

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
        if proto == "FTP":
            default_port = 21
        elif proto == "SMB":
            default_port = 445
        else:   # SFTP, SSH
            default_port = 22
        if self._port.value() in (21, 22, 445):
            self._port.setValue(default_port)
        is_smb = (proto == "SMB")
        is_ssh = (proto == "SSH")
        if hasattr(self, "_remote"):
            self._remote.setEnabled(not is_ssh and not is_smb)
        if hasattr(self, "_domain"):
            self._domain.setEnabled(is_smb)
        if hasattr(self, "_smb_share"):
            self._smb_share.setEnabled(is_smb)

    def _on_accept(self) -> None:
        if not self._host.text().strip():
            QMessageBox.warning(self, "Errore", "Inserire l'host.")
            return
        proto = self._protocol.currentText()
        if proto == "SMB" and not self._smb_share.text().strip():
            QMessageBox.warning(self, "Errore", "Inserire il nome della share SMB.")
            return
        self._profile.name      = self._name.text().strip() or self._host.text()
        self._profile.host      = self._host.text().strip()
        self._profile.port      = self._port.value()
        self._profile.user      = self._user.text()
        self._profile.password  = self._password.text()
        self._profile.protocol  = proto
        self._profile.remote_dir = self._remote.text() or "/"
        self._profile.domain    = self._domain.text().strip()
        self._profile.smb_share = self._smb_share.text().strip()
        self.accept()

    def result_profile(self) -> FtpProfile:
        return self._profile


# ─── Terminale SSH interattivo ────────────────────────────────────────────────

class _SshOutputReader(QObject):
    """Legge l'output del canale SSH in un thread separato e lo emette come segnale."""
    data_ready = pyqtSignal(str)
    finished   = pyqtSignal()

    def __init__(self, channel):
        super().__init__()
        self._channel = channel
        self._running = True

    def run(self):
        while self._running:
            try:
                if self._channel.recv_ready():
                    chunk = self._channel.recv(4096)
                    if chunk:
                        self.data_ready.emit(chunk.decode("utf-8", errors="replace"))
                    else:
                        break
                elif self._channel.closed or self._channel.exit_status_ready():
                    break
                else:
                    import time
                    time.sleep(0.05)
            except Exception:
                break
        self.finished.emit()

    def stop(self):
        self._running = False


class _SshTerminalDialog(QDialog):
    """Finestra di terminale SSH interattivo basata su paramiko."""

    def __init__(self, profile: "FtpProfile", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"SSH — {profile.user}@{profile.host}")
        self.resize(800, 520)
        self._profile = profile
        self._ssh = None
        self._channel = None
        self._reader = None
        self._reader_thread = None
        self._history: list[str] = []
        self._hist_idx = 0
        self._build_ui()
        self._connect()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        # Info bar
        info = QHBoxLayout()
        self._lbl_status = QLabel(f"Connessione a {self._profile.host}:{self._profile.port}…")
        self._lbl_status.setStyleSheet("color: #888; font-size: 11px;")
        info.addWidget(self._lbl_status)
        info.addStretch()
        btn_clear = QPushButton("Pulisci")
        btn_clear.setFixedWidth(70)
        btn_clear.clicked.connect(self._clear_output)
        info.addWidget(btn_clear)
        lay.addLayout(info)

        # Output terminal
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Monospace", 10))
        self._output.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4;"
            "  border: 1px solid #3c3c3c; border-radius: 4px; }"
        )
        lay.addWidget(self._output, stretch=1)

        # Input bar
        input_row = QHBoxLayout()
        self._lbl_prompt = QLabel("$")
        self._lbl_prompt.setStyleSheet("color: #49cc90; font-weight: bold; font-family: monospace;")
        input_row.addWidget(self._lbl_prompt)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Digita il comando e premi Invio…")
        self._input.setFont(QFont("Monospace", 10))
        self._input.setStyleSheet(
            "QLineEdit { background: #252526; color: #d4d4d4;"
            "  border: 1px solid #3c3c3c; border-radius: 4px; padding: 4px; }"
        )
        self._input.returnPressed.connect(self._send_command)
        self._input.installEventFilter(self)
        input_row.addWidget(self._input, stretch=1)

        btn_send = QPushButton("Invia")
        btn_send.setFixedWidth(70)
        btn_send.setStyleSheet(
            "QPushButton { background: #0e639c; color: white; border: none;"
            "  border-radius: 4px; padding: 4px 10px; font-weight: bold; }"
            "QPushButton:hover { background: #1177bb; }"
        )
        btn_send.clicked.connect(self._send_command)
        input_row.addWidget(btn_send)
        lay.addLayout(input_row)

        # Bottoni utility
        util_row = QHBoxLayout()
        for label, cmd in [("ls -la", "ls -la\n"), ("pwd", "pwd\n"),
                            ("df -h", "df -h\n"), ("top (q per uscire)", "top\n")]:
            b = QPushButton(label)
            b.setFixedHeight(24)
            b.setStyleSheet(
                "QPushButton { background: #2d2d2d; color: #aaa; border: 1px solid #444;"
                "  border-radius: 3px; font-size: 11px; padding: 0 8px; }"
                "QPushButton:hover { background: #3c3c3c; color: #fff; }"
            )
            b.clicked.connect(lambda checked, c=cmd: self._send_raw(c))
            util_row.addWidget(b)
        util_row.addStretch()
        lay.addLayout(util_row)

        # Pulsante chiudi
        btn_close = QPushButton("Chiudi connessione")
        btn_close.clicked.connect(self.close)
        lay.addWidget(btn_close)

    def eventFilter(self, obj, event):
        """Gestisce freccia su/giù per la cronologia comandi."""
        if obj is self._input and isinstance(event, QKeyEvent):
            from PyQt6.QtCore import Qt as _Qt
            if event.key() == _Qt.Key.Key_Up:
                if self._history and self._hist_idx < len(self._history):
                    self._hist_idx += 1
                    self._input.setText(self._history[-self._hist_idx])
                return True
            elif event.key() == _Qt.Key.Key_Down:
                if self._hist_idx > 1:
                    self._hist_idx -= 1
                    self._input.setText(self._history[-self._hist_idx])
                else:
                    self._hist_idx = 0
                    self._input.clear()
                return True
        return super().eventFilter(obj, event)

    def _connect(self):
        try:
            import paramiko
        except ImportError:
            self._append_output(
                "❌ paramiko non installato.\n"
                "   Esegui: pip install paramiko\n"
            )
            self._lbl_status.setText("paramiko mancante")
            return
        try:
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh.connect(
                self._profile.host,
                port=self._profile.port,
                username=self._profile.user,
                password=self._profile.password,
                timeout=15,
            )
            self._channel = self._ssh.invoke_shell(term="xterm", width=120, height=40)
            self._channel.setblocking(False)
            self._lbl_status.setText(
                f"✓ Connesso a {self._profile.user}@{self._profile.host}:{self._profile.port}"
            )
            self._lbl_status.setStyleSheet("color: #49cc90; font-size: 11px; font-weight: bold;")
            self._start_reader()
        except Exception as exc:
            self._append_output(f"❌ Connessione fallita:\n   {exc}\n")
            self._lbl_status.setText("Errore connessione")
            self._lbl_status.setStyleSheet("color: #f44747; font-size: 11px;")

    def _start_reader(self):
        self._reader = _SshOutputReader(self._channel)
        self._reader.data_ready.connect(self._append_output)
        self._reader.finished.connect(self._on_reader_finished)
        self._reader_thread = threading.Thread(target=self._reader.run, daemon=True)
        self._reader_thread.start()

    def _append_output(self, text: str):
        # Rimuovi sequenze ANSI di base per leggibilità
        import re
        clean = re.sub(r"\x1b\[[0-9;]*[mABCDEFGHJKSTfhil]", "", text)
        clean = re.sub(r"\x1b\].*?\x07", "", clean)
        clean = clean.replace("\r\n", "\n").replace("\r", "\n")
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._output.setTextCursor(cursor)
        self._output.insertPlainText(clean)
        self._output.ensureCursorVisible()

    def _send_command(self):
        cmd = self._input.text()
        if not cmd:
            return
        self._history.append(cmd)
        self._hist_idx = 0
        self._input.clear()
        self._send_raw(cmd + "\n")

    def _send_raw(self, raw: str):
        if self._channel and not self._channel.closed:
            try:
                self._channel.send(raw)
            except Exception as exc:
                self._append_output(f"\n❌ Errore invio: {exc}\n")
        else:
            self._append_output("\n⚠ Canale SSH non attivo.\n")

    def _clear_output(self):
        self._output.clear()

    def _on_reader_finished(self):
        self._append_output("\n\n[Connessione SSH chiusa]\n")
        self._lbl_status.setText("Disconnesso")
        self._lbl_status.setStyleSheet("color: #888; font-size: 11px;")

    def closeEvent(self, event):
        if self._reader:
            self._reader.stop()
        if self._channel:
            try:
                self._channel.close()
            except Exception:
                pass
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
        super().closeEvent(event)


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
        btn_add.setToolTip(tr("tooltip.ftp_new_profile"))
        btn_add.clicked.connect(self._add_profile)
        top.addWidget(btn_add)

        btn_edit = QPushButton("✎")
        btn_edit.setFixedWidth(28)
        btn_edit.setToolTip(tr("tooltip.ftp_edit_profile"))
        btn_edit.clicked.connect(self._edit_profile)
        top.addWidget(btn_edit)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(28)
        btn_del.setToolTip(tr("tooltip.ftp_del_profile"))
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
        btn_up.setToolTip(tr("tooltip.ftp_parent_dir"))
        btn_up.clicked.connect(self._go_up)
        path_row.addWidget(btn_up)

        btn_refresh = QPushButton("⟳")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip(tr("tooltip.ftp_refresh"))
        btn_refresh.clicked.connect(self._refresh)
        path_row.addWidget(btn_refresh)

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

        # ── SSH: apre terminale interattivo, non naviga file ──────────────────
        if profile.protocol == "SSH":
            dlg = _SshTerminalDialog(profile, parent=self)
            dlg.show()
            return

        # ── SMB: mount helper ─────────────────────────────────────────────────
        if profile.protocol == "SMB":
            self._smb_mount_helper(profile)
            return

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

    def _smb_mount_helper(self, profile: FtpProfile) -> None:
        """Controlla se la share SMB è già montata; se no, tenta il mount."""
        import sys
        import subprocess
        import shutil

        host  = profile.host
        share = profile.smb_share or ""
        user  = profile.user
        pwd   = profile.password
        dom   = profile.domain or "WORKGROUP"

        # ── Controlla se già montata ──────────────────────────────────────────
        already_mounted = self._smb_find_mount(host, share)
        if already_mounted:
            self._status.setText(f"✓ Share già montata: {already_mounted}")
            QMessageBox.information(
                self, "SMB",
                f"La share è già accessibile in:\n{already_mounted}\n\n"
                "Puoi aprire i file direttamente da quel percorso."
            )
            # Apri il file manager di sistema sulla cartella
            try:
                if sys.platform.startswith("win"):
                    os.startfile(already_mounted)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", already_mounted])
                else:
                    xdg = shutil.which("xdg-open") or shutil.which("nautilus") or shutil.which("dolphin")
                    if xdg:
                        subprocess.Popen([xdg, already_mounted])
            except Exception:
                pass
            return

        # ── Non montata: chiedi conferma e tenta mount ────────────────────────
        unc = f"//\"{host}\"/\"{share}\"" if share else f"//\"{host}\""
        reply = QMessageBox.question(
            self, "SMB — Mount share",
            f"La share  \\\\{host}\\{share}  non risulta montata.\n\n"
            f"Vuoi montarla ora con le credenziali del profilo?\n"
            f"  Utente: {dom}\\{user}\n"
            f"  Host:   {host}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._status.setText(f"Mount {host}/{share}…")
        QApplication.processEvents()

        try:
            if sys.platform.startswith("win"):
                # Windows: net use \\host\share password /user:domain\user
                cmd = ["net", "use",
                       f"\\\\{host}\\{share}",
                       pwd or "*",
                       f"/user:{dom}\\{user}"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if result.returncode == 0:
                    mounted_path = f"\\\\{host}\\{share}"
                    self._status.setText(f"✓ Montata: {mounted_path}")
                    QMessageBox.information(self, "SMB",
                        f"✓ Share montata con successo:\n{mounted_path}")
                    os.startfile(mounted_path)
                else:
                    raise RuntimeError(result.stderr.strip() or result.stdout.strip())

            elif sys.platform == "darwin":
                # macOS: mount_smbfs //user:pass@host/share /Volumes/share
                mnt_dir = f"/Volumes/{share or host}"
                os.makedirs(mnt_dir, exist_ok=True)
                safe_pwd = pwd.replace("@", "%40").replace(":", "%3A")
                smb_url  = f"smb://{user}:{safe_pwd}@{host}/{share}"
                result = subprocess.run(
                    ["mount_smbfs", smb_url, mnt_dir],
                    capture_output=True, text=True, timeout=20
                )
                if result.returncode == 0:
                    self._status.setText(f"✓ Montata: {mnt_dir}")
                    QMessageBox.information(self, "SMB",
                        f"✓ Share montata in:\n{mnt_dir}")
                    subprocess.Popen(["open", mnt_dir])
                else:
                    raise RuntimeError(result.stderr.strip() or "mount_smbfs fallito")

            else:
                # Linux: mount.cifs //host/share /mnt/share -o user=,pass=,domain=
                if not shutil.which("mount.cifs") and not shutil.which("mount"):
                    raise RuntimeError(
                        "mount.cifs non trovato.\n"
                        "Installa: sudo apt install cifs-utils"
                    )
                mnt_dir = f"/mnt/smb_{host}_{share}".replace(" ", "_")
                os.makedirs(mnt_dir, exist_ok=True)
                opts = f"username={user},password={pwd},domain={dom},uid={os.getuid()},gid={os.getgid()}"
                cmd = ["pkexec", "mount", "-t", "cifs",
                       f"//{host}/{share}", mnt_dir,
                       "-o", opts]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    self._status.setText(f"✓ Montata: {mnt_dir}")
                    QMessageBox.information(self, "SMB",
                        f"✓ Share montata in:\n{mnt_dir}\n\n"
                        "Puoi aprire i file direttamente da quella cartella.")
                    xdg = shutil.which("xdg-open") or shutil.which("nautilus") or shutil.which("dolphin")
                    if xdg:
                        subprocess.Popen([xdg, mnt_dir])
                else:
                    err = result.stderr.strip() or "mount fallito"
                    raise RuntimeError(err)

        except Exception as exc:
            self._status.setText("Mount fallito")
            QMessageBox.critical(self, "SMB — Errore mount",
                f"Impossibile montare la share:\n\n{exc}\n\n"
                "Suggerimenti:\n"
                "• Linux: sudo apt install cifs-utils\n"
                "• Verifica host, share, credenziali e firewall (porta 445)")

    @staticmethod
    def _smb_find_mount(host: str, share: str) -> Optional[str]:
        """Cerca se //host/share è già montata. Restituisce il mountpoint o None."""
        import sys
        try:
            if sys.platform.startswith("win"):
                # Su Windows controlla se \\host\share è accessibile
                p = f"\\\\{host}\\{share}"
                return p if os.path.isdir(p) else None
            elif sys.platform == "darwin":
                mnt = f"/Volumes/{share}"
                return mnt if os.path.ismount(mnt) else None
            else:
                # Linux: cerca in /proc/mounts
                needle = f"//{host}/{share}"
                needle2 = f"\\\\{host}\\{share}"
                with open("/proc/mounts", "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2:
                            dev, mnt = parts[0], parts[1]
                            if dev.lower() in (needle.lower(), needle2.lower()):
                                return mnt
                # Controlla anche path diretti tipo /mnt/smb_host_share
                candidate = f"/mnt/smb_{host}_{share}".replace(" ", "_")
                if os.path.ismount(candidate):
                    return candidate
        except Exception:
            pass
        return None

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

    def _refresh(self) -> None:
        if self._conn is None:
            self._status.setText(tr("plugin.ftp_not_connected", default="Non connesso"))
            return
        self._list_directory(self._current_dir)

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
            actual_tm = tm.tab_manager_for(tab)
            if actual_tm is None:
                return

            # 1. Aggiorna la linguetta del tab
            idx = actual_tm.indexOf(actual_tm._containers[tab])
            if idx >= 0:
                mod_tab = "* " if tab.is_modified() else ""
                actual_tm.setTabText(idx, f"{mod_tab}{name}")

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
        menu = QMenu(self)

        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                parent_dir, name, is_dir = data
                full_path = str(PurePosixPath(parent_dir) / name)
                if not is_dir:
                    menu.addAction("Apri", lambda: self._download_and_open(full_path))
                menu.addAction("Rinomina", lambda: self._rename(full_path, name))
                menu.addAction("Elimina", lambda: self._delete(full_path, name))
                menu.addSeparator()

        menu.addAction("📄 Nuovo file", self._new_file)
        menu.addAction("📁 Nuova cartella", self._mkdir)
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

    def _new_file(self) -> None:
        if not self._conn:
            QMessageBox.warning(self, "FTP Browser", "Non connesso.")
            return
        name, ok = QInputDialog.getText(self, "Nuovo file", "Nome file:")
        if not ok or not name.strip():
            return
        remote_path = str(PurePosixPath(self._current_dir) / name.strip())
        try:
            kind = self._conn[0]
            buf = io.BytesIO(b"")
            if kind == "ftp":
                self._conn[1].storbinary(f"STOR {remote_path}", buf)
            elif kind == "sftp":
                self._conn[1].putfo(buf, remote_path)
            self._list_directory(self._current_dir)
            self._open_in_editor(remote_path, b"")
            self._status.setText(f"✓ Creato: {remote_path}")
        except Exception as e:
            QMessageBox.warning(self, "FTP Browser", f"Creazione file fallita:\n{e}")

    # ── Upload file corrente ──────────────────────────────────────────────────

    def _do_upload(self, remote_path: str, raw: bytes, profile=None) -> bool:
        """Low-level upload: send raw bytes to remote_path, reconnect if needed.

        Does NOT touch editor state (setModified, mark_saved, etc.).
        Returns True on success.
        """
        if self._conn is None:
            p = profile or self._current_profile
            if not p:
                return False
            self._status.setText(f"Riconnessione a {p.host}…")
            QApplication.processEvents()
            try:
                if p.protocol == "SFTP":
                    self._conn = self._connect_sftp(p)
                else:
                    self._conn = self._connect_ftp(p)
                self._btn_connect.setText("Disconnetti")
                self._current_profile = p
            except Exception as e:
                self._status.setText(f"Riconnessione fallita: {e}")
                return False
        try:
            kind = self._conn[0]
            buf = io.BytesIO(raw)
            if kind == "ftp":
                self._conn[1].storbinary(f"STOR {remote_path}", buf)
            elif kind == "sftp":
                self._conn[1].putfo(buf, remote_path)
            return True
        except Exception as e:
            self._status.setText(f"Upload fallito: {e}")
            self._conn = None
            return False

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
        raw = editor.get_content().encode(editor.encoding, errors="replace")
        if self._do_upload(remote_path, raw, getattr(editor, "_ftp_profile", None)):
            editor.setModified(False)
            self._mw._on_editor_changed(editor)
            self._upload_ok(remote_path)
        else:
            QMessageBox.warning(self, "FTP Browser", "Upload fallito — vedi barra di stato.")

    def upload_editor(self, editor) -> None:
        """Upload a local editor file to the currently browsed FTP directory."""
        if not editor or not editor.file_path:
            QMessageBox.information(self, "FTP Browser", "Il file non è ancora salvato localmente.")
            return
        if not self._conn:
            QMessageBox.information(self, "FTP Browser", "Nessuna connessione FTP attiva.")
            return
        if not self._current_dir:
            QMessageBox.information(self, "FTP Browser", "Nessuna cartella FTP aperta nel browser.")
            return
        remote_path = self._current_dir.rstrip("/") + "/" + editor.file_path.name
        raw = editor.get_content().encode(editor.encoding, errors="replace")
        if self._do_upload(remote_path, raw):
            editor.setModified(False)
            self._mw._on_editor_changed(editor)
            self._upload_ok(remote_path)
        else:
            QMessageBox.warning(self, "FTP Browser", "Upload fallito — vedi barra di stato.")

    def _upload_ok(self, remote_path: str) -> None:
        """Show upload success feedback and refresh the directory listing."""
        msg = tr("plugin.ftp_upload_ok", path=remote_path, default=f"✓ Caricato: {remote_path}")
        self._status.setStyleSheet("font-size: 11px; color: #2ecc71; font-weight: bold;")
        self._status.setText(msg)
        # Show in main window status bar too
        if hasattr(self._mw, "statusBar"):
            self._mw.statusBar().showMessage(msg, 5000)
        # Reset status label style and refresh listing after 4 s
        QTimer.singleShot(4000, self._reset_status_style)
        # Refresh directory so size/date update
        try:
            self._list_directory(self._current_dir)
        except Exception:
            pass

    def _reset_status_style(self) -> None:
        self._status.setStyleSheet("font-size: 11px; color: #888;")

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

        self._dock = QDockWidget(tr("plugin.ftp_browser.dock_title"), main_window)
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
                             tr("plugin.ftp_browser.menu"),
                             lambda: self._dock.setVisible(not self._dock.isVisible()),
                             icon_key="plugin_ftp")
        main_window._menus["plugins"].menuAction().setVisible(True)

    def on_unload(self) -> None:
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()
