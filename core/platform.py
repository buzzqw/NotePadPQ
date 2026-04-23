"""
core/platform.py — Compatibility layer multipiattaforma
NotePadPQ

Centralizza tutto il rilevamento di piattaforma e le operazioni
dipendenti dall'OS. Tutti gli altri moduli importano da qui —
mai sys.platform o os.path sparsi nel codice.

Uso:
    from core.platform import IS_LINUX, IS_BSD, IS_WINDOWS
    from core.platform import get_config_dir, get_data_dir, get_font_families
    from core.platform import open_path_in_filemanager, get_default_shell
"""

import sys
import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QFontDatabase

# ─── Costanti piattaforma ─────────────────────────────────────────────────────

IS_LINUX   = sys.platform.startswith("linux")
IS_BSD     = sys.platform.startswith("freebsd") or sys.platform.startswith("openbsd") or sys.platform.startswith("netbsd")
IS_WINDOWS = sys.platform == "win32"
IS_MAC     = sys.platform == "darwin"  # non target, ma meglio gestirlo

PLATFORM_NAME = (
    "Linux"   if IS_LINUX   else
    "FreeBSD" if IS_BSD     else
    "Windows" if IS_WINDOWS else
    "macOS"   if IS_MAC     else
    sys.platform
)

# ─── Directory di configurazione e dati ──────────────────────────────────────

def get_config_dir() -> Path:
    """
    Restituisce la directory di configurazione dell'applicazione.
    - Linux/BSD: ~/.config/NotePadPQ/
    - Windows:   %APPDATA%/NotePadPQ/
    La directory viene creata se non esiste.
    """
    path = Path(
        QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    """
    Restituisce la directory dati dell'applicazione (sessioni, plugin, ecc.).
    - Linux/BSD: ~/.local/share/NotePadPQ/
    - Windows:   %APPDATA%/NotePadPQ/data/
    """
    path = Path(
        QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir() -> Path:
    """
    Restituisce la directory cache (file temporanei, indici autocomplete).
    - Linux/BSD: ~/.cache/NotePadPQ/
    - Windows:   %LOCALAPPDATA%/NotePadPQ/cache/
    """
    path = Path(
        QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_plugins_dir() -> Path:
    """
    Directory plugin utente, dentro la dir dati.
    """
    path = get_data_dir() / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path

# ─── Font ─────────────────────────────────────────────────────────────────────

# Font monospace preferiti per piattaforma, in ordine di priorità
_MONOSPACE_PREFERENCES = {
    "linux":   ["JetBrains Mono", "Fira Code", "Hack", "DejaVu Sans Mono",
                "Liberation Mono", "Courier New", "Monospace"],
    "freebsd": ["JetBrains Mono", "DejaVu Sans Mono", "Courier New",
                "Liberation Mono", "Monospace"],
    "windows": ["JetBrains Mono", "Fira Code", "Consolas", "Courier New",
                "Lucida Console"],
    "default": ["Courier New", "Monospace"],
}


def get_preferred_monospace_font() -> str:
    """
    Restituisce il primo font monospace disponibile nel sistema,
    secondo la lista di preferenze per piattaforma.
    """
    available = set(QFontDatabase.families())

    if IS_LINUX:
        candidates = _MONOSPACE_PREFERENCES["linux"]
    elif IS_BSD:
        candidates = _MONOSPACE_PREFERENCES["freebsd"]
    elif IS_WINDOWS:
        candidates = _MONOSPACE_PREFERENCES["windows"]
    else:
        candidates = _MONOSPACE_PREFERENCES["default"]

    for font in candidates:
        if font in available:
            return font

    # Fallback assoluto: chiedi a Qt il font monospace di sistema
    return QFontDatabase.systemFont(
        QFontDatabase.SystemFont.FixedFont
    ).family()


def get_monospace_font_families() -> list[str]:
    """
    Restituisce tutte le famiglie monospace disponibili nel sistema,
    ordinate con le preferite in cima.
    """
    available = set(QFontDatabase.families())
    preferred = (
        _MONOSPACE_PREFERENCES.get("linux" if IS_LINUX else
                                   "freebsd" if IS_BSD else
                                   "windows" if IS_WINDOWS else
                                   "default")
    )
    # Prima i preferiti disponibili, poi gli altri monospace del sistema
    result = [f for f in preferred if f in available]
    for family in sorted(available):
        if family not in result:
            db = QFontDatabase()
            # Controlla se è monospace controllando che sia a larghezza fissa
            if QFontDatabase.isFixedPitch(family, "Regular") or \
               QFontDatabase.isFixedPitch(family, ""):
                result.append(family)
    return result

# ─── Shell e comandi di sistema ───────────────────────────────────────────────

def get_default_shell() -> str:
    """
    Restituisce la shell di default per i build profiles.
    - Linux/BSD: $SHELL o /bin/sh come fallback
    - Windows:   cmd.exe
    """
    if IS_WINDOWS:
        return os.environ.get("COMSPEC", "cmd.exe")

    # Linux / BSD
    shell = os.environ.get("SHELL", "")
    if shell and Path(shell).exists():
        return shell
    # Fallback POSIX universale
    for sh in ["/bin/bash", "/bin/sh", "/usr/local/bin/bash"]:
        if Path(sh).exists():
            return sh
    return "/bin/sh"


def get_shell_exec_flag() -> str:
    """
    Flag per eseguire un comando con la shell.
    - Unix:    '-c'
    - Windows: '/C'
    """
    return "/C" if IS_WINDOWS else "-c"


def open_path_in_filemanager(path: Path) -> bool:
    """
    Apre il percorso nel file manager nativo del sistema.
    Restituisce True se il comando è stato avviato correttamente.
    """
    try:
        if IS_WINDOWS:
            # explorer.exe accetta sia file che directory
            target = str(path.parent) if path.is_file() else str(path)
            subprocess.Popen(["explorer", target])
        elif IS_MAC:
            subprocess.Popen(["open", str(path.parent if path.is_file() else path)])
        else:
            # Linux / BSD — prova i file manager più comuni
            target = str(path.parent if path.is_file() else path)
            for fm in ["xdg-open", "nautilus", "thunar", "dolphin",
                       "nemo", "pcmanfm", "xfce4-file-manager"]:
                if _command_exists(fm):
                    subprocess.Popen([fm, target])
                    return True
            return False
        return True
    except Exception:
        return False


def open_url_in_browser(url: str) -> bool:
    """
    Apre un URL nel browser predefinito. Cross-platform.
    """
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        return False

# ─── Utility interne ──────────────────────────────────────────────────────────

def _command_exists(cmd: str) -> bool:
    """Verifica se un comando è disponibile nel PATH."""
    import shutil
    return shutil.which(cmd) is not None


def get_line_separator() -> str:
    """
    Separatore di riga nativo dell'OS (per nuovi file senza encoding rilevato).
    - Windows: \\r\\n
    - Unix:    \\n
    Il file_manager gestisce la conversione per file esistenti.
    """
    return "\r\n" if IS_WINDOWS else "\n"


def get_platform_info() -> dict:
    """
    Restituisce un dizionario con informazioni diagnostiche sulla piattaforma.
    Usato nelle Preferenze → Informazioni di sistema.
    """
    return {
        "platform":      PLATFORM_NAME,
        "python":        sys.version,
        "sys.platform":  sys.platform,
        "config_dir":    str(get_config_dir()),
        "data_dir":      str(get_data_dir()),
        "cache_dir":     str(get_cache_dir()),
        "plugins_dir":   str(get_plugins_dir()),
        "default_shell": get_default_shell(),
        "default_font":  get_preferred_monospace_font(),
    }

# ─── Test standalone ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== NotePadPQ — Platform Info ===")
    info = get_platform_info()
    for k, v in info.items():
        print(f"  {k:<18}: {v}")
    print()
    print(f"  IS_LINUX   : {IS_LINUX}")
    print(f"  IS_BSD     : {IS_BSD}")
    print(f"  IS_WINDOWS : {IS_WINDOWS}")
    print()
    print(f"  Shell      : {get_default_shell()}  (flag: {get_shell_exec_flag()})")
    print(f"  Line sep   : {repr(get_line_separator())}")
    print()
    print("=== Font monospace disponibili (top 5) ===")
    # QFontDatabase richiede QApplication — skip nel test CLI puro
    print("  (richiede QApplication attiva — avviare tramite main.py)")
