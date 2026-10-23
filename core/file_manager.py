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

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, pyqtSignal

from core.diagnostics import operation
from core.persistence import atomic_copy_file, atomic_write_text
from editor.editor_widget import LineEnding


@lru_cache(maxsize=1)
def _chardet_module():
    """Import chardet lazily: it is only needed for encoding auto-detection."""
    try:
        import chardet
    except ImportError:
        return None
    return chardet

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
        with operation("file.read", path=path) as details:
            raw = path.read_bytes()
            details["size_bytes"] = len(raw)
            return FileManager.decode_bytes(raw)

    @staticmethod
    def decode_bytes(raw: bytes) -> tuple[str, str, LineEnding]:
        """Decode bytes already read by the caller without a second disk read."""

        # Rilevamento BOM
        encoding, bom_len = FileManager._detect_bom(raw)
        if encoding:
            content_bytes = raw[bom_len:]
            try:
                text = content_bytes.decode(encoding)
                le = LineEnding.detect(text)
                display = encoding.upper()
                if display in ("UTF-16-LE", "UTF-16-BE",
                               "UTF-32-LE", "UTF-32-BE"):
                    display += " BOM"
                else:
                    display = display.replace("-SIG", " BOM")
                return text, display, le
            except UnicodeDecodeError:
                pass

        # UTF-16/UTF-32 senza BOM: i byte NUL rendono il file formalmente
        # UTF-8 valido (le sequenze NUL sono legali), ma il testo sarebbe
        # pieno di \x00 e un salvataggio corromperebbe il file. Riconosciamo
        # il pattern prima del tentativo UTF-8.
        bomless = FileManager._detect_bomless_unicode(raw)
        if bomless is not None:
            try:
                text = raw.decode(bomless)
                le = LineEnding.detect(text)
                return text, bomless, le
            except UnicodeDecodeError:
                pass

        # UTF-8 strict: se i byte sono UTF-8 validi, è definitivamente UTF-8.
        try:
            text = raw.decode("utf-8")
            le = LineEnding.detect(text)
            return text, "UTF-8", le
        except UnicodeDecodeError:
            pass

        detected_enc = FileManager._chardet_detect(raw)

        for enc in ([detected_enc] if detected_enc else []) + _FALLBACK_ENCODINGS:
            try:
                text = raw.decode(enc)
                le = LineEnding.detect(text)
                display_enc = enc.upper()
                return text, display_enc, le
            except (UnicodeDecodeError, LookupError):
                continue

        text = raw.decode("latin-1", errors="replace")
        le = LineEnding.detect(text)
        return text, "Latin-1", le

    @staticmethod
    def normalize_encoding(encoding: str) -> tuple[str, bool]:
        """Return ``(codec_name, has_bom_suffix)`` for display names.

        ``editor.encoding`` may be ``"UTF-8 BOM"`` or ``"UTF-16-LE BOM"``;
        those names are for the UI, not valid Python codec names.
        """
        raw = encoding.upper().strip().replace(" ", "-")
        has_bom = raw.endswith("-BOM")
        clean = raw[:-4] if has_bom else raw
        if clean == "UTF8":
            clean = "UTF-8"
        return clean, has_bom

    @staticmethod
    def encode_text(content: str, encoding: str,
                    write_bom: bool = False,
                    errors: str = "strict") -> bytes:
        """Encode text using an editor encoding name, preserving BOM rules."""
        clean, has_bom_name = FileManager.normalize_encoding(encoding)
        write_bom = write_bom or has_bom_name
        if clean in ("UTF-8", "UTF8"):
            return content.encode(
                "utf-8-sig" if write_bom else "utf-8", errors=errors)
        if clean == "UTF-8-SIG":
            return content.encode("utf-8-sig", errors=errors)
        prefix = b""
        if write_bom:
            prefix = {
                "UTF-16-LE": b"\xff\xfe",
                "UTF-16-BE": b"\xfe\xff",
                "UTF-32-LE": b"\xff\xfe\x00\x00",
                "UTF-32-BE": b"\x00\x00\xfe\xff",
            }.get(clean, b"")
        return prefix + content.encode(clean, errors=errors)

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
        with operation("file.write", path=path, encoding=encoding) as details:
            if backup and path.exists():
                FileManager._make_backup(path)

            # Normalizza nome encoding. I nomi con "BOM" (UTF-8 BOM,
            # UTF-16-LE BOM, ...) indicano che il BOM va riscritto.
            enc_clean, has_bom_name = FileManager.normalize_encoding(encoding)

            # Gestione BOM esplicito. Per gli encoding endian-specifici Python
            # non aggiunge automaticamente il BOM, quindi lo aggiungiamo.
            bom = b""
            if write_bom or has_bom_name:
                if enc_clean in ("UTF-8", "UTF-8-SIG"):
                    enc_clean = "UTF-8-SIG"
                else:
                    bom = {
                        "UTF-16-LE": b"\xff\xfe",
                        "UTF-16-BE": b"\xfe\xff",
                        "UTF-32-LE": b"\xff\xfe\x00\x00",
                        "UTF-32-BE": b"\x00\x00\xfe\xff",
                    }.get(enc_clean, b"")

            # The shared writer fsyncs a sibling temporary file before replacing
            # the destination, preserving content if interrupted mid-save.
            # Avoid encoding the whole document a second time only for a log
            # field.  The exact byte size is not needed for correctness.
            details["size_bytes"] = atomic_write_text(
                path, content, encoding=enc_clean, prefix=bom, return_size=True
            )
            from core.latex_project import invalidate_cached_text
            invalidate_cached_text(path.resolve())

    @staticmethod
    def _detect_bom(raw: bytes) -> tuple[str | None, int]:
        """Rileva BOM all'inizio del file. Restituisce (encoding, bom_len)."""
        for bom, enc in _BOM_MAP:
            if raw.startswith(bom):
                return enc, len(bom)
        return None, 0

    @staticmethod
    def looks_binary(raw: bytes) -> bool:
        """Heuristic for search/replace: skip binary files, keep UTF-16/32 text."""
        sample = raw[:4096]
        if b"\x00" not in sample:
            return False
        if FileManager._detect_bom(sample)[0] is not None:
            return False
        return FileManager._detect_bomless_unicode(sample) is None

    @staticmethod
    def _chardet_detect(raw: bytes) -> str | None:
        """Usa chardet per rilevare l'encoding. Restituisce None se non disponibile."""
        chardet = _chardet_module()
        if chardet is None:
            return None
        # Use a larger sample: LaTeX/source files often have a long ASCII preamble
        # that misleads chardet with a tiny sample (e.g. MacRoman instead of UTF-8).
        result = chardet.detect(raw[:65536])
        if result and result.get("confidence", 0) > 0.7:
            enc = result.get("encoding", "")
            return enc if enc else None
        return None

    @staticmethod
    def _detect_bomless_unicode(raw: bytes) -> str | None:
        """Riconosce UTF-16/UTF-32 senza BOM dal pattern dei byte NUL.

        Un file UTF-16LE composto da testo ASCII è ``x\\0y\\0...``: è UTF-8
        valido, quindi senza questo controllo verrebbe aperto con NUL nel
        testo e salvato in UTF-8, corrompendolo. Richiediamo un pattern molto
        regolare e una decodifica prevalentemente testuale per non scambiare
        file binari per UTF-16.
        """
        sample = raw[:8192]
        if len(sample) < 4 or b"\x00" not in sample:
            return None

        counts = [0, 0, 0, 0]
        totals = [0, 0, 0, 0]
        for index, value in enumerate(sample):
            slot = index % 4
            totals[slot] += 1
            if value == 0:
                counts[slot] += 1
        ratios = [
            (counts[i] / totals[i]) if totals[i] else 0.0
            for i in range(4)
        ]

        candidates: list[str] = []
        # UTF-32 prima di UTF-16: UTF-32LE ha zeri anche nelle posizioni
        # dispari e verrebbe riconosciuto anche come UTF-16LE.
        if ratios[1] > 0.7 and ratios[2] > 0.7 and ratios[3] > 0.7:
            candidates.append("utf-32-le")
        if ratios[0] > 0.7 and ratios[1] > 0.7 and ratios[2] > 0.7:
            candidates.append("utf-32-be")
        if ratios[1] > 0.55 and ratios[0] < 0.2:
            candidates.append("utf-16-le")
        if ratios[0] > 0.55 and ratios[1] < 0.2:
            candidates.append("utf-16-be")

        for candidate in candidates:
            width = 4 if "32" in candidate else 2
            if len(raw) % width:
                continue
            try:
                text = raw.decode(candidate)
            except UnicodeDecodeError:
                continue
            if not text:
                continue
            sample_text = text[:4096]
            printable = sum(
                1 for char in sample_text
                if char.isprintable() or char in "\r\n\t"
            )
            if printable / len(sample_text) >= 0.85:
                return candidate.upper()
        return None

    @staticmethod
    def _make_backup(path: Path) -> None:
        """Create a byte-for-byte backup without exposing a partial .bak file."""
        backup_path = path.with_suffix(path.suffix + ".bak")
        atomic_copy_file(path, backup_path)


# ─── FileWatcher ─────────────────────────────────────────────────────────────

class FileWatcher(QObject):
    """
    Monitora i file aperti per rilevare modifiche esterne.
    Emette file_changed(path) quando un file viene modificato o eliminato.
    """

    file_changed  = pyqtSignal(str)   # path stringa
    file_deleted  = pyqtSignal(str)

    _instance: FileWatcher | None = None

    def __init__(self):
        super().__init__()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watched: set[str] = set()

    @classmethod
    def instance(cls) -> FileWatcher:
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
        changed_path = P(path).resolve()
        from core.latex_project import invalidate_cached_text
        invalidate_cached_text(changed_path)
        if changed_path.exists():
            self.file_changed.emit(path)
            # Re-aggiunge il file (alcuni OS rimuovono il watch dopo modifica)
            self._watcher.addPath(path)
        else:
            self.file_deleted.emit(path)
            self._watched.discard(path)
