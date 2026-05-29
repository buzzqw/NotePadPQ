"""
Web Search plugin — cerca parola/selezione su Wikipedia (pannello inline),
Google, StackOverflow, Reddit, DuckDuckGo, GitHub e motori custom configurabili.

Tasto destro su parola o selezione → "Cerca su…" → sottomenu con tutti i motori abilitati.
Wikipedia apre il pannello laterale con l'estratto dell'API REST; gli altri aprono il browser.
"""

import json
import urllib.parse
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QDialog,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.settings import Settings
from i18n.i18n import tr
from plugins.base_plugin import BasePlugin


# (id, display_name, url_template)
# url_template "wiki" è speciale: apre il pannello laterale
_BUILTIN_ENGINES = [
    ("wiki",    "Wikipedia",     "wiki"),
    ("google",  "Google",        "https://www.google.com/search?q={query}"),
    ("so",      "StackOverflow", "https://stackoverflow.com/search?q={query}"),
    ("reddit",  "Reddit",        "https://www.reddit.com/search/?q={query}"),
    ("ddg",     "DuckDuckGo",    "https://duckduckgo.com/?q={query}"),
    ("github",  "GitHub",        "https://github.com/search?q={query}"),
]

_DEFAULT_ENABLED = [e[0] for e in _BUILTIN_ENGINES]


# ---------------------------------------------------------------------------
# Pannello laterale Wikipedia — QWebEngineView sulla versione mobile
# ---------------------------------------------------------------------------

_HIDE_CSS = """
    header.minerva-header, .header-container,
    .minerva-footer, #mw-mf-viewport footer,
    .page-actions-menu, .mw-mf-page-center > header,
    .talk-overlay, .noprint, #siteNotice,
    .catlinks, #coordinates { display: none !important; }
    .mw-mf-page-center, #content { padding-top: 4px !important; }
    body { margin: 8px !important; }
"""

_INJECT_JS = f"""
(function() {{
    var s = document.createElement('style');
    s.textContent = `{_HIDE_CSS}`;
    document.head.appendChild(s);
}})();
"""


class _WikiPanel(QWidget):
    search_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._desktop_url = ""
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # barra di ricerca
        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("websearch.search_placeholder"))
        self._search.returnPressed.connect(self._do_search)
        bar.addWidget(self._search)
        btn = QPushButton(tr("websearch.search_btn"))
        btn.setToolTip(tr("tooltip.websearch_search_btn"))
        btn.clicked.connect(self._do_search)
        bar.addWidget(btn)
        lay.addLayout(bar)

        # pulsante apri nel browser (allineato a destra sopra la view)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._open_btn = QPushButton(tr("websearch.open_browser"))
        self._open_btn.setToolTip(tr("tooltip.websearch_open_browser"))
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_in_browser)
        btn_row.addWidget(self._open_btn)
        lay.addLayout(btn_row)

        # barra di avanzamento caricamento
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.hide()
        lay.addWidget(self._progress)

        # view Wikipedia mobile
        from ui._webengine import safe_webview
        self._view = safe_webview()
        if self._view is not None:
            self._view.loadStarted.connect(self._on_load_started)
            self._view.loadProgress.connect(self._progress.setValue)
            self._view.loadFinished.connect(self._on_load_finished)
            lay.addWidget(self._view)
        else:
            from PyQt6.QtWidgets import QLabel
            from PyQt6.QtCore import Qt
            lbl = QLabel(tr("plugin.terminal.no_gl"))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lay.addWidget(lbl)

    # ------------------------------------------------------------------

    def search(self, query: str, lang: str) -> None:
        """Cerca su Wikipedia (versione mobile) con CSS cleanup."""
        if self._view is None:
            return
        self._search.setText(query)
        self._open_btn.setEnabled(False)
        encoded = urllib.parse.quote(query.replace(" ", "_"))
        self._desktop_url = f"https://{lang}.wikipedia.org/wiki/{encoded}"
        self._view.load(QUrl(f"https://{lang}.m.wikipedia.org/wiki/{encoded}"))

    def load_url(self, url: str) -> None:
        """Carica un URL generico nel pannello (Google, Reddit, SO, ecc.)."""
        if self._view is None:
            return
        self._search.clear()
        self._open_btn.setEnabled(False)
        self._desktop_url = url
        self._view.load(QUrl(url))

    def _do_search(self) -> None:
        query = self._search.text().strip()
        if query:
            self.search_requested.emit(query)

    def _on_load_started(self) -> None:
        self._progress.setValue(0)
        self._progress.show()

    def _on_load_finished(self, ok: bool) -> None:
        self._progress.hide()
        if ok and self._view is not None:
            self._open_btn.setEnabled(True)
            # CSS cleanup solo sulle pagine Wikipedia
            if ".wikipedia.org" in self._view.url().toString():
                self._view.page().runJavaScript(_INJECT_JS)

    def _open_in_browser(self) -> None:
        if self._desktop_url:
            QDesktopServices.openUrl(QUrl(self._desktop_url))


# ---------------------------------------------------------------------------
# Dialog impostazioni
# ---------------------------------------------------------------------------

class _SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("websearch.settings_title"))
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # --- motori built-in ---
        grp1 = QGroupBox(tr("websearch.builtin_engines"))
        grp1_lay = QVBoxLayout(grp1)
        self._checks: dict[str, QCheckBox] = {}
        for eid, name, _ in _BUILTIN_ENGINES:
            cb = QCheckBox(name)
            self._checks[eid] = cb
            grp1_lay.addWidget(cb)
        lay.addWidget(grp1)

        # --- motori custom ---
        grp2 = QGroupBox(tr("websearch.custom_engines"))
        grp2_lay = QVBoxLayout(grp2)

        info = QLabel(tr("websearch.custom_url_hint"))
        info.setWordWrap(True)
        grp2_lay.addWidget(info)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels([
            tr("websearch.engine_name"),
            tr("websearch.engine_url"),
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        grp2_lay.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(tr("websearch.add_engine"))
        add_btn.clicked.connect(lambda: self._add_row())
        del_btn = QPushButton(tr("websearch.del_engine"))
        del_btn.clicked.connect(self._del_row)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        grp2_lay.addLayout(btn_row)
        lay.addWidget(grp2)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._save_and_accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _load(self) -> None:
        s = Settings.instance()
        enabled = set(json.loads(s.get("websearch/enabled_engines", json.dumps(_DEFAULT_ENABLED))))
        for eid, cb in self._checks.items():
            cb.setChecked(eid in enabled)
        custom = json.loads(s.get("websearch/custom_engines", "[]"))
        for item in custom:
            self._add_row(item.get("name", ""), item.get("url", ""))

    def _add_row(self, name: str = "", url: str = "") -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem(name))
        self._table.setItem(r, 1, QTableWidgetItem(url))

    def _del_row(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedItems()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)

    def _save_and_accept(self) -> None:
        s = Settings.instance()
        enabled = [eid for eid, cb in self._checks.items() if cb.isChecked()]
        s.set("websearch/enabled_engines", json.dumps(enabled))
        custom = []
        for r in range(self._table.rowCount()):
            n_item = self._table.item(r, 0)
            u_item = self._table.item(r, 1)
            n = n_item.text().strip() if n_item else ""
            u = u_item.text().strip() if u_item else ""
            if n and u:
                custom.append({"name": n, "url": u})
        s.set("websearch/custom_engines", json.dumps(custom))
        self.accept()


# ---------------------------------------------------------------------------
# Plugin principale
# ---------------------------------------------------------------------------

class WebSearchPlugin(BasePlugin):
    NAME        = "Web Search"
    VERSION     = "1.0"
    DESCRIPTION = "Cerca parola/selezione su Wikipedia, Google, SO, Reddit e motori custom."
    AUTHOR      = "NotePadPQ"

    def on_load(self, main_window) -> None:
        super().on_load(main_window)
        self._last_editor = None

        # pannello Wikipedia
        self._panel = _WikiPanel(main_window)
        self._panel.search_requested.connect(self._on_panel_search)

        self._dock = QDockWidget(tr("websearch.panel_title"), main_window)
        self._dock.setObjectName("WebSearchDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(280)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
        self._dock.hide()

        from PyQt6.QtGui import QAction
        from PyQt6.QtWidgets import QMenu
        plugins_menu = main_window._menus.get("plugins")
        if plugins_menu:
            sub = QMenu(tr("websearch.submenu_title"), plugins_menu)
            act_wiki = QAction(tr("websearch.menu_action"), sub)
            act_wiki.triggered.connect(self._toggle)
            sub.addAction(act_wiki)
            act_settings = QAction(tr("websearch.settings_action"), sub)
            act_settings.triggered.connect(self._open_settings)
            sub.addAction(act_settings)
            sub_action = plugins_menu.addMenu(sub)
            self._menu_actions.append(sub_action)

        main_window._tab_manager.current_editor_changed.connect(self._on_editor_changed)
        cur = main_window._tab_manager.current_editor()
        if cur:
            self._on_editor_changed(cur)

    def on_unload(self) -> None:
        if hasattr(self, "_dock") and self._dock:
            self._dock.deleteLater()
        super().on_unload()

    def on_editor_changed(self, editor) -> None:
        self._on_editor_changed(editor)

    # ------------------------------------------------------------------

    def _on_editor_changed(self, editor) -> None:
        if self._last_editor:
            try:
                self._last_editor.context_menu_requested.disconnect(self._inject_context_menu)
            except Exception:
                pass
        self._last_editor = editor
        if editor and hasattr(editor, "context_menu_requested"):
            editor.context_menu_requested.connect(self._inject_context_menu)

    def _inject_context_menu(self, menu) -> None:
        editor = self._last_editor
        if not editor:
            return

        # selezione multipla o parola singola sotto il cursore
        query = editor.selectedText().strip()
        if not query:
            line, col = editor.getCursorPosition()
            query = editor.wordAtLineIndex(line, col).strip()
        if not query:
            return

        s = Settings.instance()
        enabled = set(
            json.loads(s.get("websearch/enabled_engines", json.dumps(_DEFAULT_ENABLED)))
        )
        custom = json.loads(s.get("websearch/custom_engines", "[]"))

        label = f'{tr("websearch.context_menu_title")} "{_truncate(query, 30)}"'
        sub = menu.addMenu(label)

        for eid, name, url_tmpl in _BUILTIN_ENGINES:
            if eid not in enabled:
                continue
            act = sub.addAction(name)
            if url_tmpl == "wiki":
                act.triggered.connect(
                    lambda checked=False, q=query: self._search_wiki(q)
                )
            else:
                act.triggered.connect(
                    lambda checked=False, q=query, u=url_tmpl: self._open_url(q, u)
                )

        for item in custom:
            name = item.get("name", "")
            url  = item.get("url", "")
            if name and url:
                act = sub.addAction(name)
                act.triggered.connect(
                    lambda checked=False, q=query, u=url: self._open_url(q, u)
                )

    # ------------------------------------------------------------------

    def _search_wiki(self, query: str) -> None:
        lang = Settings.instance().get("i18n/language", "it")
        self._dock.show()
        self._dock.raise_()
        self._panel.search(query, lang)

    def _on_panel_search(self, query: str) -> None:
        lang = Settings.instance().get("i18n/language", "it")
        self._panel.search(query, lang)

    def _open_url(self, query: str, url_tmpl: str) -> None:
        encoded = urllib.parse.quote_plus(query)
        url = url_tmpl.replace("{query}", encoded)
        self._dock.show()
        self._dock.raise_()
        self._panel.load_url(url)

    def _toggle(self) -> None:
        if self._dock.isVisible():
            self._dock.hide()
        else:
            self._dock.show()
            self._dock.raise_()

    def _open_settings(self) -> None:
        _SettingsDialog(self._mw).exec()


# ---------------------------------------------------------------------------

def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "…"
