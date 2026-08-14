"""
core/recent_files.py — Gestione file recenti
NotePadPQ
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.persistence import atomic_write_json, load_json
from core.platform import get_config_dir


class RecentFiles:

    MAX_ITEMS = 20
    _instance: Optional["RecentFiles"] = None

    def __init__(self):
        self._path = get_config_dir() / "recent_files.json"
        self._list: list[str]
        self._pinned: set[str]
        self._list, self._pinned = self._load()

    @classmethod
    def instance(cls) -> "RecentFiles":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> tuple[list[str], set[str]]:
        def valid(data: object) -> bool:
            if isinstance(data, list):
                return all(isinstance(path, str) for path in data)
            return (isinstance(data, dict)
                    and isinstance(data.get("recent"), list)
                    and isinstance(data.get("pinned"), list)
                    and all(isinstance(path, str) for path in data["recent"])
                    and all(isinstance(path, str) for path in data["pinned"]))

        data = load_json(self._path, validate=valid)
        if isinstance(data, list):
            # Formato legacy: lista piatta senza pin.
            return [path for path in data if Path(path).exists()], set()
        if isinstance(data, dict):
            recent = [path for path in data["recent"] if Path(path).exists()]
            pinned = {path for path in data["pinned"] if Path(path).exists()}
            return recent, pinned
        return [], set()

    def _save(self) -> None:
        try:
            atomic_write_json(self._path, {"recent": self._list, "pinned": sorted(self._pinned)})
        except OSError:
            pass

    def add(self, path: Path) -> None:
        p = str(path.resolve())
        if p in self._list:
            self._list.remove(p)
        self._list.insert(0, p)
        # Tronca solo le voci non fissate: i file pinnati restano sempre
        # in lista, anche oltre MAX_ITEMS, così non vengono mai spinti
        # fuori da un uso intenso di file temporanei/di appoggio.
        kept_pinned   = [p for p in self._list if p in self._pinned]
        kept_unpinned = [p for p in self._list if p not in self._pinned][:self.MAX_ITEMS]
        keep = set(kept_pinned) | set(kept_unpinned)
        self._list = [p for p in self._list if p in keep]
        self._save()

    def get_list(self) -> list[str]:
        """File pinnati per primi (in ordine di recenza tra loro), poi gli altri."""
        pinned   = [p for p in self._list if p in self._pinned]
        unpinned = [p for p in self._list if p not in self._pinned]
        return pinned + unpinned

    def is_pinned(self, path: Path) -> bool:
        return str(path.resolve()) in self._pinned

    def toggle_pin(self, path: Path) -> bool:
        """Fissa/rimuove il fissaggio di path. Restituisce il nuovo stato (True = fissato)."""
        p = str(path.resolve())
        if p in self._pinned:
            self._pinned.discard(p)
        else:
            self._pinned.add(p)
            if p not in self._list:
                self._list.insert(0, p)
        self._save()
        return p in self._pinned

    def clear(self) -> None:
        """Svuota i recenti non fissati; i file pinnati restano."""
        self._list = [p for p in self._list if p in self._pinned]
        self._save()

    def remove(self, path: Path) -> None:
        p = str(path.resolve())
        if p in self._list:
            self._list.remove(p)
        self._pinned.discard(p)
        self._save()
