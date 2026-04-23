"""
plugins/plugin_manager.py — Gestione plugin
NotePadPQ

Carica dinamicamente i plugin dalla directory plugins/ utente,
gestisce enable/disable, e mostra il dialog di gestione.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QLabel, QDialogButtonBox,
    QAbstractItemView, QTextEdit, QSplitter, QWidget,
)

from core.platform import get_data_dir
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class PluginManager:
    """Singleton. Carica e gestisce il ciclo di vita dei plugin."""

    _instance: Optional["PluginManager"] = None

    def __init__(self):
        self._plugins: dict[str, dict] = {}   # name → {instance, enabled, path, meta}
        self._main_window: Optional["MainWindow"] = None
        self._disabled_path = get_data_dir() / "disabled_plugins.json"
        self._disabled: set[str] = self._load_disabled()

    @classmethod
    def instance(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _plugins_dir(self) -> Path:
        # Usa la cartella 'plugins' in cui si trova questo stesso script,
        # ignorando quella in ~/.local/share/...
        return Path(__file__).parent.resolve()

    def _load_disabled(self) -> set[str]:
        try:
            if self._disabled_path.exists():
                return set(json.loads(
                    self._disabled_path.read_text(encoding="utf-8")
                ))
        except Exception:
            pass
        return set()

    def _save_disabled(self) -> None:
        try:
            self._disabled_path.write_text(
                json.dumps(list(self._disabled), ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def load_all(self, main_window: "MainWindow") -> None:
        """Carica tutti i plugin dalla directory plugin utente."""
        self._main_window = main_window
        plugins_dir = self._plugins_dir()

        for plugin_file in sorted(plugins_dir.glob("*.py")):
            if plugin_file.name.startswith("_"):
                continue
            self._load_plugin_file(plugin_file, main_window)

    def _load_plugin_file(self, path: Path,
                          main_window: "MainWindow") -> bool:
        """Carica un singolo file plugin."""
        try:
            spec = importlib.util.spec_from_file_location(
                path.stem, str(path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Cerca una classe che estende BasePlugin
            from plugins.base_plugin import BasePlugin
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                try:
                    if (isinstance(attr, type) and
                            issubclass(attr, BasePlugin) and
                            attr is not BasePlugin):
                        plugin_class = attr
                        break
                except TypeError:
                    continue

            if plugin_class is None:
                return False

            instance = plugin_class()
            name = getattr(plugin_class, "NAME", path.stem)

            self._plugins[name] = {
                "instance": instance,
                "enabled":  name not in self._disabled,
                "path":     path,
                "meta": {
                    "name":        name,
                    "version":     getattr(plugin_class, "VERSION", "?"),
                    "description": getattr(plugin_class, "DESCRIPTION", ""),
                    "author":      getattr(plugin_class, "AUTHOR", ""),
                },
            }

            if name not in self._disabled:
                instance.on_load(main_window)
                print(tr("msg.plugin_loaded", name=name))

            return True

        except Exception as e:
            print(tr("msg.plugin_load_error", name=path.stem, error=str(e)))
            return False

    def enable_plugin(self, name: str) -> bool:
        entry = self._plugins.get(name)
        if not entry or entry["enabled"]:
            return False
        try:
            entry["instance"].on_load(self._main_window)
            entry["enabled"] = True
            self._disabled.discard(name)
            self._save_disabled()
            return True
        except Exception as e:
            print(f"[plugins] Errore abilitazione {name}: {e}")
            return False

    def disable_plugin(self, name: str) -> bool:
        entry = self._plugins.get(name)
        if not entry or not entry["enabled"]:
            return False
        try:
            entry["instance"].on_unload()
            entry["enabled"] = False
            self._disabled.add(name)
            self._save_disabled()
            return True
        except Exception as e:
            print(f"[plugins] Errore disabilitazione {name}: {e}")
            return False

    def get_all(self) -> dict[str, dict]:
        return dict(self._plugins)

    def notify_editor_changed(self, editor) -> None:
        for entry in self._plugins.values():
            if entry["enabled"]:
                try:
                    entry["instance"].on_editor_changed(editor)
                except Exception:
                    pass

    def notify_file_opened(self, path: Path) -> None:
        for entry in self._plugins.values():
            if entry["enabled"]:
                try:
                    entry["instance"].on_file_opened(path)
                except Exception:
                    pass

    def notify_file_saved(self, path: Path) -> None:
        for entry in self._plugins.values():
            if entry["enabled"]:
                try:
                    entry["instance"].on_file_saved(path)
                except Exception:
                    pass


# ─── Dialog gestione plugin ───────────────────────────────────────────────────

class PluginManagerDialog(QDialog):

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._pm = PluginManager.instance()
        self.setWindowTitle(tr("action.plugin_manager"))
        self.resize(700, 450)
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Tabella plugin
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels([
            tr("label.plugin_name"),
            tr("label.plugin_version"),
            tr("label.plugin_enabled"),
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.itemSelectionChanged.connect(self._on_selection)
        splitter.addWidget(self._table)

        # Dettaglio
        right = QWidget()
        rl = QVBoxLayout(right)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        rl.addWidget(QLabel("Dettagli:"))
        rl.addWidget(self._detail, 1)

        btn_row = QHBoxLayout()
        self._btn_enable  = QPushButton(tr("button.enable"))
        self._btn_disable = QPushButton(tr("button.disable"))
        self._btn_open_dir = QPushButton("Apri directory plugin")
        self._btn_enable.clicked.connect(self._enable)
        self._btn_disable.clicked.connect(self._disable)
        self._btn_open_dir.clicked.connect(self._open_plugins_dir)
        for b in [self._btn_enable, self._btn_disable, self._btn_open_dir]:
            btn_row.addWidget(b)
        btn_row.addStretch()
        rl.addLayout(btn_row)
        splitter.addWidget(right)

        layout.addWidget(splitter, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.accept)
        layout.addWidget(btns)

    def _populate(self) -> None:
        self._table.setRowCount(0)
        for name, entry in self._pm.get_all().items():
            meta = entry["meta"]
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(meta.get("version", "")))
            enabled_item = QTableWidgetItem("✓" if entry["enabled"] else "✗")
            enabled_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, enabled_item)

    def _on_selection(self) -> None:
        rows = self._table.selectedItems()
        if not rows:
            return
        name = self._table.item(rows[0].row(), 0).text()
        entry = self._pm.get_all().get(name, {})
        meta = entry.get("meta", {})
        self._detail.setPlainText(
            f"Nome: {meta.get('name', name)}\n"
            f"Versione: {meta.get('version', '')}\n"
            f"Autore: {meta.get('author', '')}\n"
            f"Stato: {'Abilitato' if entry.get('enabled') else 'Disabilitato'}\n\n"
            f"{meta.get('description', '')}"
        )
        enabled = entry.get("enabled", False)
        self._btn_enable.setEnabled(not enabled)
        self._btn_disable.setEnabled(enabled)

    def _current_name(self) -> Optional[str]:
        rows = self._table.selectedItems()
        return self._table.item(rows[0].row(), 0).text() if rows else None

    def _enable(self) -> None:
        name = self._current_name()
        if name:
            self._pm.enable_plugin(name)
            self._populate()

    def _disable(self) -> None:
        name = self._current_name()
        if name:
            self._pm.disable_plugin(name)
            self._populate()

    def _open_plugins_dir(self) -> None:
        from core.platform import open_path_in_filemanager
        open_path_in_filemanager(PluginManager.instance()._plugins_dir())
