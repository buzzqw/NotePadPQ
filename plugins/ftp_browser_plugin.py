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
import ssl
import threading
from pathlib import Path, PurePosixPath
from typing import Optional, List, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QThread
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget,
    QTreeWidgetItem, QPushButton, QLabel, QLineEdit, QSpinBox,
    QComboBox, QDialog, QFormLayout, QDialogButtonBox,
    QMessageBox, QProgressDialog, QMenu, QInputDialog,
    QCheckBox,
)
from PyQt6.QtGui import QIcon, QFont, QColor

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr
from ui.busy_indicator import BusyIndicator


_ORPHANED_FTP_WORKERS: set[QThread] = set()
_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


class _DownloadTooLarge(RuntimeError):
    pass


class _OperationCancelled(RuntimeError):
    pass

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Worker generico per operazioni FTP/SFTP/SMB bloccanti ───────────────────

class _FtpOpWorker(QThread):
    """Esegue in background una funzione bloccante (socket I/O, subprocess).

    Un solo worker alla volta per pannello: connect/list/download/upload
    condividono lo stesso oggetto connessione, non thread-safe per uso
    concorrente.
    """

    finished_ok  = pyqtSignal(object)
    finished_err = pyqtSignal(str)
    finished_cancelled = pyqtSignal(object)

    def __init__(self, fn, *args, **kwargs):
        super().__init__(None)
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as e:
            if self._cancelled.is_set():
                self.finished_cancelled.emit(None)
            else:
                self.finished_err.emit(str(e))
            return
        if not self._cancelled.is_set():
            self.finished_ok.emit(result)
        else:
            self.finished_cancelled.emit(result)


# ─── Modello connessione ──────────────────────────────────────────────────────

class FtpProfile:
    """Dati di una connessione FTP/SFTP/SMB."""

    def __init__(self, name="", host="", port=21, user="anonymous",
                 password="", protocol="FTPS", remote_dir="/",
                 domain="", smb_share="", allow_insecure_ftp=False):
        self.name       = name
        self.host       = host
        self.port       = port
        self.user       = user
        self.password   = password
        self.protocol   = protocol   # "FTP", "SFTP" o "SMB"
        self.remote_dir = remote_dir
        self.domain     = domain      # per SMB/AD
        self.smb_share  = smb_share   # nome share SMB (es. "documents")
        self.allow_insecure_ftp = allow_insecure_ftp

    def to_dict(self) -> dict:
        data = self.__dict__.copy()
        data["password"] = ""
        return data

    @classmethod
    def from_dict(cls, d: dict) -> "FtpProfile":
        p = cls()
        for k, v in d.items():
            if k != "password":
                setattr(p, k, v)
        return p


# ─── Dialog configurazione profilo ────────────────────────────────────────────

class _ProfileDialog(QDialog):

    def __init__(self, profile: Optional[FtpProfile] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("plugin.ftp_browser.profile_dialog_title"))
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
        self._protocol.addItems(["FTPS", "SFTP", "FTP", "SMB"])
        self._protocol.setCurrentText(self._profile.protocol)
        self._remote   = QLineEdit(self._profile.remote_dir)

        self._domain    = QLineEdit(getattr(self._profile, "domain", ""))
        self._domain.setPlaceholderText(tr("plugin.ftp_browser.domain_placeholder"))
        self._smb_share = QLineEdit(getattr(self._profile, "smb_share", ""))
        self._smb_share.setPlaceholderText(tr("plugin.ftp_browser.smb_share_placeholder"))
        self._allow_insecure_ftp = QCheckBox(
            "Allow insecure FTP (credentials and files are unencrypted)")
        self._allow_insecure_ftp.setChecked(
            bool(getattr(self._profile, "allow_insecure_ftp", False)))

        form.addRow(tr("plugin.ftp_browser.label_profile_name"), self._name)
        form.addRow(tr("plugin.ftp_browser.label_host"), self._host)
        form.addRow(tr("plugin.ftp_browser.label_port"), self._port)
        form.addRow(tr("plugin.ftp_browser.label_user"), self._user)
        form.addRow(tr("plugin.ftp_browser.label_password"), self._password)
        form.addRow(tr("plugin.ftp_browser.label_protocol"), self._protocol)
        form.addRow(tr("plugin.ftp_browser.label_remote_dir"), self._remote)
        self._row_domain    = form.addRow(tr("plugin.ftp_browser.label_domain"), self._domain)
        self._row_smb_share = form.addRow(tr("plugin.ftp_browser.label_smb_share"), self._smb_share)
        form.addRow("", self._allow_insecure_ftp)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))

        self._protocol.currentTextChanged.connect(self._on_protocol_changed)
        self._on_protocol_changed(self._protocol.currentText())

    def _on_protocol_changed(self, proto: str) -> None:
        if proto in ("FTP", "FTPS"):
            default_port = 21
        elif proto == "SMB":
            default_port = 445
        else:   # SFTP
            default_port = 22
        if self._port.value() in (21, 22, 445):
            self._port.setValue(default_port)
        is_smb = (proto == "SMB")
        self._allow_insecure_ftp.setVisible(proto == "FTP")
        if hasattr(self, "_remote"):
            self._remote.setEnabled(not is_smb)
        if hasattr(self, "_domain"):
            self._domain.setEnabled(is_smb)
        if hasattr(self, "_smb_share"):
            self._smb_share.setEnabled(is_smb)

    def _on_accept(self) -> None:
        if not self._host.text().strip():
            QMessageBox.warning(self, tr("plugin.ftp_browser.profile_dialog_title"),
                                tr("plugin.ftp_browser.error_host_required"))
            return
        proto = self._protocol.currentText()
        if proto == "SMB" and not self._smb_share.text().strip():
            QMessageBox.warning(self, tr("plugin.ftp_browser.profile_dialog_title"),
                                tr("plugin.ftp_browser.error_smb_share_required"))
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
        self._profile.allow_insecure_ftp = self._allow_insecure_ftp.isChecked()
        self.accept()

    def result_profile(self) -> FtpProfile:
        return self._profile




# ─── Dialog conferma mount SMB ────────────────────────────────────────────────

class _SmbMountDialog(QDialog):
    """Dialog di conferma mount SMB con nota di sicurezza.

    Mostra host/share/credenziali e la nota che le credenziali
    vengono gestite in modo sicuro (file tmpfs / stdin / dialog nativo).
    """

    def __init__(self, host: str, share: str, domain: str, user: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("plugin.ftp_browser.smb_mount_title"))
        self.resize(460, 200)
        self._build_ui(host, share, domain, user)

    def _build_ui(self, host: str, share: str, domain: str, user: str):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        # Intestazione
        title = QLabel(tr("plugin.ftp_browser.smb_mount_question",
                          host=host, share=share, domain=domain, user=user))
        title.setWordWrap(True)
        lay.addWidget(title)

        # Nota sicurezza
        note = QLabel(tr("plugin.ftp_browser.smb_security_note"))
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        lay.addWidget(note)

        lay.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))


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
        self._worker: Optional[_FtpOpWorker] = None
        self._closed    = False
        self._cancel_requested = False

        self._load_profiles()
        self._build_ui()

    # ── Esecuzione asincrona ─────────────────────────────────────────────────

    def _run_async(self, fn, on_ok=None, on_err=None, busy_msg: str = "",
                    cancellable: bool = False) -> bool:
        """Esegue fn() su un worker in background. Un'operazione alla volta."""
        if self._worker is not None and self._worker.isRunning():
            return False
        if busy_msg:
            self._status.setText(busy_msg)
        self._cancel_requested = False
        self._set_busy(True, cancellable)

        worker = _FtpOpWorker(fn)
        worker.finished_ok.connect(lambda result: self._on_async_ok(worker, on_ok, result))
        worker.finished_err.connect(lambda err: self._on_async_err(worker, on_err, err))
        worker.finished_cancelled.connect(lambda result: self._on_async_cancelled(worker, result))
        worker.finished.connect(lambda: self._clear_worker(worker))
        self._worker = worker
        worker.start()
        return True

    def _on_async_ok(self, worker, on_ok, result) -> None:
        self._set_busy(False)
        if self._closed:
            return
        if on_ok:
            on_ok(result)

    def _on_async_err(self, worker, on_err, err: str) -> None:
        self._set_busy(False)
        if self._closed:
            return
        if self._cancel_requested:
            # L'errore è l'effetto atteso della chiusura forzata della
            # connessione da _abort_current_op, non un fallimento reale.
            self._cancel_requested = False
            self._conn = None
            self._btn_connect.setText(tr("plugin.ftp_browser.connect_btn"))
            self._status.setText(
                tr("plugin.ftp_browser.status_cancelled", default="Operazione annullata."))
            return
        if on_err:
            on_err(err)
        else:
            self._status.setText(tr("plugin.ftp_browser.status_conn_error"))
            QMessageBox.warning(self, "FTP/SFTP/SMB", err)

    @staticmethod
    def _close_connection(conn) -> None:
        if not conn:
            return
        try:
            if conn[0] in ("ftp", "ftps"):
                conn[1].close()
            elif conn[0] == "sftp":
                conn[1].close()
                conn[2].close()
        except Exception:
            pass

    def _on_async_cancelled(self, worker, result) -> None:
        """Always restore the panel, including connections created after cancel."""
        self._set_busy(False)
        if result is not self._conn:
            self._close_connection(result)
        self._close_connection(self._conn)
        self._conn = None
        self._cancel_requested = False
        self._btn_connect.setText(tr("plugin.ftp_browser.connect_btn"))
        self._status.setText(
            tr("plugin.ftp_browser.status_cancelled", default="Operazione annullata."))

    def _clear_worker(self, worker) -> None:
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()

    def _set_busy(self, busy: bool, cancellable: bool = False) -> None:
        self._btn_connect.setEnabled(not busy)
        self._tree.setEnabled(not busy)
        self._status.set_busy(busy, cancellable)

    def _abort_current_op(self) -> None:
        """Tenta di interrompere l'operazione in corso chiudendo la
        connessione: sblocca la chiamata socket bloccante nel worker,
        che terminerà con un errore intercettato come cancellazione."""
        if self._worker is None or not self._worker.isRunning():
            return
        self._cancel_requested = True
        self._worker.cancel()
        self._close_connection(self._conn)

    def _notify_busy(self) -> None:
        self._status.setText(
            tr("plugin.ftp_browser.status_busy", default="Operazione FTP già in corso…"))

    def shutdown(self) -> None:
        """Scollega i callback pendenti; il worker in corso termina da solo.

        Disconnette anche 'finished' (non solo finished_ok/finished_err):
        è agganciato a _clear_worker tramite lambda, quindi non viene
        auto-disconnesso da Qt quando il pannello viene distrutto — se il
        worker termina dopo la chiusura del pannello, quella lambda
        chiamerebbe un metodo su un oggetto Qt già cancellato.
        """
        if self._closed:
            return
        self._closed = True
        worker = self._worker
        if worker is not None:
            self._abort_current_op()
            try:
                worker.disconnect()
            except (TypeError, RuntimeError):
                pass
            if worker.isRunning() and not worker.wait(2000):
                _ORPHANED_FTP_WORKERS.add(worker)
                worker.finished.connect(lambda w=worker: _ORPHANED_FTP_WORKERS.discard(w))
            else:
                worker.deleteLater()
        self._worker = None
        self._disconnect()

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

        self._btn_connect = QPushButton(tr("plugin.ftp_browser.connect_btn"))
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
        self._tree.setHeaderLabels([tr("plugin.ftp_browser.col_name"), tr("plugin.ftp_browser.col_size"), tr("plugin.ftp_browser.col_date")])
        self._tree.header().resizeSection(0, 200)
        self._tree.header().resizeSection(1, 80)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree, 1)

        # Barra di stato (etichetta + indicatore di attività + Annulla)
        self._status = BusyIndicator()
        self._status.setText(tr("plugin.ftp_not_connected", default="Non connesso"))
        self._status.setStyleSheet("font-size: 11px; color: #888;")
        self._status.cancelled.connect(self._abort_current_op)
        layout.addWidget(self._status)

    def _populate_combo(self) -> None:
        self._profile_combo.clear()
        for p in self._profiles:
            self._profile_combo.addItem(f"{p.protocol} · {p.name} ({p.host})")
        if not self._profiles:
            self._profile_combo.addItem(tr("plugin.ftp_browser.no_profile"))

    # ── Profili ───────────────────────────────────────────────────────────────

    def _profiles_path(self) -> Path:
        from core.platform import get_data_dir
        return get_data_dir() / "ftp_profiles.json"

    def _load_profiles(self) -> None:
        import json
        from core.secrets import SecretStorageUnavailable, get_secret, set_secret

        p = self._profiles_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._profiles = []
                needs_rewrite = False
                for d in data:
                    if not isinstance(d, dict):
                        continue
                    prof = FtpProfile.from_dict(d)
                    secret_key = f"ftp/{prof.name}/password"
                    legacy_password = d.get("password", "")
                    if isinstance(legacy_password, str) and legacy_password:
                        try:
                            set_secret(secret_key, legacy_password)
                        except SecretStorageUnavailable:
                            # Keep the JSON unchanged: it remains the only copy.
                            self._profiles = []
                            return
                        prof.password = legacy_password
                        needs_rewrite = True
                    else:
                        prof.password = get_secret(secret_key)
                    if not prof.password:
                        try:
                            import keyring
                            legacy_password = keyring.get_password("NotePadPQ_FTP", prof.name)
                            if legacy_password:
                                set_secret(secret_key, legacy_password)
                                prof.password = legacy_password
                                try:
                                    keyring.delete_password("NotePadPQ_FTP", prof.name)
                                except Exception:
                                    pass
                        except SecretStorageUnavailable:
                            self._profiles = []
                            return
                        except Exception:
                            pass
                    self._profiles.append(prof)
                if needs_rewrite:
                    # Old versions wrote passwords into this JSON file. Redact
                    # only after every migration above reached the keyring.
                    self._save_profiles()
            except Exception:
                self._profiles = []

    def _save_profiles(self) -> bool:
        import json
        from core.secrets import SecretStorageUnavailable, set_secret

        try:
            for p in self._profiles:
                if p.password:
                    set_secret(f"ftp/{p.name}/password", p.password)
        except SecretStorageUnavailable as exc:
            print(f"Errore salvataggio nel portachiavi: {exc}")
            return False
        save_list = [p.to_dict() for p in self._profiles]

        try:
            self._profiles_path().write_text(
                json.dumps(save_list, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            return True
        except Exception:
            return False

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
                self._profiles[idx] = new_profile
                saved = self._save_profiles()
                # Do not remove the old credential until the new key was saved.
                if saved and old_name != new_profile.name:
                    from core.secrets import delete_secret
                    try:
                        delete_secret(f"ftp/{old_name}/password")
                    except Exception:
                        pass
                self._populate_combo()
                self._profile_combo.setCurrentIndex(idx)

    def _delete_profile(self) -> None:
        idx = self._profile_combo.currentIndex()
        if 0 <= idx < len(self._profiles):
            p_to_delete = self._profiles[idx]
            reply = QMessageBox.question(
                self, tr("plugin.ftp_browser.delete_profile_title"),
                tr("plugin.ftp_browser.delete_profile_msg", name=p_to_delete.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                from core.secrets import delete_secret
                try:
                    delete_secret(f"ftp/{p_to_delete.name}/password")
                except Exception:
                    pass
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
            QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.select_profile"))
            return

        profile = self._profiles[idx]
        if profile.protocol == "FTP":
            if not getattr(profile, "allow_insecure_ftp", False):
                QMessageBox.warning(
                    self, "FTP/SFTP/SMB",
                    "Plain FTP is disabled because it exposes credentials and files. "
                    "Edit this profile and explicitly allow insecure FTP to continue.")
                return
            if QMessageBox.warning(
                    self, "FTP/SFTP/SMB",
                    "Plain FTP sends credentials and files without encryption. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
                return
        self._current_profile = profile

        # ── SMB: mount helper ─────────────────────────────────────────────────
        if profile.protocol == "SMB":
            self._smb_mount_helper(profile)
            return

        def _do_connect():
            if profile.protocol == "SFTP":
                return self._connect_sftp(profile)
            return self._connect_ftp(profile)

        def _on_ok(conn):
            self._conn = conn
            self._btn_connect.setText(tr("plugin.ftp_browser.disconnect_btn"))
            self._status.setText(tr("plugin.ftp_browser.status_connected", user=profile.user,
                                    host=profile.host, port=profile.port))
            self._list_directory(profile.remote_dir)

        def _on_err(err):
            self._conn = None
            self._status.setText(tr("plugin.ftp_browser.status_conn_error"))
            QMessageBox.critical(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.status_download_failed", error=err))

        self._run_async(
            _do_connect, _on_ok, _on_err,
            busy_msg=tr("plugin.ftp_browser.status_connecting", host=profile.host),
        )

    def _smb_mount_helper(self, profile: FtpProfile) -> None:
        """Controlla se la share SMB è già montata; se no, propone opzioni di mount.

        SICUREZZA: le credenziali NON vengono mai passate come argomenti
        visibili in ps/Task Manager. Linux usa un file credenziali temporaneo
        in tmpfs (/run/user/UID); macOS delega il dialog password al sistema;
        Windows usa stdin per passare la password a net use.
        """
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
            self._status.setText(tr("plugin.ftp_browser.smb_mount_ok", path=already_mounted))
            QMessageBox.information(
                self, tr("plugin.ftp_browser.smb_already_mounted_title"),
                tr("plugin.ftp_browser.smb_already_mounted_msg", path=already_mounted)
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

        # ── Non montata: chiedi conferma ──────────────────────────────────────
        dlg = _SmbMountDialog(host, share, dom, user, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # ── Mount (in background: pkexec/net use possono impiegare fino a 30s) ──
        def _on_ok(result):
            mounted_path, open_kind = result
            if open_kind == "win":
                self._status.setText(tr("plugin.ftp_browser.smb_mount_ok", path=mounted_path))
                QMessageBox.information(self, tr("plugin.ftp_browser.smb_already_mounted_title"),
                    tr("plugin.ftp_browser.smb_mount_ok_win", path=mounted_path))
                os.startfile(mounted_path)
            elif open_kind == "darwin":
                self._status.setText(tr("plugin.ftp_browser.smb_mount_ok", path=mounted_path))
                QMessageBox.information(self, tr("plugin.ftp_browser.smb_already_mounted_title"),
                    tr("plugin.ftp_browser.smb_mount_ok_msg", path=mounted_path))
            else:
                self._status.setText(tr("plugin.ftp_browser.smb_mount_ok", path=mounted_path))
                QMessageBox.information(self, tr("plugin.ftp_browser.smb_already_mounted_title"),
                    tr("plugin.ftp_browser.smb_mount_ok_msg", path=mounted_path))
                xdg = shutil.which("xdg-open") or shutil.which("nautilus") or shutil.which("dolphin")
                if xdg:
                    subprocess.Popen([xdg, mounted_path])

        def _on_err(err):
            self._status.setText(tr("plugin.ftp_browser.status_conn_error"))
            QMessageBox.critical(self, tr("plugin.ftp_browser.smb_mount_failed_title"),
                tr("plugin.ftp_browser.smb_mount_failed_msg", error=err))

        self._run_async(
            lambda: self._smb_mount_blocking(host, share, user, pwd, dom),
            _on_ok, _on_err,
            busy_msg=tr("plugin.ftp_browser.smb_mounting", host=host, share=share),
        )

    @staticmethod
    def _smb_mount_blocking(host: str, share: str, user: str, pwd: str, dom: str):
        """Esegue il mount SMB (bloccante — va chiamato da worker in background).

        Ritorna (mounted_path, platform_kind) dove platform_kind indica al
        chiamante (sul thread UI) quale dialog/azione post-mount eseguire.
        """
        import sys
        import subprocess
        import shutil

        if sys.platform.startswith("win"):
            # Windows: net use \\host\share /user:domain\user
            # La password è passata via STDIN — non visibile in ps/Task Manager
            unc = f"\\\\{host}\\{share}"
            cmd = ["net", "use", unc, f"/user:{dom}\\{user}"]
            result = subprocess.run(
                cmd,
                input=(pwd + "\n") if pwd else "\n",
                capture_output=True, text=True, timeout=20
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            return unc, "win"

        elif sys.platform == "darwin":
            # macOS: apre la URL smb://user@host/share SENZA password nell'URL.
            # Il sistema operativo mostra il suo dialog nativo per la password.
            smb_url = f"smb://{user}@{host}/{share}" if share else f"smb://{user}@{host}"
            result = subprocess.run(
                ["open", smb_url],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "open smb:// fallito")
            return smb_url, "darwin"

        else:
            # Linux: usa un file credenziali temporaneo in /run/user/UID (tmpfs).
            # La password NON appare come argomento del processo (non visibile in ps).
            if not shutil.which("mount.cifs") and not shutil.which("mount"):
                raise RuntimeError(tr("plugin.ftp_browser.smb_cifs_missing"))

            mnt_dir = f"/mnt/smb_{host}_{share}".replace(" ", "_")
            os.makedirs(mnt_dir, exist_ok=True)

            # Directory sicura in tmpfs (non sul disco fisso)
            run_dir = f"/run/user/{os.getuid()}"
            if not os.path.isdir(run_dir):
                run_dir = "/tmp"  # fallback

            import tempfile, stat
            cred_fd, cred_path = tempfile.mkstemp(prefix="npq_smb_", dir=run_dir)
            try:
                # Scrivi il file credenziali con permessi 0600 (solo owner)
                os.chmod(cred_path, stat.S_IRUSR | stat.S_IWUSR)
                cred_content = (
                    f"username={user}\n"
                    f"password={pwd}\n"
                    f"domain={dom}\n"
                )
                os.write(cred_fd, cred_content.encode())
                os.close(cred_fd)

                opts = (
                    f"credentials={cred_path},"
                    f"uid={os.getuid()},gid={os.getgid()}"
                )
                cmd = ["pkexec", "mount", "-t", "cifs",
                       f"//{host}/{share}", mnt_dir,
                       "-o", opts]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            finally:
                # Elimina sempre il file credenziali, anche in caso di errore
                try:
                    os.unlink(cred_path)
                except Exception:
                    pass

            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "mount fallito")
            return mnt_dir, "linux"

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
        if profile.protocol == "FTPS":
            # create_default_context validates the certificate chain and hostname.
            ftp = ftplib.FTP_TLS(context=ssl.create_default_context())
        else:
            ftp = ftplib.FTP()
        ftp.connect(profile.host, profile.port, timeout=15)
        ftp.login(profile.user, profile.password)
        if profile.protocol == "FTPS":
            ftp.prot_p()
            return ("ftps", ftp)
        return ("ftp", ftp)

    def _connect_sftp(self, profile: FtpProfile):
        try:
            import paramiko
        except ImportError:
            raise RuntimeError(tr("plugin.ftp_browser.sftp_missing"))
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        # Non accettare automaticamente chiavi sconosciute: altrimenti una
        # connessione SFTP può essere intercettata senza alcun avviso.
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
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
                if kind in ("ftp", "ftps"):
                    self._conn[1].quit()
                elif kind == "sftp":
                    self._conn[1].close()
                    self._conn[2].close()
            except Exception:
                pass
        self._conn = None
        self._btn_connect.setText(tr("plugin.ftp_browser.connect_btn"))
        self._status.setText(tr("plugin.ftp_browser.status_disconnected"))
        self._tree.clear()

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _list_directory(self, path: str) -> None:
        self._current_dir = path
        self._path_label.setText(path)
        self._tree.clear()

        def _on_ok(entries):
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
            self._status.setText(tr("plugin.ftp_browser.status_listing_count", count=count, path=path))

        def _on_err(err):
            self._status.setText(tr("plugin.ftp_browser.status_read_error"))
            QMessageBox.warning(self, "FTP/SFTP/SMB", err)

        started = self._run_async(
            lambda: self._fetch_listing(path), _on_ok, _on_err,
            busy_msg=tr("plugin.ftp_browser.status_listing", path=path),
            cancellable=True,
        )
        if not started:
            # Un'altra operazione è già in corso (es. connessione appena avviata
            # che sta per richiamare questo stesso metodo): riprova a breve.
            QTimer.singleShot(200, lambda: self._list_directory(path))

    def _fetch_listing(self, path: str) -> list:
        """Restituisce [(name, size, date, is_dir), ...]"""
        if not self._conn:
            return []
        kind = self._conn[0]

        if kind in ("ftp", "ftps"):
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
        def _on_ok(content):
            self._open_in_editor(remote_path, content)
            self._status.setText(tr("plugin.ftp_browser.status_download_ok", path=remote_path))

        def _on_err(err):
            self._status.setText(tr("plugin.ftp_browser.status_download_error"))
            QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.status_download_failed", error=err))

        self._run_async(
            lambda: self._fetch_file(remote_path), _on_ok, _on_err,
            busy_msg=tr("plugin.ftp_browser.status_downloading", path=remote_path),
            cancellable=True,
        )

    def _fetch_file(self, remote_path: str) -> bytes:
        """Download in bounded chunks so remote content cannot exhaust memory."""
        kind = self._conn[0]
        buf = io.BytesIO()
        worker = self._worker

        def cancelled() -> bool:
            return worker is not None and worker._cancelled.is_set()

        def write_chunk(chunk: bytes) -> None:
            if cancelled():
                raise _OperationCancelled()
            if buf.tell() + len(chunk) > _MAX_DOWNLOAD_BYTES:
                raise _DownloadTooLarge(
                    f"Download exceeds the {self._fmt_size(_MAX_DOWNLOAD_BYTES)} safety limit")
            buf.write(chunk)

        if kind in ("ftp", "ftps"):
            size = self._conn[1].size(remote_path)
            if size is not None and size > _MAX_DOWNLOAD_BYTES:
                raise _DownloadTooLarge(
                    f"Download exceeds the {self._fmt_size(_MAX_DOWNLOAD_BYTES)} safety limit")
            self._conn[1].retrbinary(f"RETR {remote_path}", write_chunk, blocksize=64 * 1024)
        elif kind == "sftp":
            sftp = self._conn[1]
            if sftp.stat(remote_path).st_size > _MAX_DOWNLOAD_BYTES:
                raise _DownloadTooLarge(
                    f"Download exceeds the {self._fmt_size(_MAX_DOWNLOAD_BYTES)} safety limit")
            with sftp.open(remote_path, "rb") as remote:
                while True:
                    if cancelled():
                        raise _OperationCancelled()
                    chunk = remote.read(64 * 1024)
                    if not chunk:
                        break
                    write_chunk(chunk)
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
                    menu.addAction(tr("plugin.ftp_browser.ctx_open"), lambda: self._download_and_open(full_path))
                menu.addAction(tr("plugin.ftp_browser.ctx_rename"), lambda: self._rename(full_path, name))
                menu.addAction(tr("plugin.ftp_browser.ctx_delete"), lambda: self._delete(full_path, name))
                menu.addSeparator()

        menu.addAction(tr("plugin.ftp_browser.ctx_new_file"), self._new_file)
        menu.addAction(tr("plugin.ftp_browser.ctx_new_folder"), self._mkdir)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _rename(self, path: str, old_name: str) -> None:
        new_name, ok = QInputDialog.getText(
            self, tr("plugin.ftp_browser.rename_dialog_title"),
            tr("plugin.ftp_browser.rename_dialog_label"), text=old_name
        )
        if not ok or not new_name.strip() or new_name == old_name:
            return
        new_path = str(PurePosixPath(path).parent / new_name)

        def _do():
            kind = self._conn[0]
            if kind in ("ftp", "ftps", "sftp"):
                self._conn[1].rename(path, new_path)

        def _on_err(err):
            QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.rename_failed", error=err))

        if not self._run_async(_do, lambda _r: self._list_directory(self._current_dir), _on_err,
                                cancellable=True):
            self._notify_busy()

    def _delete(self, path: str, name: str) -> None:
        reply = QMessageBox.question(
            self, tr("plugin.ftp_browser.delete_dialog_title"),
            tr("plugin.ftp_browser.delete_dialog_msg", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def _do():
            kind = self._conn[0]
            if kind in ("ftp", "ftps"):
                try:
                    self._conn[1].delete(path)
                except Exception:
                    self._conn[1].rmd(path)
            elif kind == "sftp":
                self._conn[1].remove(path)

        def _on_err(err):
            QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.delete_failed", error=err))

        if not self._run_async(_do, lambda _r: self._list_directory(self._current_dir), _on_err,
                                cancellable=True):
            self._notify_busy()

    def _mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, tr("plugin.ftp_browser.mkdir_dialog_title"),
                                        tr("plugin.ftp_browser.mkdir_dialog_label"))
        if not ok or not name.strip():
            return
        new_path = str(PurePosixPath(self._current_dir) / name)

        def _do():
            kind = self._conn[0]
            if kind in ("ftp", "ftps"):
                self._conn[1].mkd(new_path)
            elif kind == "sftp":
                self._conn[1].mkdir(new_path)

        def _on_err(err):
            QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.mkdir_failed", error=err))

        if not self._run_async(_do, lambda _r: self._list_directory(self._current_dir), _on_err,
                                cancellable=True):
            self._notify_busy()

    def _new_file(self) -> None:
        if not self._conn:
            QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.new_file_not_connected"))
            return
        name, ok = QInputDialog.getText(self, tr("plugin.ftp_browser.new_file_dialog_title"),
                                        tr("plugin.ftp_browser.new_file_dialog_label"))
        if not ok or not name.strip():
            return
        remote_path = str(PurePosixPath(self._current_dir) / name.strip())

        def _do():
            kind = self._conn[0]
            buf = io.BytesIO(b"")
            if kind in ("ftp", "ftps"):
                self._conn[1].storbinary(f"STOR {remote_path}", buf)
            elif kind == "sftp":
                self._conn[1].putfo(buf, remote_path)

        def _on_ok(_result):
            self._list_directory(self._current_dir)
            self._open_in_editor(remote_path, b"")
            self._status.setText(tr("plugin.ftp_browser.status_file_created", path=remote_path))

        def _on_err(err):
            QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.new_file_failed", error=err))

        if not self._run_async(_do, _on_ok, _on_err, cancellable=True):
            self._notify_busy()

    # ── Upload file corrente ──────────────────────────────────────────────────

    def _do_upload(self, remote_path: str, raw: bytes, profile=None, on_done=None) -> bool:
        """Upload asincrono: invia raw bytes a remote_path, riconnettendo se serve.

        Non tocca lo stato dell'editor (setModified, mark_saved, ecc.):
        a operazione completata chiama on_done(ok: bool) se fornita.
        Ritorna True se l'operazione è stata avviata (non l'esito dell'upload,
        disponibile solo in on_done).
        """
        p = profile or self._current_profile
        reconnecting = self._conn is None

        def _do():
            conn = self._conn
            if conn is None:
                if not p:
                    raise RuntimeError(tr("plugin.ftp_browser.not_connected_upload"))
                conn = self._connect_sftp(p) if p.protocol == "SFTP" else self._connect_ftp(p)
            kind = conn[0]
            buf = io.BytesIO(raw)
            if kind in ("ftp", "ftps"):
                conn[1].storbinary(f"STOR {remote_path}", buf)
            elif kind == "sftp":
                conn[1].putfo(buf, remote_path)
            return conn

        def _on_ok(conn):
            if self._conn is None:
                self._conn = conn
                self._btn_connect.setText(tr("plugin.ftp_browser.disconnect_btn"))
                self._current_profile = p
            if on_done:
                on_done(True)

        def _on_err(err):
            self._status.setText(tr("plugin.ftp_browser.status_upload_failed", error=err))
            self._conn = None
            if on_done:
                on_done(False)

        busy_msg = (tr("plugin.ftp_browser.status_reconnecting", host=p.host)
                    if reconnecting and p else "")
        # Annulla non disponibile durante la riconnessione: non c'è ancora
        # una connessione da chiudere per interrompere la chiamata bloccante.
        return self._run_async(_do, _on_ok, _on_err, busy_msg=busy_msg,
                                cancellable=not reconnecting)

    def upload_current(self) -> None:
        """Carica il file corrente dell'editor sul server (se proveniente da FTP)."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        remote_path = getattr(editor, "_ftp_remote_path", None)
        if not remote_path:
            QMessageBox.information(
                self, "FTP/SFTP/SMB",
                tr("plugin.ftp_browser.not_connected_upload")
            )
            return
        if getattr(editor, "_paged_doc", None) is not None:
            # editor.get_content() è solo la pagina caricata su un tab
            # paginato (>200MB): caricare qui sostituirebbe silenziosamente il
            # file remoto con la sola pagina corrente.
            QMessageBox.warning(
                self, "FTP/SFTP/SMB",
                tr("plugin.ftp_browser.paged_upload_unavailable",
                   default="Non disponibile per file di grandi dimensioni in "
                           "modalità paginata.")
            )
            return
        raw = editor.get_content().encode(editor.encoding, errors="replace")

        def _on_done(ok: bool) -> None:
            if ok:
                editor.setModified(False)
                self._mw._on_editor_changed(editor)
                self._upload_ok(remote_path)
            else:
                QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.upload_failed_msg"))

        if not self._do_upload(remote_path, raw, getattr(editor, "_ftp_profile", None), _on_done):
            self._mw.statusBar().showMessage(
                tr("plugin.ftp_browser.status_busy", default="Operazione FTP già in corso…"), 3000)

    def upload_editor(self, editor) -> None:
        """Upload a local editor file to the currently browsed FTP directory."""
        if not editor or not editor.file_path:
            QMessageBox.information(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.not_saved_upload"))
            return
        if not self._conn:
            QMessageBox.information(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.no_active_conn_upload"))
            return
        if not self._current_dir:
            QMessageBox.information(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.no_folder_open_upload"))
            return
        remote_path = self._current_dir.rstrip("/") + "/" + editor.file_path.name
        raw = editor.get_content().encode(editor.encoding, errors="replace")

        def _on_done(ok: bool) -> None:
            if ok:
                editor.setModified(False)
                self._mw._on_editor_changed(editor)
                self._upload_ok(remote_path)
            else:
                QMessageBox.warning(self, "FTP/SFTP/SMB", tr("plugin.ftp_browser.upload_failed_msg"))

        if not self._do_upload(remote_path, raw, on_done=_on_done):
            self._mw.statusBar().showMessage(
                tr("plugin.ftp_browser.status_busy", default="Operazione FTP già in corso…"), 3000)

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

    NAME        = "FTP/SFTP/SMB Browser"
    VERSION     = "1.1"
    DESCRIPTION = "FTP/SFTP navigation panel with SMB mount helper."
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
        if hasattr(self, "_panel"):
            self._panel.shutdown()
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()
