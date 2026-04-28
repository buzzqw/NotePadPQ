"""
ui/main_window.py — Finestra principale NotePadPQ
NotePadPQ

Gestisce:
- Menubar completa (File, Modifica, Cerca, Visualizza, Documento, Strumenti, Plugin, Aiuto)
- Toolbar principale
- Coordinamento tra tab_manager, editor, statusbar
- Drag & drop file sulla finestra
- Gestione chiusura con controllo modifiche

NON gestisce: logica I/O file (→ core/file_manager.py),
              logica tab (→ ui/tab_manager.py),
              find/replace (→ ui/find_replace.py)
"""

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QObject, QEvent
from PyQt6.QtGui import (
    QAction, QIcon, QKeySequence, QCloseEvent, QDragEnterEvent, QDropEvent, QPageSize,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QMainWindow, QMenuBar, QMenu, QToolBar, QStatusBar, QDockWidget,
    QWidget, QVBoxLayout, QApplication, QMessageBox,
    QFileDialog, QInputDialog, QLabel, QSizePolicy, QPushButton,
)
from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog, QPageSetupDialog

from editor.editor_widget import EditorWidget, LineEnding
from i18n.i18n import tr, I18n
from core.platform import IS_WINDOWS, get_config_dir

# ─── MainWindow ───────────────────────────────────────────────────────────────


class TripleClickFilter(QObject):
    """Riconosce 3 click rapidi su un widget e lancia un'azione."""
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        self.clicks = 0
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.reset)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.clicks += 1
            if self.clicks == 1:
                self.timer.start(600) # Finestra di 600ms per fare i 3 click
            elif self.clicks == 3:
                self.callback()
                self.reset()
        return super().eventFilter(obj, event)

    def reset(self):
        self.clicks = 0

class MainWindow(QMainWindow):

    APP_NAME    = "NotePadPQ"
    APP_VERSION = "0.3.7"

    def __init__(self):
        super().__init__()

        # Importazioni locali per evitare dipendenze circolari
        from ui.tab_manager import TabManager
        from ui.statusbar import StatusBar

        self._tab_manager: TabManager = TabManager(self)
        self._statusbar: StatusBar    = StatusBar(self)
        
        # Usa ScreenResolution per far coincidere i DPI di QScintilla con quelli di stampa
        self._printer: QPrinter = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        
        # (Opzionale ma consigliato) Imposta l'A4 come default per un'anteprima corretta
        self._printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))

        self._setup_window()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_central()
        self._setup_dock_panels()
        self._setup_connections()
        self._setup_i18n()
        self._setup_autobackup()
        self._setup_autosave()
        self._setup_git_gutter()
        self._setup_clock()

        self.setAcceptDrops(True)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowTitle(self.APP_NAME)
        self.resize(1200, 750)
        self.setMinimumSize(600, 400)
        # Icona applicazione — carica da icons/NotePadPQ_N.png con tutte le
        # risoluzioni disponibili; Qt sceglie la taglia ottimale per ogni contesto
        # (titlebar, taskbar, dock, alt-tab...).
        icons_dir = Path(__file__).parent.parent / "icons"
        icon = QIcon()
        for size in [256, 128, 64, 48, 32, 16]:
            p = icons_dir / f"NotePadPQ_{size}.png"
            if p.exists():
                icon.addFile(str(p))
        if icon.isNull():
            # Fallback: file singolo nella cartella icons
            for name in ["NotePadPQ.png", "NotePadPQ.svg"]:
                p = icons_dir / name
                if p.exists():
                    icon = QIcon(str(p))
                    break
        if not icon.isNull():
            self.setWindowIcon(icon)

    def _setup_central(self) -> None:
        self.setCentralWidget(self._tab_manager)

    def _setup_dock_panels(self) -> None:
        """Inizializza i pannelli dockable (build, output, file browser, terminale)."""
        from ui.build_panel import BuildPanel
        from ui.file_browser import FileBrowser
        from ui.terminal_panel import TerminalPanel
        from PyQt6.QtWidgets import QTabWidget as _QTabWidget, QTreeWidget as _QTreeWidget, QTreeWidgetItem as _QTreeWidgetItem

        # ── Dock sinistro: File Browser ───────────────────────────────────────
        self._file_browser = FileBrowser(self)
        self._file_browser.file_open_requested.connect(
            lambda p: self.open_files([p])
        )
        self._file_browser_dock = QDockWidget("📁  File Browser", self)
        self._file_browser_dock.setObjectName("FileBrowserDock")
        self._file_browser_dock.setWidget(self._file_browser)
        self._file_browser_dock.setMinimumWidth(180)
        self._file_browser_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._file_browser_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._file_browser_dock)
        self._file_browser_dock.hide()

        # ── Dock sinistro: Gestione Progetti ─────────────────────────────────
        from ui.project_manager import ProjectManager
        self._project_manager = ProjectManager(self)
        self._project_manager.file_open_requested.connect(
            lambda p: self.open_files([p])
        )
        self._project_dock = QDockWidget("Progetti", self)
        self._project_dock.setObjectName("ProjectDock")
        self._project_dock.setWidget(self._project_manager)
        self._project_dock.setMinimumWidth(200)
        self._project_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._project_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._project_dock)
        self._project_dock.hide()

        # ── Dock anteprima (spostabile, alternativa allo split inline) ────────
        from ui.preview_panel import PreviewPanel
        self._preview_panel_dock = PreviewPanel()
        self._preview_dock = QDockWidget("👁  Anteprima", self)
        self._preview_dock.setObjectName("PreviewDock")
        self._preview_dock.setWidget(self._preview_panel_dock)
        self._preview_dock.setMinimumWidth(220)
        self._preview_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._preview_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._preview_dock)
        self._preview_dock.hide()
        # Aggiorna la preview quando cambia tab
        self._preview_dock.visibilityChanged.connect(self._on_preview_dock_visibility)

        # ── Pannello inferiore multiuso ───────────────────────────────────────
        self._bottom_tabs = _QTabWidget()
        self._bottom_tabs.setTabPosition(_QTabWidget.TabPosition.South)

        # Tab 1: Output compilazione
        self._build_panel = BuildPanel(self)
        self._bottom_tabs.addTab(self._build_panel, "⚙  Output compilazione")

        # Nota: i risultati ricerca sono ora embedded nel dialog find_replace.py

        # Tab 3: Terminale integrato
        self._terminal_panel = TerminalPanel(self)
        self._bottom_tabs.addTab(self._terminal_panel, "🖥  Terminale")

        self._build_dock = QDockWidget(tr("label.build_output", default="Pannello inferiore"), self)
        self._build_dock.setObjectName("BuildDock")
        self._build_dock.setWidget(self._bottom_tabs)
        self._build_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._build_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._build_dock)

        # Mostra all'avvio in base alle preferenze utente
        try:
            from config.settings import Settings
            s = Settings.instance()
            if s.get("build/panel_always", False):
                self._build_dock.show()
            else:
                self._build_dock.hide()

        except Exception:
            self._build_dock.hide()
        self._build_dock.visibilityChanged.connect(self._on_build_dock_visibility_changed)

    def _setup_statusbar(self) -> None:
        self.setStatusBar(self._statusbar)

    def _setup_connections(self) -> None:
        tm = self._tab_manager
        tm.current_editor_changed.connect(self._on_editor_changed)
        tm.tab_modified_changed.connect(self._on_tab_modified)

        # Notifica il PluginManager quando cambia l'editor attivo
        tm.current_editor_changed.connect(self._notify_plugins_editor_changed)

        # i18n: ricostruisce i menu quando cambia la lingua
        I18n.instance().language_changed.connect(self._rebuild_menus)
        self._on_editor_changed(tm.current_editor())

        # Auto-save su perdita fuoco — segnale cross-platform più affidabile di changeEvent
        QApplication.instance().applicationStateChanged.connect(
            self._on_application_state_changed
        )

    def _setup_autobackup(self) -> None:
        """Avvia il timer autobackup se abilitato nelle preferenze."""
        self._autobackup_timer = QTimer(self)
        self._autobackup_timer.timeout.connect(self._do_autobackup)
        self._apply_autobackup_settings()

    def _apply_autobackup_settings(self) -> None:
        from config.settings import Settings
        s = Settings.instance()
        enabled  = s.get("file/autobackup_enabled", False)
        interval = s.get("file/autobackup_interval", 5)
        self._autobackup_timer.stop()
        if enabled:
            self._autobackup_timer.start(interval * 60 * 1000)

    def _do_autobackup(self) -> None:
        """Salva una copia di backup di tutti i file aperti modificati."""
        from config.settings import Settings
        from core.platform import get_data_dir
        import datetime
        s = Settings.instance()
        backup_dir_str = s.get("file/autobackup_dir", "")
        backup_dir = Path(backup_dir_str) if backup_dir_str else get_data_dir() / "autobackup"
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        for editor in self._tab_manager.all_editors():
            if editor.file_path:
                try:
                    content = editor.get_content()
                    name = f"{editor.file_path.stem}_{ts}{editor.file_path.suffix}.bak"
                    (backup_dir / name).write_text(content, encoding="utf-8", errors="replace")
                except Exception:
                    pass

    # ── Auto-save ─────────────────────────────────────────────────────────────

    def _setup_autosave(self) -> None:
        """Avvia il timer auto-save se abilitato nelle preferenze."""
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._apply_autosave_settings()

    def _apply_autosave_settings(self) -> None:
        from config.settings import Settings
        s = Settings.instance()
        enabled  = s.get("file/autosave_enabled", False)
        interval = s.get("file/autosave_interval", 2)
        self._autosave_timer.stop()
        if enabled:
            self._autosave_timer.start(interval * 60 * 1000)

    def _do_autosave(self) -> None:
        """Salva silenziosamente tutti i file modificati che hanno già un path su disco."""
        for editor in self._tab_manager.all_editors():
            if editor.isModified() and editor.file_path:
                try:
                    self.action_save()
                except Exception:
                    pass

    # ── Git Gutter ────────────────────────────────────────────────────────────

    def _setup_git_gutter(self) -> None:
        from config.settings import Settings
        if Settings.instance().get("editor/git_gutter", True):
            try:
                from ui.git_gutter import GitGutter
                self._git_gutter = GitGutter(self)
            except Exception:
                pass

    # ── Command Palette ───────────────────────────────────────────────────────

    def action_command_palette(self) -> None:
        from ui.command_palette import CommandPaletteDialog
        dlg = CommandPaletteDialog(self)
        dlg.exec()

    def action_goto_anything(self) -> None:
        from ui.goto_anything import GotoAnythingDialog
        dlg = GotoAnythingDialog(self)
        dlg.exec()

    # ── Diff vs Saved ─────────────────────────────────────────────────────────

    def action_diff_vs_saved(self) -> None:
        """Confronta il buffer corrente con la versione salvata su disco."""
        editor = self._tab_manager.current_editor()
        if not editor or not editor.file_path or not editor.file_path.exists():
            self.statusBar().showMessage("Nessun file salvato da confrontare.", 3000)
            return
        try:
            disk_content = editor.file_path.read_text(encoding=editor.encoding or "utf-8",
                                                       errors="replace")
        except Exception as e:
            self.statusBar().showMessage(f"Errore lettura file: {e}", 4000)
            return

        current_content = editor.get_content()
        if current_content == disk_content:
            self.statusBar().showMessage("Il buffer è identico alla versione su disco.", 3000)
            return

        # Usa il plugin Compare se disponibile, altrimenti apri il file su disco in un nuovo tab
        try:
            from plugins.compare_plugin import ComparePlugin
            plugin = ComparePlugin.instance() if hasattr(ComparePlugin, "instance") else None
        except ImportError:
            plugin = None

        if plugin and hasattr(plugin, "compare_texts"):
            plugin.compare_texts(
                disk_content, current_content,
                label_a=f"{editor.file_path.name} (disco)",
                label_b=f"{editor.file_path.name} (buffer)",
            )
        else:
            # Fallback: apri la versione su disco in un nuovo tab affiancato
            import tempfile, os
            suffix = editor.file_path.suffix
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False,
                encoding="utf-8", prefix="saved_"
            ) as tmp:
                tmp.write(disk_content)
                tmp_path = Path(tmp.name)
            self.open_files([tmp_path])
            self.statusBar().showMessage(
                "Versione su disco aperta in un nuovo tab per il confronto manuale.", 4000
            )

    def _setup_i18n(self) -> None:
        """Applica le traduzioni iniziali a tutti i widget."""
        self._rebuild_menus()

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        self._menubar = self.menuBar()
        self._menus: dict[str, QMenu] = {}
        self._actions: dict[str, QAction] = {}
        self._build_menus()

    def _build_menus(self) -> None:
        """Costruisce la menubar completa."""
        mb = self._menubar
        mb.clear()

        self._build_menu_file(mb)
        self._build_menu_edit(mb)
        self._build_menu_search(mb)
        self._build_menu_view(mb)
        self._build_menu_document(mb)
        self._build_menu_tools(mb)
        self._build_menu_plugins(mb)
        self._build_menu_help(mb)

    def _rebuild_menus(self, lang: str = "") -> None:
        """Ricostruisce i menu dopo un cambio lingua."""
        self._build_menus()
        self._rebuild_toolbar()

    def _act(self, key: str, shortcut: str = "",
             slot=None, checkable: bool = False,
             checked: bool = False) -> QAction:
        """
        Crea o aggiorna un QAction identificato da key i18n.
        Registra l'azione in self._actions per l'editor scorciatoie.
        """
        action = QAction(tr(f"action.{key}"), self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(
                Qt.ShortcutContext.WindowShortcut
            )
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
        if slot:
            action.triggered.connect(slot)
        self._actions[key] = action
        return action

    def _sep(self, menu: QMenu) -> None:
        menu.addSeparator()

    # ── Menu File ─────────────────────────────────────────────────────────────

    def _build_menu_file(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.file"))
        self._menus["file"] = m

        m.addAction(self._act("new",       "Ctrl+N",       self.action_new))
        # Nuovo da modello — submenu
        sub_tmpl = m.addMenu(tr("action.new_from_template"))
        self._menus["new_from_template"] = sub_tmpl
        self._populate_templates_menu(sub_tmpl)

        self._sep(m)
        m.addAction(self._act("open",          "Ctrl+O",           self.action_open))
        m.addAction(self._act("open_selected",  "Shift+Ctrl+O",    self.action_open_selected))

        # File recenti — submenu
        self._recent_menu = m.addMenu(tr("action.open_recent"))
        self._menus["open_recent"] = self._recent_menu
        self._populate_recent_menu()

        self._sep(m)
        m.addAction(self._act("save",      "Ctrl+S",       self.action_save))
        m.addAction(self._act("save_as",   "Shift+Ctrl+S", self.action_save_as))
        m.addAction(self._act("save_all",  "Shift+Ctrl+S", self.action_save_all))

        self._sep(m)
        m.addAction(self._act("reload",         "Shift+Ctrl+R", self.action_reload))
        m.addAction(self._act("diff_vs_saved",  "",             self.action_diff_vs_saved))

        # Ripristina come — submenu
        sub_restore = m.addMenu(tr("action.restore_as"))
        self._menus["restore_as"] = sub_restore
        sub_restore.addAction(tr("action.reload"),     self.action_reload)
        sub_restore.addAction(tr("action.open_recent"), lambda: None)  # placeholder backup

        self._sep(m)
        m.addAction(self._act("file_properties", "Shift+Ctrl+V", self.action_file_properties))
        m.addAction(self._act("page_setup",      "",             self.action_page_setup))

        self._sep(m)
        m.addAction(self._act("print",      "Ctrl+P",       self.action_print))
        m.addAction(self._act("print_preview", "",           self.action_print_preview))
        m.addAction(self._act("export_pdf", "",              self.action_export_pdf))

        self._sep(m)
        m.addAction(self._act("close",        "Ctrl+W",       self.action_close))
        m.addAction(self._act("close_others", "",             self.action_close_others))
        m.addAction(self._act("close_all",    "Shift+Ctrl+W", self.action_close_all))

        self._sep(m)
        m.addAction(self._act("quit", "Ctrl+Q", self.close))

    def _populate_templates_menu(self, menu: QMenu) -> None:
        """Popola il submenu Nuovo da modello."""
        templates = [
            ("Python",     ".py"),
            ("HTML",       ".html"),
            ("LaTeX",      ".tex"),
            ("Markdown",   ".md"),
            ("Bash",       ".sh"),
            ("C/C++",      ".c"),
            ("JavaScript", ".js"),
        ]
        for name, ext in templates:
            action = QAction(name, self)
            action.triggered.connect(
                lambda checked, e=ext: self.action_new_from_template(e)
            )
            menu.addAction(action)

    def _populate_recent_menu(self) -> None:
        """Popola il submenu File recenti dalla cronologia."""
        self._recent_menu.clear()
        try:
            from core.recent_files import RecentFiles
            recent = RecentFiles.instance().get_list()
        except Exception:
            recent = []

        if not recent:
            empty = QAction(tr("msg.no_results").format(query=""), self)
            empty.setEnabled(False)
            self._recent_menu.addAction(empty)
            return

        for path in recent:
            p = Path(path)
            action = QAction(str(p), self)
            action.setToolTip(str(p))
            action.triggered.connect(
                lambda checked, fp=p: self.open_files([fp])
            )
            self._recent_menu.addAction(action)

        self._recent_menu.addSeparator()
        clear_act = QAction(tr("button.clear"), self)
        clear_act.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear_act)

    # ── Menu Modifica ─────────────────────────────────────────────────────────

    def _build_menu_edit(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.edit"))
        self._menus["edit"] = m

        # Undo/Redo/Cut/Copy/Paste: QsciScintilla gestisce queste shortcut
        # nativamente via keyPressEvent. Le shortcut nelle QAction sono solo
        # visive (WidgetWithChildrenShortcut) per evitare conflitti/duplicati.
        for _key, _sc in [("undo", "Ctrl+Z"), ("redo", "Ctrl+Y")]:
            _a = self._act(_key, "", self._relay(_key))
            _a.setShortcut(QKeySequence(_sc))
            _a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            m.addAction(_a)
        self._sep(m)
        for _key, _sc in [("cut", "Ctrl+X"), ("copy", "Ctrl+C"), ("paste", "Ctrl+V")]:
            _a = self._act(_key, "", self._relay(_key))
            _a.setShortcut(QKeySequence(_sc))
            _a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            m.addAction(_a)
        m.addAction(self._act("delete",     "Del",      self._relay("removeSelectedText")))
        self._sep(m)
        _a = self._act("select_all", "", self._relay("selectAll"))
        _a.setShortcut(QKeySequence("Ctrl+A"))
        _a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        m.addAction(_a)
        m.addAction(self._act("copy_path",  "",         self.action_copy_path))
        m.addAction(self._act("copy_filename", "",      self.action_copy_filename))
        self._sep(m)

        # Formatta submenu
        sub_fmt = m.addMenu(tr("menu.format"))
        self._menus["format"] = sub_fmt
        sub_fmt.addAction(self._act("join_lines",    "",         self.action_join_lines))
        sub_fmt.addAction(self._act("line_break",    "",         self.action_line_break))
        sub_fmt.addAction(self._act("wrap_lines",    "",         self.action_wrap_lines))
        sub_fmt.addSeparator()
        sub_fmt.addAction(self._act("uppercase",     "",         self.action_uppercase))
        sub_fmt.addAction(self._act("lowercase",     "",         self.action_lowercase))
        sub_fmt.addAction(self._act("titlecase",     "",         self.action_titlecase))
        sub_fmt.addAction(self._act("invert_case",   "Ctrl+Alt+U", self.action_invert_case))
        # --- AGGIUNTA SCORCIATOIE MARKUP ---
        sub_fmt.addSeparator()
        sub_fmt.addAction(self._act("markup_bold",   "Ctrl+B",       lambda: self._apply_markup("bold")))
        sub_fmt.addAction(self._act("markup_italic", "Ctrl+I",       lambda: self._apply_markup("italic")))
        sub_fmt.addAction(self._act("markup_strike", "Ctrl+Shift+X", lambda: self._apply_markup("strike")))
        sub_fmt.addAction(self._act("wrap_env",      "Alt+E",        self.action_wrap_env))
        sub_fmt.addSeparator()
        sub_fmt.addAction(self._act("toggle_comment","Ctrl+E",   self.action_toggle_comment))
        sub_fmt.addAction(self._act("comment_line",  "",         self.action_comment_lines))
        sub_fmt.addAction(self._act("uncomment_line","",         self.action_uncomment_lines))
        sub_fmt.addSeparator()
        sub_fmt.addAction(self._act("align_table",   "Alt+T",    self.action_align_table))
        sub_fmt.addSeparator()
        sub_fmt.addAction(self._act("indent",        "Ctrl+Shift+I",   self.action_indent))
        sub_fmt.addAction(self._act("unindent",      "Ctrl+U",   self.action_unindent))
        sub_fmt.addAction(self._act("indent_smart",  "",         self.action_indent_smart))
        sub_fmt.addSeparator()
        sub_fmt.addAction(self._act("trim_trailing", "",         self.action_trim_trailing))
        sub_fmt.addAction(self._act("tabs_to_spaces","",         self.action_tabs_to_spaces))
        sub_fmt.addAction(self._act("spaces_to_tabs","",         self.action_spaces_to_tabs))

        self._sep(m)
        m.addAction(self._act("insert_date",     "", self.action_insert_date))
        m.addAction(self._act("word_count",      "", self.action_word_count))
        m.addAction(self._act("word_frequency",  "", self.action_word_frequency))
        m.addAction(self._act("sort_lines_menu", "", self.action_sort_lines_dialog))
        self._sep(m)
        # ── Multi-cursore ─────────────────────────────────────────────────────
        sub_mc = m.addMenu("🖊  " + tr("menu.multicursor"))
        self._menus["multicursor"] = sub_mc
        sub_mc.addAction(self._act("mc_next_occ",    "Ctrl+D",
                                   self._mc_select_next))
        sub_mc.addAction(self._act("mc_all_occ",     "Ctrl+Shift+D",
                                   self._mc_select_all))
        sub_mc.addAction(self._act("mc_add_above",   "Ctrl+Alt+Up",
                                   self._mc_add_above))
        sub_mc.addAction(self._act("mc_add_below",   "Ctrl+Alt+Down",
                                   self._mc_add_below))
        sub_mc.addAction(self._act("mc_numbers",     "Ctrl+Shift+Alt+C",
                                   self._mc_insert_numbers))
        sub_mc.addAction(self._act("mc_clear",       "Escape",
                                   self._mc_clear))
        self._sep(m)
        m.addAction(self._act("autoclose_toggle", "", self._toggle_autoclose,
                               checkable=True, checked=True))
        self._sep(m)
        m.addAction(self._act("preferences", "Ctrl+Alt+P", self.action_preferences))

    # ── Menu Cerca ────────────────────────────────────────────────────────────

    def _build_menu_search(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.search"))
        self._menus["search"] = m

        m.addAction(self._act("command_palette", "Ctrl+Shift+P", self.action_command_palette))
        m.addAction(self._act("goto_anything",   "Ctrl+Shift+G", self.action_goto_anything))
        self._sep(m)
        m.addAction(self._act("find",            "Ctrl+F",       self.action_find))
        m.addAction(self._act("find_next",       "F3",           self.action_find_next))
        m.addAction(self._act("find_prev",       "Shift+F3",     self.action_find_prev))
        m.addAction(self._act("replace",         "Ctrl+H",       self.action_replace))
        self._sep(m)
        # Ricerca incrementale inline (non sostituisce il dialog)
        #act_inc = self._act("incremental_search", "Ctrl+F2", self._toggle_incremental_search,
        #                    checkable=True, checked=False)
        #m.addAction(act_inc)
        self._sep(m)
        m.addAction(self._act("find_in_files",      "Ctrl+Shift+F", self.action_find_in_files))
        m.addAction(self._act("find_in_all_docs",   "",             self.action_find_in_all_docs))
        m.addAction(self._act("replace_in_all_docs","",             self.action_replace_in_all_docs))
        self._sep(m)
        m.addAction(self._act("go_to_line",      "Ctrl+G",       self.action_go_to_line))
        m.addAction(self._act("go_to_matching",  "Ctrl+]",       self.action_go_to_matching))
        self._sep(m)
        m.addAction(self._act("mark_all",        "",             self.action_mark_all))
        m.addAction(self._act("remove_markers",  "",             self.action_remove_markers))
        self._sep(m)
        # Le voci "Segna con colore 1-5" e "Rimuovi tutti i mark" (Ctrl+0..5)
        # vengono aggiunte da MultiMarkManager.install_into_main_window() in main.py
        # dopo l'inizializzazione — non duplicarle qui.
        self._sep(m)
        m.addAction(self._act("toggle_bookmark", "Ctrl+F2",      self.action_toggle_bookmark))
        m.addAction(self._act("next_bookmark",   "F2",           self.action_next_bookmark))
        m.addAction(self._act("prev_bookmark",   "Shift+F2",     self.action_prev_bookmark))
        m.addAction(self._act("clear_bookmarks", "",             self.action_clear_bookmarks))

    # ── Menu Visualizza ───────────────────────────────────────────────────────

    def _build_menu_view(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.view"))
        self._menus["view"] = m

        # --- IMPORTIAMO LE IMPOSTAZIONI ---
        from config.settings import Settings
        s = Settings.instance()

        # Ora usiamo s.get(...) per leggere le tue preferenze salvate al posto di forzare True o False!
        m.addAction(self._act("view_toolbar",     "", self._toggle_toolbar,     checkable=True, checked=s.get("view/toolbar", True)))
        m.addAction(self._act("view_statusbar",   "", self._toggle_statusbar,   checkable=True, checked=s.get("view/statusbar", True)))
        self._sep(m)
        m.addAction(self._act("view_line_numbers","", self._toggle_line_numbers,checkable=True, checked=s.get("editor/show_line_numbers", True)))
        m.addAction(self._act("view_fold_margin", "", self._toggle_fold_margin, checkable=True, checked=s.get("editor/show_fold_margin", True)))
        m.addAction(self._act("view_whitespace",  "", self._toggle_whitespace,  checkable=True, checked=s.get("editor/show_whitespace", False)))
        m.addAction(self._act("view_eol",         "", self._toggle_eol,         checkable=True, checked=s.get("editor/show_eol", False)))
        # view_word_wrap: registrata qui per _actions ma aggiunta solo al menu Documento
        self._act("view_word_wrap", "Alt+Z", self._toggle_word_wrap, checkable=True, checked=s.get("editor/word_wrap", False))
        self._sep(m)

        # --- DA QUI IN POI IL MENU RIMANE UGUALE A PRIMA ---
        m.addAction(self._act("view_minimap",       "", self._toggle_minimap,        checkable=True, checked=False))
        m.addAction(self._act("view_build_panel",  "Ctrl+`", self._toggle_build_panel,   checkable=True, checked=False))
        m.addAction(self._act("view_file_browser", "Ctrl+Shift+E", self._toggle_file_browser, checkable=True, checked=False))
        m.addAction(self._act("view_project_manager", "", self._toggle_project_manager, checkable=True, checked=False))
        m.addAction(self._act("preview_toggle",  "F12", self._toggle_preview,   checkable=True, checked=False))
        self._sep(m)
        m.addAction(self._act("view_zoom_in",    "Ctrl+=",   self.action_zoom_in))
        m.addAction(self._act("view_zoom_out",   "Ctrl+-",   self.action_zoom_out))
        m.addAction(self._act("view_zoom_reset", "Ctrl+0",   self.action_zoom_reset))
        self._sep(m)
        _df_act = self._act("distraction_free", "F11", self._toggle_distraction_free, checkable=True, checked=False)
        _df_act.setShortcuts([QKeySequence("F11"), QKeySequence("Ctrl+Shift+F11"), QKeySequence("Ctrl+F11")])
        m.addAction(_df_act)
        self._sep(m)
        m.addAction(self._act("view_plain_text_mode", "Ctrl+Alt+T",
                               self._toggle_plain_text_mode,
                               checkable=True, checked=False))
        self._sep(m)

        # ── Split View submenu ─────────────────────────────────────────────────
        sub_split = m.addMenu("🔲  " + tr("menu.split_view"))
        self._menus["split_view"] = sub_split

        sub_split.addAction(self._act(
            "split_vertical",    "Ctrl+Alt+2",
            lambda: self._tab_manager.split(
                self._tab_manager.SPLIT_SIDE_BY_SIDE, clone_current=True
            ) if hasattr(self._tab_manager, "split") else None
        ))
        sub_split.addAction(self._act(
            "split_horizontal",  "Ctrl+Alt+3",
            lambda: self._tab_manager.split(
                self._tab_manager.SPLIT_TOP_BOTTOM, clone_current=True
            ) if hasattr(self._tab_manager, "split") else None
        ))
        sub_split.addAction(self._act(
            "split_rotate",      "Ctrl+Alt+R",
            lambda: self._tab_manager.rotate_split()
            if hasattr(self._tab_manager, "rotate_split") else None
        ))
        self._sep(sub_split)
        sub_split.addAction(self._act(
            "split_move_tab",    "Ctrl+Alt+M",
            lambda: self._tab_manager.move_to_other_panel()
            if hasattr(self._tab_manager, "move_to_other_panel") else None
        ))
        sub_split.addAction(self._act(
            "split_sync_cursor", "",
            self._toggle_split_sync,
            checkable=True, checked=False
        ))
        self._sep(sub_split)
        sub_split.addAction(self._act(
            "unsplit",           "Ctrl+Alt+1",
            lambda: self._tab_manager.unsplit()
            if hasattr(self._tab_manager, "unsplit") else None
        ))

    # ── Menu Documento ────────────────────────────────────────────────────────

    def _build_menu_document(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.document"))
        self._menus["document"] = m

        m.addAction(self._actions["view_word_wrap"])  # stessa action di Visualizza → checkbox sincronizzato
        m.addAction(self._act("line_break",        "", self.action_line_break,           checkable=False))
        m.addAction(self._act("auto_indent",       "", self._toggle_auto_indent,         checkable=True, checked=True))
        m.addAction(self._act("auto_indent_paste", "", self._toggle_auto_indent_paste,   checkable=True, checked=True))
        from config.settings import Settings as _S
        _spell_enabled = _S.instance().get("spellcheck/enabled", False)
        _spell_saved   = _S.instance().get("spellcheck/language", "it")
        m.addAction(self._act("spell_check", "F4", self._toggle_spellcheck,
                              checkable=True, checked=_spell_enabled))

        # Submenu lingua dizionario (indipendente dalla lingua dell'interfaccia)
        sub_spell = m.addMenu(tr("action.spell_lang"))
        self._menus["spell_lang"] = sub_spell
        from PyQt6.QtGui import QActionGroup as _SpellAG
        _spell_ag = _SpellAG(self)
        _spell_ag.setExclusive(True)
        self._spell_lang_actions: dict[str, QAction] = {}
        for _code, _label in [("it", "Italiano"), ("en", "English"),
                               ("de", "Deutsch"), ("fr", "Français"), ("es", "Español")]:
            _a = QAction(_label, self, checkable=True)
            _a.setChecked(_code == _spell_saved)
            _a.triggered.connect(lambda _checked, c=_code: self._set_spell_lang(c))
            _spell_ag.addAction(_a)
            sub_spell.addAction(_a)
            self._spell_lang_actions[_code] = _a
        self._sep(m)

        # Tipo indentazione submenu
        sub_indent = m.addMenu(tr("action.indent_type"))
        self._menus["indent_type"] = sub_indent
        ag_indent = sub_indent  # QActionGroup per radio
        act_tabs   = QAction(tr("label.tab_size") + " (Tab)", self, checkable=True)
        act_spaces = QAction(tr("label.use_spaces"), self, checkable=True, checked=True)
        act_tabs.triggered.connect(lambda: self._set_indent_type(False))
        act_spaces.triggered.connect(lambda: self._set_indent_type(True))
        sub_indent.addAction(act_tabs)
        sub_indent.addAction(act_spaces)

        m.addAction(self._act("indent_width", "", self.action_set_indent_width))
        self._sep(m)
        m.addAction(self._act("read_only",   "", self._toggle_read_only,   checkable=True, checked=False))
        m.addAction(self._act("write_bom",   "", self._toggle_write_bom,   checkable=True, checked=False))
        self._sep(m)

        # Imposta tipo di file submenu
        sub_type = m.addMenu(tr("action.set_file_type"))
        self._menus["set_file_type"] = sub_type
        self._populate_file_type_menu(sub_type)

        # Imposta codifica submenu
        sub_enc = m.addMenu(tr("action.set_encoding"))
        self._menus["set_encoding"] = sub_enc
        self._populate_encoding_menu(sub_enc)

        # Imposta terminatori di riga submenu
        sub_le = m.addMenu(tr("action.set_line_ending"))
        self._menus["set_line_ending"] = sub_le
        from PyQt6.QtGui import QActionGroup as _AG
        _le_grp = _AG(self)
        _le_grp.setExclusive(True)
        self._le_actions: dict[str, QAction] = {}
        for _label, _le, _key in [
            ("LF (Unix)",     LineEnding.LF,   "lf"),
            ("CRLF (Windows)",LineEnding.CRLF, "crlf"),
            ("CR (Mac)",      LineEnding.CR,   "cr"),
        ]:
            _a = QAction(_label, self)
            _a.setCheckable(True)
            _a.triggered.connect(lambda checked, le=_le: self.action_set_line_ending(le))
            _le_grp.addAction(_a)
            sub_le.addAction(_a)
            self._le_actions[_key] = _a

        self._sep(m)
        m.addAction(self._act("clone_document",       "", self.action_clone))
        m.addAction(self._act("trim_trailing",        "", self.action_trim_trailing))
        m.addAction(self._act("tabs_to_spaces",       "", self.action_tabs_to_spaces))
        m.addAction(self._act("spaces_to_tabs",       "", self.action_spaces_to_tabs))
        self._sep(m)
        m.addAction(self._act("fold_all",             "", self.action_fold_all))
        m.addAction(self._act("unfold_all",           "", self.action_unfold_all))
        self._sep(m)
        m.addAction(self._act("remove_markers",       "", self.action_remove_markers))
        m.addAction(self._act("remove_error_markers", "", self.action_remove_error_markers))

    def _populate_file_type_menu(self, menu: QMenu) -> None:
        """Popola il submenu Imposta tipo di file — ordinato alfabeticamente con checkmark."""
        types = sorted([
            "Bash/Shell", "C/C++", "C#", "CMake", "CSS", "Diff",
            "Go", "HTML", "INI/Config", "Java", "JavaScript",
            "JSON", "LaTeX", "Lua", "Makefile", "Markdown",
            "PHP", "Python", "Ruby", "Rust", "SQL",
            "Testo normale", "TypeScript", "XML", "YAML",
        ])
        # QActionGroup per checkmark esclusivo
        from PyQt6.QtGui import QActionGroup
        grp = QActionGroup(self)
        grp.setExclusive(True)
        self._file_type_actions: dict[str, QAction] = {}
        for t in types:
            action = QAction(t, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked, lang=t: self.action_set_language(lang)
            )
            grp.addAction(action)
            menu.addAction(action)
            self._file_type_actions[t.lower()] = action

    def _update_file_type_menu(self, editor: "EditorWidget") -> None:
        """Aggiorna i checkmark nei menu tipo file, codifica e fine riga."""
        # Tipo file
        if hasattr(self, "_file_type_actions"):
            from editor.lexers import get_language_name
            lang = get_language_name(editor).lower()
            _aliases = {
                "text": "testo normale", "plain": "testo normale",
                "bash": "bash/shell", "shell": "bash/shell",
                "c++": "c/c++", "c": "c/c++",
            }
            lang = _aliases.get(lang, lang)
            for key, act in self._file_type_actions.items():
                act.setChecked(key == lang)

        # Codifica
        if hasattr(self, "_enc_actions"):
            enc_key = editor.encoding.lower().replace(" ", "-")
            for key, act in self._enc_actions.items():
                act.setChecked(key == enc_key)

        # Fine riga
        if hasattr(self, "_le_actions"):
            from editor.editor_widget import LineEnding
            le = getattr(editor, "_line_ending", LineEnding.LF)
            le_map = {
                LineEnding.LF:   "lf",
                LineEnding.CRLF: "crlf",
                LineEnding.CR:   "cr",
            }
            active = le_map.get(le, "lf")
            for key, act in self._le_actions.items():
                act.setChecked(key == active)

    def _populate_encoding_menu(self, menu: QMenu) -> None:
        """Popola il submenu Imposta codifica con checkmark esclusivo."""
        from PyQt6.QtGui import QActionGroup
        encodings = [
            "UTF-8", "UTF-8 BOM", "UTF-16 LE", "UTF-16 BE",
            "ISO-8859-1 (Latin-1)", "ISO-8859-15", "Windows-1252",
            "GB2312", "GBK", "Big5", "KOI8-R", "ASCII",
        ]
        grp = QActionGroup(self)
        grp.setExclusive(True)
        self._enc_actions: dict[str, QAction] = {}
        for enc in encodings:
            action = QAction(enc, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked, e=enc: self.action_set_encoding(e)
            )
            grp.addAction(action)
            menu.addAction(action)
            # Chiave normalizzata per il lookup
            self._enc_actions[enc.lower().replace(" ", "-")] = action

    # ── Menu Strumenti ────────────────────────────────────────────────────────

    def _build_menu_tools(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.tools"))
        self._menus["tools"] = m

        # Line Operations submenu
        sub_lo = m.addMenu(tr("menu.line_operations"))
        from ui.line_operations_menu import build_line_ops_menu
        build_line_ops_menu(sub_lo, self)

        self._sep(m)
        m.addAction(self._act("record_macro",    "",    self.action_record_macro))
        m.addAction(self._act("stop_macro",      "",    self.action_stop_macro))
        m.addAction(self._act("play_macro",      "",    self.action_play_macro))
        m.addAction(self._act("play_macro_n",    "",    self.action_play_macro_n))
        m.addAction(self._act("save_macro",      "",    self.action_save_macro))
        m.addAction(self._act("load_macro",      "",    self.action_load_macro))
        self._sep(m)
        m.addAction(self._act("named_sessions",  "",    self.action_named_sessions))
        self._sep(m)
        m.addAction(self._act("compare_files",   "", self.action_compare))
        m.addAction(self._act("color_picker",    "", self.action_color_picker))
        m.addAction(self._act("regex_tester",    "", self.action_regex_tester))
        m.addAction(self._act("number_converter","", self.action_number_converter))
        m.addAction(self._act("column_stats",    "Ctrl+Alt+S", self.action_column_stats))
        m.addAction(self._act("lorem_ipsum",     "", self.action_lorem_ipsum))
        self._sep(m)
        m.addAction(self._act("build_profiles",  "F8", self.action_build_profiles))
        m.addAction(self._act("compile",         "F6", self.action_compile))
        m.addAction(self._act("run",             "F5", self.action_run))
        m.addAction(self._act("build",           "F7", self.action_build))
        m.addAction(self._act("stop_build",      "",   self.action_stop_build))
        self._sep(m)
        m.addAction(self._act("keybinding_editor","",  self.action_keybinding_editor))
        m.addAction(self._act("reload_config",   "",   self.action_reload_config))
        self._sep(m)
        m.addAction(self._act("preferences", "Ctrl+Alt+P", self.action_preferences))

    # ── Menu Plugin ───────────────────────────────────────────────────────────

    def _build_menu_plugins(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.plugins"))
        self._menus["plugins"] = m
        m.addAction(self._act("plugin_manager", "", self.action_plugin_manager))
        self._sep(m)
        # Il separatore divide le voci di sistema dai plugin caricati dinamicamente.
        # Il menu è SEMPRE visibile: l'utente deve poter aprire il Plugin Manager
        # anche quando non ci sono plugin attivi.
        m.menuAction().setVisible(True)

    # ── Menu Aiuto ────────────────────────────────────────────────────────────

    def _build_menu_help(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.help"))
        self._menus["help"] = m
        m.addAction(self._act("about",         "", self.action_about))
        m.addAction(self._act("about_qt",      "", lambda: QApplication.aboutQt()))
        self._sep(m)
        m.addAction(self._act("check_updates", "", self.action_check_updates))
        self._sep(m)
        m.addAction(self._act("donate",        "", self.action_donate))

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _setup_toolbar(self) -> None:
        self._toolbar = self.addToolBar("Main")
        self._toolbar.setObjectName("MainToolbar")
        self._toolbar.setMovable(False)
        from PyQt6.QtCore import QSize
        self._toolbar.setIconSize(QSize(20, 20))
        self._rebuild_toolbar()

    def _rebuild_toolbar(self) -> None:
        """Carica le icone dal disco. Nessun download qui (per non bloccare l'avvio)."""
        from PyQt6.QtWidgets import QStyle
        from PyQt6.QtGui import QIcon
        from pathlib import Path
        from config.settings import Settings

        tb = self._toolbar
        tb.clear()
        style = self.style()
        
        settings = Settings.instance()
        selected_set = settings.get("ui/icon_set", "lucide")

        # Configurazione mappatura (stessa di prima)
        ICON_MAPS = {
            "lucide": {
                "new": "file-plus.svg", "open": "folder-open.svg", "save": "save.svg",
                "save_all": "database.svg", "close": "x-square.svg", "find": "search.svg",
                "replace": "refresh-cw.svg", "undo": "undo.svg", "redo": "redo.svg",
                "compile": "play.svg", "run": "fast-forward.svg", "build": "hammer.svg",
                "stop_build": "square.svg", "preferences": "settings.svg", "about": "info.svg"
            },
            "material": {
                "new": "note_add.svg", "open": "folder_open.svg", "save": "save.svg",
                "save_all": "library_add.svg", "close": "close.svg", "find": "search.svg",
                "replace": "find_replace.svg", "undo": "undo.svg", "redo": "redo.svg",
                "compile": "play_arrow.svg", "run": "fast_forward.svg", "build": "build.svg",
                "stop_build": "stop.svg", "preferences": "settings.svg", "about": "info.svg"
            }
        }

        current_map = ICON_MAPS.get(selected_set, {})
        icons_dir = Path(__file__).parent.parent / "icons" / selected_set

        # Icone di sistema (Integrated / Default)
        toolbar_actions = {
            "new": QStyle.StandardPixmap.SP_FileIcon,
            "open": QStyle.StandardPixmap.SP_DirOpenIcon,
            "save": QStyle.StandardPixmap.SP_DialogSaveButton,
            "save_all": QStyle.StandardPixmap.SP_DriveFDIcon,
            "find": QStyle.StandardPixmap.SP_FileDialogContentsView,
            "replace": QStyle.StandardPixmap.SP_BrowserReload,
            "undo": QStyle.StandardPixmap.SP_ArrowBack,
            "redo": QStyle.StandardPixmap.SP_ArrowForward,
            "compile": QStyle.StandardPixmap.SP_MediaPlay,
            "run": QStyle.StandardPixmap.SP_MediaSkipForward,
            "build": QStyle.StandardPixmap.SP_BrowserReload,
            "stop_build": QStyle.StandardPixmap.SP_MediaStop,
            "preferences": QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "about": QStyle.StandardPixmap.SP_MessageBoxInformation,
        }

        for key, fallback in toolbar_actions.items():
            if key not in self._actions: continue
            
            icon_file = current_map.get(key)
            icon_path = icons_dir / icon_file if icon_file else None

            if icon_path and icon_path.exists():
                self._actions[key].setIcon(QIcon(str(icon_path)))
            else:
                self._actions[key].setIcon(style.standardIcon(fallback))

        # Ricostruzione fisica toolbar
        _groups = [["new", "open", "save", "save_all"], ["find", "replace"], ["undo", "redo"], ["compile", "run"]]
        for group in _groups:
            added = False
            for k in group:
                if k in self._actions:
                    tb.addAction(self._actions[k])
                    added = True
            if added: tb.addSeparator()

    def download_icon_set(self, set_name: str) -> None:
        """Scarica un set di icone completo. Chiamato dal pannello Preferenze."""
        import urllib.request
        import ssl
        from pathlib import Path
        from PyQt6.QtWidgets import QProgressDialog

        if set_name == "system":
            print("[download_icon_set] set 'system' selezionato, rebuild toolbar diretto")
            self._rebuild_toolbar()
            return

        print(f"[download_icon_set] avvio download set='{set_name}'")

        URL_TEMPLATES = {
            "lucide":   "https://unpkg.com/lucide-static@latest/icons/{icon}.svg",
            "material": "https://fonts.gstatic.com/s/i/materialicons/{icon}/v4/24px.svg",
        }

        icons_to_download = [
            "file-plus", "folder-open", "save", "database", "x-square",
            "search", "refresh-cw", "undo", "redo", "play", "fast-forward",
            "hammer", "square", "settings", "info"
        ] if set_name == "lucide" else [
            "note_add", "folder_open", "save", "library_add", "close",
            "search", "find_replace", "undo", "redo", "play_arrow",
            "fast_forward", "build", "stop", "settings", "info"
        ]

        total = len(icons_to_download)
        dest_dir = Path(__file__).parent.parent / "icons" / set_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"[download_icon_set] destinazione: {dest_dir}")

        already = sum(1 for ic in icons_to_download if (dest_dir / f"{ic}.svg").exists())
        print(f"[download_icon_set] {already}/{total} icone già presenti")

        progress = QProgressDialog(self)
        progress.setWindowTitle(f"Download icone '{set_name}'")
        progress.setLabelText(f"Preparazione… ({total - already} da scaricare)")
        progress.setCancelButtonText("Annulla")
        progress.setRange(0, total)
        progress.setValue(already)
        progress.setMinimumWidth(420)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        QApplication.processEvents()

        # TLS: verifica disabilitata intenzionalmente per compatibilità
        # con proxy aziendali MITM che sostituiscono il certificato del server.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        downloaded = 0
        failed = 0

        for i, icon in enumerate(icons_to_download):
            if progress.wasCanceled():
                print(f"[download_icon_set] annullato dall'utente a i={i}")
                break

            local_file = dest_dir / f"{icon}.svg"

            if local_file.exists():
                progress.setValue(i + 1)
                progress.setLabelText(f"[{i+1}/{total}] {icon}.svg — già presente")
                QApplication.processEvents()
                continue

            progress.setLabelText(f"[{i+1}/{total}]  Scarico  {icon}.svg …")
            QApplication.processEvents()

            url = URL_TEMPLATES[set_name].format(icon=icon)
            print(f"[download_icon_set] GET {url}")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10.0, context=ctx) as resp:
                    data = resp.read()
                    local_file.write_bytes(data)
                    downloaded += 1
                    print(f"[download_icon_set] OK {icon}.svg ({len(data)} bytes)")
            except Exception as e:
                failed += 1
                print(f"[download_icon_set] ERRORE {icon}.svg: {e}")
                progress.setLabelText(f"[{i+1}/{total}]  ⚠ Errore: {icon}.svg")
                QApplication.processEvents()
                continue

            progress.setValue(i + 1)
            QApplication.processEvents()

        progress.setValue(total)
        summary = f"Completato: {downloaded} scaricate, {already} già presenti"
        if failed:
            summary += f", {failed} errori"
        print(f"[download_icon_set] {summary}")

        if not progress.wasCanceled():
            progress.setLabelText(summary)
            QApplication.processEvents()

        progress.close()
        self._rebuild_toolbar()

    # ── Slot: cambio editor corrente ──────────────────────────────────────────

    @pyqtSlot(object)
    def _on_editor_changed(self, editor: Optional[EditorWidget]) -> None:
        """Aggiorna titolo finestra e statusbar quando cambia il tab attivo."""
        if editor is None:
            self.setWindowTitle(self.APP_NAME)
            return

        # Controllo se il file proviene dall'FTP
        if hasattr(editor, "_ftp_remote_path") and editor._ftp_remote_path:
            proto = getattr(editor, "_ftp_profile", None)
            prefix = f"{proto.protocol.lower()}://{proto.host}" if proto else "ftp://"
            name = f"{prefix}{editor._ftp_remote_path}"
        else:
            # File locale normale
            path = editor.file_path
            name = str(path) if path else tr("label.untitled")

        mod  = " *" if editor.is_modified() else ""
        self.setWindowTitle(f"{name}{mod} — {self.APP_NAME}")

        self._statusbar.update_from_editor(editor)

        # --- AGGIUNGI DA QUI ---
        # Forza le impostazioni visive del menu sul tab corrente
        if "view_word_wrap" in self._actions:
            editor.set_word_wrap(self._actions["view_word_wrap"].isChecked())
        if "view_line_numbers" in self._actions:
            editor.set_show_line_numbers(self._actions["view_line_numbers"].isChecked())
        if "view_whitespace" in self._actions:
            editor.set_show_whitespace(self._actions["view_whitespace"].isChecked())
        if "view_eol" in self._actions:
            editor.set_show_eol(self._actions["view_eol"].isChecked())
        # Applica edge column dalla impostazione corrente
        from config.settings import Settings
        editor.set_edge_column(Settings.instance().get("editor/edge_column", 0))
        # Applica spell check se abilitato (il nuovo tab potrebbe non averlo ancora)
        if Settings.instance().get("spellcheck/enabled", False):
            if hasattr(editor, "set_spellcheck_enabled") and editor._spell_checker is None:
                editor.set_spellcheck_enabled(
                    True, Settings.instance().get("spellcheck/language", "it")
                )
        # --- FINE AGGIUNTA ---

        # Aggiorna checkmark nel menu tipo file
        self._update_file_type_menu(editor)

        # Sincronizza il checkmark "Modalità testo semplice" al tab corrente
        if "view_plain_text_mode" in self._actions:
            act = self._actions["view_plain_text_mode"]
            act.blockSignals(True)
            act.setChecked(getattr(editor, "_plain_text_mode", False))
            act.blockSignals(False)

        # Aggiorna dock anteprima se visibile
        # Aggiorna SEMPRE il dock anteprima, indipendentemente dalla visibilità di Qt
        if hasattr(self, "_preview_panel_dock"):
            self._preview_panel_dock.set_editor(editor)

        # Collega i segnali del nuovo editor allo statusbar
        editor.cursor_changed.connect(self._statusbar.set_cursor)
        editor.selection_changed_info.connect(self._statusbar.set_selection)
        editor.encoding_changed.connect(self._statusbar.set_encoding)
        editor.line_ending_changed.connect(self._statusbar.set_line_ending)
        editor.modified_changed.connect(
            lambda mod: self._on_tab_modified(editor, mod)
        )
        editor.overwrite_changed.connect(self._statusbar.set_overwrite)
        editor.zoom_changed.connect(self._statusbar.set_zoom)

    @pyqtSlot(object, bool)
    def _on_tab_modified(self, editor: EditorWidget, modified: bool) -> None:
        # Controllo se il file proviene dall'FTP
        if hasattr(editor, "_ftp_remote_path") and editor._ftp_remote_path:
            proto = getattr(editor, "_ftp_profile", None)
            prefix = f"{proto.protocol.lower()}://{proto.host}" if proto else "ftp://"
            name = f"{prefix}{editor._ftp_remote_path}"
        else:
            # File locale normale
            path = editor.file_path
            name = str(path) if path else tr("label.untitled")

        mod  = " *" if modified else ""
        self.setWindowTitle(f"{name}{mod} — {self.APP_NAME}")

    # ── Helper: relay all'editor corrente ────────────────────────────────────

    def _relay(self, method_name: str):
        """Restituisce uno slot che chiama method_name sull'editor corrente."""
        def _slot():
            editor = self._tab_manager.current_editor()
            if editor:
                getattr(editor, method_name)()
        return _slot

    def _current_editor(self) -> Optional[EditorWidget]:
        return self._tab_manager.current_editor()

    # ── Azioni File ───────────────────────────────────────────────────────────

    def action_new(self) -> None:
        self._tab_manager.new_tab()

    def action_new_from_template(self, extension: str) -> None:
        self._tab_manager.new_tab(template_ext=extension)

    def action_open(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("action.open"),
            str(Path.home()),
            "Tutti i file (*)"
        )
        if paths:
            self.open_files([Path(p) for p in paths])

    def action_open_selected(self) -> None:
        """Apre come file il testo selezionato nell'editor corrente."""
        editor = self._current_editor()
        if not editor:
            return
        text = editor.selectedText().strip()
        if not text:
            return
        path = Path(text)
        # Se percorso relativo, prova relativo al file corrente
        if not path.is_absolute() and editor.file_path:
            path = editor.file_path.parent / path
        if path.exists():
            self.open_files([path])
        else:
            QMessageBox.warning(
                self, self.APP_NAME,
                tr("msg.file_not_found", path=str(path))
            )

    def open_files(self, paths: list[Path]) -> None:
        """Apre una lista di file in nuovi tab (chiamato anche da drag&drop)."""
        from core.file_manager import FileManager
        for path in paths:
            if not path.is_file():
                continue
            # Controlla se il file è già aperto
            existing = self._tab_manager.find_tab_by_path(path)
            if existing is not None:
                self._tab_manager.set_current_index(existing)
                continue
            try:
                content, encoding, line_ending = FileManager.read(path)
                tab = self._tab_manager.new_tab(path=path)
                tab.load_content(content, encoding, line_ending)
                # Notifica plugin: file aperto
                self._notify_plugins_file_opened(path)
                # Se il lexer non è stato rilevato dall'estensione,
                # tenta il rilevamento dal contenuto (shebang, magic numbers)
                if tab.lexer() is None and content:
                    try:
                        from editor.lexers import set_lexer_by_path
                        set_lexer_by_path(tab, path)
                    except Exception:
                        pass
                # Aggiorna statusbar con il linguaggio rilevato
                if hasattr(self, "_statusbar"):
                    self._statusbar._update_lang(tab)
            except Exception as e:
                QMessageBox.critical(
                    self, self.APP_NAME,
                    tr("msg.file_read_error", path=str(path), error=str(e))
                )

    def action_save(self) -> bool:
        editor = self._current_editor()
        if not editor:
            return False
            
        # --- SE IL FILE È FTP, SALVA SUL SERVER ---
        if hasattr(editor, "_ftp_remote_path") and editor._ftp_remote_path:
            if hasattr(editor, "_ftp_panel_ref") and editor._ftp_panel_ref:
                editor._ftp_panel_ref.upload_current()
                return True
        # ------------------------------------------

        if editor.file_path is None:
            return self.action_save_as()
        return self._save_editor(editor, editor.file_path)

    def action_save_as(self) -> bool:
        editor = self._current_editor()
        if not editor:
            return False
        default = str(editor.file_path or Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self, tr("action.save_as"), default, "Tutti i file (*)"
        )
        if not path:
            return False
        return self._save_editor(editor, Path(path))

    def action_save_all(self) -> None:
        for editor in self._tab_manager.all_editors():
            if editor.is_modified():
                if editor.file_path:
                    self._save_editor(editor, editor.file_path)
                else:
                    self._tab_manager.set_current_editor(editor)
                    self.action_save_as()

    def _save_editor(self, editor: EditorWidget, path: Path) -> bool:
        from core.file_manager import FileManager
        from PyQt6.QtCore import QTimer
        
        try:
            # 1. Flag di sicurezza: avvisa il sistema che stiamo salvando noi
            editor._is_saving = True
            
            # 2. Rimuovi fisicamente il file dal watcher per "accecarlo" temporaneamente
            if hasattr(editor, "_watcher"):
                watched = editor._watcher.files()
                if watched:
                    editor._watcher.removePaths(watched)

            # 3. Esegui il salvataggio sul disco
            FileManager.write(path, editor.get_content(), editor.encoding)
            editor.file_path = path

            # 4. Aggiorna lo stato dell'editor
            editor.mark_saved()
            self._on_tab_modified(editor, False)
            self._update_recent(path)
            self._notify_plugins_file_saved(path)

            # 5. Riattiva il watcher in modo sicuro dopo un ritardo maggiore
            if hasattr(editor, "_watcher"):
                def restore_watcher():
                    # Ri-aggiunge il percorso al controllo
                    if str(path) not in editor._watcher.files():
                        editor._watcher.addPath(str(path))
                    # Abbassa la bandiera di sicurezza
                    editor._is_saving = False
           
                # 1000 ms (1 secondo) dà al SO tutto il tempo di smaltire gli eventi file pendenti
                QTimer.singleShot(1000, restore_watcher)
            else:
                editor._is_saving = False
                
            return True
            
        except Exception as e:
            editor._is_saving = False
            QMessageBox.critical(
                self, self.APP_NAME,
                tr("msg.file_write_error", path=str(path), error=str(e))
            )
            return False

    def action_reload(self) -> None:
        editor = self._current_editor()
        if not editor or not editor.file_path:
            return
        if editor.is_modified():
            reply = QMessageBox.question(
                self, self.APP_NAME,
                tr("msg.file_changed_reload", name=editor.file_path.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.open_files([editor.file_path])

    def action_file_properties(self) -> None:
        from ui.file_properties import FilePropertiesDialog
        editor = self._current_editor()
        if editor:
            dlg = FilePropertiesDialog(editor, self)
            dlg.exec()

    def action_page_setup(self) -> None:
        dlg = QPageSetupDialog(self._printer, self)
        dlg.exec()

    def action_print(self) -> None:
        from PyQt6.QtPrintSupport import QPrintDialog
        dlg = QPrintDialog(self._printer, self)
        if dlg.exec() == QPrintDialog.DialogCode.Accepted:
            self._do_print(self._printer)

    def action_print_preview(self) -> None:
        dlg = QPrintPreviewDialog(self._printer, self)
        dlg.paintRequested.connect(self._do_print)
        
        # Forza una dimensione ampia (es. 1000x800) in modo che il window manager non la schiacci
        dlg.resize(1000, 800)
        
        dlg.exec()

    def _do_print(self, printer: QPrinter) -> None:
        editor = self._current_editor()
        if editor:
            editor.print(printer)

    def action_export_pdf(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        default = str(editor.file_path.with_suffix(".pdf")
                      if editor.file_path else Path.home() / "documento.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("action.export_pdf"), default,
            "PDF (*.pdf)"
        )
        if not path:
            return
        self._printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        self._printer.setOutputFileName(path)
        editor.print(self._printer)
        self._printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)

    def action_close(self) -> None:
        self._tab_manager.close_current_tab()

    def action_close_others(self) -> None:
        self._tab_manager.close_other_tabs()

    def action_close_all(self) -> None:
        self._tab_manager.close_all_tabs()

    # ── Azioni Modifica ───────────────────────────────────────────────────────

    def action_copy_path(self) -> None:
        editor = self._current_editor()
        if editor and editor.file_path:
            QApplication.clipboard().setText(str(editor.file_path))

    def action_copy_filename(self) -> None:
        editor = self._current_editor()
        if editor and editor.file_path:
            QApplication.clipboard().setText(editor.file_path.name)

    def action_join_lines(self) -> None:
        from core.text_tools import join_lines
        self._apply_text_op(join_lines)

    def action_line_break(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.insert("\n")

    def action_wrap_lines(self) -> None:
        width, ok = QInputDialog.getInt(
            self, tr("action.wrap_lines"), "Larghezza colonne:", 80, 20, 500
        )
        if ok:
            from core.text_tools import wrap_lines
            self._apply_text_op(lambda t: wrap_lines(t, width))

    def action_uppercase(self) -> None:
        self._apply_selection_op(str.upper)

    def action_lowercase(self) -> None:
        self._apply_selection_op(str.lower)

    def action_titlecase(self) -> None:
        self._apply_selection_op(str.title)

    def action_invert_case(self) -> None:
        self._apply_selection_op(str.swapcase)

    def action_toggle_comment(self) -> None:
        from core.text_tools import toggle_comment
        editor = self._current_editor()
        if editor:
            toggle_comment(editor)

    def action_comment_lines(self) -> None:
        from core.text_tools import comment_lines
        editor = self._current_editor()
        if editor:
            comment_lines(editor, uncomment=False)

    def action_uncomment_lines(self) -> None:
        from core.text_tools import comment_lines
        editor = self._current_editor()
        if editor:
            comment_lines(editor, uncomment=True)

    def action_indent(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.indent(editor.getCursorPosition()[0])

    def action_unindent(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.unindent(editor.getCursorPosition()[0])

    def action_indent_smart(self) -> None:
        pass  # implementato in text_tools.py

    def action_trim_trailing(self) -> None:
        from core.text_tools import trim_trailing_whitespace
        self._apply_text_op(trim_trailing_whitespace)

    def action_tabs_to_spaces(self) -> None:
        editor = self._current_editor()
        if editor:
            from core.text_tools import tabs_to_spaces
            self._apply_text_op(
                lambda t: tabs_to_spaces(t, editor.tabWidth())
            )

    def action_spaces_to_tabs(self) -> None:
        editor = self._current_editor()
        if editor:
            width, ok = QInputDialog.getInt(
                self, tr("action.spaces_to_tabs"),
                "Dimensione tab:", editor.tabWidth(), 1, 32
            )
            if ok:
                from core.text_tools import spaces_to_tabs
                self._apply_text_op(
                    lambda t: spaces_to_tabs(t, width)
                )

    def action_insert_date(self) -> None:
        from datetime import datetime
        from core.platform import get_config_dir
        # Formato configurabile — default ISO
        fmt = "%Y-%m-%d %H:%M:%S"
        editor = self._current_editor()
        if editor:
            editor.insert(datetime.now().strftime(fmt))

    def action_word_count(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        info = editor.get_selected_text_info()
        if not info["text"]:
            # Conta tutto il documento
            text = editor.text()
            info = {
                "chars": len(text),
                "words": len(text.split()),
                "lines": editor.lines(),
            }
        QMessageBox.information(
            self, tr("action.word_count"),
            f"{tr('label.lines_total')}: {info.get('lines', editor.lines())}\n"
            f"{tr('label.words')}: {info['words']}\n"
            f"{tr('label.chars')}: {info['chars']}"
        )

    def action_preferences(self) -> None:
        from ui.preferences import PreferencesDialog
        dlg = PreferencesDialog(self)
        dlg.exec()
        self._apply_autobackup_settings()

    # ── Azioni Cerca ──────────────────────────────────────────────────────────

    def action_find(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.show_find(self)

    def action_find_next(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.find_next(self)

    def action_find_prev(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.find_prev(self)

    def action_replace(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.show_replace(self)

    def action_find_in_files(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.show_find_in_files(self)

    def action_find_in_all_docs(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.show_find_all_docs(self)

    def action_replace_in_all_docs(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.show_replace_all_docs(self)

    def action_go_to_line(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        max_line = editor.lines()
        line, ok = QInputDialog.getInt(
            self, tr("action.go_to_line"),
            tr("msg.go_to_line_prompt", max=max_line),
            editor.get_cursor_position_1based()[0], 1, max_line
        )
        if ok:
            editor.go_to_line(line)

    def action_go_to_matching(self) -> None:
        editor = self._current_editor()
        if editor:
            pos = editor.SendScintilla(editor.SCI_GETCURRENTPOS)
            match_pos = editor.SendScintilla(editor.SCI_BRACEMATCH, pos, 0)
            if match_pos == -1:
                # Prova anche il carattere precedente
                if pos > 0:
                    match_pos = editor.SendScintilla(editor.SCI_BRACEMATCH, pos - 1, 0)
            if match_pos != -1:
                editor.SendScintilla(editor.SCI_SETCURRENTPOS, match_pos)
                editor.SendScintilla(editor.SCI_SETSEL, match_pos, match_pos)
                line = editor.SendScintilla(editor.SCI_LINEFROMPOSITION, match_pos)
                editor.ensureLineVisible(line)
            else:
                self.statusBar().showMessage("Nessuna parentesi corrispondente trovata", 3000)

    def action_mark_all(self) -> None:
        from ui.find_replace import FindReplaceDialog
        FindReplaceDialog.mark_all(self)

    def action_remove_markers(self) -> None:
        editor = self._current_editor()
        if editor:
            for i in range(5):
                editor.clear_indicator(i)

    def action_remove_error_markers(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.markerDeleteAll(-1)

    def action_regex_tester(self) -> None:
        from ui.regex_tester import RegexTesterDialog
        dlg = RegexTesterDialog(self)
        dlg.show()

    # ── Azioni Visualizza ─────────────────────────────────────────────────────

    def _toggle_toolbar(self, checked: bool) -> None:
        self._toolbar.setVisible(checked)
        from config.settings import Settings
        Settings.instance().set("view/toolbar", checked)

    def _toggle_statusbar(self, checked: bool) -> None:
        self._statusbar.setVisible(checked)
        from config.settings import Settings
        Settings.instance().set("view/statusbar", checked)

    def _toggle_line_numbers(self, checked: bool) -> None:
        for ed in self._tab_manager.all_editors():
            ed.set_show_line_numbers(checked)
        from config.settings import Settings
        Settings.instance().set("editor/show_line_numbers", checked)

    def _toggle_fold_margin(self, checked: bool) -> None:
        from editor.editor_widget import MARGIN_FOLD
        for ed in self._tab_manager.all_editors():
            ed.setMarginWidth(MARGIN_FOLD, 14 if checked else 0)
        from config.settings import Settings
        Settings.instance().set("editor/show_fold_margin", checked)

    def _toggle_whitespace(self, checked: bool) -> None:
        for ed in self._tab_manager.all_editors():
            ed.set_show_whitespace(checked)
        from config.settings import Settings
        Settings.instance().set("editor/show_whitespace", checked)

    def _toggle_eol(self, checked: bool) -> None:
        for ed in self._tab_manager.all_editors():
            ed.set_show_eol(checked)
        from config.settings import Settings
        Settings.instance().set("editor/show_eol", checked)

    def _toggle_word_wrap(self, checked: bool) -> None:
        for ed in self._tab_manager.all_editors():
            ed.set_word_wrap(checked)
        from config.settings import Settings
        Settings.instance().set("editor/word_wrap", checked)

    def _toggle_minimap(self, checked: bool) -> None:
        """Attiva/disattiva la minimap per tutti i tab."""
        self._tab_manager.toggle_minimap(checked)

    def _action_minimap_side(self) -> None:
        """Sposta la minimap a sinistra o destra dell'editor."""
        from config.settings import Settings
        self._tab_manager.toggle_minimap_side()
        side = Settings.instance().get("editor/minimap_side", "right")
        side_label = tr("label.left") if side == "left" else tr("label.right")
        self.statusBar().showMessage(
            f"🗺  Minimap spostata a {side_label}", 3000
        )

    def _toggle_build_panel(self, checked: bool) -> None:
        """Mostra/nasconde il pannello build."""
        if checked:
            self._build_dock.show()
        else:
            self._build_dock.hide()

    def _toggle_file_browser(self, checked: bool) -> None:
        """Mostra/nasconde il pannello File Browser."""
        if checked:
            self._file_browser_dock.show()
        else:
            self._file_browser_dock.hide()

    def _toggle_project_manager(self, checked: bool) -> None:
        if checked:
            self._project_dock.show()
        else:
            self._project_dock.hide()

    def _on_build_dock_visibility_changed(self, visible: bool) -> None:
        """Sincronizza lo stato dell'azione nel menu con la visibilità del dock."""
        if "view_build_panel" in self._actions:
            self._actions["view_build_panel"].blockSignals(True)
            self._actions["view_build_panel"].setChecked(visible)
            self._actions["view_build_panel"].blockSignals(False)





    def _toggle_preview(self, checked: bool) -> None:
        """Mostra/nasconde il pannello anteprima come dock spostabile."""
        if checked:
            self._preview_dock.show()
            # Collega l'editor corrente alla preview
            editor = self._current_editor()
            if editor:
                self._preview_panel_dock.set_editor(editor)
        else:
            self._preview_dock.hide()
        self.statusBar().showMessage(
            "Anteprima attivata" if checked else "Anteprima disattivata", 2000
        )

    def _on_preview_dock_visibility(self, visible: bool) -> None:
        """Quando il dock preview diventa visibile, collega l'editor corrente."""
        if visible:
            editor = self._current_editor()
            if editor:
                self._preview_panel_dock.set_editor(editor)
            # Sincronizza il checkmark nel menu
            act = self._actions.get("preview_toggle")
            if act:
                act.blockSignals(True)
                act.setChecked(True)
                act.blockSignals(False)
        else:
            act = self._actions.get("preview_toggle")
            if act:
                act.blockSignals(True)
                act.setChecked(False)
                act.blockSignals(False)

    def _toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _toggle_distraction_free(self, checked: bool) -> None:
        if checked:
            self._df_toolbar_visible  = self._toolbar.isVisible()
            self._df_statusbar_visible = self._statusbar.isVisible()
            self._df_menubar_visible  = self.menuBar().isVisible()
            self._df_docks_visible: list = []
            for dock in self.findChildren(QDockWidget):
                self._df_docks_visible.append((dock, dock.isVisible()))
                dock.hide()
            self._toolbar.hide()
            self._statusbar.hide()
            self.menuBar().hide()
            self.showFullScreen()
            self._show_df_exit_button()
        else:
            self._hide_df_exit_button()
            self.showNormal()
            self.menuBar().setVisible(getattr(self, "_df_menubar_visible", True))
            self._toolbar.setVisible(getattr(self, "_df_toolbar_visible", True))
            self._statusbar.setVisible(getattr(self, "_df_statusbar_visible", True))
            for dock, was_visible in getattr(self, "_df_docks_visible", []):
                dock.setVisible(was_visible)

    def _show_df_exit_button(self) -> None:
        if not hasattr(self, "_df_exit_btn"):
            btn = QPushButton("✕  Esci (Esc)", self)
            btn.setObjectName("df_exit_btn")
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(60,60,60,200); color: #ccc;
                    border: 1px solid #555; border-radius: 4px;
                    padding: 4px 10px; font-size: 12px;
                }
                QPushButton:hover { background: rgba(100,60,60,220); color: #fff; }
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._exit_distraction_free)
            self._df_exit_btn = btn
        self._df_exit_btn.adjustSize()
        self._df_exit_btn.move(self.width() - self._df_exit_btn.width() - 12, 12)
        self._df_exit_btn.raise_()
        self._df_exit_btn.show()
        # QShortcut con WindowShortcut cattura Escape anche quando l'editor ha il focus
        if not hasattr(self, "_df_esc_shortcut"):
            sc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(self._exit_distraction_free)
            self._df_esc_shortcut = sc
        self._df_esc_shortcut.setEnabled(True)

    def _hide_df_exit_button(self) -> None:
        if hasattr(self, "_df_exit_btn"):
            self._df_exit_btn.hide()
        if hasattr(self, "_df_esc_shortcut"):
            self._df_esc_shortcut.setEnabled(False)

    def _exit_distraction_free(self) -> None:
        act = self._actions.get("distraction_free")
        if act and act.isChecked():
            act.setChecked(False)
            self._toggle_distraction_free(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_df_exit_btn") and self._df_exit_btn.isVisible():
            self._df_exit_btn.move(self.width() - self._df_exit_btn.width() - 12, 12)

    def keyPressEvent(self, event) -> None:
        act = self._actions.get("distraction_free")
        if act and act.isChecked() and event.key() == Qt.Key.Key_Escape:
            self._exit_distraction_free()
            return
        super().keyPressEvent(event)

    def _toggle_plain_text_mode(self, checked: bool) -> None:
        editor = self._current_editor()
        if editor:
            editor.set_plain_text_mode(checked)

    def action_zoom_in(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.zoom_in()

    def action_zoom_out(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.zoom_out()

    def action_zoom_reset(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.zoom_reset()

    # ── Azioni Documento ──────────────────────────────────────────────────────

    def _toggle_auto_indent(self, checked: bool) -> None:
        editor = self._current_editor()
        if editor:
            editor.setAutoIndent(checked)

    def _toggle_auto_indent_paste(self, checked: bool) -> None:
        for ed in self._tab_manager.all_editors():
            if hasattr(ed, "set_auto_indent_paste"):
                ed.set_auto_indent_paste(checked)
        from config.settings import Settings
        Settings.instance().set("editor/auto_indent_paste", checked)

    def _toggle_read_only(self, checked: bool) -> None:
        editor = self._current_editor()
        if editor:
            editor.set_read_only(checked)

    def _toggle_write_bom(self, checked: bool) -> None:
        editor = self._current_editor()
        if editor:
            editor._write_bom = checked  # letto da file_manager al salvataggio

    def _set_indent_type(self, use_spaces: bool) -> None:
        editor = self._current_editor()
        if editor:
            editor.set_use_tabs(not use_spaces)

    def action_set_indent_width(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        width, ok = QInputDialog.getInt(
            self, tr("action.indent_width"),
            tr("label.tab_size") + ":",
            editor.tabWidth(), 1, 32
        )
        if ok:
            editor.set_tab_width(width)

    def action_set_language(self, lang: str) -> None:
        from editor.lexers import set_lexer_by_name
        editor = self._current_editor()
        if not editor:
            return
        set_lexer_by_name(editor, lang)
        # Aggiorna statusbar e checkmark menu
        if hasattr(self, "_statusbar"):
            self._statusbar._update_lang(editor)
        self._update_file_type_menu(editor)
        self.statusBar().showMessage(f"Linguaggio impostato: {lang}", 3000)

    def action_set_encoding(self, encoding: str) -> None:
        editor = self._current_editor()
        if not editor:
            return
        clean = encoding.split("(")[0].strip()
        editor.set_encoding(clean)
        if hasattr(self, "_statusbar"):
            self._statusbar.set_encoding(clean)
        self._update_file_type_menu(editor)
        self.statusBar().showMessage(f"Codifica impostata: {clean}", 3000)

    def action_set_line_ending(self, le: LineEnding) -> None:
        editor = self._current_editor()
        if not editor:
            return
        editor.convert_line_endings(le)
        if hasattr(self, "_statusbar"):
            self._statusbar.set_line_ending(le.label())
        self._update_file_type_menu(editor)
        self.statusBar().showMessage(f"Fine riga impostata: {le.label()}", 3000)

    def action_clone(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        content  = editor.get_content()
        encoding = editor.encoding
        le       = editor.line_ending
        new_tab  = self._tab_manager.new_tab()
        new_tab.load_content(content, encoding, le)

    def action_fold_all(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.foldAll(True)

    def action_unfold_all(self) -> None:
        editor = self._current_editor()
        if editor:
            editor.foldAll(False)

    # ── Azioni Strumenti ──────────────────────────────────────────────────────

    def action_record_macro(self) -> None:
        from core.macro import MacroManager
        MacroManager.instance().start_recording(self._current_editor())
        self.statusBar().showMessage("⏺  Registrazione macro avviata — premi 'Ferma macro' per terminare", 5000)

    def action_stop_macro(self) -> None:
        from core.macro import MacroManager
        mm = MacroManager.instance()
        count = len(mm._actions) if hasattr(mm, '_actions') else 0
        mm.stop_recording()
        self.statusBar().showMessage(f"⏹  Registrazione macro terminata ({count} azioni registrate)", 5000)

    def action_play_macro(self) -> None:
        from core.macro import MacroManager
        MacroManager.instance().play(self._current_editor())

    def action_save_macro(self) -> None:
        from core.macro import MacroManager
        MacroManager.instance().save_dialog(self)

    def action_load_macro(self) -> None:
        from core.macro import MacroManager
        MacroManager.instance().load_dialog(self)

    def action_compare(self) -> None:
        from ui.compare import CompareDialog
        dlg = CompareDialog(self)
        dlg.exec()

    def action_color_picker(self) -> None:
        from ui.color_translator import ColorTranslatorDialog
        dlg = ColorTranslatorDialog(self)
        dlg.exec()

    def action_lorem_ipsum(self) -> None:
        from ui.lorem_ipsum import LoremIpsumDialog
        dlg = LoremIpsumDialog(self)
        dlg.exec()

    def action_compile(self) -> None:
        self._build_dock.show()
        from core.build_manager import BuildManager
        BuildManager.instance().run("compile", self._current_editor())

    def action_run(self) -> None:
        self._build_dock.show()
        from core.build_manager import BuildManager
        BuildManager.instance().run("run", self._current_editor())

    def action_build(self) -> None:
        self._build_dock.show()
        from core.build_manager import BuildManager
        BuildManager.instance().run("build", self._current_editor())

    def action_stop_build(self) -> None:
        from core.build_manager import BuildManager
        BuildManager.instance().stop()

    def action_build_profiles(self) -> None:
        from ui.build_panel import BuildProfilesDialog
        dlg = BuildProfilesDialog(self)
        dlg.exec()

    def action_keybinding_editor(self) -> None:
        from ui.keybinding import KeyBindingDialog
        dlg = KeyBindingDialog(self._actions, self)
        dlg.exec()

    def action_reload_config(self) -> None:
        from config.settings import Settings
        Settings.instance().reload()
        self._apply_autobackup_settings()

    def action_plugin_manager(self) -> None:
        from plugins.plugin_manager import PluginManagerDialog
        dlg = PluginManagerDialog(self)
        dlg.exec()

    def action_about(self) -> None:
        from PyQt6.QtWidgets import QMessageBox, QLabel
        from PyQt6.QtCore import Qt

        # Creiamo l'istanza del messaggio
        msg = QMessageBox(self)
        msg.setWindowTitle(tr("action.about"))
        
        # Inseriamo il tuo HTML originale
        content = (
            f"<h2>NotePadPQ {self.APP_VERSION}</h2>"
            "<p>Editor di testo avanzato multi-linguaggio.</p>"
            "<hr>"
            "<p><b>Sviluppato da:</b> Andres Zanzani<br>"
            "<b>Contatto:</b> <a href='mailto:azanzani@gmail.com'>azanzani@gmail.com</a></p>"
            "<p><b>Supporta il progetto:</b><br>"
            "Dona via PayPal a <a href='https://paypal.me/azanzani'>azanzani@gmail.com</a></p>"
            "<hr>"
            f"<small>Python · PyQt6 · QScintilla</small>"
        )
        
        msg.setText(content)
        # Usiamo l'icona informativa standard (simile a .about)
        msg.setIcon(QMessageBox.Icon.Information)

        # --- LOGICA SEGRETA: Triplo click sulla scritta NotePadPQ ---
        for label in msg.findChildren(QLabel):
            if "NotePadPQ" in label.text():
                # Cambiamo il cursore per dare un indizio che "c'è qualcosa"
                label.setCursor(Qt.CursorShape.PointingHandCursor)
                # Installiamo il filtro (assicurati che TripleClickFilter sia definito nel file)
                self._about_arc_filter = TripleClickFilter(self, self._launch_arcade)
                label.installEventFilter(self._about_arc_filter)
        # ------------------------------------------------------------

        msg.exec()

    def action_check_updates(self) -> None:
        import urllib.request
        import json
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        # URL delle API di GitHub per l'ultima release del tuo progetto
        api_url = "https://api.github.com/repos/buzzqw/NotePadPQ/releases/latest"
        
        try:
            # Effettuiamo la richiesta (mettiamo un timeout breve per non bloccare l'editor)
            req = urllib.request.Request(api_url, headers={"User-Agent": "NotePadPQ"})
            with urllib.request.urlopen(req, timeout=5.0) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Otteniamo il tag della versione su GitHub (es. "v0.2.1") e rimuoviamo la "v"
                latest_version = data.get("tag_name", "").lstrip("v")
                release_url = data.get("html_url", "https://github.com/buzzqw/NotePadPQ/releases")
                
                current_version = self.APP_VERSION
                
                # Confronto basilare tra stringhe di versione
                if latest_version > current_version:
                    reply = QMessageBox.question(
                        self, tr("action.check_updates"),
                        f"È disponibile una nuova versione di NotePadPQ!\n\n"
                        f"Versione corrente: {current_version}\n"
                        f"Nuova versione: {latest_version}\n\n"
                        f"Vuoi aprire la pagina per scaricare l'aggiornamento?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        QDesktopServices.openUrl(QUrl(release_url))
                else:
                    QMessageBox.information(
                        self, tr("action.check_updates"),
                        f"Stai usando l'ultima versione disponibile ({current_version}).\nNessun aggiornamento necessario."
                    )
        except Exception as e:
            QMessageBox.warning(
                self, "Errore di Rete",
                f"Impossibile controllare gli aggiornamenti al momento.\nVerifica la tua connessione o riprova più tardi.\n\nDettaglio: {str(e)}"
            )

    def action_donate(self) -> None:
        """Apre la pagina di donazione PayPal nel browser."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        url = QUrl("https://www.paypal.com/cgi-bin/webscr?cmd=_donations"
                   "&business=azanzani@gmail.com&item_name=Support+NotePadPQ+Project")
        QDesktopServices.openUrl(url)

    # ── Azioni Bookmark ───────────────────────────────────────────────────────

    def action_toggle_bookmark(self) -> None:
        editor = self._current_editor()
        if editor:
            from ui.bookmarks import toggle_bookmark
            toggle_bookmark(editor)

    def action_next_bookmark(self) -> None:
        editor = self._current_editor()
        if editor:
            from ui.bookmarks import next_bookmark
            next_bookmark(editor)

    def action_prev_bookmark(self) -> None:
        editor = self._current_editor()
        if editor:
            from ui.bookmarks import prev_bookmark
            prev_bookmark(editor)

    def action_clear_bookmarks(self) -> None:
        editor = self._current_editor()
        if editor:
            from ui.bookmarks import clear_all_bookmarks
            clear_all_bookmarks(editor)

    # ── Azioni Macro N volte ──────────────────────────────────────────────────

    def action_play_macro_n(self) -> None:
        from core.macro import MacroManager
        mm = MacroManager.instance()
        if not mm.has_macro():
            QMessageBox.information(self, self.APP_NAME, "Nessuna macro registrata.")
            return
        n, ok = QInputDialog.getInt(
            self, "Esegui macro N volte", "Numero di ripetizioni:", 1, 1, 9999
        )
        if ok:
            mm.play_n_times(self._current_editor(), n)

    # ── Azioni Sessioni nominate ──────────────────────────────────────────────

    def action_named_sessions(self) -> None:
        from ui.named_sessions import NamedSessionsDialog
        dlg = NamedSessionsDialog(self)
        dlg.exec()

    # ── Azioni Convertitore numeri ────────────────────────────────────────────

    def action_number_converter(self) -> None:
        from ui.number_converter import NumberConverterDialog
        editor = self._current_editor()
        initial = editor.selectedText().strip() if editor else ""
        dlg = NumberConverterDialog(self, initial_text=initial)
        dlg.exec()

    def action_column_stats(self) -> None:
        from ui.column_stats import ColumnStatsDialog
        editor = self._current_editor()
        if editor:
            dlg = ColumnStatsDialog(editor, self)
            dlg.exec()

    # ── Utility testo ─────────────────────────────────────────────────────────

    def _apply_selection_op(self, op) -> None:
        """Applica un'operazione stringa al testo selezionato o all'intera riga."""
        editor = self._current_editor()
        if not editor:
            return
        if editor.hasSelectedText():
            editor.replaceSelectedText(op(editor.selectedText()))
        else:
            line, col = editor.getCursorPosition()
            text = editor.text(line)
            editor.setSelection(line, 0, line, len(text))
            editor.replaceSelectedText(op(text))

    def _apply_text_op(self, op) -> None:
        """Applica un'operazione sull'intero testo del documento corrente.
        Usa beginUndoAction/endUndoAction per preservare la stack undo di Scintilla.
        """
        editor = self._current_editor()
        if not editor:
            return
        cursor   = editor.getCursorPosition()
        new_text = op(editor.text())
        editor.beginUndoAction()
        editor.selectAll()
        editor.replaceSelectedText(new_text)
        editor.endUndoAction()
        line = min(cursor[0], max(0, editor.lines() - 1))
        editor.setCursorPosition(line, cursor[1])

    # ── Auto-save su perdita focus ────────────────────────────────────────────

    def _on_application_state_changed(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationInactive:
            from config.settings import Settings
            if Settings.instance().get("file/autosave_on_focus_loss", False):
                for editor in self._tab_manager.all_editors():
                    if editor.is_modified() and editor.file_path:
                        try:
                            self._save_editor(editor, editor.file_path)
                        except Exception:
                            pass

    # ── Frequenza parole ─────────────────────────────────────────────────────

    def action_word_frequency(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        text = editor.selectedText() or editor.text()
        from collections import Counter
        import re
        words = re.findall(r"\b[a-zA-ZàèìòùéÀÈÌÒÙÉ']+\b", text, re.UNICODE)
        if not words:
            QMessageBox.information(self, "Frequenza parole", "Nessuna parola trovata.")
            return
        freq = Counter(w.lower() for w in words)
        top = freq.most_common(50)

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Frequenza parole")
        dlg.resize(360, 500)
        vl = QVBoxLayout(dlg)
        vl.addWidget(QLabel(f"Parole totali: {len(words)}  —  Uniche: {len(freq)}"))
        tbl = QTableWidget(len(top), 2)
        tbl.setHorizontalHeaderLabels(["Parola", "Occorrenze"])
        tbl.horizontalHeader().setStretchLastSection(True)
        for i, (word, count) in enumerate(top):
            tbl.setItem(i, 0, QTableWidgetItem(word))
            tbl.setItem(i, 1, QTableWidgetItem(str(count)))
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.sortItems(1, Qt.SortOrder.DescendingOrder)
        vl.addWidget(tbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        vl.addWidget(bb)
        dlg.exec()

    # ── Ordina righe (dialog) ────────────────────────────────────────────────

    def action_sort_lines_dialog(self) -> None:
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QRadioButton, QDialogButtonBox, QGroupBox
        import core.line_operations as lo

        editor = self._current_editor()
        if not editor:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Ordina righe")
        vl = QVBoxLayout(dlg)

        grp = QGroupBox("Criterio")
        gl = QVBoxLayout(grp)
        r_asc    = QRadioButton("Alfabetico crescente (A→Z)")
        r_desc   = QRadioButton("Alfabetico decrescente (Z→A)")
        r_len_a  = QRadioButton("Per lunghezza crescente")
        r_len_d  = QRadioButton("Per lunghezza decrescente")
        r_rand   = QRadioButton("Casuale")
        r_asc.setChecked(True)
        for r in [r_asc, r_desc, r_len_a, r_len_d, r_rand]:
            gl.addWidget(r)
        vl.addWidget(grp)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        vl.addWidget(bb)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if r_asc.isChecked():
            lo.apply_sort_asc(editor)
        elif r_desc.isChecked():
            lo.apply_sort_desc(editor)
        elif r_len_a.isChecked():
            lo.apply_sort_by_length(editor)
        elif r_len_d.isChecked():
            lo.apply_sort_by_length_desc(editor)
        elif r_rand.isChecked():
            lo.apply_sort_random(editor)

    # ── File recenti ─────────────────────────────────────────────────────────

    def _update_recent(self, path: Path) -> None:
        try:
            from core.recent_files import RecentFiles
            RecentFiles.instance().add(path)
            self._populate_recent_menu()
        except Exception:
            pass

    def _clear_recent(self) -> None:
        try:
            from core.recent_files import RecentFiles
            RecentFiles.instance().clear()
            self._populate_recent_menu()
        except Exception:
            pass

    # ── Drag & Drop ───────────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile())
                 for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self.open_files(paths)

    # ── Chiusura ──────────────────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        """Controlla modifiche non salvate prima di chiudere."""
        modified = [ed for ed in self._tab_manager.all_editors()
                    if ed.is_modified()]
        if not modified:
            self._save_session()
            event.accept()
            return

        count = len(modified)
        msg = (tr("msg.unsaved_changes_many", count=count)
               if count > 1 else
               tr("msg.unsaved_changes",
                  name=(modified[0].file_path.name
                        if modified[0].file_path
                        else tr("label.untitled"))))

        reply = QMessageBox.question(
            self, self.APP_NAME, msg,
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
        elif reply == QMessageBox.StandardButton.Save:
            self.action_save_all()
            self._save_session()
            event.accept()
        else:
            self._save_session()
            event.accept()

    def _save_session(self) -> None:
        try:
            from core.session import Session
            s = Session.instance()
            s.save(self._tab_manager)
            s.save_ui_state(self)
        except Exception:
            pass

    # ── Split View ────────────────────────────────────────────────────────────

    def _toggle_split_sync(self, checked: bool) -> None:
        """Attiva/disattiva la sincronizzazione cursore tra i pannelli split."""
        if hasattr(self._tab_manager, "set_sync_cursor"):
            self._tab_manager.set_sync_cursor(checked)
        self.statusBar().showMessage(
            "Sincronizzazione cursore split: " +
            ("attiva" if checked else "disattiva"), 3000
        )

    # ── Notifiche verso il PluginManager ─────────────────────────────────────
    # Tutti i metodi usano try/except: un plugin bacato non deve mai
    # crashare l'applicazione principale.

    def _notify_plugins_editor_changed(self, editor) -> None:
        """Chiamato quando l'utente cambia tab attivo."""
        try:
            from plugins.plugin_manager import PluginManager
            PluginManager.instance().notify_editor_changed(editor)
        except Exception:
            pass

    def _notify_plugins_file_saved(self, path: Path) -> None:
        """Chiamato dopo ogni salvataggio riuscito."""
        try:
            from plugins.plugin_manager import PluginManager
            PluginManager.instance().notify_file_saved(path)
        except Exception:
            pass

    def _notify_plugins_file_opened(self, path: Path) -> None:
        """Chiamato quando un file viene aperto in un nuovo tab."""
        try:
            from plugins.plugin_manager import PluginManager
            PluginManager.instance().notify_file_opened(path)
        except Exception:
            pass


    # ── Multi-cursore ─────────────────────────────────────────────────────────

    def _mc_select_next(self) -> None:
        ed = self._current_editor()
        mc = getattr(ed, "_multicursor", None)
        if mc:
            mc.select_next_occurrence()

    def _mc_select_all(self) -> None:
        ed = self._current_editor()
        mc = getattr(ed, "_multicursor", None)
        if mc:
            mc.select_all_occurrences()

    def _mc_add_above(self) -> None:
        ed = self._current_editor()
        mc = getattr(ed, "_multicursor", None)
        if mc:
            mc.add_cursor_above()

    def _mc_add_below(self) -> None:
        ed = self._current_editor()
        mc = getattr(ed, "_multicursor", None)
        if mc:
            mc.add_cursor_below()

    def _mc_insert_numbers(self) -> None:
        ed = self._current_editor()
        mc = getattr(ed, "_multicursor", None)
        if mc:
            mc.insert_incremental_numbers()

    def _mc_clear(self) -> None:
        ed = self._current_editor()
        mc = getattr(ed, "_multicursor", None)
        if mc:
            mc.clear_extra_cursors()

    # ── Auto-chiusura parentesi ───────────────────────────────────────────────

    def _toggle_autoclose(self, checked: bool) -> None:
        for ed in self._tab_manager.all_editors():
            if hasattr(ed, "set_autoclose_enabled"):
                ed.set_autoclose_enabled(checked)
        from config.settings import Settings
        Settings.instance().set("editor/autoclose", checked)
        self.statusBar().showMessage(
            "Auto-chiusura parentesi: " + ("attiva" if checked else "disattiva"), 3000
        )

    # ── Smart Highlight e Mark colori ─────────────────────────────────────────

    def _mark_color(self, color_index: int) -> None:
        if hasattr(self, "_mark_manager"):
            self._mark_manager.mark(color_index)

    def _mark_clear_all(self) -> None:
        if hasattr(self, "_mark_manager"):
            self._mark_manager.clear_all()

    # ── Ricerca incrementale ──────────────────────────────────────────────────

    def _toggle_incremental_search(self, checked: bool) -> None:
        if hasattr(self, "_inc_search"):
            if checked:
                self._inc_search.show_bar()
            else:
                self._inc_search.hide_bar()

    # ── Function List ─────────────────────────────────────────────────────────

    def _toggle_function_list(self, checked: bool) -> None:
        if hasattr(self, "_function_list_dock"):
            self._function_list_dock.setVisible(checked)
            
    def _on_file_changed_externally(self, editor: EditorWidget) -> None:
        """Gestisce la modifica esterna con ricaricamento reale e confronto."""
        if not editor or not editor.file_path:
            return

        # --- FIX: Ignora l'evento se siamo noi a scriverlo! ---
        if getattr(editor, "_is_saving", False):
            return

        editor._watcher.blockSignals(True)
        
        msg = tr("msg.file_changed_on_disk", name=editor.file_path.name)
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.APP_NAME)
        msg_box.setText(msg)
        msg_box.setIcon(QMessageBox.Icon.Question)
        
        # Pulsanti
        btn_reload = msg_box.addButton(tr("action.reload"), QMessageBox.ButtonRole.ActionRole)
        btn_compare = msg_box.addButton(tr("action.compare_changes"), QMessageBox.ButtonRole.ActionRole)
        btn_overwrite = msg_box.addButton(tr("action.overwrite"), QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton(tr("button.cancel"), QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()
        clicked = msg_box.clickedButton()

        if clicked == btn_reload:
            # FIX: Ricarica reale del contenuto dal disco
            from core.file_manager import FileManager
            try:
                content, enc, le = FileManager.read(editor.file_path)
                editor.load_content(content, enc, le)
                editor.setModified(False) # Toglie l'asterisco
                self.statusBar().showMessage(f"🔄 File ricaricato: {editor.file_path.name}", 3000)
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile ricaricare: {e}")

        elif clicked == btn_compare:
            # Funzione di confronto: salva la versione corrente in un file temp e confronta
            import tempfile
            from pathlib import Path
            
            # 1. Creiamo un file temporaneo con quello che hai SCRITTO TU (versione in memoria)
            # Usiamo delete=False perché dobbiamo passarlo a un'altra finestra
            with tempfile.NamedTemporaryFile(mode='w', delete=False, 
                                             suffix=editor.file_path.suffix, 
                                             encoding=editor.encoding) as tmp:
                tmp.write(editor.get_content())
                tmp_path = Path(tmp.name)
            
            from ui.compare import CompareDialog
            dlg = CompareDialog(self)
            
            # 2. Diciamo al dialog di caricare i file e avviare il confronto subito
            # File 1: Quello sul DISCO (la versione dell'altro programma)
            # File 2: Quello TEMPORANEO (la tua versione di NotePadPQ)
            if hasattr(dlg, "set_files"):
                dlg.set_files(editor.file_path, tmp_path)
            
            dlg.exec()
            
            # 3. Una volta chiusa la finestra, cancelliamo il file temporaneo
            try:
                tmp_path.unlink()
            except:
                pass

        elif clicked == btn_overwrite:
            # Vince NotePadPQ e scrive sul disco
            self._save_editor(editor, editor.file_path)

        # Riattiva il monitoraggio
        if editor.file_path.exists():
            editor._watcher.addPath(str(editor.file_path))
        editor._watcher.blockSignals(False)
        
    # ── Orologio in alto a destra ─────────────────────────────────────────────

    # ── Orologio in alto a destra ─────────────────────────────────────────────

    def _setup_clock(self):
        self._clock_label = QLabel()
        self._clock_label.setStyleSheet("padding-right: 10px; padding-left: 10px; font-size: 12px; color: #555;")
        self.menuBar().setCornerWidget(self._clock_label, Qt.Corner.TopRightCorner)

        # --- AGGIUNTA EASTER EGG ---
        self._clock_arc_filter = TripleClickFilter(self, self._launch_arcade)
        self._clock_label.installEventFilter(self._clock_arc_filter)
        # ---------------------------

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    def _launch_arcade(self):
        """Apre la finestra segreta dell'Arcade."""
        try:
            from ui.arcade import ArcadeDialog
            dlg = ArcadeDialog(self)
            dlg.exec()
        except Exception as e:
            self.statusBar().showMessage(f"Errore avvio Arcade: {e}", 5000)

    def _update_clock(self):        
        from PyQt6.QtCore import QDateTime, QLocale
        from i18n.i18n import I18n

        # 1. Leggiamo quale lingua stai usando in NotePadPQ in questo momento (es. "it", "en", "es")
        lingua_corrente = I18n.instance().current_language()
        
        # 2. Diciamo a Qt di preparare il "traduttore di date" per quella lingua specifica
        locale = QLocale(lingua_corrente)
        
        # 3. Prendiamo la data e l'ora esatte di questo istante
        adesso = QDateTime.currentDateTime()
        
        # 4. Formattiamo il testo. 
        # Il codice segreto "dddd" dice a Qt di scrivere il nome del giorno per intero tradotto!
        testo = locale.toString(adesso, "yyyy-MM-dd dddd HH:mm")
        
        # 5. In alcune lingue (come francese o spagnolo) i giorni si scrivono in minuscolo (es: "jeudi").
        # Usando .title() forziamo elegantemente la prima lettera in Maiuscolo (diventa "Jeudi").
        self._clock_label.setText(testo.title()) 
        
    def _apply_markup(self, style: str):
        """Applica grassetto, corsivo o barrato in base al linguaggio (MD o LaTeX)."""
        editor = self._current_editor()
        if not editor:
            return

        # 1. Identifichiamo il linguaggio corrente
        from editor.lexers import get_language_name
        lang = get_language_name(editor).lower()
        
        is_md = "markdown" in lang
        is_latex = "latex" in lang or "tex" in lang

        # Se non è né Markdown né LaTeX, non fare nulla
        if not is_md and not is_latex:
            return

        # 2. Definiamo i tag per ogni stile
        # Per il barrato LaTeX usiamo \sout{} (richiede il pacchetto ulem)
        markup_map = {
            "bold":   ("**", "**") if is_md else ("\\textbf{", "}"),
            "italic": ("*", "*")   if is_md else ("\\textit{", "}"),
            "strike": ("~~", "~~") if is_md else ("\\sout{", "}"),
        }

        prefix, suffix = markup_map.get(style, ("", ""))
        
        # 3. Applichiamo la formattazione
        if editor.hasSelectedText():
            # Se c'è testo selezionato, lo avvolgiamo nei tag
            sel_text = editor.selectedText()
            editor.replaceSelectedText(f"{prefix}{sel_text}{suffix}")
        else:
            # Se non c'è selezione, inseriamo i tag e mettiamo il cursore nel mezzo
            line, col = editor.getCursorPosition()
            editor.insert(f"{prefix}{suffix}")
            editor.setCursorPosition(line, col + len(prefix))
        
        editor.setFocus()
    
    def action_wrap_env(self) -> None:
        """Avvolge il testo selezionato in un ambiente LaTeX o tag HTML."""
        editor = self._current_editor()
        if not editor:
            return

        from editor.lexers import get_language_name
        lang = get_language_name(editor).lower()
        
        # Identifica se usare la sintassi LaTeX o HTML
        is_html_md = "html" in lang or "markdown" in lang
        is_tex = not is_html_md # Fallback predefinito a LaTeX per gli altri file

        # Chiede all'utente il nome dell'ambiente
        env_name, ok = QInputDialog.getText(
            self, "Avvolgi in Ambiente",
            "Nome ambiente (es. itemize, center, div):"
        )
        
        if ok and env_name.strip():
            env = env_name.strip()
            
            if editor.hasSelectedText():
                # Se c'è testo selezionato, lo indenta e lo avvolge
                text = editor.selectedText()
                # Aggiunge 4 spazi di indentazione a ogni riga del testo
                indented = "\n".join("    " + line for line in text.split("\n"))
                
                if is_tex:
                    res = f"\\begin{{{env}}}\n{indented}\n\\end{{{env}}}"
                else:
                    res = f"<{env}>\n{indented}\n</{env}>"
                    
                editor.replaceSelectedText(res)
            else:
                # Se non c'è selezione, crea l'ambiente vuoto e mette il cursore in mezzo
                line, col = editor.getCursorPosition()
                if is_tex:
                    editor.insert(f"\\begin{{{env}}}\n    \n\\end{{{env}}}")
                else:
                    editor.insert(f"<{env}>\n    \n</{env}>")
                
                # Posiziona il cursore nella riga vuota indentata
                editor.setCursorPosition(line + 1, 4)
            
            editor.setFocus()
            
    def action_align_table(self) -> None:
        """Allinea automaticamente le colonne di una tabella in LaTeX (&) o Markdown (|)."""
        editor = self._current_editor()
        if not editor or not editor.hasSelectedText():
            self.statusBar().showMessage("⚠️ Seleziona prima le righe della tabella da allineare!", 3000)
            return

        from editor.lexers import get_language_name
        lang = get_language_name(editor).lower()
        
        # Capisce se stiamo lavorando in Markdown o LaTeX
        is_md = "markdown" in lang
        sep = "|" if is_md else "&"

        text = editor.selectedText()
        lines = text.splitlines()
        if not lines:
            return

        # 1. Suddivide le righe nelle loro singole celle
        parsed_rows = []
        for line in lines:
            end_marker = ""
            
            # Preserva la fine riga tipica di LaTeX (\\)
            if sep == "&":
                line_stripped = line.rstrip()
                if line_stripped.endswith(r"\\"):
                    end_marker = r" \\"
                    line = line_stripped[:-2] # Taglia via i due backslash per analizzare la cella nuda
            
            # Spezza la riga e pulisce gli spazi attorno al testo
            cells = [c.strip() for c in line.split(sep)]
            parsed_rows.append((cells, end_marker))

        # 2. Calcola quanto deve essere larga al massimo ogni colonna
        max_cols = max((len(c) for c, _ in parsed_rows), default=0)
        col_widths = [0] * max_cols
        for cells, _ in parsed_rows:
            for i, cell in enumerate(cells):
                col_widths[i] = max(col_widths[i], len(cell))

        # 3. Ricostruisce le righe della tabella aggiungendo gli spazi vuoti necessari
        new_lines = []
        for cells, end_marker in parsed_rows:
            padded_cells = []
            for i, cell in enumerate(cells):
                # Gestione speciale per la riga di divisione del Markdown (es: |---|---|)
                if is_md and set(cell) <= {"-", ":"}:
                    if len(cell) > 0:
                        padded_cells.append(cell.ljust(col_widths[i], "-"))
                    else:
                        padded_cells.append("")
                else:
                    padded_cells.append(cell.ljust(col_widths[i]))
            
            # Ricuce i pezzi mettendo il separatore in mezzo
            joined_line = f" {sep} ".join(padded_cells)
            
            # Pulizia dei bordi esterni (utile specialmente per Markdown)
            joined_line = joined_line.strip()
            
            if end_marker:
                joined_line += end_marker
                
            new_lines.append(joined_line)

        # 4. Sostituisce il pasticcio nell'editor con la tabella perfettamente allineata!
        aligned_text = "\n".join(new_lines)
        editor.replaceSelectedText(aligned_text)
        self.statusBar().showMessage("✨ Tabella allineata con successo!", 3000)

    def _toggle_spellcheck(self, checked: bool) -> None:
        """Attiva o disattiva il controllo ortografico per tutti i tab aperti."""
        from config.settings import Settings
        Settings.instance().set("spellcheck/enabled", checked)
        lang = Settings.instance().get("spellcheck/language", "it")
        for ed in self._tab_manager.all_editors():
            if hasattr(ed, "set_spellcheck_enabled"):
                ed.set_spellcheck_enabled(checked, lang)
        label = tr("label.spell_on") if checked else tr("label.spell_off")
        self.statusBar().showMessage(f"{label} ({lang})", 3000)

    def _set_spell_lang(self, lang: str) -> None:
        """Cambia la lingua del dizionario ortografico."""
        from config.settings import Settings
        Settings.instance().set("spellcheck/language", lang)
        if "spell_check" in self._actions and self._actions["spell_check"].isChecked():
            for ed in self._tab_manager.all_editors():
                if hasattr(ed, "set_spell_language"):
                    ed.set_spell_language(lang)


# ─── Test standalone ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("NotePadPQ")
    app.setOrganizationName("NotePadPQ")

    win = MainWindow()
    win.show()

    # Apri file passati come argomenti CLI
    if len(sys.argv) > 1:
        win.open_files([Path(p) for p in sys.argv[1:]])
    else:
        win._tab_manager.new_tab()

    sys.exit(app.exec())
