"""
plugins/plugin_manager.py — Gestione plugin
NotePadPQ

Carica dinamicamente i plugin dalla directory plugins/ utente,
gestisce enable/disable, e mostra il dialog di gestione.
"""

from __future__ import annotations

import ast
import hashlib
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
from core.persistence import atomic_write_json
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
        self._trusted_path = get_data_dir() / "trusted_plugins.json"
        self._trusted: dict[str, dict[str, str]] = self._load_trusted()

    @classmethod
    def instance(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _plugins_dir(self) -> Path:
        from core.platform import get_plugins_dir
        return get_plugins_dir()

    def _plugin_files(self) -> list[Path]:
        """Return bundled plugins followed by user-installed plugins."""
        bundled = Path(__file__).parent.resolve()
        user_dir = self._plugins_dir().resolve()
        files = sorted(
            path for path in bundled.glob("*.py") if not path.name.startswith("_")
        )
        if user_dir != bundled:
            files.extend(
                sorted(
                    path for path in user_dir.glob("*.py")
                    if not path.name.startswith("_") and not path.is_symlink()
                )
            )
        return files

    def _load_disabled(self) -> set[str]:
        try:
            if self._disabled_path.exists():
                return set(json.loads(
                    self._disabled_path.read_text(encoding="utf-8")
                ))
        except Exception:
            pass
        return set()

    def _load_trusted(self) -> dict[str, dict[str, str]]:
        try:
            if self._trusted_path.exists():
                data = json.loads(self._trusted_path.read_text(encoding="utf-8"))
                bindings = data.get("bindings", {}) if isinstance(data, dict) else {}
                if isinstance(bindings, dict):
                    return {
                        name: binding for name, binding in bindings.items()
                        if isinstance(name, str) and isinstance(binding, dict)
                    }
        except Exception:
            pass
        return {}

    def _save_disabled(self) -> None:
        try:
            atomic_write_json(self._disabled_path, list(self._disabled))
        except Exception:
            pass

    def _save_trusted(self) -> None:
        try:
            atomic_write_json(self._trusted_path, {"bindings": self._trusted})
        except Exception:
            pass

    def _is_user_plugin(self, path: Path) -> bool:
        try:
            return path.absolute().parent == self._plugins_dir().resolve()
        except OSError:
            return False

    @staticmethod
    def _trust_binding(path: Path) -> dict[str, str] | None:
        try:
            if path.is_symlink():
                return None
            resolved = path.resolve(strict=True)
            return {
                "path": str(resolved),
                "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            }
        except OSError:
            return None

    def _is_trusted(self, name: str, path: Path) -> bool:
        trusted = getattr(self, "_trusted", {})
        return isinstance(trusted, dict) and trusted.get(name) == self._trust_binding(path)

    def load_all(self, main_window: "MainWindow") -> None:
        """Carica tutti i plugin dalla directory plugin utente."""
        self._main_window = main_window
        for plugin_file in self._plugin_files():
            self._load_plugin_file(plugin_file, main_window)

    def load_all_deferred(self, main_window: "MainWindow",
                          on_done=None) -> None:
        """Carica i plugin uno per tick dell'event loop.

        La finestra rimane responsiva durante il caricamento. `on_done` viene
        chiamata senza argomenti quando tutti i plugin sono stati caricati.
        """
        from PyQt6.QtCore import QTimer
        self._main_window = main_window
        files = self._plugin_files()
        _iter = iter(files)

        def _load_next():
            try:
                self._load_plugin_file(next(_iter), main_window)
                QTimer.singleShot(0, _load_next)
            except StopIteration:
                if on_done:
                    on_done()

        QTimer.singleShot(0, _load_next)

    def _load_plugin_file(self, path: Path,
                          main_window: "MainWindow") -> bool:
        """Carica un singolo file plugin."""
        is_user_plugin = self._is_user_plugin(path)
        if is_user_plugin and path.is_symlink():
            print(f"[plugins] Plugin utente symlink rifiutato: {path.name}")
            return False
        meta = self._read_static_metadata(path)
        if meta is not None and meta["name"] in self._plugins:
            print(f"[plugins] Nome plugin duplicato rifiutato: {meta['name']}")
            return False

        if is_user_plugin and meta is None:
            # Importing is code execution: user plugins need literal metadata so
            # they can be shown and explicitly trusted without importing them.
            print(f"[plugins] Plugin utente rifiutato senza metadata statici: {path.name}")
            return False
        if meta is not None and (meta["name"] in self._disabled or
                                  (is_user_plugin and not self._is_trusted(meta["name"], path))):
            self._plugins[meta["name"]] = {
                "instance": None,
                "enabled": False,
                "path": path,
                "meta": meta,
            }
            return True

        try:
            binding = self._trust_binding(path) if is_user_plugin else None
            loaded = self._import_plugin(path, binding)
            if loaded is None:
                return False
            instance, meta = loaded
            name = meta["name"]

            if name in self._plugins:
                print(f"[plugins] Nome plugin duplicato rifiutato: {name}")
                return False

            self._plugins[name] = {
                "instance": instance,
                "enabled": name not in self._disabled,
                "path": path,
                "meta": meta,
            }

            if name not in self._disabled:
                instance.on_load(main_window)
                print(tr("msg.plugin_loaded", name=name))

            return True

        except Exception as e:
            print(tr("msg.plugin_load_error", name=path.stem, error=str(e)))
            return False

    @staticmethod
    def _read_static_metadata(path: Path) -> Optional[dict]:
        """Legge i metadata letterali senza importare o eseguire il plugin."""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError):
            return None

        plugin_classes = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if any(
                (isinstance(base, ast.Name) and base.id == "BasePlugin") or
                (isinstance(base, ast.Attribute) and base.attr == "BasePlugin")
                for base in node.bases
            ):
                plugin_classes.append(node)

        if not plugin_classes:
            return None

        # Il loader storico sceglie la prima classe restituita da dir(module).
        plugin_class = min(plugin_classes, key=lambda node: node.name)
        values = {}
        for statement in plugin_class.body:
            targets = []
            value = None
            if isinstance(statement, ast.Assign):
                targets = statement.targets
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
                value = statement.value
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {
                    "NAME", "VERSION", "DESCRIPTION", "AUTHOR"
                }:
                    try:
                        literal = ast.literal_eval(value)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(literal, str):
                        values[target.id] = literal

        # Senza un nome letterale non è possibile associarlo con certezza alla
        # lista dei disabilitati; in quel caso resta il loader compatibile.
        if "NAME" not in values:
            return None
        return {
            "name": values["NAME"],
            "version": values.get("VERSION", "0.0"),
            "description": values.get("DESCRIPTION", ""),
            "author": values.get("AUTHOR", ""),
        }

    @staticmethod
    def _import_plugin(path: Path, binding: dict[str, str] | None = None):
        """Importa e istanzia un plugin, senza attivarne il ciclo di vita."""
        if binding is not None and PluginManager._trust_binding(path) != binding:
            return None
        spec = importlib.util.spec_from_file_location(path.stem, str(path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

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
            return None

        instance = plugin_class()
        name = getattr(plugin_class, "NAME", path.stem)
        return instance, {
            "name": name,
            "version": getattr(plugin_class, "VERSION", "?"),
            "description": getattr(plugin_class, "DESCRIPTION", ""),
            "author": getattr(plugin_class, "AUTHOR", ""),
        }

    def enable_plugin(self, name: str) -> bool:
        entry = self._plugins.get(name)
        if not entry or entry["enabled"]:
            return False
        try:
            if entry["instance"] is None:
                is_user_plugin = self._is_user_plugin(entry["path"])
                if is_user_plugin:
                    binding = self._trust_binding(entry["path"])
                    if binding is None:
                        return False
                    # Enabling is the explicit trust decision for these exact bytes.
                    if not isinstance(getattr(self, "_trusted", None), dict):
                        self._trusted = {}
                    self._trusted[name] = binding
                loaded = self._import_plugin(entry["path"], binding if is_user_plugin else None)
                if loaded is None:
                    return False
                instance, meta = loaded
                actual_name = meta["name"]
                if actual_name != name and actual_name in self._plugins:
                    raise ValueError(f"Nome plugin duplicato: {actual_name}")
                if actual_name != name and self._is_trusted(actual_name, entry["path"]):
                    raise ValueError(f"Nome plugin duplicato: {actual_name}")
                entry["instance"] = instance
                entry["meta"] = meta

            entry["instance"].on_load(self._main_window)
            entry["enabled"] = True
            self._disabled.discard(name)
            actual_name = entry["meta"]["name"]
            self._disabled.discard(actual_name)
            if self._is_user_plugin(entry["path"]):
                binding = self._trust_binding(entry["path"])
                if binding is None:
                    return False
                self._trusted[actual_name] = binding
                if actual_name != name:
                    self._trusted.pop(name, None)
                self._save_trusted()
            if actual_name != name:
                del self._plugins[name]
                self._plugins[actual_name] = entry
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

    def unload_all(self) -> None:
        """Scarica i plugin attivi prima della chiusura dell'applicazione."""
        for name, entry in list(self._plugins.items()):
            if not entry["enabled"]:
                continue
            try:
                entry["instance"].on_unload()
            except Exception as e:
                print(f"[plugins] Errore scaricamento {name}: {e}")
            finally:
                entry["enabled"] = False
        self._main_window = None

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
