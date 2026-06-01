"""
ui/preferences.py — Dialog Preferenze
NotePadPQ

Finestra preferenze completa, organizzata in schede:
  - Editor      (font, tab, indentazione, comportamento)
  - Aspetto     (tema, colori UI)
  - File        (encoding, line ending, backup, sessione)
  - Autocompletamento
  - Preview
  - Build
  - Lingua      (i18n)

Usa Settings.instance() per leggere/scrivere.
Emette settings_changed su ogni modifica salvata.
"""

from __future__ import annotations

import json as _json
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QTabWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QSlider, QPushButton, QFileDialog, QMessageBox,
    QListWidget, QListWidgetItem, QSizePolicy,
    QScrollArea, QFrame,
)

from config.settings import Settings
from config.themes import ThemeManager
from i18n.i18n import tr


class PreferencesDialog(QDialog):
    """Dialog modale preferenze, organizzata a schede."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = Settings.instance()
        self._theme_mgr = ThemeManager.instance()

        self.setWindowTitle(tr("dialog.preferences", default="Preferenze"))
        self.setMinimumSize(680, 520)
        self.resize(720, 680)

        self._build_ui()
        self._load_values()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._tab_editor(),  tr("pref.tab.editor",  default="Editor"))
        self._tabs.addTab(self._tab_aspect(),  tr("pref.tab.aspect",  default="Aspetto"))
        self._tabs.addTab(self._tab_file(),    tr("pref.tab.file",    default="File"))
        self._tabs.addTab(self._tab_autocomplete(), tr("pref.tab.autocomplete", default="Autocompletamento"))
        self._tabs.addTab(self._tab_preview(), tr("pref.tab.preview", default="Anteprima"))
        self._tabs.addTab(self._tab_build(),   tr("pref.tab.build",   default="Build"))
        self._tabs.addTab(self._tab_function_list(), tr("pref.tab.function_list", default="Function List"))
        self._tabs.addTab(self._tab_i18n(),    tr("pref.tab.language",default="Lingua"))

        # Pulsanti OK / Annulla / Applica
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        layout.addWidget(buttons)

    # ── Scheda Editor ─────────────────────────────────────────────────────────

    def _tab_editor(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout()
        w.setLayout(vl)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Font
        grp_font = QGroupBox(tr("pref.editor.font", default="Font"))
        fl = QFormLayout()
        grp_font.setLayout(fl)

        self._font_family = QComboBox()
        self._font_family.setEditable(True)
        mono_fonts = QFontDatabase.families(QFontDatabase.WritingSystem.Latin)
        for f in mono_fonts:
            if QFontDatabase.isFixedPitch(f):
                self._font_family.addItem(f)
        fl.addRow(tr("pref.editor.font_family", default="Famiglia:"), self._font_family)

        self._font_size = QSpinBox()
        self._font_size.setRange(6, 72)
        self._font_size.setSuffix(" pt")
        fl.addRow(tr("pref.editor.font_size", default="Dimensione:"), self._font_size)

        vl.addWidget(grp_font)

        # Indentazione
        grp_indent = QGroupBox(tr("pref.editor.indent", default="Indentazione"))
        il = QFormLayout()
        grp_indent.setLayout(il)

        self._tab_width = QSpinBox()
        self._tab_width.setRange(1, 16)
        il.addRow(tr("pref.editor.tab_width", default="Larghezza tab:"), self._tab_width)

        self._use_tabs = QCheckBox(tr("pref.editor.use_tabs", default="Usa tabulazioni (invece di spazi)"))
        il.addRow("", self._use_tabs)

        self._auto_indent = QCheckBox(tr("pref.editor.auto_indent", default="Indentazione automatica"))
        il.addRow("", self._auto_indent)

        vl.addWidget(grp_indent)

        # Edge column (riga guida verticale)
        grp_edge = QGroupBox(tr("pref.editor.edge_group"))
        el = QFormLayout(grp_edge)
        self._edge_column = QSpinBox()
        self._edge_column.setRange(0, 300)
        self._edge_column.setSpecialValueText(tr("pref.editor.edge_disabled"))
        self._edge_column.setSuffix(tr("pref.editor.edge_col_suffix"))
        el.addRow(tr("pref.editor.edge_col_label"), self._edge_column)
        vl.addWidget(grp_edge)

        vl.addStretch()
        return w

    # ── Scheda Aspetto ────────────────────────────────────────────────────────

    def _tab_aspect(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- GRUPPO TEMA ---
        grp_theme = QGroupBox(tr("pref.aspect.theme", default="Tema"))
        tl = QFormLayout(grp_theme)

        self._theme_combo = QComboBox()
        for t in self._theme_mgr.available_themes():
            self._theme_combo.addItem(t)
        tl.addRow(tr("pref.aspect.active_theme", default="Tema attivo:"), self._theme_combo)
        self._theme_combo.currentTextChanged.connect(self._apply_theme_preview)

        btn_theme_editor = QPushButton(tr("pref.aspect.edit_theme", default="Modifica tema…"))
        btn_theme_editor.clicked.connect(self._open_theme_editor)
        tl.addRow("", btn_theme_editor)

        btn_import = QPushButton(tr("pref.aspect.import_theme", default="Importa tema JSON…"))
        btn_import.clicked.connect(self._import_theme)
        tl.addRow("", btn_import)

        btn_export = QPushButton(tr("pref.aspect.export_theme", default="Esporta tema JSON…"))
        btn_export.clicked.connect(self._export_theme)
        tl.addRow("", btn_export)

        vl.addWidget(grp_theme)
        
        # --- GRUPPO ICONE ---
        grp_icons = QGroupBox(tr("pref.aspect.icons"))
        il = QFormLayout(grp_icons)

        self._icon_set_combo = QComboBox()
        self._icon_set_combo.addItem(tr("pref.aspect.icon_lucide"),   "lucide")
        self._icon_set_combo.addItem(tr("pref.aspect.icon_material"), "material")
        self._icon_set_combo.addItem(tr("pref.aspect.icon_system"),   "system")

        il.addRow(tr("pref.aspect.icon_set_label"), self._icon_set_combo)

        note_icon = QLabel(tr("pref.aspect.icon_note"))
        note_icon.setWordWrap(True)
        note_icon.setStyleSheet("color: gray; font-size: 11px;")
        il.addRow("", note_icon)

        vl.addWidget(grp_icons)

        vl.addStretch()
        return w

    # ── Scheda File ───────────────────────────────────────────────────────────

    def _tab_file(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        grp_enc = QGroupBox(tr("pref.file.encoding", default="Encoding e line ending"))
        el = QFormLayout(grp_enc)

        self._default_encoding = QComboBox()
        for enc in ["UTF-8", "UTF-8-BOM", "Latin-1", "CP1252", "GB2312", "UTF-16"]:
            self._default_encoding.addItem(enc)
        el.addRow(tr("pref.file.def_encoding", default="Encoding predefinito:"), self._default_encoding)

        self._default_le = QComboBox()
        for le in ["LF", "CRLF", "CR"]:
            self._default_le.addItem(le)
        el.addRow(tr("pref.file.def_le", default="Line ending predefinito:"), self._default_le)

        vl.addWidget(grp_enc)

        grp_save = QGroupBox(tr("pref.file.save", default="Salvataggio"))
        sl = QVBoxLayout(grp_save)

        self._backup_on_save   = QCheckBox(tr("pref.file.backup",   default="Crea backup al salvataggio (.bak)"))
        self._trim_trailing    = QCheckBox(tr("pref.file.trim",     default="Rimuovi spazi in coda al salvataggio"))
        self._add_newline_eof  = QCheckBox(tr("pref.file.newline_eof", default="Aggiungi nuova riga a fine file"))
        self._restore_session  = QCheckBox(tr("pref.file.restore_session", default="Ripristina sessione all'avvio"))

        for cb in (self._backup_on_save, self._trim_trailing,
                   self._add_newline_eof, self._restore_session):
            sl.addWidget(cb)

        vl.addWidget(grp_save)

        grp_recent = QGroupBox(tr("pref.file.recent", default="File recenti"))
        rl = QFormLayout(grp_recent)
        self._recent_max = QSpinBox()
        self._recent_max.setRange(5, 50)
        rl.addRow(tr("pref.file.recent_max", default="Numero massimo:"), self._recent_max)
        vl.addWidget(grp_recent)

        grp_autobackup = QGroupBox(tr("pref.file.autobackup_group"))
        al = QFormLayout(grp_autobackup)

        self._autobackup_enabled = QCheckBox(tr("pref.file.autobackup_enabled"))
        al.addRow("", self._autobackup_enabled)

        self._autosave_to_backup = QCheckBox(tr("pref.file.autosave_to_backup"))
        self._autosave_to_backup.setToolTip(tr("tooltip.pref_autosave_to_backup"))
        al.addRow("", self._autosave_to_backup)

        self._autobackup_interval = QSpinBox()
        self._autobackup_interval.setRange(1, 120)
        self._autobackup_interval.setSuffix(tr("pref.file.autobackup_interval_suffix"))
        al.addRow(tr("pref.file.autobackup_interval_label"), self._autobackup_interval)

        backup_dir_row = QHBoxLayout()
        self._autobackup_dir = QLineEdit()
        self._autobackup_dir.setPlaceholderText(tr("pref.file.autobackup_dir_placeholder"))
        self._autobackup_dir.setReadOnly(True)
        btn_browse_backup = QPushButton(tr("pref.file.browse"))
        btn_browse_backup.clicked.connect(self._browse_backup_dir)
        backup_dir_row.addWidget(self._autobackup_dir, 1)
        backup_dir_row.addWidget(btn_browse_backup)
        al.addRow(tr("pref.file.autobackup_dir_label"), backup_dir_row)

        vl.addWidget(grp_autobackup)

        grp_autosave = QGroupBox(tr("pref.file.autosave_group"))
        asl = QVBoxLayout(grp_autosave)
        self._autoreload_on_change   = QCheckBox(tr("pref.file.autoreload"))
        asl.addWidget(self._autoreload_on_change)
        self._autosave_on_focus_loss = QCheckBox(tr("pref.file.autosave_focus_loss"))
        asl.addWidget(self._autosave_on_focus_loss)
        vl.addWidget(grp_autosave)

        vl.addStretch()
        return w

    # ── Scheda Autocompletamento ──────────────────────────────────────────────

    def _tab_autocomplete(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        grp = QGroupBox(tr("pref.ac.general", default="Autocompletamento"))
        gl = QVBoxLayout(grp)

        self._ac_enabled  = QCheckBox(tr("pref.ac.enabled",    default="Abilita autocompletamento"))
        self._ac_cross    = QCheckBox(tr("pref.ac.cross_tab",  default="Parole da tutti i tab aperti"))
        self._ac_snippets = QCheckBox(tr("pref.ac.snippets",   default="Snippet per linguaggio"))
        self._ac_api      = QCheckBox(tr("pref.ac.api_dict",   default="Dizionari API per linguaggio"))
        self._ac_lsp      = QCheckBox(tr("pref.ac.lsp",        default="LSP (Language Server Protocol, se installato)"))

        for cb in (self._ac_enabled, self._ac_cross, self._ac_snippets,
                   self._ac_api, self._ac_lsp):
            gl.addWidget(cb)

        fl = QFormLayout()
        self._ac_threshold = QSpinBox()
        self._ac_threshold.setRange(1, 10)
        self._ac_threshold.setSuffix(tr("pref.ac.chars", default=" caratteri"))
        fl.addRow(tr("pref.ac.trigger", default="Attiva dopo:"), self._ac_threshold)
        gl.addLayout(fl)

        vl.addWidget(grp)
        vl.addStretch()
        return w

    # ── Scheda Preview ────────────────────────────────────────────────────────

    def _tab_preview(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        grp = QGroupBox(tr("pref.preview.general", default="Pannello anteprima"))
        gl = QVBoxLayout(grp)

        self._preview_sync    = QCheckBox(tr("pref.preview.sync",
                                             default="Sincronizzazione cursore ↔ anteprima"))
        gl.addWidget(self._preview_sync)

        fl = QFormLayout()
        self._preview_delay = QSpinBox()
        self._preview_delay.setRange(100, 5000)
        self._preview_delay.setSingleStep(100)
        self._preview_delay.setSuffix(" ms")
        fl.addRow(tr("pref.preview.delay", default="Ritardo aggiornamento:"), self._preview_delay)
        gl.addLayout(fl)

        vl.addWidget(grp)
        vl.addStretch()
        return w

    # ── Scheda Build ──────────────────────────────────────────────────────────

    def _tab_build(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        grp = QGroupBox(tr("pref.build.general", default="Compilazione"))
        gl = QVBoxLayout(grp)

        self._build_save_before = QCheckBox(tr("pref.build.save_before",
                                               default="Salva automaticamente prima di compilare"))
        gl.addWidget(self._build_save_before)

        self._build_panel_always = QCheckBox(tr("pref.build.panel_always",
                                               default="Tieni sempre visibile il pannello di output"))
        gl.addWidget(self._build_panel_always)

        vl.addWidget(grp)

        # ── Terminale ─────────────────────────────────────────────────────────
        grp_term = QGroupBox(tr("pref.build.terminal_group"))
        tl = QFormLayout(grp_term)

        self._terminal_combo = QComboBox()
        _terminals = [
            (tr("pref.build.terminal_auto"),        ""),
            ("gnome-terminal",    "gnome-terminal --working-directory={DIR}"),
            ("konsole",           "konsole --workdir {DIR}"),
            ("xfce4-terminal",    "xfce4-terminal --working-directory={DIR}"),
            ("tilix",             "tilix --working-directory={DIR}"),
            ("alacritty",         "alacritty --working-directory {DIR}"),
            ("kitty",             "kitty --directory={DIR}"),
            ("lxterminal",        "lxterminal --working-directory={DIR}"),
            ("mate-terminal",     "mate-terminal --working-directory={DIR}"),
            ("xterm",             "xterm -e 'cd {DIR}; exec bash'"),
            ("Windows Terminal",  "wt.exe -d {DIR}"),
            ("cmd.exe",           'cmd.exe /K "cd /d {DIR}"'),
            (tr("pref.build.terminal_custom_item"), "__custom__"),
        ]
        for label, cmd in _terminals:
            self._terminal_combo.addItem(label, cmd)
        tl.addRow(tr("pref.build.terminal_label"), self._terminal_combo)

        self._terminal_custom = QLineEdit()
        self._terminal_custom.setPlaceholderText(tr("pref.build.terminal_placeholder"))
        self._terminal_custom.setToolTip(tr("tooltip.pref_terminal_custom"))
        tl.addRow(tr("pref.build.terminal_cmd_label"), self._terminal_custom)

        lbl_token = QLabel(tr("pref.build.terminal_dir_token"))
        lbl_token.setStyleSheet("color: gray; font-size: 9px;")
        tl.addRow("", lbl_token)

        vl.addWidget(grp_term)
        vl.addStretch()
        return w

    # ── Scheda Function List ──────────────────────────────────────────────────

    def _tab_function_list(self) -> QWidget:
        from ui.function_list import _JSON_PRESET_DEFS
        w = QWidget()
        vl = QVBoxLayout(w)
        # Niente AlignTop: vogliamo che il secondo widget si espanda

        # ── Preset disponibili ─────────────────────────────────────────────────
        grp_presets = QGroupBox(tr("pref.fl.presets_group", default="Preset disponibili"))
        pl = QVBoxLayout(grp_presets)
        note = QLabel(tr("pref.fl.presets_note",
                         default="Seleziona i preset da usare nella lista delle funzioni. "
                                  "I preset abilitati sostituiscono i parser integrati per quel linguaggio. "
                                  "Clicca su un preset per configurare quali pattern mostrare."))
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        pl.addWidget(note)

        self._fl_preset_list = QListWidget()
        self._fl_preset_list.setFixedHeight(180)
        self._fl_preset_list.setAlternatingRowColors(True)

        for data in _JSON_PRESET_DEFS:
            lang = data.get("language", "")
            name = data.get("display_name", lang)
            exts = ", ".join(data.get("extensions", []))
            count = len(data.get("patterns", []))
            label = f"{name}  ({exts})  —  {count} pattern"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, lang)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._fl_preset_list.addItem(item)

        pl.addWidget(self._fl_preset_list)
        vl.addWidget(grp_presets)

        # ── Pattern visibili (dinamico: si aggiorna con la selezione) ──────────
        self._fl_kinds_group = QGroupBox("—")
        self._fl_kinds_group.setEnabled(False)
        self._fl_kinds_group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        kinds_outer = QVBoxLayout(self._fl_kinds_group)
        kinds_outer.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fl_kinds_container = QWidget()
        self._fl_kinds_layout = QVBoxLayout(self._fl_kinds_container)
        self._fl_kinds_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._fl_kinds_layout.setSpacing(2)
        scroll.setWidget(self._fl_kinds_container)
        kinds_outer.addWidget(scroll)
        vl.addWidget(self._fl_kinds_group, stretch=1)

        # Stato interno
        self._fl_kind_checks: dict[str, QCheckBox] = {}
        self._fl_current_lang: Optional[str] = None
        self._fl_hidden_kinds_draft: dict[str, list] = {}
        # compat: mantieni _fl_latex_checks vuoto per non rompere vecchio codice
        self._fl_latex_checks: dict[str, QCheckBox] = {}

        self._fl_preset_list.currentItemChanged.connect(self._fl_on_preset_selected)

        return w

    def _fl_on_preset_selected(self, current, previous) -> None:
        """Salva lo stato del preset precedente e mostra i kind di quello nuovo."""
        if self._fl_current_lang and self._fl_kind_checks:
            hidden = [k for k, cb in self._fl_kind_checks.items() if not cb.isChecked()]
            self._fl_hidden_kinds_draft[self._fl_current_lang] = hidden

        if current is None:
            self._fl_current_lang = None
            self._fl_rebuild_kinds(None, set())
            return

        lang = current.data(Qt.ItemDataRole.UserRole)
        self._fl_current_lang = lang
        from ui.function_list import _JSON_PRESET_DEFS
        preset_def = next((d for d in _JSON_PRESET_DEFS if d.get("language") == lang), None)
        hidden_for_lang = set(self._fl_hidden_kinds_draft.get(lang, []))
        self._fl_rebuild_kinds(preset_def, hidden_for_lang)

    def _fl_rebuild_kinds(self, preset_def: Optional[dict], hidden: set) -> None:
        """Svuota e ricostruisce i checkbox dei kind per il preset selezionato."""
        while self._fl_kinds_layout.count():
            item = self._fl_kinds_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

        self._fl_kind_checks = {}

        if preset_def is None:
            self._fl_kinds_group.setTitle("—")
            self._fl_kinds_group.setEnabled(False)
            return

        self._fl_kinds_group.setEnabled(True)
        name = preset_def.get("display_name", preset_def.get("language", ""))
        self._fl_kinds_group.setTitle(
            tr("pref.fl.kinds_group", default="Pattern visibili") + f"  —  {name}"
        )

        seen: set[str] = set()
        for p in preset_def.get("patterns", []):
            kind = p.get("kind", "")
            icon = p.get("icon", "")
            if not kind or kind in seen:
                continue
            seen.add(kind)
            label = f"{icon}  {kind}" if icon else kind
            cb = QCheckBox(label)
            cb.setChecked(kind not in hidden)
            self._fl_kinds_layout.addWidget(cb)
            self._fl_kind_checks[kind] = cb

    # ── Scheda Lingua ─────────────────────────────────────────────────────────

    def _tab_i18n(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        grp = QGroupBox(tr("pref.lang.choose", default="Lingua interfaccia"))
        fl = QFormLayout(grp)

        self._lang_combo = QComboBox()
        from i18n.i18n import I18n as _I18n
        langs = sorted(_I18n.instance().available_languages().items(),
                       key=lambda x: x[1])   # ordine alfabetico per nome nativo
        for code, label in langs:
            self._lang_combo.addItem(label, code)
        fl.addRow(tr("pref.lang.label", default="Lingua:"), self._lang_combo)

        note = QLabel(tr("pref.lang.restart_note",
                         default="Il cambio lingua viene applicato immediatamente."))
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        fl.addRow("", note)

        vl.addWidget(grp)
        vl.addStretch()
        return w

    # ── Carica / Salva valori ─────────────────────────────────────────────────

    def _load_values(self) -> None:
        s = self._settings

        # Editor
        family = s.get("editor/font_family") or ""
        idx = self._font_family.findText(family)
        if idx >= 0:
            self._font_family.setCurrentIndex(idx)
        else:
            self._font_family.setCurrentText(family)
        self._font_size.setValue(s.get("editor/font_size", 11))
        self._tab_width.setValue(s.get("editor/tab_width", 4))
        self._use_tabs.setChecked(s.get("editor/use_tabs", False))
        self._auto_indent.setChecked(s.get("editor/auto_indent", True))
        self._edge_column.setValue(s.get("editor/edge_column",   0))

        # Aspetto
        theme_name = s.get("theme/active", "Dark")
        idx = self._theme_combo.findText(theme_name)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        # --- INIZIO CARICAMENTO ICONE ---
        icon_set = s.get("ui/icon_set", "lucide")
        self._original_icon_set = icon_set   # riferimento per confronto in _apply
        for i in range(self._icon_set_combo.count()):
            if self._icon_set_combo.itemData(i) == icon_set:
                self._icon_set_combo.setCurrentIndex(i)
                break
        # --- FINE CARICAMENTO ICONE ---

        # File
        enc = s.get("file/default_encoding", "UTF-8")
        idx = self._default_encoding.findText(enc)
        if idx >= 0:
            self._default_encoding.setCurrentIndex(idx)
        le = s.get("file/default_line_ending", "LF")
        idx = self._default_le.findText(le)
        if idx >= 0:
            self._default_le.setCurrentIndex(idx)
        self._backup_on_save.setChecked(s.get("file/backup_on_save", False))
        self._trim_trailing.setChecked(s.get("file/trim_trailing", False))
        self._add_newline_eof.setChecked(s.get("file/add_newline_eof", True))
        self._restore_session.setChecked(s.get("file/restore_session", True))
        self._recent_max.setValue(s.get("file/recent_max", 20))
        self._autobackup_enabled.setChecked(s.get("file/autobackup_enabled", False))
        self._autosave_to_backup.setChecked(s.get("file/autosave_to_backup", False))
        self._autobackup_interval.setValue(s.get("file/autobackup_interval", 5))
        self._autobackup_dir.setText(s.get("file/autobackup_dir", ""))
        #self._autosave_enabled.setChecked(s.get("file/autosave_enabled", False))
        #self._autosave_interval.setValue(s.get("file/autosave_interval", 2))
        self._autoreload_on_change.setChecked(s.get("file/autoreload_on_change", False))
        self._autosave_on_focus_loss.setChecked(s.get("file/autosave_on_focus_loss", False))

        # Autocompletamento
        self._ac_enabled.setChecked(s.get("autocomplete/enabled", True))
        self._ac_cross.setChecked(s.get("autocomplete/cross_tab", False))
        self._ac_snippets.setChecked(s.get("autocomplete/snippets", True))
        self._ac_api.setChecked(s.get("autocomplete/api_dict", True))
        self._ac_lsp.setChecked(s.get("autocomplete/lsp", False))
        self._ac_threshold.setValue(s.get("autocomplete/threshold", 2))

        # Preview
        self._preview_sync.setChecked(s.get("preview/sync_cursor", True))
        self._preview_delay.setValue(s.get("preview/delay_ms", 500))

        # Build
        self._build_save_before.setChecked(s.get("build/save_before", True))
        self._build_panel_always.setChecked(s.get("build/panel_always", False))
        saved_term_cmd = s.get("build/terminal_cmd", "")
        matched = False
        for i in range(self._terminal_combo.count()):
            if self._terminal_combo.itemData(i) == saved_term_cmd:
                self._terminal_combo.setCurrentIndex(i)
                matched = True
                break
        if not matched and saved_term_cmd:
            # Comando personalizzato salvato
            for i in range(self._terminal_combo.count()):
                if self._terminal_combo.itemData(i) == "__custom__":
                    self._terminal_combo.setCurrentIndex(i)
                    break
            self._terminal_custom.setText(saved_term_cmd)
        else:
            self._terminal_custom.setText("")
        # Function List — preset abilitati/disabilitati
        disabled_presets = set(
            k.strip() for k in
            (s.get("function_list/disabled_presets") or "").split(",")
            if k.strip()
        )
        for i in range(self._fl_preset_list.count()):
            item = self._fl_preset_list.item(i)
            lang = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(
                Qt.CheckState.Unchecked if lang in disabled_presets
                else Qt.CheckState.Checked
            )
        # Function List — kinds nascosti per preset (carica PRIMA di selezionare)
        try:
            self._fl_hidden_kinds_draft = _json.loads(
                s.get("function_list/hidden_kinds") or "{}"
            )
        except Exception:
            self._fl_hidden_kinds_draft = {}
        # Seleziona il primo preset: scatena _fl_on_preset_selected → mostra i kind
        if self._fl_preset_list.count() > 0:
            self._fl_preset_list.setCurrentRow(0)

        # Lingua — usa la lingua attualmente in uso (non il default hardcoded)
        from i18n.i18n import I18n
        lang = s.get("i18n/language", I18n.instance().current_language())
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == lang:
                self._lang_combo.setCurrentIndex(i)
                break

    def _apply_theme_preview(self, theme_name: str) -> None:
        """Applica il tema immediatamente a tutti gli editor aperti."""
        if not theme_name:
            return
        self._theme_mgr.set_active(theme_name)
        # Risale alla MainWindow
        mw = self.parent()
        while mw is not None and not hasattr(mw, "_tab_manager"):
            mw = mw.parent()
        if mw is None:
            return
        for ed in mw._tab_manager.all_editors():
            self._theme_mgr.apply_to_editor(ed, theme_name)
        
        # Risale alla MainWindow e applica il tema a tutti gli editor
        mw = self.parent()
        while mw is not None and not hasattr(mw, "_tab_manager"):
            mw = mw.parent()
        if mw is None:
            return
        for ed in mw._tab_manager.all_editors():
            self._theme_mgr.apply_to_editor(ed, theme_name)

    def _apply(self) -> None:
        s = self._settings

        # Editor
        family = self._font_family.currentText().strip()
        s.set("editor/font_family",       family or None)
        s.set("editor/font_size",         self._font_size.value())
        s.set("editor/tab_width",         self._tab_width.value())
        s.set("editor/use_tabs",          self._use_tabs.isChecked())
        s.set("editor/auto_indent",  self._auto_indent.isChecked())
        s.set("editor/edge_column", self._edge_column.value())

        # Aspetto — applica tema a caldo e ri-applica a tutti gli editor
        # (include le nuove impostazioni font che apply_to_editor legge da QSettings)
        theme_name = self._theme_combo.currentText()
        s.set("theme/active", theme_name)
        self._theme_mgr.set_active(theme_name)
        mw_apply = self.parent()
        while mw_apply is not None and not hasattr(mw_apply, "_tab_manager"):
            mw_apply = mw_apply.parent()
        if mw_apply is not None:
            for ed in mw_apply._tab_manager.all_editors():
                self._theme_mgr.apply_to_editor(ed, theme_name)
        
        # --- LOGICA ICONE E DOWNLOAD ---
        old_icon_set = getattr(self, "_original_icon_set", s.get("ui/icon_set", "lucide"))
        new_icon_set = self._icon_set_combo.currentData()

        if old_icon_set != new_icon_set:
            s.set("ui/icon_set", new_icon_set)
            self._original_icon_set = new_icon_set  # aggiorna per eventuali Applica successivi

            # Risale la catena dei parent per trovare la MainWindow
            mw = self.parent()
            while mw is not None and not hasattr(mw, "download_icon_set"):
                mw = mw.parent()

            if mw is not None:
                if new_icon_set != "system":
                    mw.download_icon_set(new_icon_set)
                else:
                    mw._rebuild_toolbar()
        # --------------------------------

        # File
        s.set("file/default_encoding",   self._default_encoding.currentText())
        s.set("file/default_line_ending",self._default_le.currentText())
        s.set("file/backup_on_save",     self._backup_on_save.isChecked())
        s.set("file/trim_trailing",      self._trim_trailing.isChecked())
        s.set("file/add_newline_eof",    self._add_newline_eof.isChecked())
        s.set("file/restore_session",    self._restore_session.isChecked())
        s.set("file/recent_max",         self._recent_max.value())
        s.set("file/autobackup_enabled",     self._autobackup_enabled.isChecked())
        s.set("file/autosave_to_backup",     self._autosave_to_backup.isChecked())
        s.set("file/autobackup_interval",    self._autobackup_interval.value())
        s.set("file/autobackup_dir",         self._autobackup_dir.text().strip())
        s.set("file/autoreload_on_change",   self._autoreload_on_change.isChecked())
        s.set("file/autosave_on_focus_loss", self._autosave_on_focus_loss.isChecked())
        
        # Autocompletamento
        s.set("autocomplete/enabled",   self._ac_enabled.isChecked())
        s.set("autocomplete/cross_tab", self._ac_cross.isChecked())
        s.set("autocomplete/snippets",  self._ac_snippets.isChecked())
        s.set("autocomplete/api_dict",  self._ac_api.isChecked())
        s.set("autocomplete/lsp",       self._ac_lsp.isChecked())
        s.set("autocomplete/threshold", self._ac_threshold.value())

        # Preview
        s.set("preview/sync_cursor",self._preview_sync.isChecked())
        s.set("preview/delay_ms",   self._preview_delay.value())

        # Build
        s.set("build/save_before",  self._build_save_before.isChecked())
        s.set("build/panel_always", self._build_panel_always.isChecked())
        term_data = self._terminal_combo.currentData()
        if term_data == "__custom__":
            s.set("build/terminal_cmd", self._terminal_custom.text().strip())
        else:
            s.set("build/terminal_cmd", term_data or "")
        # Applica subito la visibilità dei pannelli
        mw_panels = self.parent()
        if hasattr(mw_panels, "_build_dock"):
            if self._build_panel_always.isChecked():
                mw_panels._build_dock.show()

        # Function List — preset disabilitati
        disabled = []
        for i in range(self._fl_preset_list.count()):
            item = self._fl_preset_list.item(i)
            if item.checkState() == Qt.CheckState.Unchecked:
                disabled.append(item.data(Qt.ItemDataRole.UserRole))
        s.set("function_list/disabled_presets", ",".join(disabled))
        # Function List — kinds nascosti: salva prima il preset correntemente mostrato
        if self._fl_current_lang and self._fl_kind_checks:
            hidden = [k for k, cb in self._fl_kind_checks.items() if not cb.isChecked()]
            self._fl_hidden_kinds_draft[self._fl_current_lang] = hidden
        s.set("function_list/hidden_kinds", _json.dumps(self._fl_hidden_kinds_draft))
        # Forza refresh del pannello function list se aperto
        mw_fl = self.parent()
        while mw_fl and not hasattr(mw_fl, "_function_list_panel"):
            mw_fl = mw_fl.parent()
        if mw_fl and hasattr(mw_fl, "_function_list_panel"):
            try:
                mw_fl._function_list_panel._refresh()
            except Exception:
                pass

        # Lingua
        lang_code = self._lang_combo.currentData()
        from i18n.i18n import I18n
        old_lang  = s.get("i18n/language", I18n.instance().current_language())
        s.set("i18n/language", lang_code)
        if lang_code != old_lang:
            from i18n.i18n import I18n
            I18n.instance().set_language(lang_code)

    def _on_ok(self) -> None:
        self._apply()
        self.accept()

    # ── Azioni tema ───────────────────────────────────────────────────────────

    def _browse_backup_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Seleziona cartella autobackup",
            self._autobackup_dir.text() or ""
        )
        if d:
            self._autobackup_dir.setText(d)

    def _open_theme_editor(self) -> None:
        try:
            from ui.theme_editor import ThemeEditorDialog
            dlg = ThemeEditorDialog(self, self._theme_combo.currentText())
            if dlg.exec() == QDialog.DialogCode.Accepted:
                # Ricarica lista temi (potrebbe esserci un tema nuovo)
                current = self._theme_combo.currentText()
                self._theme_combo.clear()
                for t in self._theme_mgr.available_themes():
                    self._theme_combo.addItem(t)
                idx = self._theme_combo.findText(current)
                if idx >= 0:
                    self._theme_combo.setCurrentIndex(idx)
        except ImportError:
            QMessageBox.information(
                self,
                tr("dialog.info", default="Info"),
                tr("pref.theme_editor_unavailable",
                   default="Editor tema non disponibile in questa versione.")
            )

    def _import_theme(self) -> None:
        from pathlib import Path
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("pref.aspect.import_theme", default="Importa tema JSON"),
            "",
            "JSON (*.json)"
        )
        if not path:
            return
        name = self._theme_mgr.import_theme(Path(path))
        if name:
            self._theme_combo.clear()
            for t in self._theme_mgr.available_themes():
                self._theme_combo.addItem(t)
            idx = self._theme_combo.findText(name)
            if idx >= 0:
                self._theme_combo.setCurrentIndex(idx)
            QMessageBox.information(
                self,
                tr("dialog.ok", default="OK"),
                tr("pref.theme_imported", default="Tema importato: {name}", name=name)
            )
        else:
            QMessageBox.warning(
                self,
                tr("dialog.error", default="Errore"),
                tr("pref.theme_import_failed", default="Impossibile importare il tema.")
            )

    def _export_theme(self) -> None:
        from pathlib import Path
        name = self._theme_combo.currentText()
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("pref.aspect.export_theme", default="Esporta tema JSON"),
            f"{name}.json",
            "JSON (*.json)"
        )
        if not path:
            return
        ok = self._theme_mgr.export_theme(name, Path(path))
        if ok:
            QMessageBox.information(
                self,
                tr("dialog.ok", default="OK"),
                tr("pref.theme_exported", default="Tema esportato in {path}", path=path)
            )
        else:
            QMessageBox.warning(
                self,
                tr("dialog.error", default="Errore"),
                tr("pref.theme_export_failed", default="Impossibile esportare il tema.")
            )
