"""
i18n/i18n.py — Motore multilingue
NotePadPQ

Singleton che carica i file JSON di traduzione e fornisce la funzione
globale tr() importabile da qualsiasi modulo.

Uso:
    from i18n.i18n import tr, I18n

    # Testo semplice
    label.setText(tr("action.save"))

    # Testo con parametri
    msg = tr("msg.file_not_found", path="/etc/foo")

    # Cambio lingua a caldo (emette segnale → tutti i widget si aggiornano)
    I18n.instance().set_language("en")

Struttura JSON attesa:
    {
      "meta": { "language": "it", "name": "Italiano", "version": "1.0" },
      "menu": { "file": "File", ... },
      "action": { "save": "Salva", ... },
      "msg": { "file_not_found": "File non trovato: {path}", ... }
    }

Fallback a cascata: lingua scelta → "en" → chiave grezza
"""

import json
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

# Directory dei file JSON — relativa a questo file
_I18N_DIR = Path(__file__).parent


class I18n(QObject):
    """
    Singleton per la gestione delle traduzioni.
    Emette language_changed quando la lingua viene cambiata a caldo.
    """

    language_changed = pyqtSignal(str)  # codice lingua es. "it", "en"

    _instance: Optional["I18n"] = None

    def __init__(self):
        super().__init__()
        self._language: str = "it"          # lingua corrente
        self._data: dict = {}               # traduzioni lingua corrente
        self._fallback: dict = {}           # traduzioni inglese (fallback)
        self._available: dict[str, str] = {}  # codice → nome nativo

        self._scan_available()
        self._load("en")                    # carica sempre l'inglese come base
        self._load("it")                    # poi la lingua di default

    # ── Singleton ────────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "I18n":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Lingue disponibili ────────────────────────────────────────────────────

    def _scan_available(self) -> None:
        """Scansiona la dir i18n e costruisce il dizionario lingue disponibili."""
        self._available = {}
        for f in sorted(_I18N_DIR.glob("*.json")):
            try:
                with f.open(encoding="utf-8") as fp:
                    data = json.load(fp)
                meta = data.get("meta", {})
                code = meta.get("language", f.stem)
                name = meta.get("name", code)
                self._available[code] = name
            except Exception:
                pass

    def available_languages(self) -> dict[str, str]:
        """Restituisce {codice: nome_nativo} per tutte le lingue disponibili."""
        return dict(self._available)

    def current_language(self) -> str:
        return self._language

    # ── Caricamento ───────────────────────────────────────────────────────────

    def _load_file(self, code: str) -> dict:
        """Carica e restituisce il dizionario da <code>.json, {} se mancante."""
        path = _I18N_DIR / f"{code}.json"
        if not path.exists():
            return {}
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[i18n] Errore caricamento {path}: {e}", file=sys.stderr)
            return {}

    def _load(self, code: str) -> None:
        """Carica una lingua. Se è 'en' aggiorna il fallback, altrimenti _data."""
        data = self._load_file(code)
        if code == "en":
            self._fallback = data
        else:
            self._data = data
        self._language = code

    def set_language(self, code: str) -> bool:
        """
        Cambia la lingua a caldo. Emette language_changed se la lingua
        è disponibile e diversa da quella corrente.
        Restituisce True se il cambio è avvenuto.
        """
        if code == self._language:
            return True

        if code not in self._available and code != "en":
            print(f"[i18n] Lingua non disponibile: {code}", file=sys.stderr)
            return False

        if code == "en":
            # Inglese: usa il fallback come _data, svuota _data separato
            self._data = self._fallback
        else:
            self._data = self._load_file(code)

        self._language = code
        self.language_changed.emit(code)
        return True

    # ── Traduzione ────────────────────────────────────────────────────────────

    def translate(self, key: str, **kwargs) -> str:
        """
        Traduce una chiave puntata es. "action.save" → "Salva".

        Fallback a cascata:
          1. lingua corrente (_data)
          2. inglese (_fallback)
          3. chiave grezza (mai stringa vuota)

        kwargs vengono sostituiti nel testo via str.format_map():
          tr("msg.file_not_found", path="/etc/foo")
          → "File non trovato: /etc/foo"
        """
        text = self._resolve(key, self._data)
        if text is None:
            text = self._resolve(key, self._fallback)
        if text is None:
            text = key  # chiave grezza come ultimo fallback

        if kwargs:
            try:
                text = text.format_map(kwargs)
            except (KeyError, ValueError):
                pass  # restituisce il testo non formattato se i parametri mancano

        return text

    def _resolve(self, key: str, data: dict) -> Optional[str]:
        """
        Naviga un dizionario annidato seguendo una chiave puntata.
        "menu.file" → data["menu"]["file"]
        Restituisce None se la chiave non esiste.
        """
        parts = key.split(".")
        node = data
        for part in parts:
            if not isinstance(node, dict):
                return None
            node = node.get(part)
            if node is None:
                return None
        return str(node) if not isinstance(node, dict) else None


# ─── Funzione globale shortcut ────────────────────────────────────────────────

def tr(key: str, **kwargs) -> str:
    """
    Funzione globale di traduzione. Importare da qualsiasi modulo:
        from i18n.i18n import tr
    """
    return I18n.instance().translate(key, **kwargs)


# ─── Test standalone ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    i18n = I18n.instance()
    print(f"=== NotePadPQ i18n Test ===")
    print(f"Lingue disponibili: {i18n.available_languages()}")
    print(f"Lingua corrente: {i18n.current_language()}")
    print()

    chiavi_test = [
        "menu.file",
        "menu.edit",
        "action.save",
        "action.open",
        "msg.unsaved_changes",
        "msg.file_not_found",
        "chiave.inesistente",  # test fallback chiave grezza
    ]

    print("── Italiano (default) ──")
    for k in chiavi_test:
        print(f"  {k:<30} → {tr(k)}")

    print()
    print("── Test parametri ──")
    print(f"  {tr('msg.file_not_found', path='/home/andres/test.txt')}")

    print()
    print("── Cambio a inglese ──")
    i18n.set_language("en")
    for k in chiavi_test:
        print(f"  {k:<30} → {tr(k)}")

    print()
    print("── Cambio a lingua inesistente ──")
    result = i18n.set_language("zz")
    print(f"  set_language('zz') → {result}")
    print(f"  lingua corrente rimasta: {i18n.current_language()}")
