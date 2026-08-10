"""
editor/bibtex_wizard.py — Wizard per la creazione di voci bibliografiche BibTeX.
NotePadPQ

Pattern: segue la struttura di LaTeXWizardDialog (QDialog con tab, anteprima, Insert/Copy/Close).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlsplit

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QComboBox, QFormLayout, QLineEdit, QPlainTextEdit,
    QGroupBox, QPushButton, QLabel, QWidget, QMessageBox,
    QApplication,
)
from PyQt6.QtGui import QFont

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


BIBTEX_TYPES = {
    "article": {
        "label": "Article — rivista scientifica",
        "required": ["author", "title", "journal", "year"],
        "optional": ["volume", "number", "pages", "month", "doi", "url", "note"],
    },
    "book": {
        "label": "Book — libro",
        "required": ["author", "title", "publisher", "year"],
        "optional": ["editor", "volume", "series", "address", "edition", "isbn", "note"],
    },
    "inproceedings": {
        "label": "InProceedings — conferenza",
        "required": ["author", "title", "booktitle", "year"],
        "optional": ["editor", "pages", "organization", "address", "series", "doi", "note"],
    },
    "incollection": {
        "label": "InCollection — capitolo in libro",
        "required": ["author", "title", "booktitle", "publisher", "year"],
        "optional": ["editor", "pages", "volume", "series", "address", "note"],
    },
    "inbook": {
        "label": "InBook — sezione di libro",
        "required": ["author", "title", "chapter", "publisher", "year"],
        "optional": ["editor", "pages", "volume", "series", "address", "edition", "note"],
    },
    "proceedings": {
        "label": "Proceedings — atti",
        "required": ["title", "year"],
        "optional": ["editor", "publisher", "organization", "address", "series", "isbn", "note"],
    },
    "phdthesis": {
        "label": "PhD Thesis — tesi di dottorato",
        "required": ["author", "title", "school", "year"],
        "optional": ["type", "address", "month", "note"],
    },
    "mastersthesis": {
        "label": "Masters Thesis — tesi magistrale",
        "required": ["author", "title", "school", "year"],
        "optional": ["type", "address", "month", "note"],
    },
    "techreport": {
        "label": "Tech Report — rapporto tecnico",
        "required": ["author", "title", "institution", "year"],
        "optional": ["type", "number", "address", "note"],
    },
    "misc": {
        "label": "Misc — generico",
        "required": [],
        "optional": ["author", "title", "howpublished", "year", "month", "note", "url"],
    },
    "unpublished": {
        "label": "Unpublished — non pubblicato",
        "required": ["author", "title", "note"],
        "optional": ["month", "year"],
    },
    "manual": {
        "label": "Manual — manuale tecnico",
        "required": ["title"],
        "optional": ["author", "organization", "address", "edition", "year", "month", "note"],
    },
    "booklet": {
        "label": "Booklet — opuscolo",
        "required": ["title"],
        "optional": ["author", "howpublished", "address", "month", "year", "note"],
    },
    "online": {
        "label": "Online — risorsa web (biblatex)",
        "required": ["author", "title", "url", "urldate"],
        "optional": ["year", "month", "note", "doi"],
    },
}

FIELD_LABELS = {
    "author": "Autore",
    "editor": "Curatore",
    "title": "Titolo",
    "booktitle": "Titolo conferenza/libro",
    "journal": "Rivista",
    "publisher": "Editore",
    "organization": "Organizzazione",
    "institution": "Istituzione",
    "school": "Università",
    "year": "Anno",
    "volume": "Volume",
    "number": "Numero",
    "series": "Collana",
    "chapter": "Capitolo",
    "pages": "Pagine",
    "edition": "Edizione",
    "address": "Luogo",
    "month": "Mese",
    "type": "Tipo",
    "howpublished": "Pubblicato come",
    "note": "Note",
    "doi": "DOI",
    "isbn": "ISBN",
    "url": "URL",
    "urldate": "Data accesso",
    "key": "Chiave BibTeX",
}


_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_ENTRY_HEADER_RE = re.compile(r"@([A-Za-z][\w-]*)\s*([{(])")
_ENTRY_TYPE_RE = re.compile(r"^[A-Za-z][\w-]*$")


def _strip_outer_delimiters(value: str) -> str:
    """Remove delimiters commonly returned by BibTeX parsers."""
    value = value.strip()
    if len(value) < 2:
        return value
    if value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    if value[0] != "{" or value[-1] != "}":
        return value

    depth = 0
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and index != len(value) - 1:
                return value
            if depth < 0:
                return value
    return value[1:-1].strip() if depth == 0 else value


def normalize_doi(value: object) -> str:
    """Return a canonical DOI, or an empty string when *value* is not a DOI."""
    candidate = _strip_outer_delimiters(str(value or "")).strip()
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    if candidate.lower().startswith(("https://doi.org/", "http://doi.org/",
                                     "https://dx.doi.org/", "http://dx.doi.org/")):
        parsed = urlsplit(candidate)
        if parsed.query or parsed.fragment:
            return ""
        candidate = parsed.path.lstrip("/")
    candidate = candidate.rstrip(".,;:")
    return candidate.lower() if _DOI_RE.fullmatch(candidate) else ""


def normalize_url(value: object) -> str:
    """Trim a BibTeX URL without performing a network request."""
    return _strip_outer_delimiters(str(value or "")).strip()


def normalize_bibtex_record(
    record: Mapping[str, object], entry_type: Optional[str] = None
) -> dict[str, str]:
    """Normalize field names and the DOI/URL values of one BibTeX record.

    Unknown fields are retained so that valid BibLaTeX fields are not discarded.
    The entry type is stored as ``_type`` to distinguish it from BibTeX's
    ordinary ``type`` field.
    """
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")

    raw_type = entry_type
    if raw_type is None:
        for name in ("_type", "entry_type", "entrytype", "ENTRYTYPE"):
            if name in record:
                raw_type = record[name]
                break

    normalized: dict[str, str] = {}
    if raw_type is not None and str(raw_type).strip():
        normalized["_type"] = str(raw_type).strip().lstrip("@").lower()

    for raw_name, raw_value in record.items():
        name = str(raw_name).strip().lower()
        if name in {"_type", "entry_type", "entrytype"}:
            continue
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value:
            continue
        if name == "doi":
            value = normalize_doi(value) or _strip_outer_delimiters(value)
        elif name == "url":
            value = normalize_url(value)
        normalized[name] = value
    return normalized


def find_bibtex_keys(text: str) -> list[str]:
    """Extract entry keys from BibTeX/BibLaTeX text without opening files."""
    # A commented-out entry must not make the current key look duplicated.
    uncommented = re.sub(r"(?<!\\)%[^\r\n]*", "", text or "")
    ignored = {"comment", "preamble", "string"}
    keys: list[str] = []
    index = 0
    while index < len(uncommented):
        match = _ENTRY_HEADER_RE.match(uncommented, index)
        if not match:
            index += 1
            continue
        end = _find_entry_end(uncommented, match.end() - 1, match.group(2))
        if end is None:
            index = match.end()
            continue
        parts = _split_bibtex_items(uncommented[match.end():end])
        if match.group(1).lower() not in ignored and parts and parts[0].strip():
            keys.append(parts[0].strip())
        index = end + 1
    return keys


def find_duplicate_keys(keys: Iterable[str] | str) -> list[str]:
    """Return duplicate keys once each, preserving their first-seen order."""
    if isinstance(keys, str):
        keys = find_bibtex_keys(keys) if "@" in keys else [keys]
    seen: set[str] = set()
    duplicates: list[str] = []
    for raw_key in keys:
        key = str(raw_key).strip()
        if not key:
            continue
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return duplicates


def find_duplicate_bibtex_keys(text: str) -> list[str]:
    """Return duplicate entry keys found in BibTeX/BibLaTeX text."""
    return find_duplicate_keys(find_bibtex_keys(text))


def _is_valid_url(value: str) -> bool:
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return False
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def validate_bibtex_record(
    record: Mapping[str, object],
    entry_type: Optional[str] = None,
    existing_keys: Optional[Iterable[str] | str] = None,
) -> list[str]:
    """Validate one record and return non-modal, human-readable errors.

    Validation is deliberately local: DOI and URL checks only inspect syntax,
    and no URL is fetched. Unknown entry types are accepted with no guessed
    required fields, which keeps the validator usable for newer BibLaTeX types.
    """
    normalized = normalize_bibtex_record(record, entry_type)
    errors: list[str] = []
    type_key = normalized.get("_type", "")
    if not type_key or not _ENTRY_TYPE_RE.fullmatch(type_key):
        errors.append("Missing or invalid entry type")

    bib_key = normalized.get("key", "")
    if not bib_key:
        errors.append("Missing required field: key")
    elif any(char.isspace() or char in "{}," for char in bib_key):
        errors.append("Invalid BibTeX key")

    required = BIBTEX_TYPES.get(type_key, {}).get("required", [])
    missing = [field for field in required if not normalized.get(field, "").strip()]
    if missing:
        errors.append(f"Missing required fields for @{type_key}: {', '.join(missing)}")

    if "doi" in normalized and not normalize_doi(normalized["doi"]):
        errors.append("Invalid DOI")
    if "url" in normalized and not _is_valid_url(normalized["url"]):
        errors.append("Invalid URL")

    if existing_keys is not None:
        if isinstance(existing_keys, str):
            keys = find_bibtex_keys(existing_keys) if "@" in existing_keys else [existing_keys]
        else:
            keys = existing_keys
        duplicate_keys = {str(key).strip() for key in keys if str(key).strip()}
        if bib_key and bib_key in duplicate_keys:
            errors.append(f"Duplicate BibTeX key: {bib_key}")
    return errors


def _split_bibtex_items(text: str) -> list[str]:
    """Split an entry body on top-level commas, respecting braces and quotes."""
    items: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char in "{(":
            depth += 1
        elif not quoted and char in "})":
            depth = max(0, depth - 1)
        elif char == "," and not quoted and depth == 0:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    return items


def _find_entry_end(text: str, opening_index: int, opening: str) -> Optional[int]:
    closing = "}" if opening == "{" else ")"
    depth = 0
    quoted = False
    escaped = False
    for index in range(opening_index, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == opening:
            depth += 1
        elif not quoted and char == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def parse_bibtex_record(text: str) -> dict[str, str]:
    """Parse the first ordinary BibTeX entry returned by a DOI service."""
    match = re.search(r"@([A-Za-z][\w-]*)\s*([{(])", text or "")
    if not match:
        return {}
    opening = match.group(2)
    end = _find_entry_end(text, match.end() - 1, opening)
    if end is None:
        return {}

    parts = _split_bibtex_items(text[match.end():end])
    key = parts[0].strip() if parts else ""
    if not key:
        return {}
    raw_fields: dict[str, object] = {"_type": match.group(1), "key": key}
    for item in parts[1:]:
        field_match = re.match(r"\s*([A-Za-z][\w:-]*)\s*=\s*(.*?)\s*$", item, re.DOTALL)
        if field_match:
            raw_fields[field_match.group(1)] = _strip_outer_delimiters(field_match.group(2))
    return normalize_bibtex_record(raw_fields)


class BibTeXWizardDialog(QDialog):
    """Dialog per creare voci bibliografiche BibTeX con form guidato."""

    def __init__(self, editor: "EditorWidget", parent=None):
        super().__init__(parent)
        self._editor = editor
        self._fields: dict[str, QLineEdit] = {}
        self._field_layout: Optional[QFormLayout] = None
        self._type_combo: Optional[QComboBox] = None
        self._validation_status: Optional[QLabel] = None

        self.setWindowTitle(tr("bibtex_wizard.title", default="BibTeX Wizard"))
        self.resize(650, 600)
        self._build_ui()
        self._on_type_changed(0)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        tabs = QTabWidget(self)

        entry_tab = self._build_entry_tab()
        tabs.addTab(entry_tab, tr("bibtex_wizard.tab_entry", default="Nuova voce"))

        search_tab = self._build_search_tab()
        tabs.addTab(search_tab, tr("bibtex_wizard.tab_search", default="Cerca DOI"))

        main_layout.addWidget(tabs)

        preview_grp = QGroupBox(tr("bibtex_wizard.preview", default="Anteprima BibTeX"), self)
        preview_layout = QVBoxLayout(preview_grp)
        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(False)
        self._preview.setFont(QFont("monospace", 10))
        self._preview.setMinimumHeight(140)
        preview_layout.addWidget(self._preview)
        main_layout.addWidget(preview_grp)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_copy = QPushButton(tr("bibtex_wizard.copy", default="Copia"))
        btn_copy.clicked.connect(self._copy)
        btn_layout.addWidget(btn_copy)

        btn_insert = QPushButton(tr("bibtex_wizard.insert", default="Inserisci"))
        btn_insert.setDefault(True)
        btn_insert.clicked.connect(self._insert)
        btn_layout.addWidget(btn_insert)

        btn_close = QPushButton(tr("bibtex_wizard.close", default="Chiudi"))
        btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(btn_close)

        main_layout.addLayout(btn_layout)

    def _build_entry_tab(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)

        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel(tr("bibtex_wizard.label_type", default="Tipo:")))
        self._type_combo = QComboBox(w)
        for key, info in BIBTEX_TYPES.items():
            self._type_combo.addItem(f"@{key}  —  {info['label']}", key)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self._type_combo)
        type_layout.addStretch()

        btn_gen = QPushButton(tr("bibtex_wizard.auto_key", default="Genera chiave"))
        btn_gen.setToolTip(tr("bibtex_wizard.auto_key_tip",
            default="Genera chiave da autore + anno (es. Einstein1905)"))
        btn_gen.clicked.connect(self._auto_key)
        type_layout.addWidget(btn_gen)
        layout.addLayout(type_layout)

        self._field_layout = QFormLayout()
        layout.addLayout(self._field_layout)

        self._validation_status = QLabel(w)
        self._validation_status.setWordWrap(True)
        layout.addWidget(self._validation_status)
        layout.addStretch()
        return w

    def _build_search_tab(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)

        info = QLabel(tr("bibtex_wizard.doi_info",
            default="Inserisci un DOI (es. 10.1000/xyz) per caricare\nautomaticamente i dati bibliografici da Crossref."))
        info.setWordWrap(True)
        layout.addWidget(info)

        h = QHBoxLayout()
        h.addWidget(QLabel("DOI:"))
        self._doi_edit = QLineEdit(w)
        self._doi_edit.setPlaceholderText("10.1000/xyz")
        h.addWidget(self._doi_edit)

        btn_lookup = QPushButton(tr("bibtex_wizard.lookup", default="Cerca"))
        btn_lookup.clicked.connect(self._doi_lookup)
        h.addWidget(btn_lookup)
        layout.addLayout(h)

        self._doi_status = QLabel("")
        self._doi_status.setWordWrap(True)
        layout.addWidget(self._doi_status)
        layout.addStretch()
        return w

    def _on_type_changed(self, idx: int):
        if self._type_combo is None or self._field_layout is None:
            return
        while self._field_layout.count():
            item = self._field_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._fields.clear()

        type_key = self._type_combo.currentData()
        if not type_key or type_key not in BIBTEX_TYPES:
            return
        info = BIBTEX_TYPES[type_key]

        key_edit = QLineEdit(self)
        key_edit.setPlaceholderText("es. Einstein1905")
        self._field_layout.addRow("key:", key_edit)
        self._fields["key"] = key_edit
        key_edit.textChanged.connect(self._update_preview)

        for field in info["required"] + info["optional"]:
            ed = QLineEdit(self)
            lbl = FIELD_LABELS.get(field, field.capitalize())
            marker = " *" if field in info["required"] else ""
            self._field_layout.addRow(f"{lbl}{marker}:", ed)
            self._fields[field] = ed
            ed.textChanged.connect(self._update_preview)

        self._update_preview()

    def _read_fields(self) -> dict[str, str]:
        result = {}
        for name, widget in self._fields.items():
            val = widget.text().strip()
            if val:
                result[name] = val
        return result

    def _current_record(self) -> dict[str, str]:
        type_key = self._type_combo.currentData() if self._type_combo else None
        return normalize_bibtex_record(self._read_fields(), type_key)

    def _existing_bibtex_keys(self) -> list[str]:
        try:
            content = self._editor.get_content()
        except Exception:
            try:
                content = self._editor.text()
            except Exception:
                return []
        return find_bibtex_keys(content)

    def _validation_errors(self, check_existing_keys: bool = True) -> list[str]:
        return validate_bibtex_record(
            self._current_record(),
            existing_keys=self._existing_bibtex_keys() if check_existing_keys else None,
        )

    def _update_validation_status(self, errors: Optional[list[str]] = None) -> None:
        if self._validation_status is None:
            return
        errors = self._validation_errors(check_existing_keys=False) if errors is None else errors
        if errors:
            self._validation_status.setText("Record non valido: " + "; ".join(errors))
            self._validation_status.setStyleSheet("color: #e06c75;")
        else:
            self._validation_status.setText("Record BibTeX valido")
            self._validation_status.setStyleSheet("color: #56bd5b;")

    def _generate_bibtex(self) -> str:
        if self._type_combo is None:
            return ""
        type_key = self._type_combo.currentData()
        if not type_key:
            return ""
        data = self._current_record()
        data.pop("_type", None)
        bib_key = data.pop("key", type_key + "Key")
        lines = [f"@{type_key}{{{bib_key},"]
        for field, value in data.items():
            lines.append(f"  {field:<14} = {{{value}}},")
        lines.append("}")
        return "\n".join(lines)

    def _update_preview(self):
        self._preview.setPlainText(self._generate_bibtex())
        self._update_validation_status()

    def _auto_key(self):
        data = self._read_fields()
        author = data.get("author", "")
        year = data.get("year", "")
        last = author.split(",")[0].strip().split()[-1] if author else ""
        key = ""
        if last:
            key += last
        if year:
            key += year
        if not key:
            key = "ref"
        if "key" in self._fields:
            self._fields["key"].setText(key)
            self._update_preview()

    def _insert(self):
        errors = self._validation_errors()
        self._update_validation_status(errors)
        if errors:
            return
        code = self._generate_bibtex()
        if not code.strip():
            return
        self._editor.insert(code)
        self.accept()

    def _copy(self):
        errors = self._validation_errors()
        self._update_validation_status(errors)
        if errors:
            return
        code = self._generate_bibtex()
        if code.strip():
            QApplication.clipboard().setText(code)

    def _doi_lookup(self):
        doi = normalize_doi(self._doi_edit.text())
        if not doi:
            self._doi_status.setText(tr("bibtex_wizard.doi_empty",
                default="Inserisci un DOI valido."))
            self._doi_status.setStyleSheet("color: #e06c75;")
            return
        if getattr(self, "_doi_worker", None) is not None and self._doi_worker.isRunning():
            self._doi_status.setText(tr("bibtex_wizard.doi_searching",
                default="Ricerca in corso..."))
            return
        self._doi_edit.setText(doi)
        self._doi_status.setText(tr("bibtex_wizard.doi_searching",
            default="Ricerca in corso..."))
        self._doi_status.setStyleSheet("color: #61afef;")
        from PyQt6.QtCore import QThread, pyqtSignal

        class _DoiWorker(QThread):
            result = pyqtSignal(str, dict)

            def __init__(self, doi):
                super().__init__()
                self._doi = doi

            def run(self):
                try:
                    import urllib.request
                    from urllib.parse import quote
                    url = f"https://doi.org/{quote(self._doi, safe='/')}"
                    req = urllib.request.Request(url)
                    req.add_header("Accept", "application/x-bibtex")
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        bibtex = resp.read().decode("utf-8").strip()
                        parsed = self._parse_bibtex(bibtex)
                        self.result.emit(bibtex, parsed)
                except Exception as e:
                    self.result.emit("", {"_error": str(e)})

            def _parse_bibtex(self, text: str) -> dict:
                return parse_bibtex_record(text)

        worker = _DoiWorker(doi)
        self._doi_worker = worker
        worker.result.connect(self._on_doi_result)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_doi_result(self, bibtex: str, parsed: dict):
        if parsed.get("_error"):
            self._doi_status.setText(
                tr("bibtex_wizard.doi_error", default="Errore: ") + parsed["_error"])
            self._doi_status.setStyleSheet("color: #e06c75;")
            return
        if not bibtex or not parsed.get("_type") or not parsed.get("key"):
            self._doi_status.setText(
                tr("bibtex_wizard.doi_empty", default="Nessun risultato."))
            self._doi_status.setStyleSheet("color: #e06c75;")
            return
        self._doi_status.setText(
            tr("bibtex_wizard.doi_found", default="Trovato! Compila i campi dalla scheda 'Nuova voce'."))
        self._doi_status.setStyleSheet("color: #56bd5b;")

        entry_type = parsed.get("_type", "article")
        for i in range(self._type_combo.count()):
            if self._type_combo.itemData(i) == entry_type:
                self._type_combo.setCurrentIndex(i)
                break

        for field, widget in self._fields.items():
            val = parsed.get(field.lower(), "")
            if val:
                widget.setText(val)

        self._update_preview()
