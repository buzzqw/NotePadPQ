"""
editor/bibtex_wizard.py — Wizard per la creazione di voci bibliografiche BibTeX.
NotePadPQ

Pattern: segue la struttura di LaTeXWizardDialog (QDialog con tab, anteprima, Insert/Copy/Close).
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

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


class BibTeXWizardDialog(QDialog):
    """Dialog per creare voci bibliografiche BibTeX con form guidato."""

    def __init__(self, editor: "EditorWidget", parent=None):
        super().__init__(parent)
        self._editor = editor
        self._fields: dict[str, QLineEdit] = {}
        self._field_layout: Optional[QFormLayout] = None
        self._type_combo: Optional[QComboBox] = None

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

        for field in info["required"] + info["optional"]:
            ed = QLineEdit(self)
            lbl = FIELD_LABELS.get(field, field.capitalize())
            marker = " *" if field in info["required"] else ""
            self._field_layout.addRow(f"{lbl}{marker}:", ed)
            self._fields[field] = ed

        self._update_preview()

    def _read_fields(self) -> dict[str, str]:
        result = {}
        for name, widget in self._fields.items():
            val = widget.text().strip()
            if val:
                result[name] = val
        return result

    def _generate_bibtex(self) -> str:
        if self._type_combo is None:
            return ""
        type_key = self._type_combo.currentData()
        if not type_key:
            return ""
        data = self._read_fields()
        bib_key = data.pop("key", type_key + "Key")
        lines = [f"@{type_key}{{{bib_key},"]
        for field, value in data.items():
            lines.append(f"  {field:<14} = {{{value}}},")
        lines.append("}")
        return "\n".join(lines)

    def _update_preview(self):
        self._preview.setPlainText(self._generate_bibtex())

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
        code = self._generate_bibtex()
        if not code.strip():
            return
        self._editor.insert(code)
        self.accept()

    def _copy(self):
        code = self._generate_bibtex()
        if code.strip():
            QApplication.clipboard().setText(code)

    def _doi_lookup(self):
        doi = self._doi_edit.text().strip()
        if not doi:
            self._doi_status.setText(tr("bibtex_wizard.doi_empty",
                default="Inserisci un DOI valido."))
            return
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
                    url = f"https://doi.org/{self._doi}"
                    req = urllib.request.Request(url)
                    req.add_header("Accept", "application/x-bibtex")
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        bibtex = resp.read().decode("utf-8").strip()
                        parsed = self._parse_bibtex(bibtex)
                        self.result.emit(bibtex, parsed)
                except Exception as e:
                    self.result.emit("", {"_error": str(e)})

            def _parse_bibtex(self, text: str) -> dict:
                import re
                result = {}
                m = re.match(r"@(\w+)\{([^,]+),", text)
                if m:
                    result["_type"] = m.group(1)
                    result["key"] = m.group(2).strip()
                for f in re.finditer(r"(\w+)\s*=\s*\{(.+?)\}", text, re.DOTALL):
                    result[f.group(1).lower()] = f.group(2).strip()
                return result

        self._doi_worker = _DoiWorker(doi)
        self._doi_worker.result.connect(self._on_doi_result)
        self._doi_worker.finished.connect(self._doi_worker.deleteLater)
        self._doi_worker.start()

    def _on_doi_result(self, bibtex: str, parsed: dict):
        if parsed.get("_error"):
            self._doi_status.setText(
                tr("bibtex_wizard.doi_error", default="Errore: ") + parsed["_error"])
            self._doi_status.setStyleSheet("color: #e06c75;")
            return
        if not bibtex:
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
