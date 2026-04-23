"""
core/recent_files.py — Gestione file recenti
NotePadPQ
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.platform import get_config_dir


class RecentFiles:

    MAX_ITEMS = 20
    _instance: Optional["RecentFiles"] = None

    def __init__(self):
        self._path = get_config_dir() / "recent_files.json"
        self._list: list[str] = self._load()

    @classmethod
    def instance(cls) -> "RecentFiles":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> list[str]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return [p for p in data if Path(p).exists()]
        except Exception:
            pass
        return []

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._list, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def add(self, path: Path) -> None:
        p = str(path.resolve())
        if p in self._list:
            self._list.remove(p)
        self._list.insert(0, p)
        self._list = self._list[:self.MAX_ITEMS]
        self._save()

    def get_list(self) -> list[str]:
        return list(self._list)

    def clear(self) -> None:
        self._list = []
        self._save()

    def remove(self, path: Path) -> None:
        p = str(path.resolve())
        if p in self._list:
            self._list.remove(p)
            self._save()
