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
from core.external_open import open_url as _open_url

# ─── Mappa icone ──────────────────────────────────────────────────────────────
# Mapping azione → nome file SVG Lucide. Aggiungere qui nuove azioni per farle
# comparire nella toolbar e nei menu.

_ICON_MAP: dict[str, str] = {
    # Toolbar
    "new": "file-plus.svg", "open": "folder-open.svg", "save": "save.svg",
    "save_all": "database.svg", "close": "x-square.svg", "find": "search.svg",
    "customize_toolbar": "sliders.svg",
    "replace": "refresh-cw.svg", "undo": "undo.svg", "redo": "redo.svg",
    "compile": "play.svg", "run": "fast-forward.svg", "build": "hammer.svg",
    "stop_build": "square.svg", "preferences": "settings.svg", "about": "info.svg",
    # File
    "save_as": "file-check.svg", "reload": "rotate-cw.svg",
    "open_selected": "external-link.svg", "print": "printer.svg",
    "print_preview": "layout-template.svg", "export_pdf": "file-text.svg",
    "close_others": "x-circle.svg", "close_all": "layers.svg",
    "quit": "log-out.svg", "file_properties": "file-search.svg",
    "diff_vs_saved": "git-compare.svg",
    # Modifica
    "cut": "scissors.svg", "copy": "copy.svg", "paste": "clipboard.svg",
    "delete": "trash-2.svg", "select_all": "check-square.svg",
    "copy_path": "link.svg", "copy_filename": "file.svg",
    "insert_date": "calendar.svg", "word_count": "type.svg",
    "word_frequency": "bar-chart-2.svg", "sort_lines_menu": "arrow-up-down.svg",
    # Testo
    "join_lines": "git-merge.svg", "line_break": "corner-down-left.svg",
    "wrap_lines": "wrap-text.svg",
    "uppercase": "type.svg", "lowercase": "pilcrow.svg",
    "titlecase": "list-ordered.svg", "invert_case": "arrow-left-right.svg",
    "comment_line": "hash.svg", "uncomment_line": "code-2.svg",
    "indent_smart": "sparkles.svg",
    "tabs_to_spaces": "arrow-left-right.svg", "spaces_to_tabs": "outdent.svg",
    "format_document": "file-check.svg",
    # Righe
    "sort_asc": "chevrons-up.svg", "sort_desc": "chevrons-down.svg",
    "sort_by_length_asc": "arrow-up-down.svg", "sort_by_length_desc": "arrow-up-down.svg",
    "sort_random": "refresh-cw.svg",
    "remove_dup_sorted": "copy.svg", "remove_dup_ordered": "layers.svg",
    "remove_unique": "x-circle.svg", "keep_unique": "check-square.svg",
    "remove_empty": "eraser.svg", "remove_whitespace": "pilcrow.svg",
    "remove_every_nth": "list.svg",
    # Formato
    "markup_bold": "bold.svg", "markup_italic": "italic.svg",
    "markup_strike": "strikethrough.svg", "toggle_comment": "hash.svg",
    "indent": "indent.svg", "unindent": "outdent.svg",
    "trim_trailing": "eraser.svg", "align_table": "table-2.svg",
    # Cerca
    "command_palette": "command.svg", "goto_anything": "navigation.svg",
    "find_next": "chevron-down.svg", "find_prev": "chevron-up.svg",
    "find_in_files": "folder-search.svg", "go_to_line": "hash.svg",
    "go_to_matching": "braces.svg", "toggle_bookmark": "bookmark.svg",
    "next_bookmark": "bookmark-plus.svg", "prev_bookmark": "bookmark-minus.svg",
    "clear_bookmarks": "bookmark-x.svg",
    # Visualizza
    "view_toolbar": "layout-template.svg", "view_statusbar": "panel-bottom.svg",
    "view_lang_toolbar": "code-2.svg",
    "view_line_numbers": "list-ordered.svg", "view_whitespace": "pilcrow.svg",
    "view_eol": "corner-down-left.svg", "view_fold_margin": "list.svg",
    "view_minimap": "map.svg", "view_minimap_hover": "eye.svg",
    "view_build_panel": "terminal.svg", "view_file_browser": "folder-tree.svg",
    "view_project_manager": "folder-tree.svg",
    "view_character_panel": "type.svg", "column_editor": "table.svg",
    "function_list": "list-tree.svg", "view_json_xml_panel": "braces.svg",
    "preview_toggle": "eye.svg", "view_zoom_in": "zoom-in.svg",
    "view_zoom_out": "zoom-out.svg", "view_zoom_reset": "maximize-2.svg",
    "distraction_free": "focus.svg", "view_word_wrap": "wrap-text.svg",
    "view_typewriter": "type.svg", "view_plain_text_mode": "file.svg",
    "view_git_gutter": "git-branch.svg", "view_git_blame_inline": "pen.svg",
    "split_move_tab": "arrow-left-right.svg", "split_sync_cursor": "link.svg",
    "unsplit": "maximize-2.svg",
    # Strumenti
    "build_profiles": "sliders.svg", "record_macro": "circle.svg",
    "play_macro": "play-circle.svg", "play_macro_n": "play-circle.svg",
    "stop_macro": "square.svg", "save_macro": "save.svg",
    "load_macro": "folder-open.svg", "named_sessions": "layers.svg",
    "compare_files": "git-compare.svg", "color_picker": "palette.svg",
    "regex_tester": "asterisk.svg", "number_converter": "hash.svg",
    "column_stats": "bar-chart-2.svg", "lorem_ipsum": "align-left.svg",
    "text_converter": "arrow-left-right.svg",
    "keybinding_editor": "keyboard.svg", "open_terminal": "terminal.svg",
    "lsp_goto_def": "code.svg",
    "lsp_refs": "git-merge.svg", "lsp_rename": "pen.svg",
    "lsp_format": "sparkles.svg", "lsp_diag": "alert-triangle.svg",
    # Documento
    "clone_document": "copy.svg", "fold_all": "chevrons-up.svg",
    "unfold_all": "chevrons-down.svg", "remove_markers": "eraser.svg",
    "remove_error_markers": "x-circle.svg", "spell_check": "spell-check.svg",
    "auto_indent": "indent.svg", "auto_indent_paste": "indent.svg",
    "autoclose_toggle": "braces.svg", "indent_width": "sliders.svg",
    "writing_goal_set": "bookmark.svg",
    "read_only": "lock.svg", "write_bom": "file-code.svg",
    "wrap_env": "braces.svg",
    # Plugin / Aiuto
    "plugin_manager": "puzzle.svg", "manual": "book-open.svg",
    "context_help": "help-circle.svg", "about_qt": "info.svg",
    "check_updates": "refresh-cw.svg", "donate": "heart.svg",
    # Language toolbar — Markdown
    "md_h1": "heading-1.svg", "md_h2": "heading-2.svg", "md_h3": "heading-3.svg",
    "md_underline": "underline.svg", "md_code_block": "code-2.svg",
    "md_quote": "quote.svg", "md_ul": "list.svg", "md_task": "list-checks.svg",
    "md_hr": "separator-horizontal.svg", "md_image": "image.svg",
    "md_align_left": "align-left.svg", "md_align_center": "align-center.svg", "md_align_right": "align-right.svg",
    "md_code": "code.svg", "md_link": "link.svg", "md_ol": "list-ordered.svg", "md_table": "table-2.svg",
    "md_export_pdf": "file-pdf.svg", "md_export_html": "file-code.svg",
    "md_structure": "list-tree.svg",
    "latex_align_l": "align-left.svg", "latex_align_c": "align-center.svg", "latex_align_r": "align-right.svg",
    "latex_env": "braces.svg", "latex_begin": "chevron-right.svg", "latex_end": "chevron-left.svg",
    "latex_image": "image.svg",
    # Split View
    "split_vertical": "columns-2.svg", "split_horizontal": "rows-2.svg",
    "split_rotate": "rotate-cw.svg",
    # Plugin icons
    "plugin_ai": "sparkles.svg", "plugin_clipboard": "clipboard.svg",
    "plugin_compare": "git-compare.svg", "plugin_db": "database.svg",
    "plugin_ftp": "server.svg", "plugin_git": "git-branch.svg",
    "plugin_hex": "file-code.svg", "plugin_pdf": "file-text.svg",
    "plugin_richtext": "pen.svg", "plugin_spreadsheet": "table.svg",
    "plugin_encrypt": "lock.svg", "plugin_encrypt_dec": "keyboard.svg",
    "plugin_terminal": "terminal.svg", "plugin_search": "search.svg",
    "plugin_rest": "send.svg",
    # Code Formatter tool actions
    "tool_format_doc":   "sparkles.svg",
    "tool_format_sel":   "file-check.svg",
    "tool_formatter_prefs": "settings.svg",
    # Split view submenu
    "menu_split_view": "columns-2.svg",
}

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
    APP_VERSION = "1.5.7"

    def __init__(self):
        super().__init__()

        # Importazioni locali per evitare dipendenze circolari
        from ui.split_view import SplitViewManager
        from ui.statusbar import StatusBar

        self._tab_manager: SplitViewManager = SplitViewManager(self)
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
        self._setup_language_toolbar()
        self._setup_latex_menu()
        self._setup_connections()
        self._setup_i18n()
        self._setup_autobackup()
        self._setup_autosave()
        self._setup_git_gutter()
        self._setup_lsp()
        self._setup_clock()
        # _setup_logo_corner rimossa: ridondante con l'icona di finestra del WM
        self._setup_writing_goal()
        self.setAcceptDrops(True)
        self._setup_resource_monitor()

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
        # Crea un container con QVBoxLayout che ospiterà:
        #   riga 0 → language toolbar (inserita da LanguageToolbar.install())
        #   riga 1 → tab manager (editor)
        # Questo garantisce che la toolbar linguaggio sia sempre SOTTO
        # la toolbar principale e non sulla stessa riga.
        from PyQt6.QtWidgets import QVBoxLayout
        container = QWidget(self)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._tab_manager)
        self.setCentralWidget(container)

    def _setup_dock_panels(self) -> None:
        """Inizializza i pannelli dockable (build, output, file browser, terminale)."""
        from ui.build_panel import BuildPanel
        from ui.file_browser import FileBrowser
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

        # ── Dock destro: Pannello caratteri ──────────────────────────────────
        from ui.character_panel import CharacterPanel
        self._character_panel_dock = CharacterPanel(self)
        self._character_panel_dock.hide()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._character_panel_dock)

        # ── Dock anteprima (spostabile, alternativa allo split inline) ────────
        from ui.preview_panel import PreviewPanel
        self._preview_panel_dock = PreviewPanel()
        self._preview_dock = QDockWidget(f"👁  {tr('label.preview_panel')}", self)
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
        class _BottomTabWidget(_QTabWidget):
            def minimumSizeHint(self):
                from PyQt6.QtCore import QSize
                return QSize(0, 40)

        self._bottom_tabs = _BottomTabWidget()
        self._bottom_tabs.setMinimumHeight(0)
        self._bottom_tabs.setTabPosition(_QTabWidget.TabPosition.South)

        # Tab 1: Output compilazione
        self._build_panel = BuildPanel(self)
        self._bottom_tabs.addTab(self._build_panel, "⚙  Output compilazione")

        # Tab: Diagnostics LSP
        from ui.lsp_panel import DiagnosticsPanel
        self._diag_panel = DiagnosticsPanel(self)
        self._bottom_tabs.addTab(self._diag_panel, "⚡  Diagnostics")

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
        self.resizeDocks([self._build_dock], [150], Qt.Orientation.Vertical)

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

        # ── Dock destra: Minimap ─────────────────────────────────────────────
        from ui.minimap import MinimapWidget
        from config.settings import Settings as _S
        self._minimap_dock = QDockWidget("Minimap", self)
        self._minimap_dock.setObjectName("MinimapDock")
        self._minimap_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._minimap_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._minimap_dock)
        if not _S.instance().get("editor/show_minimap", False):
            self._minimap_dock.hide()
        # Sync menu checkmark quando il dock viene chiuso tramite il pulsante X
        self._minimap_dock.visibilityChanged.connect(self._on_minimap_dock_visibility)

    def _setup_statusbar(self) -> None:
        self.setStatusBar(self._statusbar)

    def _setup_connections(self) -> None:
        tm = self._tab_manager
        tm.current_editor_changed.connect(self._on_editor_changed)
        tm.tab_modified_changed.connect(self._on_tab_modified)

        # Notifica il PluginManager quando cambia l'editor attivo
        tm.current_editor_changed.connect(self._notify_plugins_editor_changed)

        # Aggiorna la minimap dock al cambio di editor
        tm.current_editor_changed.connect(self._on_minimap_editor_changed)

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
        enabled          = s.get("file/autobackup_enabled", False)
        autosave_to_bak  = s.get("file/autosave_to_backup", False)
        interval         = s.get("file/autobackup_interval", 5)
        self._autobackup_timer.stop()
        if enabled or autosave_to_bak:
            self._autobackup_timer.start(interval * 60 * 1000)

    def _get_backup_dir(self) -> Path:
        from config.settings import Settings
        from core.platform import get_data_dir
        s = Settings.instance()
        backup_dir_str = s.get("file/autobackup_dir", "")
        return Path(backup_dir_str) if backup_dir_str else get_data_dir() / "autobackup"

    def _autosave_file_to_backup(self, editor) -> None:
        """Salva una copia corrente (senza timestamp) nella cartella backup.
        Usato da open_files, _save_editor e dal timer autobackup."""
        from config.settings import Settings
        s = Settings.instance()
        if not s.get("file/autosave_to_backup", False):
            return
        if not editor.file_path:
            return
        backup_dir = self._get_backup_dir()
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            content = editor.get_content()
            (backup_dir / editor.file_path.name).write_text(
                content, encoding="utf-8", errors="replace"
            )
        except Exception:
            pass

    def _do_autobackup(self) -> None:
        """Salva una copia di backup di tutti i file aperti modificati."""
        from config.settings import Settings
        import datetime
        s = Settings.instance()
        backup_dir = self._get_backup_dir()
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        autosave_to_backup = s.get("file/autosave_to_backup", False)
        for editor in self._tab_manager.all_editors():
            if not editor.file_path:
                continue
            if not editor.is_modified():
                continue
            try:
                content = editor.get_content()
                if s.get("file/autobackup_enabled", False):
                    name = f"{editor.file_path.stem}_{ts}{editor.file_path.suffix}.bak"
                    (backup_dir / name).write_text(content, encoding="utf-8", errors="replace")
                if autosave_to_backup:
                    (backup_dir / editor.file_path.name).write_text(
                        content, encoding="utf-8", errors="replace"
                    )
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

    # ── LSP ───────────────────────────────────────────────────────────────────

    def _setup_lsp(self) -> None:
        self._lsp_hover_pos: tuple[int, int] = (0, 0)

    def _lsp_connect_editor(self, editor) -> None:
        """Connette l'editor al server LSP appropriato (se disponibile)."""
        if editor is None or not editor.file_path:
            return
        try:
            from editor.lsp_client import LSPClient, lang_to_id
            from editor.lexers import get_language_name
            lang      = get_language_name(editor).lower()
            workspace = str(editor.file_path.parent)
            client    = LSPClient.get(lang, workspace)
            if client is None:
                return

            # Evita di riconnettere se già attivo sullo stesso client
            if getattr(editor, "_lsp_client", None) is client:
                return
            editor._lsp_client = client

            # Open file nel server (idempotente)
            content = editor.get_content()
            client.open_file(editor.file_path, content, lang_to_id(lang))

            # Diagnostics → pannello
            try:
                client.diagnostics_ready.disconnect(self._diag_panel.update_diagnostics)
            except Exception:
                pass
            client.diagnostics_ready.connect(self._diag_panel.update_diagnostics)

            # Definition → naviga
            try:
                client.definition_ready.disconnect()
            except Exception:
                pass
            client.definition_ready.connect(self._on_lsp_definition)

            # Hover → tooltip testo
            try:
                editor.lsp_hover_requested.disconnect()
            except Exception:
                pass
            editor.lsp_hover_requested.connect(
                lambda line, col, _e=editor, _c=client: self._lsp_request_hover(_e, _c, line, col)
            )
            try:
                client.hover_ready.disconnect(self._on_lsp_hover_text)
            except Exception:
                pass
            client.hover_ready.connect(self._on_lsp_hover_text)

            # Formatting → applica edits
            try:
                client.formatting_ready.disconnect()
            except Exception:
                pass
            client.formatting_ready.connect(
                lambda edits, _e=editor: self._on_lsp_formatting(edits, _e)
            )

            # Rename → applica workspace edit
            try:
                client.rename_ready.disconnect()
            except Exception:
                pass
            client.rename_ready.connect(self._on_lsp_rename)

            # References → mostra in panel
            try:
                client.references_ready.disconnect()
            except Exception:
                pass
            client.references_ready.connect(self._on_lsp_references)

        except Exception as e:
            print(f"[LSP] _lsp_connect_editor: {e}")

    def _lsp_request_hover(self, editor, client, line: int, col: int) -> None:
        self._lsp_hover_pos = (line, col)
        if editor.file_path:
            client.request_hover(editor.file_path, line, col)

    def _on_lsp_hover_text(self, text: str) -> None:
        if not text.strip():
            return
        from PyQt6.QtWidgets import QToolTip
        from PyQt6.QtGui import QCursor
        QToolTip.showText(QCursor.pos(), text.strip()[:600], None, msecShowTime=6000)

    def _on_lsp_definition(self, uri: str, line: int, col: int) -> None:
        try:
            from pathlib import Path
            path = Path(uri.replace("file://", ""))
            if path.exists():
                self.open_files([path])
            editor = self._tab_manager.current_editor()
            if editor:
                editor.go_to_line(line + 1)
                editor.setFocus()
        except Exception as e:
            print(f"[LSP] goto definition: {e}")

    def _on_lsp_formatting(self, edits: list, editor) -> None:
        if not edits or editor is None:
            return
        # Applica in ordine inverso per non spostare le posizioni
        for edit in sorted(edits, key=lambda e: (
            -e.get("range", {}).get("start", {}).get("line", 0),
            -e.get("range", {}).get("start", {}).get("character", 0)
        )):
            r     = edit.get("range", {})
            start = r.get("start", {})
            end   = r.get("end", {})
            new_text = edit.get("newText", "")
            editor.setSelection(start["line"], start["character"], end["line"], end["character"])
            editor.replaceSelectedText(new_text)

    def _on_lsp_rename(self, workspace_edit: dict) -> None:
        changes = workspace_edit.get("changes", {})
        for uri, edits in changes.items():
            try:
                from pathlib import Path
                path = Path(uri.replace("file://", ""))
                self.open_files([path])
                editor = self._tab_manager.current_editor()
                if editor:
                    self._on_lsp_formatting(edits, editor)
                    self._save_editor(editor, editor.file_path)
            except Exception as e:
                print(f"[LSP] rename apply: {e}")

    def _on_lsp_references(self, refs: list) -> None:
        if not refs:
            self.statusBar().showMessage("LSP: nessun riferimento trovato", 3000)
            return
        lines = []
        for r in refs:
            try:
                from pathlib import Path
                fname = Path(r["uri"].replace("file://", "")).name
                lines.append(f"{fname}:{r['line'] + 1}:{r['col'] + 1}")
            except Exception:
                pass
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Riferimenti LSP", "\n".join(lines[:50]))

    # ── Azioni LSP pubbliche ──────────────────────────────────────────────────

    def action_lsp_goto_definition(self) -> None:
        editor = self._tab_manager.current_editor()
        client = getattr(editor, "_lsp_client", None)
        if not editor or not client or not editor.file_path:
            return
        line, col = editor.getCursorPosition()
        client.request_definition(editor.file_path, line, col)

    def action_lsp_find_references(self) -> None:
        editor = self._tab_manager.current_editor()
        client = getattr(editor, "_lsp_client", None)
        if not editor or not client or not editor.file_path:
            return
        line, col = editor.getCursorPosition()
        client.request_references(editor.file_path, line, col)

    def action_lsp_rename(self) -> None:
        editor = self._tab_manager.current_editor()
        client = getattr(editor, "_lsp_client", None)
        if not editor or not client or not editor.file_path:
            return
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(self, "Rinomina simbolo", "Nuovo nome:")
        if ok and new_name.strip():
            line, col = editor.getCursorPosition()
            client.request_rename(editor.file_path, line, col, new_name.strip())

    def action_lsp_format(self) -> None:
        editor = self._tab_manager.current_editor()
        client = getattr(editor, "_lsp_client", None)
        if not editor or not client or not editor.file_path:
            self.statusBar().showMessage("LSP: server non disponibile per questo file", 3000)
            return
        from config.settings import Settings
        tab_size = Settings.instance().get("editor/tab_width", 4)
        client.request_formatting(editor.file_path, tab_size=tab_size)

    def action_lsp_diagnostics(self) -> None:
        self._build_dock.show()
        n = self._bottom_tabs.count()
        for i in range(n):
            if "Diagnostics" in self._bottom_tabs.tabText(i):
                self._bottom_tabs.setCurrentIndex(i)
                break

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
        self._plugin_icon_actions: list[tuple] = []  # (QAction, icon_file_str)
        self._build_menus()

    def _build_menus(self) -> None:
        """Costruisce la menubar completa."""
        mb = self._menubar
        mb.clear()

        self._build_menu_file(mb)
        self._build_menu_edit(mb)
        self._build_menu_text(mb)
        self._build_menu_line(mb)
        self._build_menu_search(mb)
        self._build_menu_view(mb)
        self._build_menu_document(mb)
        self._build_menu_tools(mb)
        self._build_menu_build(mb)
        self._build_menu_plugins(mb)
        self._build_menu_windows(mb)
        self._build_menu_help(mb)

        from ui.keybinding import load_and_apply_shortcuts
        load_and_apply_shortcuts(self._actions)

    def _rebuild_menus(self, lang: str = "") -> None:
        """Ricostruisce i menu dopo un cambio lingua."""
        self._build_menus()
        self._rebuild_toolbar()
        for _a in self._actions.values():
            _a.setIconVisibleInMenu(True)
        if hasattr(self, "_build_panel") and self._build_panel:
            self._build_panel._refresh_button_labels()
        # Re-aggancia i menu dinamici dopo il mb.clear() di _build_menus
        if hasattr(self, "_latex_menu_mgr"):
            self._latex_menu_mgr._attach()

    def _act(self, key: str, shortcut: str = "",
                 slot=None, checkable: bool = False,
                 checked: bool = False) -> QAction:
            """
            Crea o aggiorna un QAction identificato da key i18n.
            Registra l'azione in self._actions per l'editor scorciatoie.
            """
            action = QAction(tr(f"action.{key}"), self)
            
            # AGGIUNGI QUESTA RIGA: 
            # Scavalca la restrizione di GNOME/Debian e forza l'icona nel menu
            action.setIconVisibleInMenu(True)
            
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
        m.addAction(self._act("save_as",   "",             self.action_save_as))
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
        m.addAction(self._act("export_as",  "",              self.action_export_as))

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
        m.addAction(self._act("delete", "Del", self._relay("removeSelectedText")))
        self._sep(m)
        _a = self._act("select_all", "", self._relay("selectAll"))
        _a.setShortcut(QKeySequence("Ctrl+A"))
        _a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        m.addAction(_a)
        m.addAction(self._act("copy_path",     "", self.action_copy_path))
        m.addAction(self._act("copy_filename", "", self.action_copy_filename))
        self._sep(m)
        # ── Multi-cursore ─────────────────────────────────────────────────────
        sub_mc = m.addMenu("🖊  " + tr("menu.multicursor"))
        self._menus["multicursor"] = sub_mc
        sub_mc.addAction(self._act("mc_next_occ",  "Ctrl+D",          self._mc_select_next))
        sub_mc.addAction(self._act("mc_all_occ",   "Ctrl+Shift+D",    self._mc_select_all))
        sub_mc.addAction(self._act("mc_add_above", "Ctrl+Alt+Up",     self._mc_add_above))
        sub_mc.addAction(self._act("mc_add_below", "Ctrl+Alt+Down",   self._mc_add_below))
        sub_mc.addAction(self._act("mc_numbers",   "Ctrl+Shift+Alt+C",self._mc_insert_numbers))
        sub_mc.addAction(self._act("mc_clear",     "Escape",          self._mc_clear))

    # ── Menu Testo ────────────────────────────────────────────────────────────

    def _build_menu_text(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.text"))
        self._menus["text"] = m
        # registra anche "format" per compatibilità con command palette e icone
        self._menus["format"] = m

        m.addAction(self._act("markup_bold",   "Ctrl+B",       lambda: self._apply_markup("bold")))
        m.addAction(self._act("markup_italic", "Ctrl+I",       lambda: self._apply_markup("italic")))
        m.addAction(self._act("markup_strike", "Ctrl+Shift+X", lambda: self._apply_markup("strike")))
        m.addAction(self._act("wrap_env",      "Alt+E",        self.action_wrap_env))
        self._sep(m)
        m.addAction(self._act("toggle_comment","Ctrl+E",       self.action_toggle_comment))
        m.addAction(self._act("comment_line",  "",             self.action_comment_lines))
        m.addAction(self._act("uncomment_line","",             self.action_uncomment_lines))
        self._sep(m)
        m.addAction(self._act("align_table",   "Alt+T",        self.action_align_table))
        sub_ct = m.addMenu(tr("action.convert_table"))
        sub_ct.addAction(self._act("convert_table_md",  "Ctrl+Alt+T", self.action_convert_table_md))
        sub_ct.addAction(self._act("convert_table_tex", "",           self.action_convert_table_tex))
        self._sep(m)
        m.addAction(self._act("indent",        "Ctrl+Shift+I", self.action_indent))
        m.addAction(self._act("unindent",      "Ctrl+U",       self.action_unindent))
        m.addAction(self._act("indent_smart",  "",             self.action_indent_smart))
        self._sep(m)
        m.addAction(self._act("trim_trailing", "",             self.action_trim_trailing))
        m.addAction(self._act("tabs_to_spaces","",             self.action_tabs_to_spaces))
        m.addAction(self._act("spaces_to_tabs","",             self.action_spaces_to_tabs))
        self._sep(m)
        m.addAction(self._act("column_editor",   "Alt+C",        self.action_column_editor))
        self._sep(m)
        m.addAction(self._act("join_lines",    "",             self.action_join_lines))
        m.addAction(self._act("line_break",    "",             self.action_line_break))
        m.addAction(self._act("wrap_lines",    "",             self.action_wrap_lines))
        self._sep(m)
        m.addAction(self._act("uppercase",     "",             self.action_uppercase))
        m.addAction(self._act("lowercase",     "",             self.action_lowercase))
        m.addAction(self._act("titlecase",     "",             self.action_titlecase))
        m.addAction(self._act("invert_case",   "Ctrl+Alt+U",  self.action_invert_case))
        self._sep(m)
        m.addAction(self._act("insert_date",     "",             self.action_insert_date))
        m.addAction(self._act("format_document", "Alt+Shift+F", self._action_format_document))

    # ── Menu Righe ────────────────────────────────────────────────────────────

    def _build_menu_line(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.line"))
        self._menus["line"] = m
        self._menus["line_operations"] = m  # alias per compatibilità

        def _editor():
            return self._tab_manager.current_editor()

        def _run(fn_name: str):
            def slot():
                ed = _editor()
                if ed:
                    import core.line_operations as lo
                    getattr(lo, fn_name)(ed)
            return slot

        m.addAction(self._act("sort_lines_menu",     "",  self.action_sort_lines_dialog))
        self._sep(m)
        m.addAction(self._act("sort_asc",            "",  _run("apply_sort_asc")))
        m.addAction(self._act("sort_desc",           "",  _run("apply_sort_desc")))
        m.addAction(self._act("sort_by_length_asc",  "",  _run("apply_sort_by_length")))
        m.addAction(self._act("sort_by_length_desc", "",  _run("apply_sort_by_length_desc")))
        m.addAction(self._act("sort_random",         "",  _run("apply_sort_random")))
        self._sep(m)
        m.addAction(self._act("remove_dup_sorted",   "",  _run("apply_remove_dup_sorted")))
        m.addAction(self._act("remove_dup_ordered",  "",  _run("apply_remove_dup_ordered")))
        m.addAction(self._act("remove_unique",       "",  _run("apply_remove_unique")))
        m.addAction(self._act("keep_unique",         "",  _run("apply_keep_unique")))
        self._sep(m)
        m.addAction(self._act("remove_empty",        "",  _run("apply_remove_empty")))
        m.addAction(self._act("remove_whitespace",   "",  _run("apply_remove_whitespace")))
        self._sep(m)

        def _remove_nth():
            from PyQt6.QtWidgets import QInputDialog
            ed = _editor()
            if not ed:
                return
            n, ok = QInputDialog.getInt(self, tr("action.remove_every_nth"), "N:", 2, 2, 100)
            if ok:
                import core.line_operations as lo
                lo.apply_remove_every_nth(ed, n)

        m.addAction(self._act("remove_every_nth", "", _remove_nth))

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
        m.addAction(self._act("find_in_files",    "Ctrl+Shift+F", self.action_find_in_files))
        m.addAction(self._act("find_in_all_docs", "Ctrl+Shift+H", self.action_find_in_all_docs))
        self._sep(m)
        m.addAction(self._act("go_to_line",      "Ctrl+G",       self.action_go_to_line))
        m.addAction(self._act("go_to_matching",  "Ctrl+]",       self.action_go_to_matching))
        self._sep(m)
        # Le voci "Segna con colore 1-5" e "Rimuovi tutti i mark" (Ctrl+0..5)
        # vengono aggiunte da MultiMarkManager.install_into_main_window() in main.py
        # dopo l'inizializzazione — non duplicarle qui.
        m.addAction(self._act("toggle_bookmark", "Ctrl+F2",      self.action_toggle_bookmark))
        m.addAction(self._act("next_bookmark",   "F2",           self.action_next_bookmark))
        m.addAction(self._act("prev_bookmark",   "Shift+F2",     self.action_prev_bookmark))
        m.addAction(self._act("clear_bookmarks", "",             self.action_clear_bookmarks))

    # ── Menu Visualizza ───────────────────────────────────────────────────────

    def _build_menu_view(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.view"))
        self._menus["view"] = m

        from config.settings import Settings
        s = Settings.instance()

        # Interfaccia
        m.addAction(self._act("view_toolbar",      "", self._toggle_toolbar,     checkable=True, checked=s.get("view/toolbar", True)))
        m.addAction(self._act("customize_toolbar", "", self._action_customize_toolbar))
        m.addAction(self._act("view_lang_toolbar", "Ctrl+Shift+L", self._toggle_lang_toolbar, checkable=True, checked=s.get("view/lang_toolbar", False)))
        m.addAction(self._act("view_statusbar",    "", self._toggle_statusbar,   checkable=True, checked=s.get("view/statusbar", True)))
        self._sep(m)

        # Visualizzazione editor
        m.addAction(self._act("view_line_numbers", "", self._toggle_line_numbers, checkable=True, checked=s.get("editor/show_line_numbers", True)))
        m.addAction(self._act("view_fold_margin",  "", self._toggle_fold_margin,  checkable=True, checked=s.get("editor/show_fold_margin", True)))
        m.addAction(self._act("view_whitespace",   "", self._toggle_whitespace,   checkable=True, checked=s.get("editor/show_whitespace", False)))
        m.addAction(self._act("view_eol",          "", self._toggle_eol,          checkable=True, checked=s.get("editor/show_eol", False)))
        # view_word_wrap: registrata qui per _actions ma aggiunta solo al menu Documento
        self._act("view_word_wrap", "Alt+Z", self._toggle_word_wrap, checkable=True, checked=s.get("editor/word_wrap", False))
        self._sep(m)

        # Pannelli
        m.addAction(self._act("view_minimap",         "", self._toggle_minimap,         checkable=True, checked=s.get("editor/show_minimap", False)))
        m.addAction(self._act("view_minimap_hover",   "", self._toggle_minimap_hover,   checkable=True, checked=s.get("editor/minimap_hover_preview", False)))
        m.addAction(self._act("view_build_panel",     "Ctrl+`",       self._toggle_build_panel,     checkable=True, checked=False))
        m.addAction(self._act("view_file_browser",    "Ctrl+Shift+E", self._toggle_file_browser,    checkable=True, checked=False))
        m.addAction(self._act("view_project_manager", "",             self._toggle_project_manager, checkable=True, checked=False))
        m.addAction(self._act("view_character_panel", "",             self._toggle_character_panel, checkable=True, checked=False))
        m.addAction(self._act("preview_toggle",       "F12",          self._toggle_preview,         checkable=True, checked=False))
        self._sep(m)

        # Zoom
        m.addAction(self._act("view_zoom_in",    "Ctrl+=", self.action_zoom_in))
        m.addAction(self._act("view_zoom_out",   "Ctrl+-", self.action_zoom_out))
        m.addAction(self._act("view_zoom_reset", "Ctrl+0", self.action_zoom_reset))
        self._sep(m)

        # ── Split View submenu ─────────────────────────────────────────────────
        sub_split = m.addMenu(tr("menu.split_view"))
        self._menus["split_view"] = sub_split
        sub_split.addAction(self._act(
            "split_vertical",   "Ctrl+Alt+2",
            lambda: self._tab_manager.split(self._tab_manager.SPLIT_SIDE_BY_SIDE, clone_current=True)
        ))
        sub_split.addAction(self._act(
            "split_horizontal", "Ctrl+Alt+3",
            lambda: self._tab_manager.split(self._tab_manager.SPLIT_TOP_BOTTOM, clone_current=True)
        ))
        sub_split.addAction(self._act(
            "split_rotate",     "Ctrl+Alt+R",
            lambda: self._tab_manager.rotate_split()
        ))
        self._sep(sub_split)
        sub_split.addAction(self._act(
            "split_move_tab",   "Ctrl+Alt+M",
            lambda: self._tab_manager.move_to_other_panel()
        ))
        sub_split.addAction(self._act(
            "split_sync_cursor", "",
            self._toggle_split_sync, checkable=True, checked=False
        ))
        self._sep(sub_split)
        sub_split.addAction(self._act(
            "unsplit",          "Ctrl+Alt+1",
            lambda: self._tab_manager.unsplit()
        ))
        self._sep(m)

        # Modalità
        _df_act = self._act("distraction_free", "F11", self._toggle_distraction_free, checkable=True, checked=False)
        _df_act.setShortcuts([QKeySequence("F11"), QKeySequence("Ctrl+Shift+F11"), QKeySequence("Ctrl+F11")])
        m.addAction(_df_act)
        m.addAction(self._act("view_typewriter",    "", self._toggle_typewriter,
                               checkable=True, checked=s.get("editor/typewriter_mode", False)))
        m.addAction(self._act("view_plain_text_mode", "Ctrl+Alt+N",
                               self._toggle_plain_text_mode, checkable=True, checked=False))
        self._sep(m)

        # Git
        m.addAction(self._act("view_git_gutter",       "", self._toggle_git_gutter,
                               checkable=True, checked=s.get("editor/git_gutter", True)))
        m.addAction(self._act("view_git_blame_inline", "", self._toggle_git_blame_inline,
                               checkable=True, checked=s.get("editor/git_blame_inline", False)))

    # ── Menu Documento ────────────────────────────────────────────────────────

    def _build_menu_document(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.document"))
        self._menus["document"] = m

        from config.settings import Settings as _S

        m.addAction(self._actions["view_word_wrap"])  # stessa action di Visualizza → checkbox sincronizzato
        m.addAction(self._act("auto_indent",       "", self._toggle_auto_indent,       checkable=True, checked=_S.instance().get("editor/auto_indent", True)))
        m.addAction(self._act("auto_indent_paste", "", self._toggle_auto_indent_paste, checkable=True, checked=_S.instance().get("editor/auto_indent_paste", False)))
        m.addAction(self._act("autoclose_toggle",  "", self._toggle_autoclose,         checkable=True, checked=True))

        _spell_enabled = _S.instance().get("spellcheck/enabled", False)
        _spell_saved   = _S.instance().get("spellcheck/language", "it")
        m.addAction(self._act("spell_check", "F4", self._toggle_spellcheck,
                              checkable=True, checked=_spell_enabled))
        m.addAction(self._act("spell_check_dialog", "Shift+F4", self._open_spell_check_dialog))

        # Tipografia intelligente (Markdown + testo)
        _smart_typo = _S.instance().get("editor/smart_typography", False)
        _act_st = self._act("smart_typography", "", self._toggle_smart_typography,
                            checkable=True, checked=_smart_typo)
        _act_st.setToolTip(tr("tooltip.smart_typography"))
        m.addAction(_act_st)

        # Focus paragrafo
        _sfocus = _S.instance().get("editor/sentence_focus", False)
        _act_sf = self._act("sentence_focus", "", self._toggle_sentence_focus,
                            checkable=True, checked=_sfocus)
        _act_sf.setToolTip(tr("tooltip.sentence_focus"))
        m.addAction(_act_sf)

        # Submenu lingua dizionario (indipendente dalla lingua dell'interfaccia)
        sub_spell = m.addMenu(tr("action.spell_lang"))
        self._menus["spell_lang"] = sub_spell
        from PyQt6.QtGui import QActionGroup as _SpellAG
        _spell_ag = _SpellAG(self)
        _spell_ag.setExclusive(True)
        self._spell_lang_actions: dict[str, QAction] = {}
        for _code, _label in [("it", "Italiano"), ("en", "English"),
                               ("de", "Deutsch"), ("fr", "Français"), ("es", "Español"),
                               ("pl", "Polski")]:
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
        act_tabs   = QAction(tr("label.tab_size") + " (Tab)", self, checkable=True)
        act_spaces = QAction(tr("label.use_spaces"), self, checkable=True, checked=True)
        act_tabs.triggered.connect(lambda: self._set_indent_type(False))
        act_spaces.triggered.connect(lambda: self._set_indent_type(True))
        sub_indent.addAction(act_tabs)
        sub_indent.addAction(act_spaces)

        m.addAction(self._act("indent_width", "", self.action_set_indent_width))
        self._sep(m)
        m.addAction(self._act("read_only",   "", self._toggle_read_only, checkable=True, checked=False))
        m.addAction(self._act("write_bom",   "", self._toggle_write_bom, checkable=True, checked=False))
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
            ("LF (Unix)",      LineEnding.LF,   "lf"),
            ("CRLF (Windows)", LineEnding.CRLF, "crlf"),
            ("CR (Mac)",       LineEnding.CR,   "cr"),
        ]:
            _a = QAction(_label, self)
            _a.setCheckable(True)
            _a.triggered.connect(lambda checked, le=_le: self.action_set_line_ending(le))
            _le_grp.addAction(_a)
            sub_le.addAction(_a)
            self._le_actions[_key] = _a

        self._sep(m)
        m.addAction(self._act("clone_document",       "", self.action_clone))
        self._sep(m)
        m.addAction(self._act("fold_all",             "", self.action_fold_all))
        m.addAction(self._act("unfold_all",           "", self.action_unfold_all))
        self._sep(m)
        m.addAction(self._act("remove_markers",       "", self.action_remove_markers))
        m.addAction(self._act("remove_error_markers", "", self.action_remove_error_markers))
        self._sep(m)
        _act_tc = self._act("toggle_checklist", "Ctrl+Shift+L", self._action_toggle_checklist)
        _act_tc.setToolTip(tr("tooltip.toggle_checklist"))
        m.addAction(_act_tc)
        self._sep(m)
        m.addAction(self._act("word_count",     "", self.action_word_count))
        m.addAction(self._act("word_frequency", "", self.action_word_frequency))
        self._sep(m)
        m.addAction(self._act("writing_goal_set", "", self.action_writing_goal))

    def _populate_file_type_menu(self, menu: QMenu) -> None:
        """Popola il submenu Imposta tipo di file — ordinato alfabeticamente con checkmark."""
        # Voce speciale "Automatico" sempre in cima
        from PyQt6.QtGui import QActionGroup
        auto_action = QAction("Automatico", self)
        auto_action.triggered.connect(lambda: self.action_set_language("Automatico"))
        menu.addAction(auto_action)
        menu.addSeparator()

        types = sorted([
            # QScintilla nativi
            "Bash/Shell", "C/C++", "C#", "CMake", "CSS", "Diff",
            "HTML", "INI/Config", "Java", "JavaScript",
            "JSON", "LaTeX", "Lua", "Makefile", "Markdown",
            "Python", "Ruby", "SQL",
            "Testo normale", "TypeScript", "XML", "YAML",
            # Pygments
            "Dart", "Elixir", "Go", "Haskell", "Julia",
            "Kotlin", "PHP", "R", "Rust", "Scala", "Swift", "TOML",
        ])
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
                "ini": "ini/config", "config": "ini/config",
                "properties": "ini/config", "toml": "toml",
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

        # Macro
        m.addAction(self._act("record_macro", "", self.action_record_macro))
        m.addAction(self._act("stop_macro",   "", self.action_stop_macro))
        m.addAction(self._act("play_macro",   "", self.action_play_macro))
        m.addAction(self._act("play_macro_n", "", self.action_play_macro_n))
        m.addAction(self._act("save_macro",   "", self.action_save_macro))
        m.addAction(self._act("load_macro",   "", self.action_load_macro))
        self._sep(m)
        m.addAction(self._act("named_sessions", "", self.action_named_sessions))
        self._sep(m)
        # Utilità
        m.addAction(self._act("compare_files",    "",           self.action_compare))
        m.addAction(self._act("color_picker",     "",           self.action_color_picker))
        m.addAction(self._act("regex_tester",     "",           self.action_regex_tester))
        m.addAction(self._act("number_converter", "",           self.action_number_converter))
        m.addAction(self._act("column_stats",     "Ctrl+Alt+S", self.action_column_stats))
        m.addAction(self._act("lorem_ipsum",      "",           self.action_lorem_ipsum))
        m.addAction(self._act("text_converter",   "",           self.action_text_converter))
        self._sep(m)
        m.addAction(self._act("keybinding_editor", "", self.action_keybinding_editor))
        m.addAction(self._act("reload_config",     "", self.action_reload_config))
        self._sep(m)
        m.addAction(self._act("preferences", "Ctrl+Alt+P", self.action_preferences))
        self._sep(m)
        m.addAction(self._act("open_terminal", "", self.action_open_terminal))

    # ── Menu Compila/Esegui ───────────────────────────────────────────────────

    def _build_menu_build(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.build"))
        self._menus["build"] = m

        m.addAction(self._act("run",          "F5", self.action_run))
        m.addAction(self._act("compile",      "F6", self.action_compile))
        m.addAction(self._act("build",        "F7", self.action_build))
        m.addAction(self._act("stop_build",   "",   self.action_stop_build))
        m.addAction(self._act("build_profiles","F8", self.action_build_profiles))
        self._sep(m)
        self._menus["lsp"] = m
        m.addSection("⚡  LSP")
        m.addAction(self._act("lsp_goto_def", "Ctrl+F12",    self.action_lsp_goto_definition))
        m.addAction(self._act("lsp_refs",     "Shift+F12",   self.action_lsp_find_references))
        m.addAction(self._act("lsp_rename",   "Shift+F6",    self.action_lsp_rename))
        m.addAction(self._act("lsp_format",   "Alt+Shift+F", self.action_lsp_format))
        m.addAction(self._act("lsp_diag",     "",            self.action_lsp_diagnostics))

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

    # ── Menu Finestre ─────────────────────────────────────────────────────────

    def _build_menu_windows(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.windows"))
        self._menus["windows"] = m
        m.aboutToShow.connect(self._populate_menu_windows)

    def _populate_menu_windows(self) -> None:
        m = self._menus.get("windows")
        if not m:
            return
        m.clear()
        tm = self._tab_manager
        current_editor = tm.current_editor()
        panels = tm._panels()
        is_split = len(panels) > 1
        for panel_idx, panel in enumerate(panels):
            tab_m = panel.tab_manager
            if is_split:
                m.addSection(tr("split_view.panel" + str(panel_idx + 1),
                                default=f"Pannello {panel_idx + 1}"))
            for i in range(tab_m.count()):
                editor = tab_m.editor_at(i)
                widget = tab_m.widget(i)
                if editor is not None:
                    fp = editor.file_path
                    label = fp.name if fp else tr("label.untitled")
                    if editor.is_modified():
                        label += " *"
                    is_current = editor is current_editor
                    act = m.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(is_current)
                    act.triggered.connect(lambda _c, ed=editor: self._tab_manager.set_current_editor(ed))
                else:
                    label = tab_m.tabText(i).rstrip(" *")
                    if hasattr(widget, "is_modified") and widget.is_modified():
                        label += " *"
                    is_current = (panel is tm._active and i == tab_m.currentIndex())
                    act = m.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(is_current)
                    act.triggered.connect(lambda _c, p=panel, idx=i: [
                        setattr(self._tab_manager, "_active", p),
                        p.tab_manager.setCurrentIndex(idx),
                    ])

    # ── Menu Aiuto ────────────────────────────────────────────────────────────

    def _build_menu_help(self, mb: QMenuBar) -> None:
        m = mb.addMenu(tr("menu.help"))
        self._menus["help"] = m
        m.addAction(self._act("context_help",  "F1", self.action_context_help))
        m.addAction(self._act("manual",        "", self.action_open_manual))
        self._sep(m)
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
        self._toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._toolbar.customContextMenuRequested.connect(self._toolbar_context_menu)
        self._rebuild_toolbar()
        # Secondo refresh dopo show(): la palette è completamente inizializzata
        # solo dopo il primo ciclo eventi. Su Debian Qt 6.8 questo è necessario
        # per avere il colore corretto nelle icone SVG e per forzare il ridisegno.
        QTimer.singleShot(300, self._rebuild_toolbar)

    def _toolbar_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        act = menu.addAction(tr("action.customize_toolbar", default="Personalizza barra degli strumenti…"))
        act.triggered.connect(self._action_customize_toolbar)
        menu.exec(self._toolbar.mapToGlobal(pos))

    def _action_customize_toolbar(self) -> None:
        from ui.customize_toolbar_dialog import CustomizeToolbarDialog
        dlg = CustomizeToolbarDialog(self)
        dlg.exec()

    def _setup_language_toolbar(self) -> None:
        """Installa la toolbar contestuale LaTeX/Markdown."""
        try:
            from ui.language_toolbar import LanguageToolbar
            LanguageToolbar.install(self)
        except Exception as e:
            print(f"[LanguageToolbar] errore installazione: {e}")

    def _setup_latex_menu(self) -> None:
        """Installa il menu LaTeX (visibile solo con file .tex attivi)."""
        try:
            from ui.latex_menu import LatexMenuManager
            LatexMenuManager.install(self)
        except Exception as e:
            print(f"[LatexMenu] errore installazione: {e}")

    def _rebuild_toolbar(self) -> None:
        """Carica le icone dal disco e le applica a toolbar e voci di menu."""
        from PyQt6.QtWidgets import QStyle
        from PyQt6.QtGui import QIcon
        from pathlib import Path
        from config.settings import Settings

        tb = self._toolbar
        tb.clear()
        style = self.style()

        icons_dir = Path(__file__).parent.parent / "icons" / "lucide"

        # Fallback icone di sistema usati solo per le azioni della toolbar
        toolbar_system_fallbacks = {
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

        # Applica icone a tutte le azioni registrate (toolbar + menu).
        # Su Qt6/Linux, QIcon(path_svg) usa il QSvgIconEngine che su alcune
        # distribuzioni (Debian) lascia availableSizes() vuoto: Qt non disegna
        # l'icona nei menu. Pre-renderizzando l'SVG come QPixmap con il colore
        # testo della palette corrente (currentColor), availableSizes() riporta
        # [24x24] e le icone sono visibili su qualsiasi tema (chiaro o scuro).
        from PyQt6.QtGui import QPixmap as _QPixmap, QPalette as _QPalette
        from ui.language_toolbar import render_svg_icon as _render_svg, toolbar_icon_color as _icon_color
        _wtext = _icon_color(self)
        for key, action in self._actions.items():
            icon_file = _ICON_MAP.get(key)
            if not icon_file:
                if key in toolbar_system_fallbacks:
                    action.setIcon(style.standardIcon(toolbar_system_fallbacks[key]))
                continue
            icon_path = icons_dir / icon_file
            if icon_path.exists():
                try:
                    pm = _render_svg(icon_path, _wtext)
                    if not pm.isNull():
                        action.setIcon(QIcon(pm))
                    else:
                        action.setIcon(QIcon(str(icon_path)))
                except Exception:
                    action.setIcon(QIcon(str(icon_path)))
            elif key in toolbar_system_fallbacks:
                action.setIcon(style.standardIcon(toolbar_system_fallbacks[key]))

        # Ricostruzione fisica toolbar dalla configurazione salvata
        from PyQt6.QtWidgets import QToolButton
        from ui.customize_toolbar_dialog import DEFAULT_TOOLBAR
        toolbar_items: list[str] = Settings.instance().get("toolbar/items", None)
        if not isinstance(toolbar_items, list) or not toolbar_items:
            toolbar_items = list(DEFAULT_TOOLBAR)
        for k in toolbar_items:
            if k == "|":
                tb.addSeparator()
            elif k in self._actions:
                action = self._actions[k]
                tb.addAction(action)
                btn = tb.widgetForAction(action)
                if isinstance(btn, QToolButton) and not action.icon().isNull():
                    btn.setIcon(action.icon())
        tb.update()

        # Applica icone ai submenu che non sono QAction in _actions
        _submenu_icons = {
            "split_view":  _ICON_MAP.get("menu_split_view", ""),
            "indent_type": _ICON_MAP.get("indent_width", ""),
        }
        for menu_key, icon_file in _submenu_icons.items():
            menu = self._menus.get(menu_key)
            if menu and icon_file:
                icon_path = icons_dir / icon_file
                if icon_path.exists():
                    try:
                        pm = _render_svg(icon_path, _wtext)
                        if not pm.isNull():
                            from PyQt6.QtGui import QIcon as _QIcon2
                            menu.setIcon(_QIcon2(pm))
                    except Exception:
                        pass

        # Re-applica icone agli action dei plugin (registrati via _plugin_icon_actions)
        for widget, icon_key in getattr(self, "_plugin_icon_actions", []):
            if not icon_key:
                continue
            icon_file = _ICON_MAP.get(icon_key)
            if not icon_file:
                continue
            icon_path = icons_dir / icon_file
            if not icon_path.exists():
                continue
            try:
                pm = _render_svg(icon_path, _wtext)
                if not pm.isNull():
                    from PyQt6.QtGui import QIcon as _PIIcon
                    widget.setIcon(_PIIcon(pm))
            except Exception:
                pass

        # Propaga il refresh alla language toolbar (palette/icone si aggiornano al cambio tema)
        lt = getattr(self, "_lang_toolbar", None)
        if lt is not None and lt.isVisible():
            lt._rebuild(
                is_md="markdown" in (lt._current_lang or ""),
                is_tex="latex"   in (lt._current_lang or "") or
                       bool(set((lt._current_lang or "").split()) & {"tex", "bibtex", "plaintex"}),
            )

    # ── Slot: cambio editor corrente ──────────────────────────────────────────

    @pyqtSlot(object)
    def _on_editor_changed(self, editor: Optional[EditorWidget]) -> None:
        """Aggiorna titolo finestra e statusbar quando cambia il tab attivo."""
        if editor is None:
            # Potrebbe essere un tab spreadsheet: mostra il suo nome nel titolo
            path = self._tab_manager.current_custom_path()
            if path:
                self.setWindowTitle(f"{path.name} — {self.APP_NAME}")
            else:
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
        if "view_typewriter" in self._actions:
            editor.set_typewriter_mode(self._actions["view_typewriter"].isChecked())
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

        # Aggiorna pannello JSON/XML
        if hasattr(self, "_json_xml_panel"):
            self._json_xml_panel.set_editor(editor)

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

        # Writing goal — ricollega al nuovo editor se l'obiettivo è attivo
        if getattr(self, "_writing_goal", 0) > 0:
            try:
                editor.textChanged.disconnect(self._wg_timer.start)
            except (RuntimeError, TypeError):
                pass
            editor.textChanged.connect(self._wg_timer.start)
            self._update_writing_goal_display()

        # Focus paragrafo — ricollega cursore al nuovo editor se la modalità è attiva
        if self._actions.get("sentence_focus") and self._actions["sentence_focus"].isChecked():
            try:
                editor.cursorPositionChanged.disconnect(self._on_focus_cursor_moved)
            except (RuntimeError, TypeError):
                pass
            editor.cursorPositionChanged.connect(self._on_focus_cursor_moved)
            try:
                from editor.markdown_support import MarkdownSupport
                MarkdownSupport.apply_paragraph_focus(editor)
            except Exception:
                pass

        # LSP — connette il server per il linguaggio corrente (no-op se non disponibile)
        self._lsp_connect_editor(editor)

        # Incolla immagine clipboard come LaTeX
        try:
            editor.paste_clipboard_image_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        editor.paste_clipboard_image_requested.connect(
            lambda ed=editor: self._paste_clipboard_image_as_latex(ed)
        )

    def _paste_clipboard_image_as_latex(self, editor: "EditorWidget") -> None:
        """Salva l'immagine dalla clipboard su disco e apre la procedura guidata LaTeX."""
        from PyQt6.QtWidgets import QFileDialog, QDialog
        from PyQt6.QtGui import QImage

        img: QImage = QApplication.clipboard().image()
        if img.isNull():
            return

        base_dir = editor.file_path.parent if editor.file_path else None
        start_dir = str(base_dir) if base_dir else ""

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("dialog.save_clipboard_image", default="Salva immagine clipboard"),
            start_dir + "/image.png" if start_dir else "image.png",
            tr("dialog.image_filter_save",
               default="Immagini PNG (*.png);;JPEG (*.jpg *.jpeg);;Tutti i file (*)"),
        )
        if not save_path:
            editor.setFocus()
            return

        if not img.save(save_path):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                tr("msg.error", default="Errore"),
                tr("msg.clipboard_image_save_failed",
                   default="Impossibile salvare l'immagine in: {path}",
                   path=save_path),
            )
            editor.setFocus()
            return

        from ui.latex_insert_image_dialog import LatexInsertImageDialog
        dlg = LatexInsertImageDialog(parent=self, base_dir=base_dir)
        dlg.set_image_file(save_path)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            editor.setFocus()
            return
        code = dlg.get_latex_code()
        if not code:
            editor.setFocus()
            return

        # Assicura che graphicx sia presente nel preambolo
        toolbar = getattr(self, "_lang_toolbar", None)
        if toolbar and hasattr(toolbar, "_ensure_latex_package"):
            toolbar._ensure_latex_package(editor, "graphicx")

        if editor.hasSelectedText():
            editor.replaceSelectedText(code)
        else:
            line, col = editor.getCursorPosition()
            editor.insert(code)
            editor.setCursorPosition(line, col + len(code.split("\n")[0]))
        editor.setFocus()

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

    _SPREADSHEET_EXTS = frozenset({".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".ods"})
    _RICHTEXT_EXTS    = frozenset({".doc", ".docx", ".odt", ".rtf", ".html", ".htm"})
    _PDF_EXTS         = frozenset({".pdf"})

    def open_files(self, paths: list[Path]) -> None:
        """Apre una lista di file in nuovi tab (chiamato anche da drag&drop)."""
        from core.file_manager import FileManager
        for path in paths:
            if not path.is_file():
                continue
            # Intercetta file spreadsheet
            if path.suffix.lower() in self._SPREADSHEET_EXTS:
                plugin = getattr(self, "_spreadsheet_plugin", None)
                if plugin is not None:
                    plugin.open_spreadsheet(path)
                    continue
                # Plugin non caricato: apre come testo normale
            # Intercetta file richtext
            if path.suffix.lower() in self._RICHTEXT_EXTS:
                plugin = getattr(self, "_richtext_plugin", None)
                if plugin is not None:
                    plugin.open_document(path)
                    continue
                # Plugin non caricato: apre come testo normale
            # Intercetta PDF
            if path.suffix.lower() in self._PDF_EXTS:
                plugin = getattr(self, "_pdf_plugin", None)
                if plugin is not None:
                    plugin.open_document(path)
                    continue
                # Plugin non caricato: apre come testo normale
            # Controlla se il file è già aperto
            existing = self._tab_manager.find_tab_by_path(path)
            if existing is not None:
                self._tab_manager.set_current_index(existing)
                continue
            try:
                content, encoding, line_ending = FileManager.read(path)
                tab = self._tab_manager.new_tab(path=path)
                tab.load_content(content, encoding, line_ending)
                self._autosave_file_to_backup(tab)
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
            # Controlla se il tab corrente è un widget custom (es. SpreadsheetWidget)
            w = self._tab_manager.current_custom_widget()
            if w is not None and hasattr(w, "save"):
                return w.save()
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
            old_lang = getattr(editor, "_current_language", "")
            old_ext = editor.file_path.suffix.lower() if editor.file_path else ""
            new_ext = path.suffix.lower()
            editor.file_path = path

            # Aggiorna lexer e statusbar solo se l'estensione è cambiata
            # (es. Save As su file con estensione diversa o primo salvataggio
            # di un file senza nome). Evita setLexer+SCI_COLOURISE ad ogni
            # Ctrl+S, che causa un salto dello scroll.
            if new_ext != old_ext:
                try:
                    from editor.lexers import set_lexer_by_path
                    set_lexer_by_path(editor, path)
                except Exception:
                    pass
                if getattr(editor, "_current_language", "") != old_lang:
                    if hasattr(self, "_statusbar"):
                        self._statusbar._update_lang(editor)

            # 4. Aggiorna lo stato dell'editor
            editor.mark_saved()
            self._on_tab_modified(editor, False)
            self._update_recent(path)
            self._notify_plugins_file_saved(path)
            self._autosave_file_to_backup(editor)

            # 5. Se il file è stato aperto da FTP, sincronizza sul server remoto
            if getattr(editor, "_ftp_remote_path", None):
                self._ftp_sync_after_save(editor)

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

    def _ftp_sync_after_save(self, editor) -> None:
        """After a local save, upload to FTP if the file was originally opened from FTP."""
        remote_path = getattr(editor, "_ftp_remote_path", None)
        if not remote_path:
            return
        try:
            from plugins.plugin_manager import PluginManager
            ftp_entry = PluginManager.instance().get_all().get("FTP Browser")
            if not (ftp_entry and ftp_entry.get("enabled")):
                return
            panel = ftp_entry["instance"]._panel
            raw = editor.get_content().encode(editor.encoding, errors="replace")
            profile = getattr(editor, "_ftp_profile", None)
            if panel._do_upload(remote_path, raw, profile):
                panel._upload_ok(remote_path)
            else:
                self.statusBar().showMessage(
                    tr("msg.ftp_sync_failed", default="FTP sync fallito — vedi pannello FTP"), 5000
                )
        except Exception as e:
            self.statusBar().showMessage(f"FTP sync error: {e}", 5000)

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
        from ui.print_options_dialog import PrintOptionsDialog, print_with_header_footer
        editor = self._current_editor()
        if not editor:
            custom = self._tab_manager.current_custom_widget()
            if custom is not None and hasattr(custom, "print_document"):
                custom.print_document()
            return
        opt_dlg = PrintOptionsDialog(self, file_path=editor.file_path)
        if opt_dlg.exec() != PrintOptionsDialog.DialogCode.Accepted:
            return
        dlg = QPrintDialog(self._printer, self)
        if dlg.exec() == QPrintDialog.DialogCode.Accepted:
            print_with_header_footer(self._printer, editor, opt_dlg)

    def action_print_preview(self) -> None:
        from ui.print_options_dialog import PrintOptionsDialog, print_with_header_footer
        editor = self._current_editor()
        if not editor:
            return
        opt_dlg = PrintOptionsDialog(self, file_path=editor.file_path)
        if opt_dlg.exec() != PrintOptionsDialog.DialogCode.Accepted:
            return
        dlg = QPrintPreviewDialog(self._printer, self)
        dlg.paintRequested.connect(
            lambda printer: print_with_header_footer(printer, editor, opt_dlg)
        )
        dlg.resize(1000, 800)
        dlg.exec()

    def _do_print(self, printer: QPrinter) -> None:
        editor = self._current_editor()
        if editor:
            editor.print(printer)

    def action_export_pdf(self) -> None:
        editor = self._current_editor()
        if not editor:
            custom = self._tab_manager.current_custom_widget()
            if custom is not None and hasattr(custom, "export_pdf"):
                custom.export_pdf()
            return
        default = str(editor.file_path.with_suffix("")
                      if editor.file_path else Path.home() / "documento")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("action.export_pdf"), default, "PDF (*.pdf)")
        if not path:
            return
        from pathlib import Path as _Path
        _p = _Path(path)
        if _p.suffix.lower() != ".pdf":
            path = str(_p.with_suffix(".pdf"))
        try:
            from PyQt6.QtPrintSupport import QPrinter as _QPrinter
            from PyQt6.QtGui import QTextDocument as _QTextDocument
            import os as _os
            printer = _QPrinter(_QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(_QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            doc = _QTextDocument()
            doc.setPlainText(editor.text())
            doc.print(printer)
            if _os.path.exists(path) and _os.path.getsize(path) > 0:
                from PyQt6.QtGui import QDesktopServices as _QDS
                from PyQt6.QtCore import QUrl as _QUrl
                _QDS.openUrl(_QUrl.fromLocalFile(path))
            else:
                from PyQt6.QtWidgets import QMessageBox as _QMB
                _QMB.warning(self, tr("action.export_pdf"),
                             tr("msg.export_pdf_empty", path=path))
        except Exception as _exc:
            from PyQt6.QtWidgets import QMessageBox as _QMB
            _QMB.critical(self, tr("action.export_pdf"), str(_exc))

    def action_export_as(self) -> None:
        from PyQt6.QtWidgets import QFileDialog, QMessageBox as _QMB
        from pathlib import Path as _Path

        # Se il tab corrente è un RichTextWidget, delega a save_as()
        custom = self._tab_manager.current_custom_widget()
        if custom is not None and hasattr(custom, "save_as"):
            custom.save_as()
            return

        editor = self._current_editor()
        if not editor:
            return

        stem = editor.file_path.stem if editor.file_path else "documento"
        default = str(_Path.home() / stem)
        _filter = (
            "Word 2007-365 DOCX (*.docx);;"
            "OpenDocument Text (*.odt);;"
            "HTML (*.html);;"
            "LaTeX (*.tex)"
        )
        path, selected_filter = QFileDialog.getSaveFileName(
            self, tr("action.export_as", default="Esporta come…"), default, _filter
        )
        if not path:
            return

        import re as _re
        p = _Path(path)
        m = _re.search(r'\*(\.\w+)', selected_filter)
        if m:
            ext = m.group(1).lower()
            if p.suffix.lower() != ext:
                p = p.with_suffix(ext)

        content = editor.text()
        src_ext = (editor.file_path.suffix.lower() if editor.file_path else "")

        # Mappa estensione → formato pandoc di input.
        # "plain" NON è un formato pandoc di input valido; si usa "markdown"
        # come parser più tollerante per testo generico.
        _PANDOC_IN = {
            ".md": "markdown", ".markdown": "markdown",
            ".html": "html", ".htm": "html",
            ".rst": "rst",
            ".tex": "latex", ".latex": "latex",
            ".org": "org",
            ".textile": "textile",
        }
        fmt_in = _PANDOC_IN.get(src_ext, "markdown")

        # Avviso se il sorgente non è un formato markup strutturato
        _RICH = {".md", ".markdown", ".html", ".htm", ".rst",
                 ".tex", ".latex", ".org", ".textile"}
        if src_ext not in _RICH and p.suffix.lower() in (".docx", ".odt", ".tex"):
            reply = _QMB.question(
                self,
                tr("action.export_as", default="Esporta come…"),
                f"Il file sorgente ({src_ext or 'senza estensione'}) non è un formato di markup.\n"
                "La conversione è possibile ma il risultato conterrà solo testo piano "
                "senza formattazione strutturata (titoli, grassetto, tabelle…).\n\n"
                "Continuare?",
                _QMB.StandardButton.Yes | _QMB.StandardButton.Cancel,
            )
            if reply != _QMB.StandardButton.Yes:
                return

        err = self._export_text_as(content, fmt_in, p)
        if err:
            _QMB.critical(self, tr("action.export_as", default="Esporta come…"), err)
        else:
            _QMB.information(self, tr("action.export_as", default="Esporta come…"),
                             f"File esportato:\n{p}")

    @staticmethod
    def _export_text_as(content: str, fmt_in: str, dest: "Path") -> str:
        """Converte testo/Markdown nel formato di dest. Ritorna stringa errore o ''."""
        import subprocess, tempfile
        from pathlib import Path as _Path

        ext = dest.suffix.lower()

        # HTML: usa markdown lib se disponibile, altrimenti wrap plain
        if ext in (".html", ".htm"):
            try:
                import markdown as _md
                body = _md.markdown(content, extensions=["tables", "fenced_code"])
            except ImportError:
                import html as _html
                body = "<pre>" + _html.escape(content) + "</pre>"
            full = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<style>body{font-family:serif;font-size:12pt;line-height:1.5;"
                "max-width:860px;margin:40px auto;padding:0 20px}</style>"
                f"</head><body>{body}</body></html>"
            )
            try:
                dest.write_text(full, encoding="utf-8")
                return ""
            except Exception as e:
                return str(e)

        # DOCX senza pandoc: markdown→html→htmldocx
        if ext == ".docx" and fmt_in == "markdown":
            try:
                import markdown as _md
                from htmldocx import HtmlToDocx
                html = _md.markdown(content, extensions=["tables", "fenced_code"])
                parser = HtmlToDocx()
                doc = parser.parse_html_string(html)
                doc.save(str(dest))
                return ""
            except ImportError:
                pass  # fallback pandoc

        # Pandoc per tutto il resto (docx plain, odt, tex)
        try:
            with tempfile.NamedTemporaryFile(suffix=".md" if fmt_in == "markdown" else ".txt",
                                             delete=False, mode="w", encoding="utf-8") as f:
                f.write(content)
                tmp = f.name
            fmt_out = ext.lstrip(".")
            if fmt_out == "tex":
                fmt_out = "latex"
            result = subprocess.run(
                ["pandoc", "-f", fmt_in, "-t", fmt_out, tmp, "-o", str(dest)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return result.stderr or f"pandoc exit {result.returncode}"
            return ""
        except FileNotFoundError:
            return "pandoc non trovato. Installa pandoc oppure htmldocx."
        except Exception as e:
            return str(e)
        finally:
            try:
                _Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass

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

    def action_column_editor(self) -> None:
        from ui.column_editor import ColumnEditorDialog
        editor = self._current_editor()
        if not editor:
            return

        # Determina le righe coinvolte dalla selezione (anche rettangolare)
        sel_start_line, sel_start_col, sel_end_line, _ = editor.getSelection()
        if sel_start_line < 0:
            # Nessuna selezione: usa solo la riga corrente
            sel_start_line = editor.getCursorPosition()[0]
            sel_end_line   = sel_start_line
            sel_start_col  = editor.getCursorPosition()[1]

        n_lines = sel_end_line - sel_start_line + 1

        dlg = ColumnEditorDialog(self)
        if dlg.exec() != ColumnEditorDialog.DialogCode.Accepted:
            return

        values = dlg.get_values(n_lines)

        editor.beginUndoAction()
        try:
            for i, val in enumerate(values):
                line_idx = sel_start_line + i
                line_text = editor.text(line_idx)
                # Rimuovi \n o \r\n finale per lavorare sul testo puro
                eol = ""
                if line_text.endswith("\r\n"):
                    eol = "\r\n"
                    line_text = line_text[:-2]
                elif line_text.endswith(("\n", "\r")):
                    eol = line_text[-1]
                    line_text = line_text[:-1]
                # Estendi la riga se la colonna di inserimento è oltre la fine
                col = sel_start_col
                if col > len(line_text):
                    line_text = line_text + " " * (col - len(line_text))
                new_text = line_text[:col] + val + line_text[col:] + eol
                editor.setSelection(line_idx, 0, line_idx, editor.lineLength(line_idx))
                editor.replaceSelectedText(new_text)
        finally:
            editor.endUndoAction()

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

    def _action_format_document(self) -> None:
        """Formatta il documento JSON/XML corrente (pretty-print)."""
        if hasattr(self, "_json_xml_panel"):
            self._json_xml_panel.format_document()

    def action_regex_tester(self) -> None:
        from ui.regex_tester import RegexTesterDialog
        dlg = RegexTesterDialog(self)
        dlg.show()

    # ── Azioni Visualizza ─────────────────────────────────────────────────────

    def _toggle_toolbar(self, checked: bool) -> None:
        self._toolbar.setVisible(checked)
        from config.settings import Settings
        Settings.instance().set("view/toolbar", checked)

    def _toggle_lang_toolbar(self, checked: bool) -> None:
        """Mostra/nasconde la toolbar contestuale LaTeX/Markdown."""
        from config.settings import Settings
        Settings.instance().set("view/lang_toolbar", checked)
        if hasattr(self, "_lang_toolbar"):
            self._lang_toolbar._user_hidden = not checked
            if not checked:
                self._lang_toolbar.setVisible(False)
            else:
                editor = self._tab_manager.current_editor()
                self._lang_toolbar._on_editor_changed(editor)

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
        """Attiva/disattiva la minimap dock."""
        from config.settings import Settings
        Settings.instance().set("editor/show_minimap", checked)
        if checked:
            editor = self._current_editor()
            if editor:
                self._on_minimap_editor_changed(editor)
            self._minimap_dock.show()
        else:
            self._minimap_dock.hide()

    def _on_minimap_dock_visibility(self, visible: bool) -> None:
        from config.settings import Settings
        Settings.instance().set("editor/show_minimap", visible)
        if "view_minimap" in self._actions:
            act = self._actions["view_minimap"]
            act.blockSignals(True)
            act.setChecked(visible)
            act.blockSignals(False)

    def _on_minimap_editor_changed(self, editor) -> None:
        if not hasattr(self, "_minimap_dock"):
            return
        if editor is None:
            return
        w = self._minimap_dock.widget()
        if w is not None and hasattr(w, "set_editor"):
            w.set_editor(editor)
        else:
            from ui.minimap import MinimapWidget
            mm = MinimapWidget(editor)
            mm.setMinimumWidth(60)
            self._minimap_dock.setWidget(mm)

    def _toggle_minimap_hover(self, checked: bool) -> None:
        from config.settings import Settings
        Settings.instance().set("editor/minimap_hover_preview", checked)
        if "view_minimap_hover" in self._actions:
            act = self._actions["view_minimap_hover"]
            if act.isChecked() != checked:
                act.blockSignals(True)
                act.setChecked(checked)
                act.blockSignals(False)

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

    def _toggle_character_panel(self, checked: bool) -> None:
        if checked:
            self._character_panel_dock.show()
        else:
            self._character_panel_dock.hide()

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

    def _toggle_typewriter(self, checked: bool) -> None:
        from config.settings import Settings
        Settings.instance().set("editor/typewriter_mode", checked)
        editor = self._current_editor()
        if editor:
            editor.set_typewriter_mode(checked)

    def _toggle_git_gutter(self, checked: bool) -> None:
        from config.settings import Settings
        Settings.instance().set("editor/git_gutter", checked)
        if hasattr(self, "_git_gutter"):
            self._git_gutter.set_enabled(checked)
        elif checked:
            try:
                from ui.git_gutter import GitGutter
                self._git_gutter = GitGutter(self)
            except Exception:
                pass

    def _toggle_git_blame_inline(self, checked: bool) -> None:
        from config.settings import Settings
        Settings.instance().set("editor/git_blame_inline", checked)
        if hasattr(self, "_git_blame_mgr"):
            self._git_blame_mgr.set_enabled(checked)

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
        from config.settings import Settings
        Settings.instance().set("editor/auto_indent", checked)

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

    def action_text_converter(self) -> None:
        from ui.text_converter import TextConverterDialog
        editor = self._current_editor()
        initial = editor.selectedText() if editor else ""
        dlg = TextConverterDialog(self, initial_text=initial)
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
        if hasattr(self, "_build_panel") and self._build_panel:
            self._build_panel._refresh_button_labels()

    def action_reload_config(self) -> None:
        from config.settings import Settings
        Settings.instance().reload()
        self._apply_autobackup_settings()

    def action_open_terminal(self) -> None:
        import subprocess, sys, shlex
        from pathlib import Path
        from config.settings import Settings

        editor = self._tab_manager.current_editor()
        folder = str(editor.file_path.parent) if (editor and editor.file_path) \
                 else str(Path(__file__).parent.parent)

        terminal_cmd = Settings.instance().get("build/terminal_cmd", "")

        try:
            if terminal_cmd:
                # Comando configurato dall'utente (con token {DIR})
                cmd_str = terminal_cmd.replace("{DIR}", folder)
                subprocess.Popen(shlex.split(cmd_str))
                return

            # Automatico: fallback per piattaforma
            if sys.platform == "win32":
                try:
                    subprocess.Popen(["wt.exe", "-d", folder])
                except FileNotFoundError:
                    subprocess.Popen(["cmd.exe", "/K", f"cd /d {folder}"])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal", folder])
            else:
                terminals = [
                    ["gnome-terminal", f"--working-directory={folder}"],
                    ["konsole", "--workdir", folder],
                    ["xfce4-terminal", f"--working-directory={folder}"],
                    ["tilix", f"--working-directory={folder}"],
                    ["alacritty", "--working-directory", folder],
                    ["kitty", f"--directory={folder}"],
                    ["lxterminal", f"--working-directory={folder}"],
                    ["mate-terminal", f"--working-directory={folder}"],
                    ["xterm", "-e", f"bash -c 'cd {folder!r}; exec bash'"],
                ]
                for cmd in terminals:
                    try:
                        subprocess.Popen(cmd)
                        return
                    except FileNotFoundError:
                        continue
                QMessageBox.warning(self, self.APP_NAME,
                                    "Nessun terminale supportato trovato.\n"
                                    "Configurane uno in Preferenze → Build.")
        except Exception as e:
            QMessageBox.warning(self, self.APP_NAME, f"Impossibile aprire il terminale:\n{e}")

    def action_plugin_manager(self) -> None:
        from plugins.plugin_manager import PluginManagerDialog
        dlg = PluginManagerDialog(self)
        dlg.exec()

    def action_open_manual(self) -> None:
        from pathlib import Path
        from i18n.i18n import I18n
        root = Path(__file__).parent.parent
        lang = I18n.instance().current_language().upper()  # "IT", "EN", "DE", "FR", "ES"
        candidates = [
            root / f"MANUAL_{lang}.md",
            root / "MANUAL_EN.md",   # fallback inglese
            root / "MANUALE.md",     # compatibilità con versioni precedenti
        ]
        for path in candidates:
            if path.is_file():
                self.open_files([path])
                return
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, tr("action.manual"), tr("msg.manual_not_found"))

    def _get_context_help_query(self) -> str:
        """Ritorna la stringa di ricerca contestuale per F1.

        Controlla nell'ordine: QToolButton sotto il cursore del mouse,
        QDockWidget sotto il cursore, parola nell'editor corrente.
        """
        import re
        from PyQt6.QtWidgets import QApplication, QToolButton, QDockWidget
        from PyQt6.QtGui import QCursor

        widget = QApplication.widgetAt(QCursor.pos())
        while widget:
            if isinstance(widget, QToolButton):
                action = widget.defaultAction()
                if action:
                    raw = (action.text() or action.toolTip() or "").strip()
                    text = re.sub(r'\s*[\(\[].*?[\)\]]\s*$', '', raw).strip()
                    if text:
                        return text
            if isinstance(widget, QDockWidget):
                return widget.windowTitle().strip()
            widget = widget.parent()

        editor = self._tab_manager.current_editor()
        if editor:
            sel = editor.selectedText().strip()
            if sel:
                return sel.split()[0]
            line, idx = editor.getCursorPosition()
            line_text = editor.text(line)
            if line_text:
                l = r = idx
                while l > 0 and (line_text[l - 1].isalnum() or line_text[l - 1] in "_-"):
                    l -= 1
                while r < len(line_text) and (line_text[r].isalnum() or line_text[r] in "_-"):
                    r += 1
                return line_text[l:r].strip()
        return ""

    def action_context_help(self) -> None:
        """F1 — ricerca nel manuale per titoli di sezione e testo in grassetto."""
        import re
        from pathlib import Path
        from i18n.i18n import I18n
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel
        )
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QFont, QColor

        root = Path(__file__).parent.parent
        lang = I18n.instance().current_language().upper()
        candidates = [root / f"MANUAL_{lang}.md", root / "MANUAL_EN.md", root / "MANUALE.md"]
        manual_path = next((c for c in candidates if c.is_file()), None)
        if not manual_path:
            self.action_open_manual()
            return

        # ── Costruisce l'indice dal manuale ─────────────────────────────────
        # Ogni entry: (match_text_lower, display_text, line_num, kind)
        # kind: "h1"/"h2"/"h3"/"h4" per intestazioni, "bold" per testo in grassetto
        entries = []
        current_section = ""
        seen_bold: set[str] = set()

        for i, line in enumerate(manual_path.read_text(encoding="utf-8").splitlines()):
            # Intestazioni
            mh = re.match(r'^(#{1,4})\s+(.+)$', line)
            if mh:
                level = len(mh.group(1))
                title = mh.group(2).strip()
                # Rimuovi decorazioni tipo *(incl. ...)* dai titoli ToC
                title = re.sub(r'\s*\*\(.*?\)\*\s*$', '', title).strip()
                current_section = title
                prefix = "  " * (level - 1)
                entries.append((title.lower(), prefix + title, i, f"h{level}"))
            else:
                # Testo in grassetto: **testo** con 2–60 caratteri
                for bm in re.finditer(r'\*\*([^*\n]{2,60})\*\*', line):
                    bold = bm.group(1).strip()
                    key = bold.lower()
                    if not bold or key in seen_bold:
                        continue
                    seen_bold.add(key)
                    display = f"  {bold}"
                    if current_section:
                        display += f"  —  {current_section}"
                    entries.append((key, display, i, "bold"))

        initial_query = self._get_context_help_query()

        # ── Dialog ──────────────────────────────────────────────────────────
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("action.context_help"))
        dlg.resize(560, 500)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(6)

        search = QLineEdit()
        search.setPlaceholderText(tr("msg.help_search_placeholder",
                                     default="Cerca un argomento nel manuale…"))
        search.setText(initial_query)
        lay.addWidget(search)

        lst = QListWidget()
        lst.setAlternatingRowColors(True)
        lay.addWidget(lst, 1)

        hint = QLabel(tr("msg.help_search_hint",
                         default="↵ Enter o doppio click per aprire nel manuale"))
        hint.setStyleSheet("color: #888; font-size: 11px;")
        lay.addWidget(hint)

        muted = dlg.palette().color(
            dlg.palette().ColorGroup.Normal,
            dlg.palette().ColorRole.PlaceholderText
        )

        def _fill(q: str) -> None:
            lst.clear()
            q_low = q.strip().lower()
            for match_key, display, line_num, kind in entries:
                # Senza query: solo intestazioni; con query: tutto
                if not q_low:
                    if kind == "bold":
                        continue
                elif q_low not in match_key:
                    continue
                item = QListWidgetItem(display)
                item.setData(Qt.ItemDataRole.UserRole, line_num)
                if kind == "h1":
                    f = QFont(); f.setBold(True); item.setFont(f)
                elif kind in ("h3", "h4", "bold"):
                    item.setForeground(muted)
                lst.addItem(item)
            if lst.count() > 0:
                lst.setCurrentRow(0)

        def _open(item=None) -> None:
            if item is None:
                item = lst.currentItem()
            if not item:
                return
            line_num = item.data(Qt.ItemDataRole.UserRole)
            dlg.accept()
            self.open_files([manual_path])
            QTimer.singleShot(200, lambda: _jump(line_num))

        def _jump(line_num: int) -> None:
            ed = self._tab_manager.current_editor()
            if ed:
                ed.setCursorPosition(line_num, 0)
                ed.ensureCursorVisible()

        search.textChanged.connect(_fill)
        lst.itemDoubleClicked.connect(_open)
        search.returnPressed.connect(lambda: _open())

        _fill(initial_query)
        search.selectAll()
        search.setFocus()
        dlg.exec()

    def action_about(self) -> None:
            from PyQt6.QtWidgets import QMessageBox, QLabel
            from PyQt6.QtCore import Qt
    
            # Creiamo l'istanza del messaggio
            msg = QMessageBox(self)
            msg.setWindowTitle(tr("action.about"))
            
            # 1. Recuperiamo il testo tradotto dal file JSON
            # Sostituiamo gli "a capo" testuali (\n) con quelli in HTML (<br>)
            testo_base = tr("msg.about_text", version=self.APP_VERSION).replace('\n', '<br>')
            
            # 2. Recuperiamo alcune etichette tradotte (Autore, Donazioni) per la parte inferiore
            autore_label = tr("label.plugin_author")
            dona_label = tr("action.donate").replace("...", "")
    
            # 3. Costruiamo l'HTML combinando le traduzioni e i tuoi link originali
            content = (
                f"<h2>{testo_base}</h2>"
                "<hr>"
                f"<p><b>{autore_label}:</b> Andres Zanzani<br>"
                "<b>Email:</b> <a href='mailto:azanzani@gmail.com'>azanzani@gmail.com</a></p>"
                f"<p><b>{dona_label}:</b><br>"
                "<a href='https://paypal.me/azanzani'>paypal.me/azanzani</a></p>"
            )
            
            msg.setText(content)
            # Usiamo l'icona informativa standard
            msg.setIcon(QMessageBox.Icon.Information)
    
            # --- LOGICA SEGRETA: Triplo click sulla scritta NotePadPQ ---
            for label in msg.findChildren(QLabel):
                if "NotePadPQ" in label.text():
                    # Cambiamo il cursore per dare un indizio che "c'è qualcosa"
                    label.setCursor(Qt.CursorShape.PointingHandCursor)
                    # Installiamo il filtro
                    self._about_arc_filter = TripleClickFilter(self, self._launch_arcade)
                    label.installEventFilter(self._about_arc_filter)
            # ------------------------------------------------------------
    
            msg.exec()

    def action_check_updates(self) -> None:
            import urllib.request
            import json
            from PyQt6.QtCore import QUrl
    
            # URL delle API di GitHub per l'ultima release del tuo progetto
            api_url = "https://api.github.com/repos/buzzqw/NotePadPQ/releases/latest"
            
            try:
                # Effettuiamo la richiesta 
                req = urllib.request.Request(api_url, headers={"User-Agent": "NotePadPQ"})
                with urllib.request.urlopen(req, timeout=5.0) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    
                    latest_version = data.get("tag_name", "").lstrip("v")
                    release_url = data.get("html_url", "https://github.com/buzzqw/NotePadPQ/releases")
                    
                    current_version = self.APP_VERSION
                    titolo = tr("action.check_updates")
                    
                    if latest_version > current_version:
                        # Recupera il messaggio di aggiornamento disponibile dal JSON
                        testo = tr("msg.update_prompt", current=current_version, latest=latest_version)
                        reply = QMessageBox.question(
                            self, titolo, testo,
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if reply == QMessageBox.StandardButton.Yes:
                            _open_url(QUrl(release_url))
                    else:
                        # Recupera il messaggio di software aggiornato dal JSON
                        testo = tr("msg.update_ok", current=current_version)
                        QMessageBox.information(self, titolo, testo)
                        
            except Exception as e:
                # Recupera il messaggio di errore dal JSON
                testo_errore = tr("msg.update_error", error=str(e))
                titolo_errore = tr("dialog.error")
                QMessageBox.warning(self, titolo_errore, testo_errore)
            

    def action_donate(self) -> None:
        """Apre la pagina di donazione PayPal nel browser."""
        from PyQt6.QtCore import QUrl
        url = QUrl("https://www.paypal.com/cgi-bin/webscr?cmd=_donations"
                   "&business=azanzani@gmail.com&item_name=Support+NotePadPQ+Project")
        _open_url(url)

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
            QMessageBox.information(self, self.APP_NAME, tr("msg.macro_no_macro"))
            return
        n, ok = QInputDialog.getInt(
            self, tr("msg.macro_play_n_title"), tr("msg.macro_play_n_prompt"), 1, 1, 9999
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
        """Gestisce la modifica o l'eliminazione esterna del file."""
        if not editor or not editor.file_path:
            return

        if getattr(editor, "_is_saving", False):
            return

        editor._watcher.blockSignals(True)

        # Caso: file eliminato dal disco
        if not editor.file_path.exists():
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.APP_NAME)
            msg_box.setText(tr("msg.file_deleted_on_disk", name=editor.file_path.name))
            msg_box.setIcon(QMessageBox.Icon.Warning)

            btn_close = msg_box.addButton(tr("action.close_tab"), QMessageBox.ButtonRole.ActionRole)
            btn_keep  = msg_box.addButton(tr("action.keep_open"),  QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_keep)

            msg_box.exec()

            if msg_box.clickedButton() == btn_close:
                tm = self._tab_manager.tab_manager_for(editor)
                if tm:
                    container = tm._containers.get(editor)
                    if container:
                        tm._close_tab_at(tm.indexOf(container))
            else:
                editor._watcher.blockSignals(False)
            return

        # Caso: file modificato da un programma esterno
        from config.settings import Settings
        if Settings.instance().get("file/autoreload_on_change", False):
            try:
                from core.file_manager import FileManager
                content, enc, le = FileManager.read(editor.file_path)
                editor.load_content(content, enc, le)
                editor.setModified(False)
                self.statusBar().showMessage(
                    f"🔄 {editor.file_path.name} ricaricato automaticamente", 3000)
            except Exception:
                pass
            if editor.file_path.exists():
                editor._watcher.addPath(str(editor.file_path))
            editor._watcher.blockSignals(False)
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.APP_NAME)
        msg_box.setText(tr("msg.file_changed_on_disk", name=editor.file_path.name))
        msg_box.setIcon(QMessageBox.Icon.Question)

        btn_reload    = msg_box.addButton(tr("action.reload"),          QMessageBox.ButtonRole.ActionRole)
        btn_compare   = msg_box.addButton(tr("action.compare_changes"),  QMessageBox.ButtonRole.ActionRole)
        btn_overwrite = msg_box.addButton(tr("action.overwrite"),        QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton(tr("button.cancel"),                           QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()
        clicked = msg_box.clickedButton()

        if clicked == btn_reload:
            from core.file_manager import FileManager
            try:
                content, enc, le = FileManager.read(editor.file_path)
                editor.load_content(content, enc, le)
                editor.setModified(False)
                self.statusBar().showMessage(f"🔄 File ricaricato: {editor.file_path.name}", 3000)
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile ricaricare: {e}")

        elif clicked == btn_compare:
            import tempfile
            from pathlib import Path

            with tempfile.NamedTemporaryFile(mode='w', delete=False,
                                             suffix=editor.file_path.suffix,
                                             encoding=editor.encoding) as tmp:
                tmp.write(editor.get_content())
                tmp_path = Path(tmp.name)

            from ui.compare import CompareDialog
            dlg = CompareDialog(self)

            if hasattr(dlg, "set_files"):
                dlg.set_files(editor.file_path, tmp_path)

            dlg.exec()

            try:
                tmp_path.unlink()
            except Exception:
                pass

        elif clicked == btn_overwrite:
            self._save_editor(editor, editor.file_path)

        # Riattiva il monitoraggio
        if editor.file_path.exists():
            editor._watcher.addPath(str(editor.file_path))
        editor._watcher.blockSignals(False)
        
    # ── Orologio in alto a destra ─────────────────────────────────────────────

    # ── Orologio in alto a destra ─────────────────────────────────────────────

    def _setup_writing_goal(self) -> None:
        self._writing_goal: int = 0
        self._wg_timer = QTimer(self)
        self._wg_timer.setSingleShot(True)
        self._wg_timer.setInterval(600)
        self._wg_timer.timeout.connect(self._update_writing_goal_display)

    def _update_writing_goal_display(self) -> None:
        if self._writing_goal <= 0:
            self._statusbar.hide_word_goal()
            return
        editor = self._current_editor()
        if not editor:
            self._statusbar.hide_word_goal()
            return
        words = len(editor.text().split())
        self._statusbar.set_word_goal(words, self._writing_goal)

    def action_writing_goal(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        current = self._writing_goal
        val, ok = QInputDialog.getInt(
            self,
            tr("action.writing_goal_set"),
            tr("label.writing_goal_prompt"),
            current, 0, 999999, 100
        )
        if not ok:
            return
        self._writing_goal = val
        if val <= 0:
            self._statusbar.hide_word_goal()
        else:
            self._update_writing_goal_display()
            # Collega textChanged dell'editor corrente al timer
            editor = self._current_editor()
            if editor:
                try:
                    editor.textChanged.disconnect(self._wg_timer.start)
                except (RuntimeError, TypeError):
                    pass
                editor.textChanged.connect(self._wg_timer.start)

    def _setup_logo_corner(self) -> None:
        """Aggiunge l'icona dell'app nel corner sinistro della menubar."""
        from PyQt6.QtWidgets import QToolButton
        from PyQt6.QtCore import QSize
        from pathlib import Path

        btn = QToolButton(self)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(f"{self.APP_NAME}  v{self.APP_VERSION}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.action_about)

        # Carica l'icona dell'app nelle dimensioni disponibili
        icons_dir = Path(__file__).parent.parent / "icons"
        icon = QIcon()
        for size in [32, 48, 64, 128, 256]:
            p = icons_dir / f"NotePadPQ_{size}.png"
            if p.exists():
                icon.addFile(str(p))
        if icon.isNull():
            for name in ["NotePadPQ.png", "NotePadPQ.svg"]:
                p = icons_dir / name
                if p.exists():
                    icon = QIcon(str(p))
                    break
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(QSize(18, 18))

        btn.setStyleSheet(
            "QToolButton { border: none; margin: 0 4px; background: transparent; }"
            "QToolButton:hover { background: rgba(128,128,128,0.15); border-radius: 4px; }"
        )
        self.menuBar().setCornerWidget(btn, Qt.Corner.TopLeftCorner)
        self._logo_btn = btn

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
        """Allinea automaticamente le colonne di una tabella in LaTeX (&), Markdown (|) o testo generico."""
        editor = self._current_editor()
        if not editor:
            return

        from editor.lexers import get_language_name
        lang = get_language_name(editor).lower()

        _lang_words = set(lang.split())
        _is_latex_lang = "latex" in lang or bool(_lang_words & {"tex", "bibtex", "plaintex"})
        if "markdown" in lang:
            sep = "|"
        elif _is_latex_lang:
            sep = "&"
        else:
            sep = None

        is_md = "markdown" in lang

        _LATEX_PASS_CMDS = (
            r"\hline", r"\toprule", r"\midrule", r"\bottomrule", r"\cline",
            r"\endfirsthead", r"\endhead", r"\endfoot", r"\endlastfoot",
        )

        def is_table_line(ln: int) -> bool:
            txt = editor.text(ln).rstrip("\n\r")
            if sep == "|":
                return "|" in txt
            elif sep == "&":
                return "&" in txt or any(txt.strip().startswith(c) for c in _LATEX_PASS_CMDS)
            else:
                return "|" in txt or "&" in txt or "\t" in txt

        # Auto-selezione quando non c'è testo selezionato
        if not editor.hasSelectedText():
            cur_line, _ = editor.getCursorPosition()
            line_count = editor.lines()
            if not is_table_line(cur_line):
                self.statusBar().showMessage("⚠️ Cursore non su una riga di tabella.", 3000)
                return
            start_line = cur_line
            while start_line > 0 and is_table_line(start_line - 1):
                start_line -= 1
            end_line = cur_line
            while end_line < line_count - 1 and is_table_line(end_line + 1):
                end_line += 1
            end_col = len(editor.text(end_line).rstrip("\n\r"))
            editor.setSelection(start_line, 0, end_line, end_col)

        text = editor.selectedText()
        lines = text.splitlines()
        if not lines:
            return

        # Auto-detect separatore per file generici
        if sep is None:
            pipe_count = sum(line.count("|") for line in lines)
            amp_count  = sum(line.count("&")  for line in lines)
            tab_count  = sum(line.count("\t")  for line in lines)
            if tab_count >= max(pipe_count, amp_count) and tab_count > 0:
                sep = "\t"
            elif pipe_count >= amp_count and pipe_count > 0:
                sep = "|"
            elif amp_count > 0:
                sep = "&"
            else:
                self.statusBar().showMessage("⚠️ Nessun separatore rilevato nel testo selezionato (|, &, tab).", 3000)
                return

        # Parsing: None = riga non-dati (passa invariata)
        parsed = []
        for line in lines:
            end_marker = ""
            if sep == "&":
                stripped = line.strip()
                if "&" not in line:
                    parsed.append(None)
                    continue
                line_stripped = line.rstrip()
                if line_stripped.endswith(r"\\"):
                    end_marker = r" \\"
                    line = line_stripped[:-2]
            cells = [c.strip() for c in line.split(sep)]
            # Rimuove celle vuote iniziali/finali generate da | col | col | format
            if sep == "|":
                if cells and cells[0] == '':
                    cells = cells[1:]
                if cells and cells[-1] == '':
                    cells = cells[:-1]
            parsed.append((cells, end_marker))

        # Larghezza massima per colonna (solo righe dati)
        max_cols = max((len(cells) for row in parsed if row is not None for cells, _ in [row]), default=0)
        col_widths = [0] * max_cols
        for row in parsed:
            if row is None:
                continue
            cells, _ = row
            for i, cell in enumerate(cells):
                if i < max_cols:
                    col_widths[i] = max(col_widths[i], len(cell))

        def pad_md_sep(cell: str, w: int) -> str:
            lc = cell.startswith(":")
            rc = cell.endswith(":")
            inner = max(1, w - int(lc) - int(rc))
            return (":" if lc else "") + "-" * inner + (":" if rc else "")

        # Ricostruzione righe allineate
        new_lines = []
        for idx, row in enumerate(parsed):
            if row is None:
                new_lines.append(lines[idx])
                continue
            cells, end_marker = row
            padded = []
            for i, cell in enumerate(cells):
                w = col_widths[i] if i < len(col_widths) else len(cell)
                if is_md and set(cell) <= {"-", ":"}:
                    padded.append(pad_md_sep(cell, w))
                else:
                    padded.append(cell.ljust(w))
            if sep == "\t":
                joined_line = "\t".join(padded)
            elif sep == "|":
                joined_line = "| " + " | ".join(padded) + " |"
            else:
                joined_line = f" {sep} ".join(padded).strip()
            if end_marker:
                joined_line += end_marker

            new_lines.append(joined_line)

        aligned_text = "\n".join(new_lines)
        editor.replaceSelectedText(aligned_text)
        self.statusBar().showMessage("✨ Tabella allineata con successo!", 3000)

    # ── Convert ASCII table → Markdown / LaTeX ────────────────────────────────

    def _parse_ascii_table(self, text: str):
        """Parse a space-padded ASCII/Unicode table.

        Separator lines (all ─ ━ ═ - = + | chars) are skipped.
        Columns are split by 2+ consecutive spaces so that numeric
        right-aligned values always align correctly with their headers.
        Returns (headers: list[str], rows: list[list[str]]) or (None, None).
        """
        import re
        SEP_RE = re.compile(r'^[\s─━═\-=+|]+$')
        SPLIT_RE = re.compile(r'\s{2,}')

        data_lines = []
        for ln in text.splitlines():
            stripped = ln.strip()
            if not stripped:
                continue
            if SEP_RE.match(stripped):
                continue
            data_lines.append(stripped)

        if not data_lines:
            return None, None

        headers = SPLIT_RE.split(data_lines[0])
        if not headers:
            return None, None
        n = len(headers)
        rows = [(SPLIT_RE.split(ln) + [''] * n)[:n] for ln in data_lines[1:]]
        return headers, rows

    def action_convert_table_md(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        text = editor.selectedText() if editor.hasSelectedText() else editor.text()
        headers, rows = self._parse_ascii_table(text)
        if not headers:
            self.statusBar().showMessage("⚠️ Nessuna tabella rilevata nel testo.", 3000)
            return

        n = len(headers)
        out = []
        out.append("| " + " | ".join(headers) + " |")
        out.append("| " + " | ".join(["---"] * n) + " |")
        for row in rows:
            padded = (row + [""] * n)[:n]
            out.append("| " + " | ".join(padded) + " |")

        result = "\n".join(out)
        if editor.hasSelectedText():
            editor.replaceSelectedText(result)
        else:
            editor.beginUndoAction()
            editor.selectAll()
            editor.replaceSelectedText(result)
            editor.endUndoAction()
        self.statusBar().showMessage("✨ Tabella convertita in Markdown!", 3000)

    def action_convert_table_tex(self) -> None:
        import re
        editor = self._current_editor()
        if not editor:
            return
        text = editor.selectedText() if editor.hasSelectedText() else editor.text()
        headers, rows = self._parse_ascii_table(text)
        if not headers:
            self.statusBar().showMessage("⚠️ Nessuna tabella rilevata nel testo.", 3000)
            return

        # Detect numeric columns for right-alignment
        NUM_RE = re.compile(r'^-?\d[\d.,]*[%hHkKmMgGbBkK]?$|^N/A$|^-$|^$')
        n = len(headers)
        alignments = []
        for i in range(n):
            vals = [(row[i] if i < len(row) else "") for row in rows]
            if i == 0 or not all(NUM_RE.match(v) for v in vals):
                alignments.append("l")
            else:
                alignments.append("r")
        col_spec = "".join(alignments)

        _ESC = str.maketrans({"&": r"\&", "%": r"\%", "_": r"\_", "#": r"\#",
                               "$": r"\$", "{": r"\{", "}": r"\}", "^": r"\^{}", "~": r"\textasciitilde{}"})

        def esc(s: str) -> str:
            return s.translate(_ESC)

        out = []
        out.append(f"\\begin{{tabularx}}{{\\linewidth}}{{{col_spec}}}")
        out.append("\\toprule")
        out.append(" & ".join(esc(h) for h in headers) + " \\\\")
        out.append("\\midrule")
        for row in rows:
            padded = (row + [""] * n)[:n]
            out.append(" & ".join(esc(c) for c in padded) + " \\\\")
        out.append("\\bottomrule")
        out.append("\\end{tabularx}")

        result = "\n".join(out)
        if editor.hasSelectedText():
            editor.replaceSelectedText(result)
        else:
            editor.beginUndoAction()
            editor.selectAll()
            editor.replaceSelectedText(result)
            editor.endUndoAction()
        self.statusBar().showMessage("✨ Tabella convertita in LaTeX tabularx!", 3000)

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
        # Aggiorna il checkmark nel submenu lingua
        if hasattr(self, "_spell_lang_actions"):
            for code, act in self._spell_lang_actions.items():
                act.blockSignals(True)
                act.setChecked(code == lang)
                act.blockSignals(False)

    def _open_spell_check_dialog(self) -> None:
        """Apre il dialog avanzato di controllo ortografico (stile LibreOffice)."""
        editor = self._current_editor()
        if editor is None:
            return
        # Se lo spell check non è ancora attivo, lo abilita prima di aprire il dialog
        if getattr(editor, "_spell_checker", None) is None:
            from config.settings import Settings
            lang = Settings.instance().get("spellcheck/language", "it")
            if hasattr(editor, "set_spellcheck_enabled"):
                editor.set_spellcheck_enabled(True, lang)
            # Segna il toggle come attivo
            if "spell_check" in self._actions:
                self._actions["spell_check"].setChecked(True)
            from config.settings import Settings as _S
            _S.instance().set("spellcheck/enabled", True)
        from ui.spell_check_dialog import SpellCheckDialog
        dlg = SpellCheckDialog(editor, parent=self)
        dlg.exec()

    # ── Tipografia intelligente ───────────────────────────────────────────────

    def _toggle_smart_typography(self, checked: bool) -> None:
        from config.settings import Settings
        Settings.instance().set("editor/smart_typography", checked)
        # Aggiorna la preferenza nel dialog se aperto (non strettamente necessario)

    # ── Focus paragrafo ───────────────────────────────────────────────────────

    def _toggle_sentence_focus(self, checked: bool) -> None:
        from config.settings import Settings
        Settings.instance().set("editor/sentence_focus", checked)
        editor = self._current_editor()
        if editor is None:
            return
        try:
            from editor.markdown_support import MarkdownSupport
            if checked:
                MarkdownSupport.apply_paragraph_focus(editor)
                # Ricollega cursore per aggiornare il focus in tempo reale
                try:
                    editor.cursorPositionChanged.disconnect(self._on_focus_cursor_moved)
                except Exception:
                    pass
                editor.cursorPositionChanged.connect(self._on_focus_cursor_moved)
            else:
                MarkdownSupport.clear_paragraph_focus(editor)
                try:
                    editor.cursorPositionChanged.disconnect(self._on_focus_cursor_moved)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_focus_cursor_moved(self) -> None:
        """Aggiorna il focus paragrafo quando il cursore si sposta."""
        if not self._actions.get("sentence_focus", None) or \
                not self._actions["sentence_focus"].isChecked():
            return
        editor = self._current_editor()
        if editor:
            try:
                from editor.markdown_support import MarkdownSupport
                MarkdownSupport.apply_paragraph_focus(editor)
            except Exception:
                pass

    # ── Toggle checklist ─────────────────────────────────────────────────────

    def _action_toggle_checklist(self) -> None:
        editor = self._current_editor()
        if editor is None:
            return
        try:
            from editor.markdown_support import MarkdownSupport
            MarkdownSupport.toggle_checklist(editor)
        except Exception:
            pass
                    
    # ── Monitoraggio Risorse (RAM / CPU) ──────────────────────────────────────

    def _setup_resource_monitor(self) -> None:
        """Inizializza il widget nella statusbar per mostrare RAM e CPU del processo."""
        self._resource_label = QLabel(" RAM: -- MB / -- / -- GB | CPU: --% / --% ")
        self._resource_label.setStyleSheet("padding: 0 8px;")
        self._statusbar.addPermanentWidget(self._resource_label)

        self._resource_timer = QTimer(self)
        self._resource_timer.timeout.connect(self._update_resource_usage)
        self._resource_timer.start(2000)

        try:
            import psutil
            import os
            self._process = psutil.Process(os.getpid())
            self._cpu_count = psutil.cpu_count() or 1
            # Prima chiamata: inizializza il delta per cpu_percent
            self._process.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None)
        except ImportError:
            self._process = None
            self._resource_label.setText(" [Installa 'psutil' per RAM/CPU] ")
            self._resource_label.setToolTip("Da terminale esegui: pip install psutil")

    def _update_resource_usage(self) -> None:
        """Calcola e aggiorna i valori di RAM e CPU nella statusbar."""
        if not getattr(self, "_process", None):
            return
        try:
            import psutil

            # RAM: app / sistema usata / sistema totale
            app_mb  = self._process.memory_info().rss / (1024 ** 2)
            vm      = psutil.virtual_memory()
            sys_used_gb  = vm.used  / (1024 ** 3)
            sys_total_gb = vm.total / (1024 ** 3)

            # CPU: app (normalizzata per core) / sistema
            app_cpu = self._process.cpu_percent(interval=None) / self._cpu_count
            sys_cpu = psutil.cpu_percent(interval=None)

            self._resource_label.setText(
                f" RAM: {app_mb:.0f} MB / {sys_used_gb:.1f} / {sys_total_gb:.0f} GB"
                f" | CPU: {app_cpu:.1f}% / {sys_cpu:.0f}% "
            )
            self._resource_label.setToolTip(
                f"RAM applicazione:  {app_mb:.1f} MB\n"
                f"RAM usata sistema: {sys_used_gb:.2f} GB\n"
                f"RAM totale:        {sys_total_gb:.2f} GB\n"
                f"CPU applicazione:  {app_cpu:.2f}%\n"
                f"CPU sistema:       {sys_cpu:.1f}%"
            )
        except Exception:
            pass


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
