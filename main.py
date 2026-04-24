#!/usr/bin/env python3
"""
main.py — Entry point NotePadPQ

Uso:
    python main.py [file1 file2 ...]
"""

import sys
from pathlib import Path
from core.single_instance import SingleInstance


def check_dependencies() -> bool:
    """Verifica le dipendenze obbligatorie prima di avviare."""
    missing = []

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        missing.append("PyQt6  →  pip install PyQt6")

    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        missing.append(
            "PyQt6-WebEngine  →  Su Arch: sudo pacman -S qt6-webengine\n"
            "                    Altrimenti: pip install PyQt6-WebEngine"
        )

    try:
        from PyQt6.Qsci import QsciScintilla
    # ... resto invariato ...
    except ImportError:
        missing.append(
            "QScintilla  →  Su Arch: sudo pacman -S python-qscintilla\n"
            "              Su Debian/Ubuntu: pip install PyQt6-QScintilla\n"
            "              Su FreeBSD: pkg install py311-qscintilla"
        )

    if missing:
        print("=" * 60)
        print("NotePadPQ — Dipendenze mancanti:")
        print("=" * 60)
        for m in missing:
            print(f"  x {m}")
        print()
        print("Esegui:  bash setup.sh")
        print("=" * 60)
        return False
    return True


def main():
    if not check_dependencies():
        sys.exit(1)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    app.setApplicationName("NotePadPQ")
    app.setOrganizationName("NotePadPQ")
    app.setApplicationVersion("0.2.3")
    
    # ... resto del file invariato ...

    # ── Single instance ───────────────────────────────────────────────────────
    # Deve essere creato DOPO QApplication (QLocalSocket ne ha bisogno)
    # ma PRIMA di caricare la MainWindow.
    _si = SingleInstance("NotePadPQ")
    files_to_send = [str(Path(p).resolve()) for p in sys.argv[1:] if Path(p).exists()]
    
    if _si.send_args_if_secondary(files_to_send):
        # Se la prima istanza è accesa, riceverà i file in un lampo.
        # Noi possiamo spegnerci silenziosamente.
        sys.exit(0)
    # ─────────────────────────────────────────────────────────────────────────

    base_dir = Path(__file__).resolve().parent
    icons_dir = base_dir / "icons"
    icon = QIcon()
    for size in [256, 128, 64, 48, 32, 16]:
        p = icons_dir / f"NotePadPQ_{size}.png"
        if p.exists():
            icon.addFile(str(p))
    if icon.isNull():
        p = icons_dir / "NotePadPQ.png"
        if p.exists():
            icon = QIcon(str(p))
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Import dopo il check — tutti i moduli che usano Qsci
    from i18n.i18n import I18n
    from config.settings import Settings
    from config.themes import ThemeManager
    from ui.main_window import MainWindow

    # Inizializza settings
    settings = Settings.instance()

    # Inizializza i18n
    i18n = I18n.instance()
    lang = settings.get("i18n/language", "it")
    if lang != "it":
        i18n.set_language(lang)

    # Crea finestra principale
    win = MainWindow()
    win.show()

    # ── Carica plugin ────────────────────────────────────────────────────────
    # Fatto DOPO win.show() perché i plugin possono aggiungere dock widget
    # che richiedono la finestra già inizializzata.
    try:
        from plugins.plugin_manager import PluginManager
        PluginManager.instance().load_all(win)
    except Exception as e:
        print(f"[main] Errore caricamento plugin: {e}")

    # ── Smart Highlight + Mark colori (Ctrl+1..5) ─────────────────────────────
    try:
        from ui.smart_highlight import SmartHighlighter, MultiMarkManager
        win._smart_highlighter = SmartHighlighter(win)
        win._mark_manager = MultiMarkManager.install_into_main_window(win)
    except Exception as e:
        print(f"[main] SmartHighlight: {e}")

    # ── Ricerca incrementale inline (Ctrl+F2) ─────────────────────────────────
    try:
        from ui.incremental_search import IncrementalSearchBar
        win._inc_search = IncrementalSearchBar.install(win)
    except Exception as e:
        print(f"[main] IncrementalSearch: {e}")

    # ── Function List (Ctrl+Shift+F) ──────────────────────────────────────────
    try:
        from ui.function_list import install as install_function_list
        install_function_list(win)
    except Exception as e:
        print(f"[main] FunctionList: {e}")

    # ── Avvia server single-instance ────────────────────────────────────────
    # Fatto dopo win.show() così open_files funziona subito
    _si.start_server(
        callback=lambda paths: win.open_files([Path(p) for p in paths])
    )
    # ─────────────────────────────────────────────────────────────────────────

    # 1. Recupera i file passati dall'esterno (es. doppio clic su un file)
    files_from_cli = [Path(p) for p in sys.argv[1:] if Path(p).is_file()]

    # 2. Ripristina SEMPRE la sessione precedente (se l'opzione è attiva nelle impostazioni)
    restored = False
    if settings.get("file/restore_session", True):
        try:
            from core.session import Session
            sess = Session.instance()
            restored = sess.restore(win)
        except Exception:
            pass

    # 3. Apri anche i file del doppio clic (se presenti)
    if files_from_cli:
        win.open_files(files_from_cli)

    # 4. Se non abbiamo ripristinato nulla e non abbiamo aperto file nuovi, 
    # allora (e solo allora) apri un foglio bianco pulito.
    if not restored and not files_from_cli:
        win._tab_manager.new_tab()

    # Ripristina layout dock/toolbar DOPO show() e dopo che i file sono stati aperti.
    # Il QTimer garantisce che Qt abbia completato il rendering iniziale
    # prima di applicare restoreState() (che richiede tutti i dock inizializzati).
    # Ripristina layout dock/toolbar DOPO show() e dopo che i file sono stati aperti.
    # Il QTimer garantisce che Qt abbia completato il rendering iniziale
    # prima di applicare restoreState() (che richiede tutti i dock inizializzati).
    try:
        from core.session import Session
        from PyQt6.QtCore import QTimer
        def _restore_layout():
            try:
                Session.instance().restore_ui_state(win)

                # --- INIZIO AGGIUNTA: FORZA APERTURA DA PREFERENZE ---
                from config.settings import Settings
                s = Settings.instance()
                
                # Usiamo il NOME CORRETTO trovato nel tuo preferences.py!
                mostra_struttura = s.get("ui/show_symbol_panel_on_start", False)
                
                if mostra_struttura and hasattr(win, "_function_list_dock"):
                    win._function_list_dock.show()
                # --- FINE AGGIUNTA ---

            except Exception as e:
                print(f"[main] restore_ui_state: {e}")
        QTimer.singleShot(200, _restore_layout)
    except Exception:
        pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
