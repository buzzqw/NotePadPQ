"""
core/file_manager.py — Gestione I/O file
NotePadPQ

Gestisce lettura e scrittura file con:
- Rilevamento automatico encoding (chardet + euristiche)
- Gestione BOM (UTF-8, UTF-16, UTF-32)
- Rilevamento e conservazione line endings
- Backup automatico prima del salvataggio
- Watcher per modifiche esterne (QFileSystemWatcher)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QFileSystemWatcher, pyqtSignal

from editor.editor_widget import LineEnding
from core.platform import get_config_dir

try:
    import chardet as _chardet
except ImportError:
    _chardet = None

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# ─── Costanti encoding ────────────────────────────────────────────────────────

# BOM signatures → (encoding, bom_bytes)
_BOM_MAP = [
    (b"\xff\xfe\x00\x00", "UTF-32-LE"),
    (b"\x00\x00\xfe\xff", "UTF-32-BE"),
    (b"\xff\xfe",         "UTF-16-LE"),
    (b"\xfe\xff",         "UTF-16-BE"),
    (b"\xef\xbb\xbf",    "UTF-8-SIG"),
]

# Encoding da tentare in fallback
_FALLBACK_ENCODINGS = [
    "utf-8", "latin-1", "cp1252", "iso-8859-15",
    "gb2312", "gbk", "big5", "koi8-r", "cp1251",
]

# ─── FileManager ─────────────────────────────────────────────────────────────

class FileManager:
    """Classe utility statica per I/O file. Nessuno stato interno."""

    @staticmethod
    def read(path: Path) -> tuple[str, str, LineEnding]:
        """
        Legge un file e restituisce (testo, encoding, line_ending).
        Rileva BOM, encoding e line ending automaticamente.
        Lancia IOError in caso di errore lettura.
        """
        raw = path.read_bytes()

        # Rilevamento BOM
        encoding, bom_len = FileManager._detect_bom(raw)
        if encoding:
            content_bytes = raw[bom_len:]
            try:
                text = content_bytes.decode(encoding)
                le = LineEnding.detect(text)
                return text, encoding.upper().replace("-SIG", " BOM"), le
            except UnicodeDecodeError:
                pass

        # chardet
        detected_enc = FileManager._chardet_detect(raw)

        # Tentativo con encoding rilevato poi fallback
        for enc in ([detected_enc] if detected_enc else []) + _FALLBACK_ENCODINGS:
            try:
                text = raw.decode(enc)
                le = LineEnding.detect(text)
                display_enc = enc.upper()
                return text, display_enc, le
            except (UnicodeDecodeError, LookupError):
                continue

        # Ultimo fallback: latin-1 non fallisce mai
        text = raw.decode("latin-1", errors="replace")
        le = LineEnding.detect(text)
        return text, "Latin-1", le

    @staticmethod
    def write(path: Path, content: str, encoding: str,
              write_bom: bool = False,
              backup: bool = False) -> None:
        """
        Scrive un file con l'encoding specificato.
        write_bom: aggiunge BOM per UTF-8/UTF-16.
        backup: crea <file>.bak prima di sovrascrivere.
        Lancia IOError in caso di errore scrittura.
        """
        if backup and path.exists():
            FileManager._make_backup(path)

        # Normalizza nome encoding
        enc_clean = encoding.upper().replace(" BOM", "-SIG").replace(" ", "-")

        # Gestione BOM esplicito
        if write_bom and enc_clean == "UTF-8":
            enc_clean = "UTF-8-SIG"

        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            path.write_text(content, encoding=enc_clean)
        except (LookupError, UnicodeEncodeError) as e:
            # Fallback a UTF-8 se l'encoding non è supportato
            path.write_text(content, encoding="utf-8")

    @staticmethod
    def _detect_bom(raw: bytes) -> tuple[Optional[str], int]:
        """Rileva BOM all'inizio del file. Restituisce (encoding, bom_len)."""
        for bom, enc in _BOM_MAP:
            if raw.startswith(bom):
                return enc, len(bom)
        return None, 0

    @staticmethod
    def _chardet_detect(raw: bytes) -> Optional[str]:
        """Usa chardet per rilevare l'encoding. Restituisce None se non disponibile."""
        if _chardet is None:
            return None
        result = _chardet.detect(raw[:4096])  # campione iniziale
        if result and result.get("confidence", 0) > 0.7:
            enc = result.get("encoding", "")
            return enc if enc else None
        return None

    @staticmethod
    def _make_backup(path: Path) -> None:
        """Crea una copia di backup del file."""
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(str(path), str(backup_path))
        except Exception:
            pass


# ─── FileWatcher ─────────────────────────────────────────────────────────────

class FileWatcher(QObject):
    """
    Monitora i file aperti per rilevare modifiche esterne.
    Emette file_changed(path) quando un file viene modificato o eliminato.
    """

    file_changed  = pyqtSignal(str)   # path stringa
    file_deleted  = pyqtSignal(str)

    _instance: Optional["FileWatcher"] = None

    def __init__(self):
        super().__init__()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watched: set[str] = set()

    @classmethod
    def instance(cls) -> "FileWatcher":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def watch(self, path: Path) -> None:
        p = str(path.resolve())
        if p not in self._watched:
            self._watcher.addPath(p)
            self._watched.add(p)

    def unwatch(self, path: Path) -> None:
        p = str(path.resolve())
        if p in self._watched:
            self._watcher.removePath(p)
            self._watched.discard(p)

    def _on_file_changed(self, path: str) -> None:
        from pathlib import Path as P
        if P(path).exists():
            self.file_changed.emit(path)
            # Re-aggiunge il file (alcuni OS rimuovono il watch dopo modifica)
            self._watcher.addPath(path)
        else:
            self.file_deleted.emit(path)
            self._watched.discard(path)
