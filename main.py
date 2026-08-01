#!/usr/bin/env python3
"""
main.py — Entry point NotePadPQ

Uso:
    python main.py [file1 file2 ...]
"""

import os
import sys
import faulthandler
from pathlib import Path
from core.single_instance import SingleInstance

# Abilita faulthandler subito: stampa lo stack trace C++ su segfault/SIGABRT
faulthandler.enable()


def _ensure_gl() -> None:
    """
    Se il probe GLX hardware fallisce e LIBGL_ALWAYS_SOFTWARE non è ancora
    impostato, lo imposta e ri-esegue il processo via os.execve().
    Il secondo avvio usa Mesa llvmpipe (software GL) caricato fin dall'inizio,
    rendendo disponibile WebEngine (terminale, rich text, web PDF).
    Senza re-exec, impostare la variabile da Python non avrebbe effetto perché
    libGL è già caricato dalla libreria Qt prima che il codice Python giri.
    """
    if 'LIBGL_ALWAYS_SOFTWARE' in os.environ:
        return  # già impostato (da AppRun o da un re-exec precedente)
    if sys.platform != 'linux' or not os.environ.get('DISPLAY'):
        return  # solo Linux/X11
    try:
        from core.webengine import _probe_glx
        if not _probe_glx():
            os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
            os.execve(sys.executable, sys.argv, os.environ)
    except Exception:
        pass  # se il probe fallisce, procediamo normalmente


_ensure_gl()


def _fix_ssl() -> None:
    """
    In bundle PyInstaller il modulo ssl è incluso ma non trova i certificati CA
    di sistema, causando SSLCertVerificationError su qualsiasi richiesta HTTPS
    (plugin AI, controllo aggiornamenti, ecc.).
    Imposta SSL_CERT_FILE sul bundle di sistema se non già definito.
    """
    if os.environ.get('SSL_CERT_FILE') or os.environ.get('SSL_CERT_DIR'):
        return
    if not getattr(sys, 'frozen', False):
        return  # fuori da PyInstaller, Python usa i cert nativi
    _candidates = [
        '/etc/ssl/certs/ca-certificates.crt',   # Debian/Ubuntu/Arch
        '/etc/pki/tls/certs/ca-bundle.crt',      # RHEL/Fedora/CentOS
        '/etc/ssl/ca-bundle.pem',                 # OpenSUSE
        '/etc/ssl/cert.pem',                      # macOS/FreeBSD
        '/usr/share/ca-certificates/ca-bundle.crt',
    ]
    for p in _candidates:
        if os.path.isfile(p):
            os.environ['SSL_CERT_FILE'] = p
            break


_fix_ssl()


def _fix_webengine_gpu() -> None:
    """
    Quando LIBGL_ALWAYS_SOFTWARE=1 (GPU hardware assente o rotta), anche
    il renderer interno di Chromium (QtWebEngine) può restare nero perché
    usa un percorso di rendering GPU separato da libGL.
    Aggiunge --disable-gpu e --use-gl=swiftshader a QTWEBENGINE_CHROMIUM_FLAGS
    per forzare SwiftShader (software renderer interno a Chromium).
    Deve essere chiamato PRIMA di QApplication().
    """
    if os.environ.get('LIBGL_ALWAYS_SOFTWARE', '0') != '1':
        return
    flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
    if '--disable-gpu' not in flags:
        flags = flags + ' --disable-gpu --use-gl=swiftshader'
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = flags.strip()


_fix_webengine_gpu()


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

    import traceback

    def _excepthook(exc_type, exc_value, exc_tb):
        print("=" * 60, file=sys.stderr)
        print("NotePadPQ — ECCEZIONE NON GESTITA:", file=sys.stderr)
        traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    def _qt_msg_handler(msg_type, context, message):
        labels = {
            QtMsgType.QtDebugMsg:    "[Qt DEBUG]",
            QtMsgType.QtInfoMsg:     "[Qt INFO]",
            QtMsgType.QtWarningMsg:  "[Qt WARNING]",
            QtMsgType.QtCriticalMsg: "[Qt CRITICAL]",
            QtMsgType.QtFatalMsg:    "[Qt FATAL]",
        }
        label = labels.get(msg_type, "[Qt]")
        if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            loc = f" ({context.file}:{context.line})" if context.file else ""
            print(f"{label}{loc} {message}", file=sys.stderr)

    qInstallMessageHandler(_qt_msg_handler)

    # Emoji fallback for QScintilla: Qt's automatic font merging doesn't
    # trigger for SMP characters (U+1F000+) without explicit fontconfig rules
    # because QScintilla reconstructs QFont from raw family-name strings.
    # Writing a fontconfig rule before QApplication() makes Qt pick up
    # Symbola as fallback when any monospace font lacks an emoji glyph.
    import platform as _platform
    if _platform.system() == "Linux":
        try:
            import os as _os
            _fc_dir = _os.path.expanduser("~/.config/fontconfig/conf.d")
            _os.makedirs(_fc_dir, exist_ok=True)
            _fc_path = _os.path.join(_fc_dir, "99-notepadpq-emoji.conf")
            _families = [
                "Hack", "DejaVu Sans Mono", "Noto Mono", "Noto Sans Mono",
                "Liberation Mono", "FreeMono", "Courier New",
                "JetBrains Mono", "Fira Code", "Cascadia Code", "Source Code Pro",
            ]
            _rules = "\n".join(
                f'  <match target="pattern">\n'
                f'    <test qual="any" name="family"><string>{f}</string></test>\n'
                f'    <edit name="family" mode="append" binding="weak"><string>Symbola</string></edit>\n'
                f'  </match>'
                for f in _families
            )
            _conf = (
                '<?xml version="1.0"?>\n'
                '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                '<fontconfig>\n'
                + _rules + '\n'
                '</fontconfig>\n'
            )
            _existing = ""
            if _os.path.exists(_fc_path):
                with open(_fc_path) as _fh:
                    _existing = _fh.read()
            if _existing != _conf:
                with open(_fc_path, "w") as _fh:
                    _fh.write(_conf)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("NotePadPQ")
    app.setOrganizationName("NotePadPQ")
    app.setApplicationVersion("1.7.7")

    # Su alcune configurazioni Linux il flag può essere True di default.
    # Lo forziamo False per garantire che le icone nei menu siano visibili.
    from PyQt6.QtCore import Qt
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)

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

    # Avviamo SUBITO il server, prima di qualunque inizializzazione pesante
    # (MainWindow, i18n, plugin, QtWebEngine...). Se il server partisse solo
    # a fine inizializzazione, un doppio click arrivato nel frattempo
    # troverebbe la porta ancora chiusa, si crederebbe "primo" a sua volta e
    # ruberebbe il socket: esattamente il bug delle finestre doppie senza
    # file. I file ricevuti prima che la finestra esista vengono bufferizzati
    # e aperti non appena `win` è pronta (vedi `_win_holder` più sotto).
    _win_holder: dict = {"win": None}
    _pending_from_ipc: list = []

    def _on_files_received_early(paths) -> None:
        w = _win_holder["win"]
        if w is None:
            _pending_from_ipc.append(paths)
        else:
            w.open_files([Path(p) for p in paths])

    _si.start_server(callback=_on_files_received_early)
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

    # Inizializza i18n — usa la lingua salvata, altrimenti rileva dalla locale
    i18n = I18n.instance()
    lang = settings.get("i18n/language", None)
    if lang is None:
        from PyQt6.QtCore import QLocale
        system_name = QLocale.system().name()        # es. "it_IT", "de_DE", "C"
        base = system_name.split("_")[0].lower()     # "it", "de", "c"
        lang = base if base in i18n.available_languages() else "en"
    if lang != "en":
        i18n.set_language(lang)

    # Crea finestra principale
    win = MainWindow()
    win.show()

    # Il server single-instance è già attivo (avviato subito dopo il check
    # di secondarietà, vedi sopra): ora che `win` esiste, colleghiamo il
    # riferimento e scarichiamo eventuali file arrivati nel frattempo.
    _win_holder["win"] = win
    for _paths in _pending_from_ipc:
        win.open_files([Path(p) for p in _paths])
    _pending_from_ipc.clear()

    # ── Post-startup deferred ─────────────────────────────────────────────────
    # Eseguito dopo che tutti i plugin sono stati caricati (uno per tick).
    # La finestra è già visibile e responsiva durante questo processo.
    def _finish_startup():
        from PyQt6.QtCore import QTimer as _QT

        win._rebuild_toolbar()

        try:
            from ui.smart_highlight import SmartHighlighter, MultiMarkManager
            win._smart_highlighter = SmartHighlighter.install_into_main_window(win)
            win._mark_manager = MultiMarkManager.install_into_main_window(win)
        except Exception as e:
            print(f"[main] SmartHighlight: {e}")

        try:
            from ui.incremental_search import IncrementalSearchBar
            win._inc_search = IncrementalSearchBar.install(win)
        except Exception as e:
            print(f"[main] IncrementalSearch: {e}")

        try:
            from ui.function_list import install as install_function_list
            install_function_list(win)
        except Exception as e:
            print(f"[main] FunctionList: {e}")

        try:
            from ui.include_list import install as install_include_list
            install_include_list(win)
        except Exception as e:
            print(f"[main] IncludeList: {e}")

        try:
            from ui.json_xml_panel import install as install_json_xml
            install_json_xml(win)
        except Exception as e:
            print(f"[main] JsonXmlPanel: {e}")

        try:
            from ui.git_blame_inline import install as install_git_blame
            install_git_blame(win)
        except Exception as e:
            print(f"[main] GitBlameInline: {e}")

        # Ripristina layout dock/toolbar dopo che tutti i dock sono stati
        # aggiunti dai plugin (200 ms lasciano a Qt il tempo di completare
        # l'aggiunta dei widget prima di restoreState).
        try:
            from core.session import Session

            def _restore_layout():
                try:
                    Session.instance().restore_ui_state(win)
                except Exception as e:
                    print(f"[main] restore_ui_state: {e}")

            _QT.singleShot(200, _restore_layout)
        except Exception:
            pass

    # ── Carica plugin ────────────────────────────────────────────────────────
    # Fatto DOPO win.show(): i plugin aggiungono dock widget che richiedono
    # la finestra già inizializzata. Il caricamento è scaglionato (un plugin
    # per tick) per non bloccare la UI.
    try:
        from plugins.plugin_manager import PluginManager
        PluginManager.instance().load_all_deferred(win, on_done=_finish_startup)
    except Exception as e:
        print(f"[main] Errore caricamento plugin: {e}")
        _finish_startup()

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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
