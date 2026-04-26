"""
plugins/encrypt_plugin.py — Plugin Encrypt/Decrypt
NotePadPQ

Cifratura e decifratura del testo selezionato (o dell'intero documento).

Algoritmi supportati:
  - AES-256-GCM       (AEAD, raccomandato, default)
  - ChaCha20-Poly1305 (AEAD, moderno, veloce)
  - AES-256-CBC
  - AES-128-CBC
  - DES-CBC       (compatibilità legacy)
  - 3DES-CBC      (Triple DES)
  - XOR           (semplice, nessuna dipendenza esterna)
  - Caesar cipher (shift configurabile, per testo ASCII)

Dipendenza:
  pip install cryptography

Se cryptography non è installato, rimangono disponibili solo XOR e Caesar.
Il testo cifrato viene codificato in Base64 per essere incollabile come testo.

Menu: Strumenti → 🔐 Encrypt/Decrypt
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct
from typing import Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QDialogButtonBox, QMessageBox, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeySequence

from plugins.base_plugin import BasePlugin

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


# ─── Algoritmi ────────────────────────────────────────────────────────────────

def _derive_key(password: str, salt: bytes, key_len: int) -> bytes:
    """Deriva una chiave dalla password tramite PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000, key_len)


def _aes_gcm_encrypt(text: str, password: str) -> str:
    """AES-256-GCM encrypt → Base64. AEAD: autentica il ciphertext."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt  = os.urandom(16)
    nonce = os.urandom(12)
    key   = _derive_key(password, salt, 32)

    ct_with_tag = AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)
    return base64.b64encode(salt + nonce + ct_with_tag).decode("ascii")


def _aes_gcm_decrypt(b64text: str, password: str) -> str:
    """AES-256-GCM decrypt da Base64."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    blob  = base64.b64decode(b64text.strip())
    salt  = blob[:16]
    nonce = blob[16:28]
    ct    = blob[28:]
    key   = _derive_key(password, salt, 32)

    plain = AESGCM(key).decrypt(nonce, ct, None)
    return plain.decode("utf-8")


def _chacha20_encrypt(text: str, password: str) -> str:
    """ChaCha20-Poly1305 encrypt → Base64. AEAD."""
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    salt  = os.urandom(16)
    nonce = os.urandom(12)
    key   = _derive_key(password, salt, 32)

    ct_with_tag = ChaCha20Poly1305(key).encrypt(nonce, text.encode("utf-8"), None)
    return base64.b64encode(salt + nonce + ct_with_tag).decode("ascii")


def _chacha20_decrypt(b64text: str, password: str) -> str:
    """ChaCha20-Poly1305 decrypt da Base64."""
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    blob  = base64.b64decode(b64text.strip())
    salt  = blob[:16]
    nonce = blob[16:28]
    ct    = blob[28:]
    key   = _derive_key(password, salt, 32)

    plain = ChaCha20Poly1305(key).decrypt(nonce, ct, None)
    return plain.decode("utf-8")


def _aes_encrypt(text: str, password: str, key_len: int = 32) -> str:
    """AES-CBC encrypt → Base64."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.backends import default_backend

    salt = os.urandom(16)
    iv   = os.urandom(16)
    key  = _derive_key(password, salt, key_len)

    padder  = sym_padding.PKCS7(128).padder()
    padded  = padder.update(text.encode("utf-8")) + padder.finalize()

    cipher  = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    enc     = cipher.encryptor()
    ct      = enc.update(padded) + enc.finalize()

    # Formato: salt(16) + iv(16) + ciphertext
    blob = salt + iv + ct
    return base64.b64encode(blob).decode("ascii")


def _aes_decrypt(b64text: str, password: str, key_len: int = 32) -> str:
    """AES-CBC decrypt da Base64."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.backends import default_backend

    blob = base64.b64decode(b64text.strip())
    salt = blob[:16]
    iv   = blob[16:32]
    ct   = blob[32:]
    key  = _derive_key(password, salt, key_len)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    dec    = cipher.decryptor()
    padded = dec.update(ct) + dec.finalize()

    unpadder = sym_padding.PKCS7(128).unpadder()
    plain    = unpadder.update(padded) + unpadder.finalize()
    return plain.decode("utf-8")


def _des_encrypt(text: str, password: str, triple: bool = False) -> str:
    """DES/3DES-CBC encrypt → Base64."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.backends import default_backend

    key_len = 24 if triple else 8
    salt    = os.urandom(8)
    iv      = os.urandom(8)
    key     = _derive_key(password, salt, key_len)

    padder  = sym_padding.PKCS7(64).padder()
    padded  = padder.update(text.encode("utf-8")) + padder.finalize()

    algo   = algorithms.TripleDES(key) if triple else algorithms.TripleDES(key * 3)
    cipher = Cipher(algo, modes.CBC(iv), backend=default_backend())
    enc    = cipher.encryptor()
    ct     = enc.update(padded) + enc.finalize()

    blob = salt + iv + ct
    return base64.b64encode(blob).decode("ascii")


def _des_decrypt(b64text: str, password: str, triple: bool = False) -> str:
    """DES/3DES-CBC decrypt da Base64."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.backends import default_backend

    blob    = base64.b64decode(b64text.strip())
    key_len = 24 if triple else 8
    salt    = blob[:8]
    iv      = blob[8:16]
    ct      = blob[16:]
    key     = _derive_key(password, salt, key_len)

    algo   = algorithms.TripleDES(key) if triple else algorithms.TripleDES(key * 3)
    cipher = Cipher(algo, modes.CBC(iv), backend=default_backend())
    dec    = cipher.decryptor()
    padded = dec.update(ct) + dec.finalize()

    unpadder = sym_padding.PKCS7(64).unpadder()
    plain    = unpadder.update(padded) + unpadder.finalize()
    return plain.decode("utf-8")


def _xor_crypt(text: str, password: str) -> str:
    """XOR semplice → Base64. Reversibile (stessa operazione per encrypt/decrypt)."""
    if not password:
        return text
    key   = password.encode("utf-8")
    raw   = text.encode("utf-8")
    out   = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return base64.b64encode(out).decode("ascii")


def _xor_decrypt(b64text: str, password: str) -> str:
    """XOR decrypt da Base64."""
    raw = base64.b64decode(b64text.strip())
    key = password.encode("utf-8")
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return out.decode("utf-8", errors="replace")


def _caesar_encrypt(text: str, shift: int) -> str:
    result = []
    for ch in text:
        if ch.isupper():
            result.append(chr((ord(ch) - 65 + shift) % 26 + 65))
        elif ch.islower():
            result.append(chr((ord(ch) - 97 + shift) % 26 + 97))
        else:
            result.append(ch)
    return "".join(result)


def _caesar_decrypt(text: str, shift: int) -> str:
    return _caesar_encrypt(text, -shift)


def _has_cryptography() -> bool:
    try:
        import cryptography  # noqa
        return True
    except ImportError:
        return False


# ─── Dialog ───────────────────────────────────────────────────────────────────

class _EncryptDialog(QDialog):

    def __init__(self, mode: str, parent=None):
        """mode: 'encrypt' o 'decrypt'"""
        super().__init__(parent)
        self.mode   = mode
        self.result_text: Optional[str] = None
        self.setWindowTitle("Cifratura" if mode == "encrypt" else "Decifratura")
        self.resize(400, 220)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form   = QFormLayout()

        # Algoritmo
        self._algo = QComboBox()
        has_crypto = _has_cryptography()
        if has_crypto:
            self._algo.addItems([
                "AES-256-GCM",
                "ChaCha20-Poly1305",
                "AES-256-CBC",
                "AES-128-CBC",
                "3DES-CBC",
                "DES-CBC",
            ])
        self._algo.addItems(["XOR", "Caesar cipher"])
        form.addRow("Algoritmo:", self._algo)

        # Password
        self._pwd = QLineEdit()
        self._pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._pwd.setPlaceholderText("Password / chiave di cifratura")
        form.addRow("Password:", self._pwd)

        self._show_pwd = QCheckBox("Mostra password")
        self._show_pwd.toggled.connect(
            lambda v: self._pwd.setEchoMode(
                QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password
            )
        )
        form.addRow("", self._show_pwd)

        # Shift Caesar (visibile solo se Caesar selezionato)
        self._shift_label = QLabel("Shift (1-25):")
        self._shift = QLineEdit("13")
        self._shift.setMaximumWidth(60)
        form.addRow(self._shift_label, self._shift)
        self._shift_label.setVisible(False)
        self._shift.setVisible(False)

        self._algo.currentTextChanged.connect(self._on_algo_changed)

        layout.addLayout(form)

        if not _has_cryptography():
            warn = QLabel(
                "⚠ 'cryptography' non installata.\n"
                "Solo XOR e Caesar disponibili.\n"
                "Installa con: pip install cryptography"
            )
            warn.setStyleSheet("color: #f0a000; font-size: 11px;")
            layout.addWidget(warn)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_algo_changed(self, algo: str) -> None:
        is_caesar = algo == "Caesar cipher"
        self._shift_label.setVisible(is_caesar)
        self._shift.setVisible(is_caesar)
        pwd_needed = algo != "Caesar cipher"
        self._pwd.setEnabled(pwd_needed)

    def _on_ok(self) -> None:
        algo = self._algo.currentText()
        pwd  = self._pwd.text()

        if algo != "Caesar cipher" and not pwd:
            QMessageBox.warning(self, "Encrypt", "Inserire una password.")
            return

        self.result_algo     = algo
        self.result_password = pwd
        try:
            self.result_shift = int(self._shift.text())
        except ValueError:
            self.result_shift = 13
        self.accept()


# ─── Operazioni ───────────────────────────────────────────────────────────────

def _get_target(editor: "EditorWidget"):
    if editor.hasSelectedText():
        return editor.selectedText(), True
    return editor.text(), False


def _apply(editor: "EditorWidget", result: str, had_sel: bool) -> None:
    if had_sel:
        editor.replaceSelectedText(result)
    else:
        editor.beginUndoAction()
        editor.selectAll()
        editor.replaceSelectedText(result)
        editor.endUndoAction()


def do_encrypt(editor: "EditorWidget", parent) -> None:
    text, sel = _get_target(editor)
    if not text:
        return

    dlg = _EncryptDialog("encrypt", parent)
    if not dlg.exec():
        return

    try:
        algo = dlg.result_algo
        pwd  = dlg.result_password

        if algo == "AES-256-GCM":
            result = _aes_gcm_encrypt(text, pwd)
        elif algo == "ChaCha20-Poly1305":
            result = _chacha20_encrypt(text, pwd)
        elif algo == "AES-256-CBC":
            result = _aes_encrypt(text, pwd, 32)
        elif algo == "AES-128-CBC":
            result = _aes_encrypt(text, pwd, 16)
        elif algo == "3DES-CBC":
            result = _des_encrypt(text, pwd, triple=True)
        elif algo == "DES-CBC":
            result = _des_encrypt(text, pwd, triple=False)
        elif algo == "XOR":
            result = _xor_crypt(text, pwd)
        elif algo == "Caesar cipher":
            result = _caesar_encrypt(text, dlg.result_shift)
        else:
            return

        _apply(editor, result, sel)

    except Exception as e:
        QMessageBox.critical(parent, "Errore cifratura", str(e))


def do_decrypt(editor: "EditorWidget", parent) -> None:
    text, sel = _get_target(editor)
    if not text:
        return

    dlg = _EncryptDialog("decrypt", parent)
    if not dlg.exec():
        return

    try:
        algo = dlg.result_algo
        pwd  = dlg.result_password

        if algo == "AES-256-GCM":
            result = _aes_gcm_decrypt(text, pwd)
        elif algo == "ChaCha20-Poly1305":
            result = _chacha20_decrypt(text, pwd)
        elif algo == "AES-256-CBC":
            result = _aes_decrypt(text, pwd, 32)
        elif algo == "AES-128-CBC":
            result = _aes_decrypt(text, pwd, 16)
        elif algo == "3DES-CBC":
            result = _des_decrypt(text, pwd, triple=True)
        elif algo == "DES-CBC":
            result = _des_decrypt(text, pwd, triple=False)
        elif algo == "XOR":
            result = _xor_decrypt(text, pwd)
        elif algo == "Caesar cipher":
            result = _caesar_decrypt(text, dlg.result_shift)
        else:
            return

        _apply(editor, result, sel)

    except Exception as e:
        QMessageBox.critical(parent, "Errore decifratura",
                             f"Decifratura fallita:\n{e}\n\n"
                             "Verifica password e algoritmo.")


# ─── Plugin ───────────────────────────────────────────────────────────────────

class EncryptPlugin(BasePlugin):

    NAME        = "Encrypt/Decrypt"
    VERSION     = "1.0"
    DESCRIPTION = (
        "Cifratura AES-256-GCM, ChaCha20-Poly1305, AES-256/128-CBC, 3DES, DES, XOR e Caesar cipher "
        "sul testo selezionato. Richiede 'pip install cryptography' per gli algoritmi forti."
    )
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        tools_menu = main_window._menus.get("tools")
        if not tools_menu:
            return

        sub = QMenu("🔐 Encrypt/Decrypt", main_window)

        def _ed():
            return main_window._tab_manager.current_editor()

        act_enc = QAction("🔒 Cifra testo selezionato…", main_window)
        act_enc.setShortcut(QKeySequence("Ctrl+Shift+E"))
        act_enc.triggered.connect(
            lambda: _ed() and do_encrypt(_ed(), main_window)
        )
        sub.addAction(act_enc)
        self._menu_actions.append(act_enc)

        act_dec = QAction("🔓 Decifra testo selezionato…", main_window)
        act_dec.setShortcut(QKeySequence("Ctrl+Shift+W"))
        act_dec.triggered.connect(
            lambda: _ed() and do_decrypt(_ed(), main_window)
        )
        sub.addAction(act_dec)
        self._menu_actions.append(act_dec)

        tools_menu.addSeparator()
        tools_menu.addMenu(sub)
        self._menu_actions.append(sub.menuAction())
