"""Pannello dock per visualizzazione e formattazione di file JSON e XML."""
from __future__ import annotations

import json
import xml.dom.minidom
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QTimer, QSortFilterProxyModel
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QKeySequence, QStandardItem, QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QDockWidget, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget
    from ui.main_window import MainWindow

# ── Colori semantici ──────────────────────────────────────────────────────────
_COL_KEY      = QColor("#569cd6")
_COL_STR      = QColor("#6aab73")
_COL_NUM      = QColor("#b5cea8")
_COL_BOOL     = QColor("#cc8800")
_COL_NULL     = QColor("#888888")
_COL_TYPE     = QColor("#666666")
_COL_XML_TAG  = QColor("#4ec9b0")
_COL_XML_ATTR = QColor("#9cdcfe")
_COL_XML_VAL  = QColor("#6aab73")

# UserRole per metadati interni
_ROLE_JUMP  = Qt.ItemDataRole.UserRole + 1   # chiave/tag per jump-to
_ROLE_PATH  = Qt.ItemDataRole.UserRole + 2   # path JSON serializzato
_ROLE_TYPE  = Qt.ItemDataRole.UserRole + 3   # "value" | "text" | "attr:<name>"


class JsonXmlPanel(QWidget):
    """Pannello ad albero per JSON e XML: visualizzazione, filtro, formattazione
    e modifica inline dei valori (doppio click)."""

    _DEBOUNCE_MS = 1500

    def __init__(self, main_window: "MainWindow", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._mw = main_window
        self._editor: Optional["EditorWidget"] = None
        self._lang: str = ""
        self._updating_editor = False   # blocca loop textChanged ↔ itemChanged
        self._ns_map: dict[str, str] = {}   # uri → prefix per preservare i namespace XML
        self._needs_refresh = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self._DEBOUNCE_MS)
        self._timer.timeout.connect(self._refresh)

        # Timer debounce per la sincronizzazione editor → pannello
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.setInterval(250)
        self._cursor_timer.timeout.connect(self._sync_tree_from_cursor)

        self._build_ui()

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        # Barra strumenti
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)
        self._btn_refresh  = self._make_btn("↻", tr("tooltip.json_xml_refresh"),  self._refresh)
        self._btn_expand   = self._make_btn("⊞", tr("tooltip.json_xml_expand"),   self._expand_all)
        self._btn_collapse = self._make_btn("⊟", tr("tooltip.json_xml_collapse"), self._collapse_all)
        self._btn_format   = QPushButton("⎁  " + tr("tooltip.json_xml_format"))
        self._btn_format.setToolTip(tr("tooltip.json_xml_format") + "  (Alt+Shift+F)")
        self._btn_format.clicked.connect(self.format_document)
        self._btn_format.setFixedHeight(22)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("tooltip.json_xml_filter"))
        self._filter.setFixedHeight(22)
        self._filter.textChanged.connect(self._on_filter_changed)
        self._filter.setClearButtonEnabled(True)

        toolbar.addWidget(self._btn_refresh)
        toolbar.addWidget(self._btn_expand)
        toolbar.addWidget(self._btn_collapse)
        toolbar.addWidget(self._btn_format, 1)
        toolbar.addWidget(self._filter, 2)
        layout.addLayout(toolbar)

        # Modello + proxy filtro
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels([tr("json_xml.col_key_tag"), tr("json_xml.col_value")])
        self._model.itemChanged.connect(self._on_item_changed)

        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setRecursiveFilteringEnabled(True)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)

        # Vista ad albero con editing inline abilitato
        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setAnimated(True)
        self._tree.header().setStretchLastSection(True)
        self._tree.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._tree.clicked.connect(self._on_node_clicked)
        layout.addWidget(self._tree, 1)

        # Hint editing
        self._hint = QLabel(tr("json_xml.edit_hint"))
        self._hint.setStyleSheet("color: #666; font-size: 10px; padding: 1px 2px;")
        layout.addWidget(self._hint)

        # Barra stato
        self._status = QLabel("")
        self._status.setStyleSheet("color: #888; font-size: 10px; padding: 1px 2px;")
        layout.addWidget(self._status)

    @staticmethod
    def _make_btn(text: str, tooltip: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(22, 22)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        return btn

    # ── Connessione editor ────────────────────────────────────────────────────

    def set_editor(self, editor: Optional["EditorWidget"]) -> None:
        if self._editor is editor:
            return
        if self._editor is not None:
            try:
                self._editor.textChanged.disconnect(self._on_text_changed)
            except Exception:
                pass
            try:
                self._editor.cursor_changed.disconnect(self._on_editor_cursor)
            except Exception:
                pass
        self._editor = editor
        if editor is not None:
            editor.textChanged.connect(self._on_text_changed)
            editor.cursor_changed.connect(self._on_editor_cursor)
            self._detect_lang()
            if self.isVisible():
                self._refresh()
            else:
                self._needs_refresh = True
        else:
            self._clear_tree()
            self._status.setText("")
            self._lang = ""

    def _on_text_changed(self) -> None:
        if not self._updating_editor:
            if self.isVisible():
                self._timer.start()
            else:
                self._needs_refresh = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self._timer.start()

    # ── Rilevamento linguaggio ────────────────────────────────────────────────

    def _detect_lang(self) -> None:
        if self._editor is None:
            self._lang = ""
            return
        try:
            from editor.lexers import get_language_name
            lang = get_language_name(self._editor).lower()
        except Exception:
            lang = ""
        if "json" in lang:
            self._lang = "json"
        elif "xml" in lang or "svg" in lang or "xsl" in lang:
            self._lang = "xml"
        else:
            snippet = (self._editor.text() or "").lstrip()[:50]
            if snippet.startswith(("{", "[")):
                self._lang = "json"
            elif snippet.startswith("<"):
                self._lang = "xml"
            else:
                self._lang = ""

    # ── Aggiornamento albero ──────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._timer.stop()
        if not self.isVisible():
            self._needs_refresh = True
            return
        if self._editor is None:
            return
        self._detect_lang()
        if not self._lang:
            self._clear_tree()
            self._status.setText(tr("json_xml.not_json_xml"))
            return
        text = self._editor.text()
        if not text.strip():
            self._clear_tree()
            self._status.setText(tr("json_xml.empty_doc"))
            return
        self._clear_tree()
        try:
            if self._lang == "json":
                self._parse_json(text)
            else:
                self._parse_xml(text)
        except json.JSONDecodeError as exc:
            self._status.setText(tr("json_xml.invalid_json", msg=exc.msg, line=exc.lineno))
        except ET.ParseError as exc:
            self._status.setText(tr("json_xml.invalid_xml", error=str(exc)))
        except Exception as exc:
            self._status.setText(tr("json_xml.parse_error", error=str(exc)))

    def _clear_tree(self) -> None:
        self._model.clear()
        self._model.setHorizontalHeaderLabels([tr("json_xml.col_key_tag"), tr("json_xml.col_value")])

    # ── Parser JSON ───────────────────────────────────────────────────────────

    def _parse_json(self, text: str) -> None:
        data = json.loads(text)
        root = self._model.invisibleRootItem()
        self._add_json_node(root, "", data, [])
        n = self._model.rowCount()
        self._status.setText(tr("json_xml.valid_json", count=n))
        self._tree.expandToDepth(1)
        self._tree.resizeColumnToContents(0)

    def _add_json_node(
        self, parent: QStandardItem, key, value, path: list
    ) -> None:
        """Aggiunge ricorsivamente un nodo JSON all'albero.
        key può essere str (chiave dict), int (indice lista) o "" (radice).
        path è la lista di chiavi dal root al padre corrente."""

        # Percorso di questo nodo
        current_path: list = path + [key] if key != "" else path
        display_key: str = f"[{key}]" if isinstance(key, int) else str(key)

        if isinstance(value, dict):
            cnt = len(value)
            k_item = self._key_item(display_key) if key != "" else QStandardItem(tr("json_xml.empty_object", default="{  }"))
            k_item.setEditable(False)
            v_item = QStandardItem(tr("json_xml.json_object", count=cnt))
            v_item.setForeground(QBrush(_COL_TYPE))
            v_item.setEditable(False)
            parent.appendRow([k_item, v_item])
            for k, v in value.items():
                self._add_json_node(k_item, k, v, current_path)

        elif isinstance(value, list):
            cnt = len(value)
            k_item = self._key_item(display_key) if key != "" else QStandardItem(tr("json_xml.empty_array", default="[  ]"))
            k_item.setEditable(False)
            v_item = QStandardItem(tr("json_xml.json_array", count=cnt))
            v_item.setForeground(QBrush(_COL_TYPE))
            v_item.setEditable(False)
            parent.appendRow([k_item, v_item])
            for i, v in enumerate(value):
                self._add_json_node(k_item, i, v, current_path)

        else:
            k_item = self._key_item(display_key) if key != "" else QStandardItem(tr("json_xml.scalar_value"))
            k_item.setEditable(False)
            v_item = QStandardItem(self._fmt_scalar(value))
            v_item.setForeground(QBrush(self._scalar_color(value)))
            v_item.setEditable(True)
            v_item.setData(json.dumps(current_path), _ROLE_PATH)
            v_item.setData("value", _ROLE_TYPE)
            k_item.setData(display_key, _ROLE_JUMP)
            parent.appendRow([k_item, v_item])

    @staticmethod
    def _key_item(key: str) -> QStandardItem:
        item = QStandardItem(key)
        item.setForeground(QBrush(_COL_KEY))
        item.setData(key, _ROLE_JUMP)
        return item

    @staticmethod
    def _fmt_scalar(v) -> str:
        if v is None:    return "null"
        if isinstance(v, bool): return "true" if v else "false"
        if isinstance(v, str):  return f'"{v}"' if len(v) <= 120 else f'"{v[:117]}…"'
        return str(v)

    @staticmethod
    def _scalar_color(v) -> QColor:
        if v is None:                  return _COL_NULL
        if isinstance(v, bool):        return _COL_BOOL
        if isinstance(v, (int, float)):return _COL_NUM
        return _COL_STR

    @staticmethod
    def _coerce_json_value(text: str):
        """Converte il testo digitato nel tipo JSON più appropriato."""
        s = text.strip()
        if s == "null":  return None
        if s == "true":  return True
        if s == "false": return False
        if s.startswith('"') and s.endswith('"') and len(s) >= 2:
            return s[1:-1]
        try:
            if "." in s or ("e" in s.lower() and not s.startswith("0x")):
                return float(s)
            return int(s)
        except ValueError:
            pass
        return text  # stringa grezza

    # ── Parser XML ────────────────────────────────────────────────────────────

    def _collect_namespaces(self, text: str) -> None:
        """Estrae e registra i prefissi namespace dal documento XML.
        Popola self._ns_map (uri→prefix) e chiama ET.register_namespace
        così ET.tostring() usa i prefissi originali invece di ns0:, ns1:, ..."""
        import io
        self._ns_map = {}
        try:
            for event, (prefix, uri) in ET.iterparse(
                io.StringIO(text), events=["start-ns"]
            ):
                self._ns_map[uri] = prefix
                ET.register_namespace(prefix, uri)
        except ET.ParseError:
            pass  # Errore gestito altrove

    def _tag_display(self, raw_tag: str) -> str:
        """Converte '{uri}local' nel formato 'prefix:local' usando _ns_map."""
        if raw_tag.startswith("{"):
            uri, local = raw_tag[1:].split("}", 1)
            prefix = self._ns_map.get(uri, "")
            return f"{prefix}:{local}" if prefix else local
        return raw_tag

    def _parse_xml(self, text: str) -> None:
        self._collect_namespaces(text)
        root_elem = ET.fromstring(text)
        root_item = self._model.invisibleRootItem()
        self._add_xml_node(root_item, root_elem, [])
        self._status.setText(tr("json_xml.valid_xml"))
        self._tree.expandToDepth(1)
        self._tree.resizeColumnToContents(0)

    def _add_xml_node(
        self, parent: QStandardItem, elem: ET.Element, elem_path: list
    ) -> None:
        display_tag = self._tag_display(elem.tag)   # "con:setting" o "setting"

        tag_item = QStandardItem(f"<{display_tag}>")
        tag_item.setForeground(QBrush(_COL_XML_TAG))
        tag_item.setData(display_tag, _ROLE_JUMP)
        tag_item.setData(json.dumps(elem_path), _ROLE_PATH)   # path per jump preciso
        tag_item.setData("tag", _ROLE_TYPE)
        tag_item.setEditable(False)

        text_val = (elem.text or "").strip()
        has_children = len(list(elem)) > 0

        val_item = QStandardItem(text_val[:100] if text_val else "")
        val_item.setForeground(QBrush(_COL_STR))
        if text_val and not has_children:
            # Testo editabile solo se elemento foglia (no elementi figli)
            val_item.setEditable(True)
            val_item.setData(json.dumps(elem_path), _ROLE_PATH)
            val_item.setData("text", _ROLE_TYPE)
        else:
            val_item.setEditable(False)

        parent.appendRow([tag_item, val_item])

        # Attributi — sempre editabili
        for attr_name, attr_val in elem.attrib.items():
            a_key = QStandardItem(f"  @{attr_name}")
            a_key.setForeground(QBrush(_COL_XML_ATTR))
            a_key.setData(attr_name, _ROLE_JUMP)
            a_key.setData(json.dumps(elem_path), _ROLE_PATH)
            a_key.setData(f"attr:{attr_name}", _ROLE_TYPE)   # stesso tipo del valore
            a_key.setEditable(False)
            a_val = QStandardItem(attr_val)
            a_val.setForeground(QBrush(_COL_XML_VAL))
            a_val.setEditable(True)
            a_val.setData(json.dumps(elem_path), _ROLE_PATH)
            a_val.setData(f"attr:{attr_name}", _ROLE_TYPE)
            tag_item.appendRow([a_key, a_val])

        for i, child in enumerate(elem):
            self._add_xml_node(tag_item, child, elem_path + [i])

    @staticmethod
    def _navigate_xml(root_elem: ET.Element, path: list) -> ET.Element:
        """Naviga la struttura XML seguendo una lista di indici."""
        elem = root_elem
        for idx in path:
            elem = list(elem)[idx]
        return elem

    # ── Editing inline ────────────────────────────────────────────────────────

    def _on_item_changed(self, item: QStandardItem) -> None:
        """Propagate la modifica di un valore dall'albero all'editor."""
        if self._updating_editor:
            return
        edit_type = item.data(_ROLE_TYPE)
        if not edit_type:
            return
        path_str = item.data(_ROLE_PATH)
        if path_str is None:
            return
        self._updating_editor = True
        try:
            if self._lang == "json":
                self._apply_json_edit(item, json.loads(path_str), edit_type)
            elif self._lang == "xml":
                self._apply_xml_edit(item, json.loads(path_str), edit_type)
        except Exception as exc:
            self._status.setText(tr("json_xml.update_error", error=str(exc)))
        finally:
            self._updating_editor = False

    def _apply_json_edit(self, item: QStandardItem, path: list, _type: str) -> None:
        if self._editor is None:
            return
        new_val = self._coerce_json_value(item.text())
        data = json.loads(self._editor.text())

        if not path:
            # Valore radice scalare — raro ma possibile
            data = new_val
        else:
            node = data
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = new_val

        formatted = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        self._write_to_editor(formatted)

        # Aggiorna colore inline senza ricostruire l'albero
        item.setForeground(QBrush(self._scalar_color(new_val)))
        item.setText(self._fmt_scalar(new_val))
        self._status.setText(tr("json_xml.doc_updated"))

    def _apply_xml_edit(self, item: QStandardItem, path: list, edit_type: str) -> None:
        if self._editor is None:
            return
        new_text = item.text()
        original = self._editor.text()
        # Registra i namespace PRIMA di fromstring/tostring per preservare i prefissi
        self._collect_namespaces(original)
        root_elem = ET.fromstring(original)
        target = self._navigate_xml(root_elem, path)

        if edit_type == "text":
            target.text = new_text
        elif edit_type.startswith("attr:"):
            attr_name = edit_type[5:]
            target.set(attr_name, new_text)

        # Ri-serializza con pretty print
        raw = ET.tostring(root_elem, encoding="unicode", xml_declaration=False)
        dom = xml.dom.minidom.parseString(raw.encode("utf-8"))
        ugly = dom.toprettyxml(indent="  ")
        lines = [l for l in ugly.splitlines() if l.strip()]
        if lines and lines[0].startswith("<?xml") and not original.lstrip().startswith("<?xml"):
            lines = lines[1:]
        formatted = "\n".join(lines) + "\n"
        self._write_to_editor(formatted)
        self._status.setText(tr("json_xml.doc_updated"))

    def _write_to_editor(self, text: str) -> None:
        if self._editor is None:
            return
        self._editor.beginUndoAction()
        self._editor.selectAll()
        self._editor.replaceSelectedText(text)
        self._editor.endUndoAction()

    # ── Click su nodo → jump nell'editor ─────────────────────────────────────

    def _on_node_clicked(self, proxy_index) -> None:
        if self._editor is None:
            return
        src_index = self._proxy.mapToSource(proxy_index)
        col       = src_index.column()
        item      = self._model.itemFromIndex(src_index)
        if item is None:
            return

        edit_type = item.data(_ROLE_TYPE)   # "tag"|"attr:name"|"text"|"value"|None
        path_str  = item.data(_ROLE_PATH)
        jump_key  = item.data(_ROLE_JUMP)

        if self._lang == "json":
            # Colonna 1 = valore → salgo alla colonna 0 fratello per il nome chiave
            if col == 1:
                par = item.parent()
                sibling = par.child(item.row(), 0) if par else None
                jump_key = sibling.data(_ROLE_JUMP) if sibling else jump_key
            self._jump_to_in_editor(f'"{jump_key}"' if jump_key else "")

        elif self._lang == "xml":
            path = json.loads(path_str) if path_str else []

            if edit_type == "tag":
                # Tag item → jump preciso per path + attributi unici
                tag = jump_key or item.text().strip("<>")
                self._jump_xml_by_path_and_tag(path, tag)

            elif edit_type and edit_type.startswith("attr:"):
                # Attributo: cerca attr_name="attr_val" (di solito unico nel doc)
                attr_name = edit_type[5:]
                if col == 1:
                    attr_val = item.text()
                else:
                    # Colonna 0 (chiave attr) → leggi valore dalla colonna 1
                    par = item.parent()
                    sibling = par.child(item.row(), 1) if par else None
                    attr_val = sibling.text() if sibling else ""
                self._jump_to_in_editor(f'{attr_name}="{attr_val}"')

            elif edit_type == "text":
                # Testo foglia → salta al tag padre
                par = item.parent()
                sibling = par.child(item.row(), 0) if par else None
                tag = sibling.data(_ROLE_JUMP) if sibling else ""
                if tag:
                    self._jump_xml_by_path_and_tag(path, tag)

    def _jump_to_in_editor(self, term: str) -> None:
        """Trova la prima occorrenza di 'term' nel testo e la seleziona."""
        if self._editor is None or not term:
            return
        text = self._editor.text()
        pos = text.find(term)
        if pos < 0:
            pos = text.lower().find(term.lower())
        if pos < 0:
            return
        before  = text[:pos]
        line    = before.count("\n")
        col     = pos - (before.rfind("\n") + 1)
        self._editor.setSelection(line, col, line, col + len(term))
        self._editor.ensureLineVisible(line)
        self._editor.setFocus()
        # Il setSelection emette cursor_changed → avvia _cursor_timer.
        # Lo fermiamo subito per evitare che il pannello ricominci a scorrere.
        self._cursor_timer.stop()

    def _jump_xml_by_path_and_tag(self, path: list, tag_display: str) -> None:
        """Jump all'elemento XML corretto usando due strategie in cascata.

        Strategia 1 — attributo unico: naviga l'albero ET fino all'elemento,
        cerca un attributo il cui valore appaia UNA SOLA VOLTA nel documento,
        poi salta a quella stringa.

        Strategia 2 — N-esima occorrenza: usa path[-1] come indice del figlio
        e conta le occorrenze di '<tag' nel testo fino alla N-esima.
        Funziona bene per strutture piatte con tutti gli stessi tag (es. SoapUI).
        """
        if self._editor is None:
            return
        text = self._editor.text()

        # ── Strategia 1: attributo con valore univoco ──────────────────────
        try:
            self._collect_namespaces(text)
            root = ET.fromstring(text)
            target = self._navigate_xml(root, path)
            for attr_name, attr_val in target.attrib.items():
                combo = f'{attr_name}="{attr_val}"'
                if combo in text and text.count(combo) == 1:
                    self._jump_to_in_editor(combo)
                    return
        except Exception:
            pass

        # ── Strategia 2: N-esima occorrenza del tag di apertura ───────────
        sibling_idx = path[-1] if path else 0
        search = f"<{tag_display}"
        pos = -1
        for _ in range(sibling_idx + 1):
            pos = text.find(search, pos + 1)
            if pos < 0:
                return
        before = text[:pos]
        line   = before.count("\n")
        col    = pos - (before.rfind("\n") + 1)
        self._editor.setSelection(line, col, line, col + len(search))
        self._editor.ensureLineVisible(line)
        self._editor.setFocus()
        self._cursor_timer.stop()

    # ── Sincronizzazione editor → pannello ────────────────────────────────────

    def _on_editor_cursor(self) -> None:
        """Scattato da cursor_changed: avvia il timer debounce."""
        if not self._updating_editor:
            self._cursor_timer.start()

    def _sync_tree_from_cursor(self) -> None:
        """Legge la riga corrente e seleziona il nodo corrispondente nell'albero.
        Per gestire tag ripetuti (es. <con:setting> × 30) conta quante volte il
        tag appare nel testo PRIMA della riga corrente e seleziona quella occorrenza."""
        import re as _re
        if self._editor is None or not self._lang:
            return

        line, _col = self._editor.getCursorPosition()
        line_text  = self._editor.text(line)

        if self._lang == "json":
            m = _re.search(r'"([^"\\]+)"\s*:', line_text)
            if not m:
                return
            key = m.group(1)
            flag  = Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive
            items = self._model.findItems(key, flag, 0)
            if not items:
                return
            target_item = items[0]   # per JSON le chiavi sono solitamente uniche

        elif self._lang == "xml":
            m = _re.search(r'<([^\s/>?!][^\s/>]*)', line_text)
            if not m:
                return
            tag = m.group(1)          # es. "con:setting" (senza slash iniziale)
            if tag.startswith("/"):
                return                # closing tag — ignora
            display = f"<{tag}>"

            # Conta quante volte '<tag' appare nel testo PRIMA di questa riga
            full_text   = self._editor.text()
            lines_split = full_text.split("\n")
            text_before = "\n".join(lines_split[:line])
            occurrence  = text_before.count(f"<{tag}")

            flag  = Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive
            items = self._model.findItems(display, flag, 0)
            if not items:
                return
            # Seleziona la N-esima occorrenza (clampata all'ultimo disponibile)
            idx         = min(occurrence, len(items) - 1)
            target_item = items[idx]
        else:
            return

        src_idx   = self._model.indexFromItem(target_item)
        proxy_idx = self._proxy.mapFromSource(src_idx)
        if not proxy_idx.isValid():
            return
        self._cursor_timer.stop()
        self._tree.setCurrentIndex(proxy_idx)
        self._tree.scrollTo(proxy_idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    # ── Filtro ────────────────────────────────────────────────────────────────

    def _on_filter_changed(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)
        if text:
            self._tree.expandAll()
        else:
            self._tree.expandToDepth(1)

    def _expand_all(self) -> None:
        self._tree.expandAll()

    def _collapse_all(self) -> None:
        self._tree.collapseAll()
        self._tree.expandToDepth(0)

    # ── Formattazione documento ───────────────────────────────────────────────

    def format_document(self) -> None:
        """Pretty-print del documento JSON o XML nell'editor."""
        if self._editor is None:
            return
        self._detect_lang()
        if not self._lang:
            self._status.setText(tr("json_xml.unrecognized_type"))
            return
        text = self._editor.text()
        if not text.strip():
            return
        try:
            formatted = self._pretty_print(text)
        except json.JSONDecodeError as exc:
            self._status.setText(tr("json_xml.invalid_json", msg=exc.msg, line=exc.lineno))
            return
        except ET.ParseError as exc:
            self._status.setText(tr("json_xml.invalid_xml", error=str(exc)))
            return
        except Exception as exc:
            self._status.setText(tr("json_xml.parse_error", error=str(exc)))
            return
        if formatted == text:
            self._status.setText(tr("json_xml.already_formatted"))
            return
        self._write_to_editor(formatted)
        self._refresh()

    def _pretty_print(self, text: str) -> str:
        if self._lang == "json":
            data = json.loads(text)
            return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        dom = xml.dom.minidom.parseString(text.encode("utf-8"))
        ugly = dom.toprettyxml(indent="  ")
        lines = [l for l in ugly.splitlines() if l.strip()]
        if not text.lstrip().startswith("<?xml") and lines and lines[0].startswith("<?xml"):
            lines = lines[1:]
        return "\n".join(lines) + "\n"


# ── Funzione di installazione ─────────────────────────────────────────────────

def install(main_window: "MainWindow") -> JsonXmlPanel:
    """Crea il dock JSON/XML, lo aggiunge alla finestra e al menu Visualizza."""
    panel = JsonXmlPanel(main_window)

    dock = QDockWidget(tr("dock.json_xml"), main_window)
    dock.setObjectName("JsonXmlDock")
    dock.setWidget(panel)
    dock.setMinimumWidth(240)
    dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetClosable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )
    main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.hide()

    view_menu = main_window._menus.get("view")
    if view_menu:
        act = QAction(tr("action.view_json_xml_panel"), main_window)
        act.setShortcut(QKeySequence("Ctrl+Shift+J"))
        act.setCheckable(True)
        act.setIconVisibleInMenu(True)
        act.toggled.connect(dock.setVisible)
        def _sync_jx(visible, a=act):
            a.blockSignals(True)
            a.setChecked(visible)
            a.blockSignals(False)
        dock.visibilityChanged.connect(_sync_jx)
        view_menu.addAction(act)
        main_window._actions["view_json_xml_panel"] = act

    main_window._json_xml_dock  = dock
    main_window._json_xml_panel = panel
    return panel
