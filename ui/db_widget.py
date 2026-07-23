"""
ui/db_widget.py — Plugin Database: connessione, schema browser, query editor
NotePadPQ

Layout ispirato a DBeaver / Beekeeper Studio:
  Sinistra  : schema browser persistente (tabelle → colonne con tipi)
  Destra    : tab multipli per query; ogni tab ha editor SQL (sopra) e
              risultati SpreadsheetWidget (sotto), con pannello messaggi.

Supporta: SQLite (stdlib), PostgreSQL (psycopg2-binary),
          MySQL/MariaDB (mysql-connector-python), Oracle (oracledb).
Driver mancanti: offerta di installazione via pip.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QRegularExpression, QStringListModel,
)
from PyQt6.QtGui import (
    QFont, QKeySequence, QColor,
    QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QPlainTextEdit,
    QLabel, QPushButton, QComboBox, QLineEdit,
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QMessageBox, QApplication, QFileDialog,
    QTabWidget, QFrame, QSizePolicy, QTabBar, QCompleter,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# ── Driver registry ───────────────────────────────────────────────────────────

_DRIVERS: dict[str, dict] = {
    "sqlite": {
        "display": "SQLite",
        "module":  "sqlite3",
        "pip":     None,
        "default_port": 0,
        "needs_host": False,
    },
    "postgresql": {
        "display": "PostgreSQL",
        "module":  "psycopg2",
        "pip":     "psycopg2-binary",
        "default_port": 5432,
        "needs_host": True,
    },
    "mysql": {
        "display": "MySQL / MariaDB",
        "module":  "mysql.connector",
        "pip":     "mysql-connector-python",
        "default_port": 3306,
        "needs_host": True,
    },
    "oracle": {
        "display": "Oracle",
        "module":  "oracledb",
        "pip":     "oracledb",
        "default_port": 1521,
        "needs_host": True,
    },
}


def _driver_available(db_type: str) -> bool:
    drv = _DRIVERS.get(db_type, {})
    if not drv:
        return False
    if drv.get("pip") is None:
        return True
    try:
        __import__(drv["module"])
        return True
    except ImportError:
        return False


# ── Icone SVG dal tema ────────────────────────────────────────────────────────

def _db_svg_icon(main_window, file_name: str):
    """Carica un'icona SVG del set Lucide colorata in base al tema attivo,
    per dare alla toolbar del plugin un look moderno e coerente con il resto
    dell'app (stesso pattern di `BasePlugin.load_plugin_icon`).

    Restituisce un `QIcon` (vuoto se il file non esiste o non è renderizzabile).
    """
    from PyQt6.QtGui import QIcon
    try:
        from ui.language_toolbar import render_svg_icon, toolbar_icon_color
    except Exception:
        return QIcon()
    path = Path(__file__).parent.parent / "icons" / "lucide" / file_name
    if not path.exists():
        return QIcon()
    try:
        color = toolbar_icon_color(main_window) if main_window is not None else "#1a1a1a"
        pm = render_svg_icon(path, color)
        if not pm.isNull():
            return QIcon(pm)
    except Exception:
        pass
    return QIcon()


# ── SQL syntax highlighter ────────────────────────────────────────────────────

def _sql_theme_colors() -> dict:
    """Colori per l'highlighter SQL letti dal tema attivo (niente più valori
    hardcoded come `#0055aa`): così la sintassi resta leggibile su tutti i 40+
    temi, chiari e scuri. Stesso pattern di `_theme_colors` in
    `plugins/search_results_plugin.py` / `_chat_palette` nel plugin AI.
    """
    try:
        from config.themes import ThemeManager
        tm      = ThemeManager.instance()
        theme   = tm.get_theme(tm._active_name) or {}
        tokens  = theme.get("tokens", {}) or {}
        is_dark = bool(theme.get("meta", {}).get("dark", True))
    except Exception:
        tokens, is_dark = {}, True

    def _tok(name: str, default: str) -> str:
        v = tokens.get(name, {})
        return (v.get("fg") if isinstance(v, dict) else None) or default

    if is_dark:
        return {
            "keyword":  _tok("keyword", "#4fa3e0"),
            "function": _tok("function", "#dcdcaa"),
            "string":   _tok("string", "#9bc36f"),
            "number":   _tok("number", "#d0935a"),
            "comment":  _tok("comment", "#7a8a7a"),
        }
    return {
        "keyword":  _tok("keyword", "#0055aa"),
        "function": _tok("function", "#7b2a8b"),
        "string":   _tok("string", "#007a00"),
        "number":   _tok("number", "#aa4400"),
        "comment":  _tok("comment", "#888888"),
    }


class _SqlHighlighter(QSyntaxHighlighter):
    _KEYWORDS = (
        "SELECT FROM WHERE AND OR NOT IN IS NULL LIKE BETWEEN EXISTS "
        "INSERT INTO VALUES UPDATE SET DELETE CREATE DROP ALTER TABLE "
        "INDEX VIEW TRIGGER PROCEDURE FUNCTION SCHEMA DATABASE "
        "JOIN INNER OUTER LEFT RIGHT FULL CROSS ON USING AS "
        "GROUP BY ORDER HAVING LIMIT OFFSET DISTINCT UNION ALL "
        "BEGIN COMMIT ROLLBACK TRANSACTION WITH RECURSIVE "
        "PRIMARY KEY FOREIGN REFERENCES CONSTRAINT UNIQUE DEFAULT "
        "CASE WHEN THEN ELSE END IF RETURN DECLARE"
    ).split()

    def __init__(self, document):
        super().__init__(document)
        colors = _sql_theme_colors()

        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor(colors["keyword"]))
        kw_fmt.setFontWeight(700)

        fn_fmt = QTextCharFormat()
        fn_fmt.setForeground(QColor(colors["function"]))

        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor(colors["string"]))

        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor(colors["number"]))

        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor(colors["comment"]))
        cmt_fmt.setFontItalic(True)

        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Keywords (case-insensitive, whole words)
        kw_pat = r"\b(?:" + "|".join(self._KEYWORDS) + r")\b"
        self._rules.append((QRegularExpression(kw_pat, QRegularExpression.PatternOption.CaseInsensitiveOption), kw_fmt))

        # Functions: name followed by (
        self._rules.append((QRegularExpression(r"\b[A-Z_][A-Z0-9_]*(?=\s*\()",
                                                QRegularExpression.PatternOption.CaseInsensitiveOption), fn_fmt))
        # Strings
        self._rules.append((QRegularExpression(r"'[^']*'"), str_fmt))
        self._rules.append((QRegularExpression(r'"[^"]*"'), str_fmt))
        # Numbers
        self._rules.append((QRegularExpression(r"\b\d+(\.\d+)?\b"), num_fmt))
        # Line comments
        self._rules.append((QRegularExpression(r"--[^\n]*"), cmt_fmt))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ── Driver installer dialog ───────────────────────────────────────────────────

class DBDriverInstallerDialog(QDialog):
    def __init__(self, db_type: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._db_type = db_type
        drv = _DRIVERS[db_type]
        self.setWindowTitle(tr("db.driver_missing_title", default="Driver mancante"))
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        lbl = QLabel(
            tr("db.driver_missing_desc", display=drv['display'], pip=drv['pip'])
        )
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self._status = QLabel("")
        self._status.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._status)

        btns = QDialogButtonBox()
        self._btn_install = btns.addButton(
            tr("db.install_driver", default="✦ Installa ora"),
            QDialogButtonBox.ButtonRole.AcceptRole
        )
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))
        btns.accepted.connect(self._do_install)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _do_install(self) -> None:
        drv = _DRIVERS[self._db_type]
        self._btn_install.setEnabled(False)
        self._status.setText(tr("db.installing_pip", pip=drv['pip']))
        QApplication.processEvents()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", drv["pip"]],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                self._status.setText(tr("db.install_completed"))
                QApplication.processEvents()
                self.accept()
            else:
                self._status.setText(tr("db.install_error"))
                QMessageBox.critical(self, "NotePadPQ",
                                     tr("db.pip_install_failed", stderr=result.stderr[-500:]))
                self._btn_install.setEnabled(True)
        except Exception as exc:
            self._status.setText(tr("db.install_error"))
            QMessageBox.critical(self, "NotePadPQ", str(exc))
            self._btn_install.setEnabled(True)


# ── Connect dialog ────────────────────────────────────────────────────────────

class DBConnectDialog(QDialog):
    def __init__(self, conn_info: Optional[dict] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._initial = conn_info or {}
        self.setWindowTitle(tr("db.connect_dialog_title",
                               default="Connessione database"))
        self.setMinimumWidth(480)
        self._build_ui()
        if conn_info:
            self._fill(conn_info)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._name = QLineEdit()
        self._name.setPlaceholderText(tr("db.conn_name_placeholder"))
        form.addRow(tr("db.conn_name", default="Nome connessione:"), self._name)

        self._type = QComboBox()
        for key, drv in _DRIVERS.items():
            self._type.addItem(drv["display"], key)
        self._type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow(tr("db.db_type", default="Tipo:"), self._type)
        layout.addLayout(form)

        # SQLite file
        self._grp_sqlite = QGroupBox(tr("db.sqlite_file_db"))
        sl = QHBoxLayout(self._grp_sqlite)
        self._sqlite_path = QLineEdit()
        self._sqlite_path.setPlaceholderText(tr("db.sqlite_path_placeholder"))
        sl.addWidget(self._sqlite_path)
        btn_br = QPushButton("…")
        btn_br.setFixedWidth(30)
        btn_br.clicked.connect(self._browse_sqlite)
        sl.addWidget(btn_br)
        layout.addWidget(self._grp_sqlite)

        # Network params
        self._grp_net = QGroupBox(tr("db.conn_details",
                                     default="Parametri di connessione"))
        nf = QFormLayout(self._grp_net)
        nf.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._host     = QLineEdit("localhost")
        self._port     = QLineEdit()
        self._database = QLineEdit()
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        nf.addRow(tr("db.host", default="Host:"),         self._host)
        nf.addRow(tr("db.port", default="Porta:"),        self._port)
        nf.addRow(tr("db.database", default="Database:"), self._database)
        nf.addRow(tr("db.username", default="Utente:"),   self._username)
        nf.addRow(tr("db.password", default="Password:"), self._password)
        layout.addWidget(self._grp_net)

        test_row = QHBoxLayout()
        btn_test = QPushButton(tr("db.test_conn", default="Testa connessione"))
        btn_test.clicked.connect(self._test)
        self._test_lbl = QLabel("")
        self._test_lbl.setStyleSheet("font-size: 11px;")
        test_row.addWidget(btn_test)
        test_row.addWidget(self._test_lbl)
        test_row.addStretch()
        layout.addLayout(test_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))

        self._on_type_changed()

    def _on_type_changed(self) -> None:
        db_type = self._type.currentData()
        self._grp_sqlite.setVisible(db_type == "sqlite")
        self._grp_net.setVisible(db_type != "sqlite")
        if db_type != "sqlite":
            dp = str(_DRIVERS[db_type]["default_port"])
            if not self._port.text() or self._port.text().isdigit():
                self._port.setText(dp)

    def _browse_sqlite(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("db.select_sqlite_db"), str(Path.home()),
            tr("db.sqlite_file_filter")
        )
        if path:
            self._sqlite_path.setText(path)
            if not self._name.text():
                self._name.setText(Path(path).stem)

    def _fill(self, info: dict) -> None:
        self._name.setText(info.get("name", ""))
        db_type = info.get("type", "sqlite")
        for i in range(self._type.count()):
            if self._type.itemData(i) == db_type:
                self._type.setCurrentIndex(i)
                break
        self._sqlite_path.setText(info.get("sqlite_path", ""))
        self._host.setText(info.get("host", "localhost"))
        self._port.setText(str(info.get("port", "")))
        self._database.setText(info.get("database", ""))
        self._username.setText(info.get("username", ""))
        self._password.setText(info.get("password", ""))

    def _test(self) -> None:
        info = self.get_info()
        if not _driver_available(info["type"]):
            dlg = DBDriverInstallerDialog(info["type"], self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
        try:
            conn = _open_connection(info)
            conn.close()
            self._test_lbl.setText(tr("db.connection_success"))
            self._test_lbl.setStyleSheet("color: green; font-size: 11px;")
        except Exception as exc:
            self._test_lbl.setText(tr("db.connection_test_failed", error=str(exc)))
            self._test_lbl.setStyleSheet("color: red; font-size: 11px;")

    def _accept(self) -> None:
        if not self._name.text().strip():
            QMessageBox.warning(self, "NotePadPQ",
                                tr("db_widget.new_conn_prompt"))
            return
        self.accept()

    def get_info(self) -> dict:
        db_type = self._type.currentData()
        return {
            "name":        self._name.text().strip(),
            "type":        db_type,
            "sqlite_path": self._sqlite_path.text().strip(),
            "host":        self._host.text().strip(),
            "port":        int(self._port.text() or
                               _DRIVERS[db_type]["default_port"]),
            "database":    self._database.text().strip(),
            "username":    self._username.text().strip(),
            "password":    self._password.text(),
        }


# ── Connection storage ────────────────────────────────────────────────────────

class DBConnectionsManager:
    _KEY = "db/connections"

    @staticmethod
    def load() -> list[dict]:
        from config.settings import Settings
        raw = Settings.instance().get(DBConnectionsManager._KEY, "[]")
        try:
            return json.loads(raw)
        except Exception:
            return []

    @staticmethod
    def save(connections: list[dict]) -> None:
        from config.settings import Settings
        Settings.instance().set(
            DBConnectionsManager._KEY, json.dumps(connections))

    @staticmethod
    def add(conn_info: dict) -> None:
        conns = DBConnectionsManager.load()
        for i, c in enumerate(conns):
            if c.get("name") == conn_info["name"]:
                conns[i] = conn_info
                DBConnectionsManager.save(conns)
                return
        conns.append(conn_info)
        DBConnectionsManager.save(conns)

    @staticmethod
    def remove(name: str) -> None:
        conns = [c for c in DBConnectionsManager.load()
                 if c.get("name") != name]
        DBConnectionsManager.save(conns)


# ── Saved connections dialog ──────────────────────────────────────────────────

class DBSavedConnectionsDialog(QDialog):
    connection_selected = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("db.saved_conns_title",
                               default="Connessioni salvate"))
        self.setMinimumSize(540, 360)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._list = QTreeWidget()
        self._list.setHeaderLabels([
            tr("db.conn_name", default="Nome"),
            tr("db.db_type",   default="Tipo"),
            tr("db.col_host_file"),
        ])
        self._list.setRootIsDecorated(False)
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._connect)
        layout.addWidget(self._list)

        row = QHBoxLayout()
        for label, slot in [
            (tr("db.connect", default="Connetti"),  self._connect),
            (tr("db.edit",    default="Modifica"),  self._edit),
            (tr("db.delete",  default="Elimina"),   self._delete),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        b_new = QPushButton(tr("db.new_conn", default="+ Nuova…"))
        b_new.clicked.connect(self._new)
        row.addWidget(b_new)
        layout.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _refresh(self) -> None:
        self._list.clear()
        for c in DBConnectionsManager.load():
            db_type = c.get("type", "")
            hf = (c.get("sqlite_path") or
                  f"{c.get('host','')}:{c.get('port','')}/{c.get('database','')}")
            item = QTreeWidgetItem([
                c.get("name", ""),
                _DRIVERS.get(db_type, {}).get("display", db_type),
                hf,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, c)
            self._list.addTopLevelItem(item)
        for i in range(3):
            self._list.resizeColumnToContents(i)

    def _selected(self) -> Optional[dict]:
        item = self._list.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _connect(self) -> None:
        info = self._selected()
        if info:
            self.connection_selected.emit(info)
            self.accept()

    def _edit(self) -> None:
        info = self._selected()
        if not info:
            return
        dlg = DBConnectDialog(info, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            DBConnectionsManager.add(dlg.get_info())
            self._refresh()

    def _delete(self) -> None:
        info = self._selected()
        if not info:
            return
        if QMessageBox.question(
            self, "NotePadPQ",
            tr("db.confirm_delete", default="Eliminare la connessione \"{name}\"?",
               name=info.get("name", ""))
        ) == QMessageBox.StandardButton.Yes:
            DBConnectionsManager.remove(info["name"])
            self._refresh()

    def _new(self) -> None:
        dlg = DBConnectDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            info = dlg.get_info()
            DBConnectionsManager.add(info)
            self._refresh()


# ── Driver manager dialog ─────────────────────────────────────────────────────

class DBDriverManagerDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("db.driver_manager_title",
                               default="Gestione driver database"))
        self.setMinimumWidth(500)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        lbl = QLabel(tr("db.driver_status_intro"))
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([
            tr("db.col_database"), tr("db.col_pip_package"), tr("db.col_status")])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        layout.addWidget(self._tree)

        btn_install = QPushButton(
            tr("db.install_selected", default="Installa driver selezionato"))
        btn_install.clicked.connect(self._install_selected)
        layout.addWidget(btn_install)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._refresh()

    def _refresh(self) -> None:
        self._tree.clear()
        for key, drv in _DRIVERS.items():
            ok = _driver_available(key)
            pip_pkg = drv["pip"] or "stdlib (built-in)"
            status = tr("db.driver_installed") if ok else tr("db.driver_not_installed")
            item = QTreeWidgetItem([drv["display"], pip_pkg, status])
            item.setForeground(
                2, Qt.GlobalColor.darkGreen if ok else Qt.GlobalColor.red)
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self._tree.addTopLevelItem(item)
        for i in range(3):
            self._tree.resizeColumnToContents(i)

    def _install_selected(self) -> None:
        item = self._tree.currentItem()
        if not item:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if _DRIVERS[key]["pip"] is None:
            QMessageBox.information(
                self, "NotePadPQ", tr("db.driver_stdlib"))
            return
        if _driver_available(key):
            QMessageBox.information(self, "NotePadPQ", tr("db.driver_already_installed"))
            return
        dlg = DBDriverInstallerDialog(key, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh()


# ── Low-level DB helpers ──────────────────────────────────────────────────────

def _open_connection(info: dict):
    db_type = info["type"]
    if db_type == "sqlite":
        import sqlite3
        return sqlite3.connect(info.get("sqlite_path") or ":memory:")
    if db_type == "postgresql":
        import psycopg2
        return psycopg2.connect(
            host=info["host"], port=info["port"],
            dbname=info["database"],
            user=info["username"], password=info["password"])
    if db_type == "mysql":
        import mysql.connector
        return mysql.connector.connect(
            host=info["host"], port=info["port"],
            database=info["database"],
            user=info["username"], password=info["password"])
    if db_type == "oracle":
        import oracledb
        return oracledb.connect(
            user=info["username"], password=info["password"],
            dsn=f"{info['host']}:{info['port']}/{info['database']}")
    raise ValueError(tr("db.unsupported_type", db_type=db_type))


def _get_tables(conn, db_type: str) -> list[tuple[str, str]]:
    cur = conn.cursor()
    if db_type == "sqlite":
        cur.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return cur.fetchall()
    if db_type == "postgresql":
        cur.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY table_name")
        return [(r[0], "table" if r[1] == "BASE TABLE" else "view")
                for r in cur.fetchall()]
    if db_type == "mysql":
        cur.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY table_name")
        return [(r[0], "table" if r[1] == "BASE TABLE" else "view")
                for r in cur.fetchall()]
    if db_type == "oracle":
        cur.execute("SELECT table_name,'table' FROM user_tables ORDER BY table_name")
        t = cur.fetchall()
        cur.execute("SELECT view_name,'view' FROM user_views ORDER BY view_name")
        return [(r[0], r[1]) for r in t + cur.fetchall()]
    return []


def _get_columns(conn, db_type: str, table: str) -> list[tuple[str, str]]:
    cur = conn.cursor()
    if db_type == "sqlite":
        cur.execute(f'PRAGMA table_info("{table}")')
        return [(r[1], r[2]) for r in cur.fetchall()]
    if db_type == "postgresql":
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position", (table,))
        return cur.fetchall()
    if db_type == "mysql":
        cur.execute(f"DESCRIBE `{table}`")
        return [(r[0], r[1]) for r in cur.fetchall()]
    if db_type == "oracle":
        cur.execute(
            "SELECT column_name, data_type FROM user_tab_columns "
            "WHERE table_name = :1 ORDER BY column_id", (table.upper(),))
        return cur.fetchall()
    return []


# ── Query worker ──────────────────────────────────────────────────────────────

import re as _re

def _quote_ident(name: str, db_type: str) -> str:
    """Quota un identificatore (tabella/colonna) secondo il dialetto, così
    nomi con maiuscole, spazi o parole riservate non rompono la query.
    MySQL usa i backtick, gli altri (PostgreSQL/SQLite/Oracle/standard) le
    doppie virgolette. Eventuali quote interne vengono raddoppiate.
    """
    if name is None:
        return name
    if db_type == "mysql":
        return "`" + str(name).replace("`", "``") + "`"
    return '"' + str(name).replace('"', '""') + '"'


def _is_select(sql: str) -> bool:
    return bool(_re.match(r"\s*SELECT\b", sql, _re.IGNORECASE))

def _wrap_page(sql: str, page_size: int, offset: int, db_type: str) -> str:
    """Avvolge una SELECT con LIMIT/OFFSET per la paginazione server-side."""
    inner = sql.rstrip("; \t\n")
    if db_type == "oracle":
        return (f"SELECT * FROM ({inner}) "
                f"OFFSET {offset} ROWS FETCH NEXT {page_size + 1} ROWS ONLY")
    return f"SELECT * FROM ({inner}) AS _npq_ LIMIT {page_size + 1} OFFSET {offset}"


class _QueryWorker(QThread):
    # headers, rows, error, elapsed, has_more
    finished = pyqtSignal(list, list, str, float, bool)

    def __init__(self, conn_info: dict, sql: str,
                 page_size: int = 0, offset: int = 0):
        super().__init__()
        self._conn_info = conn_info
        self._sql       = sql
        self._page_size = page_size   # 0 = no pagination (fetch all)
        self._offset    = offset

    def run(self) -> None:
        t0 = time.perf_counter()
        conn = None
        try:
            conn = _open_connection(self._conn_info)
            cur = conn.cursor()
            db_type  = self._conn_info.get("type", "")
            paginate = self._page_size > 0 and _is_select(self._sql)

            if paginate:
                exec_sql = _wrap_page(self._sql, self._page_size,
                                      self._offset, db_type)
            else:
                exec_sql = self._sql

            cur.execute(exec_sql)
            if cur.description:
                headers = [d[0] for d in cur.description]
                if paginate:
                    raw  = cur.fetchmany(self._page_size + 1)
                    has_more = len(raw) > self._page_size
                    rows = [[str(v) if v is not None else "" for v in r]
                            for r in raw[:self._page_size]]
                else:
                    rows     = [[str(v) if v is not None else "" for v in r]
                                for r in cur.fetchall()]
                    has_more = False
            else:
                headers  = ["Info"]
                rows     = [[tr("db.query_executed")]]
                has_more = False
                try:
                    conn.commit()
                except Exception:
                    pass
            self.finished.emit(headers, rows, "", time.perf_counter() - t0, has_more)
        except Exception as exc:
            self.finished.emit([], [], str(exc), time.perf_counter() - t0, False)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


# ── SQL editor con autocompletamento ───────────────────────────────────────────

class _SqlEditor(QPlainTextEdit):
    """Editor SQL con autocompletamento di keyword, nomi tabelle e colonne.

    Il completer mostra i suggerimenti mentre si digita (≥ 1 carattere della
    parola corrente). Le parole vengono fornite dall'esterno via
    `set_completion_words` (schema della connessione + keyword SQL).
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setModel(QStringListModel([], self._completer))
        self._completer.activated[str].connect(self._insert_completion)

    def set_completion_words(self, words: list[str]) -> None:
        model = self._completer.model()
        if isinstance(model, QStringListModel):
            model.setStringList(sorted(set(words)))

    def _text_under_cursor(self) -> str:
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        return tc.selectedText()

    def _insert_completion(self, completion: str) -> None:
        tc = self.textCursor()
        prefix_len = len(self._completer.completionPrefix())
        tc.movePosition(QTextCursor.MoveOperation.Left,
                        QTextCursor.MoveMode.KeepAnchor, prefix_len)
        tc.removeSelectedText()
        tc.insertText(completion)
        self.setTextCursor(tc)

    def keyPressEvent(self, event) -> None:
        popup = self._completer.popup()
        if popup.isVisible():
            # Tasti che il popup deve gestire/confermare/chiudere.
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return,
                                Qt.Key.Key_Tab, Qt.Key.Key_Escape,
                                Qt.Key.Key_Up, Qt.Key.Key_Down):
                event.ignore()
                return

        # Ctrl+Space: forza la comparsa del popup.
        force = (event.key() == Qt.Key.Key_Space
                 and event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if force:
            self._show_completer()
            return

        super().keyPressEvent(event)

        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                | Qt.KeyboardModifier.AltModifier):
            return
        prefix = self._text_under_cursor()
        if len(prefix) >= 1 and event.text() and (event.text().isalnum()
                                                   or event.text() in "_"):
            self._show_completer()
        else:
            popup.hide()

    def _show_completer(self) -> None:
        prefix = self._text_under_cursor()
        if not prefix:
            self._completer.popup().hide()
            return
        if prefix != self._completer.completionPrefix():
            self._completer.setCompletionPrefix(prefix)
            self._completer.popup().setCurrentIndex(
                self._completer.completionModel().index(0, 0))
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        rect = self.cursorRect()
        rect.setWidth(
            self._completer.popup().sizeHintForColumn(0)
            + self._completer.popup().verticalScrollBar().sizeHint().width())
        self._completer.complete(rect)


# ── Single query tab ──────────────────────────────────────────────────────────

class _QueryTab(QWidget):
    """
    Un tab di query: editor SQL in alto, risultati SpreadsheetWidget in basso.
    Layout a QSplitter verticale, simile a DBeaver.
    """

    PAGE_SIZE = 100

    def __init__(self, conn, conn_info: dict,
                 main_window: "MainWindow",
                 tab_index: int,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._conn         = conn
        self._conn_info    = conn_info
        self._mw           = main_window
        self._tab_index    = tab_index
        self._worker: Optional[_QueryWorker] = None
        self._result_widget: Optional[QWidget] = None
        self._raw_sql:   str  = ""
        self._page_offset: int = 0
        self._has_more:  bool = False
        self._last_headers: list = []
        self._last_rows:    list = []
        # Editing in-cella risultati
        self._editable_table: Optional[str] = None   # tabella se SELECT mono-tabella
        self._edit_orig_rows: list = []
        self._edit_headers:   list = []
        self._applying_edit:  bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Toolbar moderna a icone ---
        toolbar = QWidget()
        toolbar.setStyleSheet(
            "QWidget { background: palette(window); border-bottom: 1px solid palette(mid); }"
            "QToolButton { border: none; border-radius: 4px; padding: 4px; }"
            "QToolButton:hover { background: palette(midlight); }"
            "QToolButton:pressed { background: palette(mid); }"
            "QToolButton:disabled { opacity: 0.4; }"
        )
        trow = QHBoxLayout(toolbar)
        trow.setContentsMargins(6, 3, 6, 3)
        trow.setSpacing(2)

        from PyQt6.QtCore import QSize

        def _tool_btn(icon_file: str, fallback: str, tooltip: str, slot):
            """Crea un QToolButton a icona SVG (con fallback testuale se l'icona
            non è disponibile) per la toolbar moderna del plugin."""
            from PyQt6.QtWidgets import QToolButton
            b = QToolButton()
            icon = _db_svg_icon(self._mw, icon_file)
            if not icon.isNull():
                b.setIcon(icon)
                b.setIconSize(QSize(18, 18))
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            else:
                b.setText(fallback)
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            b.setToolTip(tooltip)
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        self._btn_run = _tool_btn(
            "play.svg", "▶",
            tr("db_widget.tooltip_run", default="Esegui (F5)"), self._execute)

        self._btn_cancel = _tool_btn(
            "square.svg", "✕",
            tr("db_widget.btn_cancel", default="Annulla"), self._cancel)
        self._btn_cancel.setEnabled(False)

        btn_clear = _tool_btn(
            "eraser.svg", tr("db_widget.btn_clear"),
            tr("db_widget.btn_clear"), self._clear_editor)

        self._btn_export = _tool_btn(
            "save.svg", tr("db_widget.btn_export"),
            tr("db_widget.btn_export"), self._export_results)
        self._btn_export.setEnabled(False)

        self._btn_history = _tool_btn(
            "rotate-cw.svg", "🕘",
            tr("db_widget.tooltip_history", default="Query eseguite di recente"),
            self._show_history_menu)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("font-size: 11px; color: gray; padding: 0 6px;")

        trow.addWidget(self._btn_run)
        trow.addWidget(self._btn_cancel)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: palette(mid);")
        trow.addWidget(sep1)

        trow.addWidget(btn_clear)
        trow.addWidget(self._btn_export)
        trow.addWidget(self._btn_history)
        trow.addWidget(self._status_lbl)
        trow.addStretch()

        hint = QLabel(tr("db_widget.run_hint",
                         default="F5 = esegui  |  Ctrl+Enter = esegui selezione"))
        hint.setStyleSheet("font-size: 10px; color: gray;")
        trow.addWidget(hint)
        layout.addWidget(toolbar)

        # --- Vertical splitter: editor + results ---
        self._splitter = QSplitter(Qt.Orientation.Vertical)

        # SQL editor (con autocompletamento)
        self._editor = _SqlEditor()
        self._editor.setPlaceholderText(
            tr("db.editor_placeholder")
        )
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        mono.setPointSize(11)
        self._editor.setFont(mono)
        _SqlHighlighter(self._editor.document())
        self._splitter.addWidget(self._editor)

        # Results area: container + pagination bar
        results_area = QWidget()
        ra_layout = QVBoxLayout(results_area)
        ra_layout.setContentsMargins(0, 0, 0, 0)
        ra_layout.setSpacing(0)

        self._results_container = QWidget()
        self._results_container.setLayout(QVBoxLayout())
        self._results_container.layout().setContentsMargins(0, 0, 0, 0)
        placeholder = QLabel(
            tr("db.results_placeholder",
               default="I risultati appariranno qui dopo l'esecuzione della query.")
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: gray; font-size: 12px; padding: 40px;")
        self._results_container.layout().addWidget(placeholder)
        ra_layout.addWidget(self._results_container, 1)

        # Pagination bar
        self._pager = QWidget()
        self._pager.setStyleSheet(
            "QWidget { background: palette(window); border-top: 1px solid palette(mid); }"
        )
        prow = QHBoxLayout(self._pager)
        prow.setContentsMargins(6, 2, 6, 2)
        prow.setSpacing(4)
        from PyQt6.QtWidgets import QToolButton
        from PyQt6.QtCore import QSize as _QSize
        self._btn_prev = QToolButton()
        _ic_prev = _db_svg_icon(self._mw, "chevron-left.svg")
        if not _ic_prev.isNull():
            self._btn_prev.setIcon(_ic_prev)
            self._btn_prev.setIconSize(_QSize(16, 16))
        else:
            self._btn_prev.setText("◀")
        self._btn_prev.setFixedSize(24, 22)
        self._btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_prev.clicked.connect(self._page_prev)
        self._page_lbl = QLabel("")
        self._page_lbl.setStyleSheet("font-size: 10px; color: gray;")
        self._btn_next = QToolButton()
        _ic_next = _db_svg_icon(self._mw, "chevron-right.svg")
        if not _ic_next.isNull():
            self._btn_next.setIcon(_ic_next)
            self._btn_next.setIconSize(_QSize(16, 16))
        else:
            self._btn_next.setText("▶")
        self._btn_next.setFixedSize(24, 22)
        self._btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_next.clicked.connect(self._page_next)
        prow.addStretch()
        prow.addWidget(self._btn_prev)
        prow.addWidget(self._page_lbl)
        prow.addWidget(self._btn_next)
        prow.addStretch()
        self._pager.setVisible(False)
        ra_layout.addWidget(self._pager)

        self._splitter.addWidget(results_area)

        self._splitter.setSizes([300, 200])
        layout.addWidget(self._splitter)

        # Shortcuts
        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("F5"), self, self._execute)
        QShortcut(QKeySequence("Ctrl+Return"), self, self._execute_selection)

    def _clear_editor(self) -> None:
        self._editor.clear()

    def set_sql(self, sql: str) -> None:
        self._editor.setPlainText(sql)

    def focus_editor(self) -> None:
        self._editor.setFocus()

    def set_completion_words(self, words: list[str]) -> None:
        """Aggiorna le parole dell'autocompletamento dell'editor SQL."""
        if hasattr(self._editor, "set_completion_words"):
            self._editor.set_completion_words(words)

    # ── Cronologia query ───────────────────────────────────────────────────────

    _HISTORY_KEY  = "db/query_history"
    _HISTORY_MAX  = 50

    def _history_load(self) -> list[str]:
        try:
            from config.settings import Settings
            raw = Settings.instance().get(self._HISTORY_KEY, "[]")
            data = json.loads(raw) if isinstance(raw, str) else (raw or [])
            return [str(x) for x in data][: self._HISTORY_MAX]
        except Exception:
            return []

    def _history_add(self, sql: str) -> None:
        sql = (sql or "").strip()
        if not sql:
            return
        try:
            from config.settings import Settings
            hist = self._history_load()
            # Niente duplicati consecutivi/ripetuti: porta in cima.
            hist = [h for h in hist if h != sql]
            hist.insert(0, sql)
            hist = hist[: self._HISTORY_MAX]
            Settings.instance().set(self._HISTORY_KEY, json.dumps(hist))
        except Exception:
            pass

    def _show_history_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        hist = self._history_load()
        menu = QMenu(self)
        if not hist:
            act = menu.addAction(tr("db_widget.history_empty",
                                    default="(nessuna query recente)"))
            act.setEnabled(False)
        else:
            for sql in hist:
                label = " ".join(sql.split())[:80]
                menu.addAction(label, lambda s=sql: self._use_history(s))
            menu.addSeparator()
            menu.addAction(tr("db_widget.history_clear",
                              default="Cancella cronologia"),
                           self._clear_history)
        menu.exec(self._btn_history.mapToGlobal(
            self._btn_history.rect().bottomLeft()))

    def _use_history(self, sql: str) -> None:
        self.set_sql(sql)
        self.focus_editor()

    def _clear_history(self) -> None:
        try:
            from config.settings import Settings
            Settings.instance().set(self._HISTORY_KEY, "[]")
        except Exception:
            pass

    # ── Execution ─────────────────────────────────────────────────────────────

    def _get_sql(self) -> str:
        tc = self._editor.textCursor()
        sel = tc.selectedText().strip()
        return sel or self._editor.toPlainText().strip()

    def _execute_selection(self) -> None:
        tc = self._editor.textCursor()
        if tc.hasSelection():
            self._execute()

    def _execute(self) -> None:
        if not self._conn_info:
            return
        if self._worker and self._worker.isRunning():
            return
        sql = self._get_sql()
        if not sql:
            return
        self._raw_sql    = sql
        self._page_offset = 0
        self._history_add(sql)
        self._run_worker(sql, offset=0)

    def _run_worker(self, sql: str, offset: int) -> None:
        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._status_lbl.setStyleSheet("color: gray; font-size: 11px;")
        self._status_lbl.setText(tr("db_widget.executing", default="Esecuzione…"))
        self._worker = _QueryWorker(
            self._conn_info, sql,
            page_size=self.PAGE_SIZE, offset=offset
        )
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._status_lbl.setText(tr("db_widget.cancelled"))

    def _on_done(self, headers: list, rows: list,
                 error: str, elapsed: float, has_more: bool) -> None:
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)

        if error:
            self._status_lbl.setStyleSheet("color: red; font-size: 11px;")
            self._status_lbl.setText("✗ " + tr("db_widget.error", default="Errore"))
            self._show_error(error)
            self._pager.setVisible(False)
            self._btn_export.setEnabled(False)
            return

        self._last_headers = headers
        self._last_rows    = rows
        self._has_more     = has_more
        # Determina se i risultati sono editabili (SELECT da singola tabella).
        self._editable_table = self._detect_editable_table(self._raw_sql)
        n = len(rows)
        offset = self._page_offset
        row_from = offset + 1
        row_to   = offset + n
        suffix   = "+" if has_more else ""
        self._status_lbl.setStyleSheet("color: green; font-size: 11px;")
        self._status_lbl.setText(
            tr("db.query_result_rows",
               row_from=row_from, row_to=row_to, suffix=suffix,
               elapsed=elapsed)
        )
        self._btn_export.setEnabled(bool(rows))
        self._show_results(headers, rows)

        # Pager
        show_pager = (offset > 0) or has_more
        self._pager.setVisible(show_pager)
        if show_pager:
            self._page_lbl.setText(
                tr("db.query_pager_rows", row_from=row_from, row_to=row_to, suffix=suffix)
            )
            self._btn_prev.setEnabled(offset > 0)
            self._btn_next.setEnabled(has_more)

    def _page_prev(self) -> None:
        self._page_offset = max(0, self._page_offset - self.PAGE_SIZE)
        self._run_worker(self._raw_sql, self._page_offset)

    def _page_next(self) -> None:
        self._page_offset += self.PAGE_SIZE
        self._run_worker(self._raw_sql, self._page_offset)

    def _export_results(self) -> None:
        """Esporta i risultati su file (stile DBeaver) tramite un UNICO dialogo
        che permette di scegliere: formato (CSV/TSV/XLSX/ODS), separatore (per
        i formati di testo), se includere la riga di intestazione, l'encoding e
        QUANTE righe esportare (pagina corrente / tutte / prime N).

        Prima il pulsante chiedeva solo "quante righe" e poi soltanto il nome
        del file, deducendo il separatore dall'estensione: l'utente non poteva
        scegliere separatore, intestazioni o encoding come fa DBeaver.
        """
        if not self._last_rows:
            # Prima qui si usciva in silenzio: il pulsante "sembrava non fare
            # nulla". Diamo un feedback esplicito all'utente.
            QMessageBox.information(
                self, "NotePadPQ",
                tr("db_widget.export_no_rows",
                   default="Nessun risultato da esportare. Esegui prima una "
                           "query che restituisca delle righe."))
            return
        try:
            opts = self._ask_export_options()
        except Exception as exc:
            QMessageBox.critical(
                self, "NotePadPQ",
                tr("db_widget.export_error", default="Errore export") + f":\n{exc}")
            return
        if opts is None:
            return

        # Recupera le righe in base alla scelta (pagina / tutte / prime N).
        if opts["rows"] == "page":
            headers, rows = self._last_headers, self._last_rows
        else:
            limit = opts["limit"] if opts["rows"] == "first_n" else 0
            fetched = self._export_fetch(limit)
            if fetched is None:
                return
            headers, rows = fetched

        self._save_rows_to_file(headers, rows, opts)

    def _ask_export_options(self):
        """Mostra il dialogo unico in stile DBeaver e restituisce un dict con
        le opzioni scelte, oppure `None` se l'utente annulla.

        Chiavi restituite: `format` (csv/tsv/xlsx/ods), `delimiter` (str),
        `header` (bool), `encoding` (str), `rows` (page/all/first_n),
        `limit` (int, valido solo per first_n).
        """
        from PyQt6.QtWidgets import (
            QRadioButton, QSpinBox, QComboBox, QCheckBox, QFormLayout, QGroupBox,
        )
        page_count = len(self._last_rows)
        has_more   = bool(getattr(self, "_has_more", False))

        dlg = QDialog(self)
        dlg.setModal(True)
        dlg.setWindowTitle(tr("db_widget.export_title", default="Esporta risultati"))
        v = QVBoxLayout(dlg)

        # --- Formato ---
        fmt_box = QGroupBox(tr("db_widget.export_format", default="Formato"))
        fmt_form = QFormLayout(fmt_box)
        fmt_combo = QComboBox()
        # (etichetta, formato, separatore di default)
        # NB: il delimitatore NON va incorporato qui (es. "CSV (,)"): si
        # sceglie nel campo "Separatore" sottostante, altrimenti l'utente lo
        # vedrebbe ripetuto in due posti (formato + separatore). Per TSV il
        # separatore è implicito (tab) e il campo Separatore è disabilitato.
        self._EXPORT_FORMATS = [
            ("CSV (.csv)",  "csv",  ","),
            ("TSV (.tsv)", "tsv", "\t"),
            ("Excel (.xlsx)", "xlsx", ""),
            ("OpenDocument (.ods)", "ods", ""),
        ]
        for label, _f, _d in self._EXPORT_FORMATS:
            fmt_combo.addItem(label)
        fmt_form.addRow(tr("db_widget.export_format", default="Formato") + ":", fmt_combo)

        # Separatore personalizzato (solo per formati di testo)
        delim_combo = QComboBox()
        delim_combo.setEditable(True)
        self._EXPORT_DELIMS = [
            (tr("db_widget.export_delim_comma", default="Virgola  ,"), ","),
            (tr("db_widget.export_delim_semicolon", default="Punto e virgola  ;"), ";"),
            (tr("db_widget.export_delim_tab", default="Tabulazione  \\t"), "\t"),
            (tr("db_widget.export_delim_pipe", default="Barra verticale  |"), "|"),
        ]
        for label, _d in self._EXPORT_DELIMS:
            delim_combo.addItem(label)
        fmt_form.addRow(
            tr("db_widget.export_delimiter", default="Separatore") + ":", delim_combo)

        # Encoding (solo per formati di testo)
        enc_combo = QComboBox()
        for enc in ("utf-8", "utf-8-sig", "latin-1", "utf-16"):
            enc_combo.addItem(enc)
        fmt_form.addRow(
            tr("db_widget.export_encoding", default="Codifica") + ":", enc_combo)

        # Intestazioni
        header_chk = QCheckBox(
            tr("db_widget.export_header", default="Includi riga di intestazione"))
        header_chk.setChecked(True)
        fmt_form.addRow("", header_chk)
        v.addWidget(fmt_box)

        # --- Righe da esportare ---
        rows_box = QGroupBox(tr("db_widget.export_rows_group", default="Righe da esportare"))
        rv = QVBoxLayout(rows_box)
        r_page = QRadioButton(
            tr("db_widget.export_page", default="Pagina corrente")
            + f"  ({page_count} " + tr("db_widget.export_rows", default="righe") + ")")
        r_all  = QRadioButton(
            tr("db_widget.export_all",
               default="Tutte le righe (ri-esegue la query senza limite)"))
        r_n    = QRadioButton(
            tr("db_widget.export_first_n", default="Prime N righe:"))
        spin   = QSpinBox()
        spin.setRange(1, 10_000_000)
        spin.setValue(1000)
        spin.setEnabled(False)
        r_n.toggled.connect(spin.setEnabled)
        if has_more:
            r_all.setChecked(True)
        else:
            r_page.setChecked(True)
        rv.addWidget(r_page)
        rv.addWidget(r_all)
        row_n = QHBoxLayout()
        row_n.addWidget(r_n)
        row_n.addWidget(spin)
        row_n.addStretch()
        rv.addLayout(row_n)
        v.addWidget(rows_box)

        # Abilita/disabilita separatore+encoding a seconda del formato scelto.
        # Per TSV il separatore è SEMPRE il tab (campo disabilitato e forzato),
        # così non c'è ambiguità con la scelta del formato.
        def _on_fmt_changed(idx: int) -> None:
            _label, fmt, default_delim = self._EXPORT_FORMATS[idx]
            is_text = fmt in ("csv", "tsv")
            # Il separatore è scelto dall'utente solo per il CSV; per TSV è
            # implicito (tab) e quindi il combo è bloccato.
            delim_combo.setEnabled(fmt == "csv")
            enc_combo.setEnabled(is_text)
            # Allinea il separatore di default a quello del formato scelto.
            if is_text:
                for i, (_l, d) in enumerate(self._EXPORT_DELIMS):
                    if d == default_delim:
                        delim_combo.setCurrentIndex(i)
                        break
        fmt_combo.currentIndexChanged.connect(_on_fmt_changed)
        _on_fmt_changed(0)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        _label, fmt, _default_delim = self._EXPORT_FORMATS[fmt_combo.currentIndex()]
        # Separatore: voce nota dalla lista, oppure testo libero digitato.
        di = delim_combo.currentIndex()
        if 0 <= di < len(self._EXPORT_DELIMS) and \
           delim_combo.currentText() == self._EXPORT_DELIMS[di][0]:
            delimiter = self._EXPORT_DELIMS[di][1]
        else:
            typed = delim_combo.currentText()
            delimiter = typed.replace("\\t", "\t") if typed else ","
        if opts_rows := r_all.isChecked():
            rows_mode = "all"
        elif r_n.isChecked():
            rows_mode = "first_n"
        else:
            rows_mode = "page"
        return {
            "format":   fmt,
            "delimiter": delimiter,
            "header":   header_chk.isChecked(),
            "encoding": enc_combo.currentText() or "utf-8",
            "rows":     rows_mode,
            "limit":    spin.value(),
        }

    def _export_fetch(self, limit: int):
        """Ri-esegue la query senza paginazione (o con LIMIT N) e restituisce
        `(headers, rows)`; `None` in caso di errore. NON modifica la griglia
        mostrata: i dati servono al salvataggio su file.
        """
        if not self._raw_sql or not self._conn_info:
            return None
        try:
            conn = _open_connection(self._conn_info)
            cur  = conn.cursor()
            db_type = self._conn_info.get("type", "")
            if limit > 0:
                sql = _wrap_page(self._raw_sql, limit, 0, db_type).replace(
                    f"LIMIT {limit + 1}", f"LIMIT {limit}"
                )
            else:
                sql = self._raw_sql
            cur.execute(sql)
            headers, rows = [], []
            if cur.description:
                headers = [d[0] for d in cur.description]
                rows    = [[str(v) if v is not None else "" for v in r]
                           for r in cur.fetchall()]
            conn.close()
            return headers, rows
        except Exception as exc:
            QMessageBox.critical(
                self, "NotePadPQ",
                tr("db_widget.export_error", default="Errore export") + f":\n{exc}")
            return None

    def _save_rows_to_file(self, headers: list, rows: list, opts: dict) -> None:
        """Salva (headers, rows) su un file scelto dall'utente onorando le
        `opts` scelte nel dialogo di export (formato, separatore, intestazioni,
        encoding).

        Per CSV/TSV scrive con uno scrittore custom che rispetta separatore,
        encoding e intestazioni sì/no; per XLSX/ODS delega a `SpreadsheetIO`.
        """
        if headers is None:
            return
        fmt        = opts.get("format", "csv")
        delimiter  = opts.get("delimiter", ",")
        encoding   = opts.get("encoding", "utf-8") or "utf-8"
        with_header = bool(opts.get("header", True))
        ext        = "." + fmt

        conn_name = self._conn_info.get("name", "query")
        suggested = f"{conn_name}_export{ext}"
        filters = {
            "csv":  "CSV (*.csv)",
            "tsv":  "TSV (*.tsv)",
            "xlsx": "Excel (*.xlsx)",
            "ods":  "OpenDocument (*.ods)",
        }
        path_str, _selected = QFileDialog.getSaveFileName(
            self,
            tr("db_widget.export_title", default="Esporta risultati"),
            suggested,
            filters.get(fmt, "CSV (*.csv)"),
        )
        if not path_str:
            return
        path = Path(path_str)
        if not path.suffix:
            path = path.with_suffix(ext)

        err = None
        try:
            if fmt in ("csv", "tsv"):
                # Scrittore custom: rispetta separatore, encoding e header
                # opzionale (SpreadsheetIO.save scrive sempre l'header in utf-8).
                import csv as _csv
                with open(path, "w", encoding=encoding, newline="") as f:
                    writer = _csv.writer(f, delimiter=delimiter)
                    if with_header:
                        writer.writerow(list(headers))
                    writer.writerows(list(rows))
            else:
                from ui.spreadsheet_widget import SpreadsheetIO
                out_headers = list(headers) if with_header else []
                err = SpreadsheetIO.save(path, out_headers, list(rows), delimiter)
        except Exception as exc:
            err = str(exc)
        if err:
            QMessageBox.critical(
                self, "NotePadPQ",
                tr("db_widget.export_error", default="Errore export") + f":\n{err}")
            return
        self._status_lbl.setStyleSheet("color: green; font-size: 11px;")
        self._status_lbl.setText(
            "✓ " + tr("db_widget.export_done",
                      default="Esportate {n} righe", n=len(rows)))

    def _open_converted_text(self, content: str, suggested_name: str) -> None:
        """Apre in una nuova scheda editor il contenuto convertito (Markdown /
        tabularx) emesso dalla SpreadsheetWidget dei risultati.

        Stesso comportamento del plugin Spreadsheet (`_open_as_text`): nel
        plugin DB il segnale `convert_to_text` non era collegato, perciò i
        pulsanti "→ Markdown" / "→ tabularx" sembravano non fare nulla.
        """
        try:
            ext = Path(suggested_name).suffix.lower()
            editor = self._mw._tab_manager.new_tab(template_ext=ext)
            editor.load_content(content)
        except Exception as exc:
            QMessageBox.critical(self, "NotePadPQ", str(exc))

    def _show_results(self, headers: list, rows: list, for_export: bool = False) -> None:
        layout = self._results_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # L'editing in-cella è permesso solo per SELECT da una singola tabella
        # (rilevata da _editable_table). In quel caso la griglia è scrivibile e
        # le modifiche generano UPDATE; altrimenti resta read-only.
        editable = (not for_export) and bool(self._editable_table) and bool(rows)
        try:
            from ui.spreadsheet_widget import SpreadsheetWidget
            conn_name = self._conn_info.get("name", "db")
            path = Path(f"{conn_name}_query_{self._tab_index}")
            widget = SpreadsheetWidget(
                path, headers, rows,
                read_only=not (for_export or editable), parent=self
            )
            # I pulsanti "→ Markdown" / "→ tabularx" della SpreadsheetWidget
            # emettono `convert_to_text`: nel plugin DB il segnale non era
            # collegato, quindi i pulsanti "non facevano nulla". Lo colleghiamo
            # all'apertura del contenuto convertito in un nuovo tab editor
            # (stesso comportamento del plugin Spreadsheet).
            try:
                widget.convert_to_text.connect(self._open_converted_text)
            except Exception:
                pass
            # Il pulsante "Esporta/Salva come…" della griglia risultati apriva
            # solo il semplice QFileDialog della SpreadsheetWidget. Nel plugin
            # DB lo deleghiamo all'interfaccia di esportazione ricca stile
            # DBeaver (`_export_results`: formato, separatore, codifica,
            # intestazioni, quante righe). Solo per la griglia visualizzata,
            # non per quella interna usata in fase di export.
            if not for_export:
                try:
                    widget.export_handler = self._export_results
                except Exception:
                    pass
            layout.addWidget(widget)
            self._result_widget = widget
            if editable:
                # Conserva una copia immutabile delle righe originali: serve a
                # costruire la clausola WHERE dell'UPDATE sui valori pre-modifica.
                self._edit_orig_rows = [list(r) for r in rows]
                self._edit_headers   = list(headers)
                self._applying_edit  = False
                try:
                    widget._model.dataChanged.connect(self._on_cell_edited)
                    self._status_lbl.setToolTip(
                        tr("db_widget.edit_enabled_hint",
                           default="Doppio clic su una cella per modificarla: "
                                   "verrà generato e applicato un UPDATE."))
                except Exception:
                    pass
            sizes = self._splitter.sizes()
            if sizes[1] < 150:
                total = sum(sizes)
                self._splitter.setSizes([int(total * 0.55), int(total * 0.45)])
        except Exception as exc:
            err_lbl = QLabel(tr("db.result_display_error", error=str(exc)))
            err_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(err_lbl)

    def _show_error(self, error: str) -> None:
        layout = self._results_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        lbl = QLabel(f"<pre style='color:red'>{error}</pre>")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lbl.setWordWrap(True)
        lbl.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(lbl)
        sizes = self._splitter.sizes()
        if sizes[1] < 100:
            total = sum(sizes)
            self._splitter.setSizes([int(total * 0.6), int(total * 0.4)])

    # ── Editing in-cella risultati ──────────────────────────────────────────────

    def _detect_editable_table(self, sql: str) -> Optional[str]:
        """Se la query è una SELECT semplice da una sola tabella (no JOIN, no
        aggregazioni/GROUP BY, no UNION), restituisce il nome della tabella;
        altrimenti None (risultati non editabili).
        """
        if not sql:
            return None
        s = " ".join(sql.split())
        low = s.lower()
        if not low.startswith("select"):
            return None
        # Esclude costrutti che impediscono un UPDATE riga-per-riga sicuro.
        for kw in (" join ", " group by ", " union ", " distinct ",
                   "count(", "sum(", "avg(", "min(", "max("):
            if kw in low:
                return None
        m = _re.search(r"\bfrom\s+([A-Za-z_][\w]*|\"[^\"]+\"|`[^`]+`)",
                       s, _re.IGNORECASE)
        if not m:
            return None
        # Niente alias/altra tabella subito dopo (FROM t1, t2 / FROM t alias).
        rest = s[m.end():].lstrip()
        if rest.startswith(","):
            return None
        table = m.group(1).strip('"`')
        return table or None

    def _on_cell_edited(self, top_left, bottom_right, _roles=None) -> None:
        """Genera ed esegue un UPDATE quando una cella viene modificata.

        Il WHERE usa i valori ORIGINALI dell'intera riga (prima della modifica):
        approccio robusto che non richiede una chiave primaria. Per sicurezza,
        se l'UPDATE tocca un numero di righe diverso da 1 si fa rollback.
        """
        if self._applying_edit or not self._editable_table:
            return
        try:
            row = top_left.row()
            col = top_left.column()
        except Exception:
            return
        if row >= len(self._edit_orig_rows):
            return
        model = self._result_widget._model if self._result_widget else None
        if model is None:
            return
        try:
            new_val = model._data[row][col]
        except Exception:
            return
        orig_row = self._edit_orig_rows[row]
        old_val  = orig_row[col] if col < len(orig_row) else ""
        if str(new_val) == str(old_val):
            return

        db = self._conn_info.get("type", "")
        headers = self._edit_headers
        qtable  = _quote_ident(self._editable_table, db)
        set_col = _quote_ident(headers[col], db)
        # Placeholder per dialetto (Oracle usa :1, gli altri ?/%s → usiamo ? per
        # sqlite, %s per gli altri; ma cur.execute con qmark non vale per pg).
        ph = "%s" if db in ("postgresql", "mysql") else "?"
        where_parts = []
        where_vals  = []
        for i, h in enumerate(headers):
            v = orig_row[i] if i < len(orig_row) else ""
            col_q = _quote_ident(h, db)
            if v == "" or v is None:
                where_parts.append(f"{col_q} IS NULL")
            else:
                where_parts.append(f"{col_q} = {ph}")
                where_vals.append(v)
        sql = (f"UPDATE {qtable} SET {set_col} = {ph} "
               f"WHERE " + " AND ".join(where_parts))
        params = [new_val] + where_vals

        ok, msg = self._apply_update(sql, params)
        if ok:
            # Aggiorna il valore di riferimento per le modifiche successive.
            if col < len(orig_row):
                orig_row[col] = new_val
            self._status_lbl.setStyleSheet("color: green; font-size: 11px;")
            self._status_lbl.setText(
                "✓ " + tr("db_widget.row_updated", default="Riga aggiornata"))
        else:
            # Ripristina il valore precedente nella griglia.
            self._applying_edit = True
            try:
                model._data[row][col] = old_val
                model.dataChanged.emit(top_left, top_left, [])
            finally:
                self._applying_edit = False
            QMessageBox.warning(
                self, "NotePadPQ",
                tr("db_widget.update_failed",
                   default="Modifica non applicata:\n{error}", error=msg))

    def _apply_update(self, sql: str, params: list) -> tuple[bool, str]:
        """Esegue un UPDATE sincrono in una connessione dedicata. Ritorna
        (ok, messaggio). Fa rollback se le righe interessate non sono esattamente 1.
        """
        conn = None
        try:
            conn = _open_connection(self._conn_info)
            cur  = conn.cursor()
            cur.execute(sql, params)
            affected = cur.rowcount
            if affected != 1:
                conn.rollback()
                return False, tr(
                    "db_widget.update_ambiguous",
                    default="L'UPDATE avrebbe modificato {n} righe (atteso 1); "
                            "annullato.", n=affected)
            conn.commit()
            return True, ""
        except Exception as exc:
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            return False, str(exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


# ── DB Browser widget ─────────────────────────────────────────────────────────

class DBBrowserWidget(QWidget):
    """
    Widget principale per una connessione database.

    Layout:
      ┌─────────────────────────────────────────────────┐
      │  [Nome connessione]  [Tipo]          [↺] stato  │
      ├──────────────┬──────────────────────────────────┤
      │ 📋 Tabelle   │ [Query 1] [Query 2] [+]           │
      │  ├ orders    │  ┌──────────────────────────────┐ │
      │  │  ├ id INT │  │  SELECT * FROM orders…       │ │
      │  │  └ ...    │  └──────────────────────────────┘ │
      │ 👁 Viste     │  ──── risultati SpreadsheetWidget ─│
      └──────────────┴──────────────────────────────────┘
    """

    modified_changed    = pyqtSignal(bool)
    _ai_ollama_ready    = pyqtSignal(object)   # list[str] | None
    _ai_anthropic_ready = pyqtSignal(object)   # list[str] | None

    def __init__(self, conn_info: dict,
                 main_window: "MainWindow",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.file_path: Optional[Path] = None
        self._conn_info  = conn_info
        self._mw         = main_window
        self._conn       = None
        self._query_count = 0
        # Cache schema: {table: [col_name, ...]} — alimenta autocomplete e
        # context menu (generazione INSERT, ecc.). Popolata in _load_schema
        # (tabelle) e _on_item_expanded (colonne, lazy).
        self._schema_cache: dict[str, list[str]] = {}

        self._build_ui()
        self._connect()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        header = QFrame()
        header.setFrameShape(QFrame.Shape.StyledPanel)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setStyleSheet(
            "QFrame { background: palette(mid); border: none; border-bottom: 1px solid palette(dark); }"
        )
        hrow = QHBoxLayout(header)
        hrow.setContentsMargins(8, 4, 8, 4)

        db_type  = self._conn_info.get("type", "")
        drv_name = _DRIVERS.get(db_type, {}).get("display", db_type)
        name     = self._conn_info.get("name", "")
        lbl = QLabel(f"<b>{name}</b>  <span style='color:gray; font-size:11px'>{drv_name}</span>")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        hrow.addWidget(lbl)
        hrow.addStretch()

        self._status_lbl = QLabel("…")
        self._status_lbl.setStyleSheet("font-size: 11px; color: gray;")
        hrow.addWidget(self._status_lbl)

        from PyQt6.QtWidgets import QToolButton
        from PyQt6.QtCore import QSize as _QSize

        btn_refresh = QToolButton()
        _ic_ref = _db_svg_icon(self._mw, "refresh-cw.svg")
        if not _ic_ref.isNull():
            btn_refresh.setIcon(_ic_ref)
            btn_refresh.setIconSize(_QSize(16, 16))
        else:
            btn_refresh.setText("↺")
        btn_refresh.setFixedSize(28, 26)
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.setToolTip(tr("db_widget.tooltip_refresh_schema",
                                  default="Aggiorna schema"))
        btn_refresh.clicked.connect(self._load_schema)
        hrow.addWidget(btn_refresh)

        btn_new_q = QToolButton()
        _ic_newq = _db_svg_icon(self._mw, "file-plus.svg")
        if not _ic_newq.isNull():
            btn_new_q.setIcon(_ic_newq)
            btn_new_q.setIconSize(_QSize(16, 16))
        else:
            btn_new_q.setText("+ Query")
        btn_new_q.setFixedSize(28, 26)
        btn_new_q.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_new_q.setToolTip(tr("db_widget.tooltip_new_query"))
        btn_new_q.clicked.connect(self._add_query_tab)
        hrow.addWidget(btn_new_q)

        root.addWidget(header)

        # ── Main splitter: schema | query tabs ────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # --- Schema tree ---
        schema_panel = QWidget()
        sp_layout = QVBoxLayout(schema_panel)
        sp_layout.setContentsMargins(0, 0, 0, 0)
        sp_layout.setSpacing(0)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(tr("db_widget.placeholder_filter"))
        self._search_box.setFixedHeight(26)
        self._search_box.textChanged.connect(self._filter_tree)
        sp_layout.addWidget(self._search_box)

        # ── AI Query panel ────────────────────────────────────────────────────
        self._ai_panel = self._build_ai_panel()
        sp_layout.addWidget(self._ai_panel)

        self._schema_tree = QTreeWidget()
        self._schema_tree.setHeaderHidden(True)
        self._schema_tree.setMinimumWidth(180)
        self._schema_tree.itemExpanded.connect(self._on_item_expanded)
        self._schema_tree.itemDoubleClicked.connect(self._on_table_double_click)
        self._schema_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._schema_tree.customContextMenuRequested.connect(
            self._schema_context_menu)
        sp_layout.addWidget(self._schema_tree)

        schema_panel.setMinimumWidth(180)
        schema_panel.setMaximumWidth(340)
        splitter.addWidget(schema_panel)

        # --- Query tab widget ---
        self._query_tabs = QTabWidget()
        self._query_tabs.setTabsClosable(True)
        self._query_tabs.tabCloseRequested.connect(self._close_query_tab)
        self._query_tabs.setMovable(True)
        splitter.addWidget(self._query_tabs)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(splitter, 1)

        # Initial query tab
        self._add_query_tab()

    # ── Connection ────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        db_type = self._conn_info.get("type", "")
        if not _driver_available(db_type):
            dlg = DBDriverInstallerDialog(db_type, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._status_lbl.setText(tr("db.driver_unavailable"))
                return

        try:
            self._conn = _open_connection(self._conn_info)
            self._status_lbl.setText(tr("db.connected"))
            self._status_lbl.setStyleSheet("color: green; font-size: 11px;")
            self._load_schema()
        except Exception as exc:
            self._status_lbl.setText(tr("db.connection_error_status", error=str(exc)[:60]))
            self._status_lbl.setStyleSheet("color: red; font-size: 11px;")
            QMessageBox.critical(
                self, "NotePadPQ",
                tr("db.connect_error", default="Errore di connessione:\n{error}",
                   error=str(exc))
            )

    # ── Schema tree ───────────────────────────────────────────────────────────

    # ── AI panel ──────────────────────────────────────────────────────────────

    def _build_ai_panel(self) -> QWidget:
        container = QWidget()
        container.setObjectName("ai_panel")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        container.setStyleSheet(
            "#ai_panel { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        # Toggle header
        header_row = QHBoxLayout()
        self._ai_toggle = QPushButton(tr("db.ai_query_button") + "  ▾")
        self._ai_toggle.setStyleSheet(
            "QPushButton { border: none; text-align: left; font-size: 11px; "
            "font-weight: bold; color: palette(text); background: transparent; }"
            "QPushButton:hover { color: palette(highlight); }"
        )
        self._ai_toggle.setFixedHeight(22)
        self._ai_toggle.clicked.connect(self._toggle_ai_panel)
        header_row.addWidget(self._ai_toggle)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Body (collapsible)
        self._ai_body = QWidget()
        body_layout = QVBoxLayout(self._ai_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(3)

        # Provider selector row
        prov_row = QHBoxLayout()
        prov_lbl = QLabel(tr("db.ai_provider") + ":")
        prov_lbl.setStyleSheet("font-size: 10px;")
        prov_row.addWidget(prov_lbl)
        self._ai_provider_combo = QComboBox()
        self._ai_provider_combo.setFixedHeight(22)
        self._ai_provider_combo.setStyleSheet("font-size: 10px;")
        self._ai_provider_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._ai_populate_providers()
        self._ai_provider_combo.currentIndexChanged.connect(self._ai_on_provider_changed)
        prov_row.addWidget(self._ai_provider_combo)
        body_layout.addLayout(prov_row)

        # Model selector row
        model_row = QHBoxLayout()
        model_lbl = QLabel(tr("db.ai_model") + ":")
        model_lbl.setStyleSheet("font-size: 10px;")
        model_row.addWidget(model_lbl)
        self._ai_model_combo = QComboBox()
        self._ai_model_combo.setFixedHeight(22)
        self._ai_model_combo.setStyleSheet("font-size: 10px;")
        self._ai_model_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_row.addWidget(self._ai_model_combo)
        self._ai_refresh_btn = QPushButton("↻")
        self._ai_refresh_btn.setFixedSize(22, 22)
        self._ai_refresh_btn.setToolTip(tr("db.refresh_models_tooltip"))
        self._ai_refresh_btn.setStyleSheet("font-size: 11px; padding: 0;")
        self._ai_refresh_btn.clicked.connect(self._ai_refresh_models)
        self._ai_refresh_btn.setVisible(False)
        model_row.addWidget(self._ai_refresh_btn)
        body_layout.addLayout(model_row)

        # Connect dynamic model signals
        self._ai_ollama_ready.connect(self._ai_set_ollama_models)
        self._ai_anthropic_ready.connect(self._ai_set_anthropic_models)

        self._ai_on_provider_changed()  # populate models for default provider

        self._ai_input = QPlainTextEdit()
        self._ai_input.setPlaceholderText(tr("db_widget.ai_placeholder"))
        self._ai_input.setFixedHeight(70)
        self._ai_input.setFont(QFont("sans-serif"))
        body_layout.addWidget(self._ai_input)

        ai_row = QHBoxLayout()
        self._btn_ai_gen = QPushButton(tr("db_widget.btn_ai_gen"))
        self._btn_ai_gen.setFixedHeight(24)
        self._btn_ai_gen.clicked.connect(self._ai_generate_sql)
        self._ai_status = QLabel("")
        self._ai_status.setStyleSheet("font-size: 10px; color: gray;")
        ai_row.addWidget(self._btn_ai_gen)
        ai_row.addWidget(self._ai_status)
        ai_row.addStretch()
        body_layout.addLayout(ai_row)

        self._ai_body.setVisible(False)
        layout.addWidget(self._ai_body)
        return container

    def _ai_populate_providers(self) -> None:
        """Popola il combo dei provider con quelli che hanno una chiave configurata."""
        self._ai_provider_combo.clear()
        try:
            from plugins.ai_plugin import PROVIDERS
            from config.settings import Settings
        except ImportError:
            return
        s = Settings.instance()
        for name, info in PROVIDERS.items():
            pid = info["id"]
            if pid == "ollama":
                self._ai_provider_combo.addItem(name, userData=info)
            else:
                key = s.get(f"ai/{pid}_key", "").strip()
                if key:
                    self._ai_provider_combo.addItem(name, userData=info)
        if self._ai_provider_combo.count() == 0:
            self._ai_provider_combo.addItem(tr("db.no_provider_configured"), userData=None)

    def _ai_on_provider_changed(self, _index: int = 0) -> None:
        """Aggiorna il combo dei modelli in base al provider selezionato."""
        self._ai_model_combo.clear()
        info = self._ai_provider_combo.currentData()
        if not info:
            if hasattr(self, "_ai_refresh_btn"):
                self._ai_refresh_btn.setVisible(False)
            return
        try:
            from config.settings import Settings
        except ImportError:
            return
        s = Settings.instance()
        pid = info["id"]
        saved_model = s.get(f"ai/{pid}_model", info.get("default", ""))
        models = info.get("models", [])
        for m in models:
            self._ai_model_combo.addItem(m)
        if saved_model in models:
            self._ai_model_combo.setCurrentText(saved_model)
        elif saved_model:
            self._ai_model_combo.insertItem(0, saved_model)
            self._ai_model_combo.setCurrentIndex(0)

        show_refresh = pid in ("anthropic", "ollama")
        if hasattr(self, "_ai_refresh_btn"):
            self._ai_refresh_btn.setVisible(show_refresh)
        if pid == "ollama":
            self._ai_fetch_ollama_models()
        elif pid == "anthropic":
            self._ai_fetch_anthropic_models()

    def _toggle_ai_panel(self) -> None:
        visible = not self._ai_body.isVisible()
        self._ai_body.setVisible(visible)
        self._ai_toggle.setText(tr("db.ai_query_button") + "  " + ("▴" if visible else "▾"))
        if visible:
            self._ai_populate_providers()  # refresh in case keys were added

    def _ai_refresh_models(self) -> None:
        info = self._ai_provider_combo.currentData()
        if not info:
            return
        pid = info["id"]
        if pid == "ollama":
            self._ai_fetch_ollama_models()
        elif pid == "anthropic":
            self._ai_fetch_anthropic_models()

    def _ai_fetch_ollama_models(self) -> None:
        import threading
        try:
            from config.settings import Settings
        except ImportError:
            return
        self._ai_refresh_btn.setEnabled(False)
        ollama_url = Settings.instance().get("ai/ollama_key", "") or "http://localhost:11434"

        def _fetch():
            try:
                import urllib.request as _ur, json as _json
                req = _ur.Request(f"{ollama_url.rstrip('/')}/api/tags", method="GET")
                with _ur.urlopen(req, timeout=3) as resp:
                    data = _json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                self._ai_ollama_ready.emit(models or None)
            except Exception:
                self._ai_ollama_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _ai_set_ollama_models(self, models) -> None:
        self._ai_refresh_btn.setEnabled(True)
        info = self._ai_provider_combo.currentData()
        if not info or info.get("id") != "ollama":
            return
        current = self._ai_model_combo.currentText()
        self._ai_model_combo.clear()
        if models is None:
            self._ai_model_combo.addItem(tr("db.ollama_not_reachable"))
            self._ai_model_combo.setEnabled(False)
            return
        self._ai_model_combo.setEnabled(True)
        for m in models:
            self._ai_model_combo.addItem(m)
        idx = self._ai_model_combo.findText(current)
        if idx >= 0:
            self._ai_model_combo.setCurrentIndex(idx)

    def _ai_fetch_anthropic_models(self) -> None:
        import threading
        try:
            from config.settings import Settings
        except ImportError:
            return
        api_key = Settings.instance().get("ai/anthropic_key", "").strip()
        if not api_key:
            return
        self._ai_refresh_btn.setEnabled(False)

        def _fetch():
            try:
                import urllib.request as _ur, json as _json
                req = _ur.Request(
                    "https://api.anthropic.com/v1/models",
                    method="GET",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                )
                with _ur.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read())
                try:
                    from plugins.ai_plugin import PROVIDERS
                    static = PROVIDERS["Anthropic (Claude)"]["models"]
                except Exception:
                    static = []
                ids = [m["id"] for m in data.get("data", []) if m.get("id","").startswith("claude-")]
                known = [m for m in static if m in ids]
                extra = [m for m in ids   if m not in static]
                self._ai_anthropic_ready.emit((known + extra) or None)
            except Exception:
                self._ai_anthropic_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _ai_set_anthropic_models(self, models) -> None:
        self._ai_refresh_btn.setEnabled(True)
        info = self._ai_provider_combo.currentData()
        if not info or info.get("id") != "anthropic":
            return
        if not models:
            return
        current = self._ai_model_combo.currentText()
        self._ai_model_combo.clear()
        for m in models:
            self._ai_model_combo.addItem(m)
        idx = self._ai_model_combo.findText(current)
        if idx >= 0:
            self._ai_model_combo.setCurrentIndex(idx)

    def _build_schema_context(self) -> str:
        """Costruisce una stringa testuale con lo schema per il prompt AI."""
        lines = [f"Database: {self._conn_info.get('name','')} ({self._conn_info.get('type','')})"]
        db_type = self._conn_info.get("type", "")
        if self._conn is None:
            return "\n".join(lines)
        try:
            tables = _get_tables(self._conn, db_type)
            for name, kind in tables[:50]:   # limit context size
                cols = _get_columns(self._conn, db_type, name)
                col_str = ", ".join(f"{c}({t})" for c, t in cols[:30])
                lines.append(f"{'TABLE' if kind == 'table' else 'VIEW'} {name}: {col_str}")
        except Exception:
            pass
        return "\n".join(lines)

    def _ai_generate_sql(self) -> None:
        question = self._ai_input.toPlainText().strip()
        if not question:
            return

        try:
            from config.settings import Settings
            from plugins.ai_plugin import _AIWorker
        except ImportError:
            QMessageBox.warning(self, "NotePadPQ", tr("msg.ai_not_available"))
            return

        pinfo = self._ai_provider_combo.currentData()
        if not pinfo:
            QMessageBox.warning(
                self, "NotePadPQ",
                tr("db.ai_no_provider_configured")
            )
            return

        s = Settings.instance()
        pid   = pinfo["id"]
        model = self._ai_model_combo.currentText() or pinfo.get("default", "")
        if pid == "ollama":
            api_key = s.get("ai/ollama_key", "") or "http://localhost:11434"
        else:
            api_key = s.get(f"ai/{pid}_key", "").strip()

        schema_ctx = self._build_schema_context()
        system_prompt = (
            "You are an expert SQL assistant.\n"
            "Given the following database schema, write a SQL query that answers "
            "the user's question.\n"
            "Respond with ONLY the raw SQL query — no markdown, no code fences, "
            "no explanation.\n\n"
            f"Schema:\n{schema_ctx}"
        )
        messages = [{"role": "user", "content": question}]

        self._btn_ai_gen.setEnabled(False)
        self._ai_status.setText(tr("db.ai_generating"))

        self._ai_worker = _AIWorker(
            pid, model, api_key,
            messages, system=system_prompt, max_tokens=512
        )
        self._ai_worker.result_ready.connect(self._on_ai_sql_ready)
        self._ai_worker.error_occurred.connect(self._on_ai_error)
        self._ai_worker.start()

    def _on_ai_sql_ready(self, text: str) -> None:
        self._btn_ai_gen.setEnabled(True)
        self._ai_status.setText(tr("db.ai_ready"))
        # Strip markdown fences if the AI added them despite instructions
        sql = text.strip()
        import re as _re
        sql = _re.sub(r'^```[a-z]*\n?', '', sql, flags=_re.IGNORECASE)
        sql = _re.sub(r'\n?```$', '', sql)
        sql = sql.strip()
        tab = self._current_query_tab()
        if tab:
            tab.set_sql(sql)
            tab.focus_editor()

    def _on_ai_error(self, error: str) -> None:
        self._btn_ai_gen.setEnabled(True)
        self._ai_status.setText(tr("db.ai_error"))
        QMessageBox.critical(self, "NotePadPQ",
                             tr("db.ai_error_detail", error=error))

    def _load_schema(self) -> None:
        if self._conn is None:
            return
        self._schema_tree.clear()
        db_type = self._conn_info.get("type", "")

        try:
            tables = _get_tables(self._conn, db_type)
        except Exception as exc:
            self._status_lbl.setText(tr("db.schema_error", error=str(exc)))
            return

        table_root = QTreeWidgetItem(["📋  Tabelle"])
        view_root  = QTreeWidgetItem(["👁  Viste"])
        table_root.setExpanded(True)

        self._schema_cache.clear()
        for name, kind in tables:
            icon = "  📄  " if kind == "table" else "  👁  "
            parent = table_root if kind == "table" else view_root
            item = QTreeWidgetItem([icon + name])
            item.setData(0, Qt.ItemDataRole.UserRole, {"table": name, "loaded": False})
            # Placeholder child so expand arrow appears
            item.addChild(QTreeWidgetItem(["  ⌛ caricamento…"]))
            parent.addChild(item)
            # Registra la tabella nella cache (colonne caricate lazy all'espansione).
            self._schema_cache.setdefault(name, [])
        self._refresh_autocomplete()

        self._schema_tree.addTopLevelItem(table_root)
        if view_root.childCount() > 0:
            self._schema_tree.addTopLevelItem(view_root)

        n = table_root.childCount() + view_root.childCount()
        self._status_lbl.setText(tr("db.schema_objects_count", n=n))
        self._status_lbl.setStyleSheet("color: green; font-size: 11px;")

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("loaded"):
            return
        table = data["table"]
        db_type = self._conn_info.get("type", "")
        item.takeChildren()  # remove placeholder
        try:
            cols = _get_columns(self._conn, db_type, table)
            for col_name, col_type in cols:
                child = QTreeWidgetItem([f"    🔹 {col_name}  ({col_type})"])
                child.setForeground(0, Qt.GlobalColor.gray)
                item.addChild(child)
            # Aggiorna la cache colonne per autocomplete e generazione SQL.
            self._schema_cache[table] = [c[0] for c in cols]
            self._refresh_autocomplete()
        except Exception as exc:
            item.addChild(QTreeWidgetItem([f"  ✗ {exc}"]))
        data["loaded"] = True
        item.setData(0, Qt.ItemDataRole.UserRole, data)

    # Keyword SQL comuni offerte dall'autocompletamento.
    _SQL_KEYWORDS = (
        "SELECT FROM WHERE GROUP BY HAVING ORDER LIMIT OFFSET INSERT INTO "
        "VALUES UPDATE SET DELETE CREATE TABLE VIEW INDEX DROP ALTER ADD "
        "JOIN INNER LEFT RIGHT OUTER FULL ON AS DISTINCT COUNT SUM AVG MIN "
        "MAX AND OR NOT NULL IS IN BETWEEN LIKE EXISTS UNION ALL ASC DESC "
        "PRIMARY KEY FOREIGN REFERENCES DEFAULT CASE WHEN THEN ELSE END"
    ).split()

    def _refresh_autocomplete(self) -> None:
        """Compone le parole per l'autocompletamento (keyword SQL + nomi
        tabelle + colonne dalla cache schema) e le invia a tutti i query-tab.
        """
        words: list[str] = list(self._SQL_KEYWORDS)
        for table, cols in self._schema_cache.items():
            words.append(table)
            words.extend(cols)
        tabs = getattr(self, "_query_tabs", None)
        if tabs is None:
            return
        for i in range(tabs.count()):
            tab = tabs.widget(i)
            if hasattr(tab, "set_completion_words"):
                tab.set_completion_words(words)

    def _filter_tree(self, text: str) -> None:
        text = text.lower()
        for i in range(self._schema_tree.topLevelItemCount()):
            root = self._schema_tree.topLevelItem(i)
            any_visible = False
            for j in range(root.childCount()):
                child = root.child(j)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                table = data["table"].lower() if data else ""
                visible = not text or text in table
                child.setHidden(not visible)
                if visible:
                    any_visible = True
            root.setHidden(not any_visible and bool(text))

    def _on_table_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or "table" not in data:
            return
        table = data["table"]
        self._run_select(table)

    def _schema_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu
        item = self._schema_tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or "table" not in data:
            return
        table = data["table"]
        menu = QMenu(self)
        menu.addAction(tr("db_widget.ctx_select_limit", default="SELECT * … LIMIT 100"),
                       lambda: self._run_select(table, 100))
        menu.addAction(tr("db_widget.ctx_select_all", default="SELECT * (tutto)"),
                       lambda: self._run_select(table))
        menu.addAction(tr("db_widget.ctx_count_rows", default="Conta righe"),
                       lambda: self._count_rows(table))
        menu.addSeparator()
        menu.addAction(tr("db_widget.ctx_structure", default="Mostra struttura"),
                       lambda: self._show_structure(table))
        menu.addAction(tr("db_widget.ctx_copy_name", default="Copia nome tabella"),
                       lambda: QApplication.clipboard().setText(table))
        menu.addSeparator()
        menu.addAction(tr("db_widget.ctx_gen_insert", default="Genera INSERT"),
                       lambda: self._gen_insert(table))
        menu.addAction(tr("db_widget.ctx_gen_drop", default="Genera DROP TABLE"),
                       lambda: self._gen_drop(table))
        menu.addSeparator()
        menu.addAction(tr("db_widget.ctx_export_table", default="Esporta tabella…"),
                       lambda: self._export_table(table))
        menu.exec(self._schema_tree.viewport().mapToGlobal(pos))

    def _db_type(self) -> str:
        return self._conn_info.get("type", "")

    def _run_select(self, table: str, limit: Optional[int] = None) -> None:
        q = _quote_ident(table, self._db_type())
        sql = f"SELECT * FROM {q}"
        if limit:
            sql += f"\nLIMIT {limit}"
        sql += ";"
        tab = self._current_query_tab()
        if tab:
            tab.set_sql(sql)
            tab._execute()

    def _count_rows(self, table: str) -> None:
        q = _quote_ident(table, self._db_type())
        tab = self._current_query_tab()
        if tab:
            tab.set_sql(f"SELECT COUNT(*) FROM {q};")
            tab._execute()

    def _ensure_columns(self, table: str) -> list[str]:
        """Restituisce le colonne della tabella, caricandole se non in cache."""
        cols = self._schema_cache.get(table)
        if cols:
            return cols
        try:
            fetched = _get_columns(self._conn, self._db_type(), table)
            cols = [c[0] for c in fetched]
            self._schema_cache[table] = cols
            return cols
        except Exception:
            return []

    def _gen_insert(self, table: str) -> None:
        db = self._db_type()
        q = _quote_ident(table, db)
        cols = self._ensure_columns(table)
        tab = self._current_query_tab()
        if not tab:
            return
        if cols:
            col_list = ", ".join(_quote_ident(c, db) for c in cols)
            placeholders = ", ".join("?" for _ in cols)
            sql = (f"INSERT INTO {q} ({col_list})\n"
                   f"VALUES ({placeholders});")
        else:
            sql = f"INSERT INTO {q} () VALUES ();"
        tab.set_sql(sql)
        tab.focus_editor()

    def _gen_drop(self, table: str) -> None:
        q = _quote_ident(table, self._db_type())
        tab = self._current_query_tab()
        if tab:
            tab.set_sql(f"DROP TABLE {q};")
            tab.focus_editor()

    def _export_table(self, table: str) -> None:
        """Carica l'intera tabella e ne propone l'export tramite il query-tab."""
        q = _quote_ident(table, self._db_type())
        tab = self._current_query_tab()
        if tab:
            tab.set_sql(f"SELECT * FROM {q};")
            tab._execute()
            QMessageBox.information(
                self, "NotePadPQ",
                tr("db_widget.export_table_hint",
                   default="Tabella caricata: usa il pulsante 'Esporta' "
                           "per salvarla su file."))

    def _show_structure(self, table: str) -> None:
        db_type = self._conn_info.get("type", "")
        try:
            cols = _get_columns(self._conn, db_type, table)
            sql = f"-- Struttura di {table}\n"
            for col, typ in cols:
                sql += f"--   {col}  {typ}\n"
            tab = self._current_query_tab()
            if tab:
                tab.set_sql(sql)
        except Exception as exc:
            QMessageBox.critical(self, "NotePadPQ", str(exc))

    # ── Query tabs ────────────────────────────────────────────────────────────

    def _add_query_tab(self) -> _QueryTab:
        self._query_count += 1
        tab = _QueryTab(
            self._conn, self._conn_info, self._mw,
            self._query_count, self
        )
        label = tr("db.query_tab_label", query_count=self._query_count)
        self._query_tabs.addTab(tab, label)
        self._query_tabs.setCurrentWidget(tab)
        tab.focus_editor()
        # Fornisci subito al nuovo tab le parole per l'autocompletamento
        # (keyword + schema già caricato).
        self._refresh_autocomplete()
        return tab

    def _current_query_tab(self) -> Optional[_QueryTab]:
        w = self._query_tabs.currentWidget()
        return w if isinstance(w, _QueryTab) else None

    def _close_query_tab(self, index: int) -> None:
        if self._query_tabs.count() <= 1:
            # Keep at least one tab
            return
        self._query_tabs.removeTab(index)

    # ── Stubs ─────────────────────────────────────────────────────────────────

    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True

    def closeEvent(self, event) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        super().closeEvent(event)
