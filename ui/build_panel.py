"""
ui/build_panel.py — Pannello output compilazione
NotePadPQ

Panel con output del build, lista errori cliccabili e
dialog configurazione profili.

Fix rispetto alla versione precedente:
- Il profilo attivo è sempre visibile e sincronizzato con il file corrente
- I pulsanti mostrano il comando che verrà eseguito nel tooltip
- Salva profilo con feedback visivo (colore + messaggio)
- Il combo del pannello e il BuildManager sono sempre allineati
- Pulsanti Compile/Run/Build disabilitati se il comando è vuoto per quel profilo
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QToolBar,
    QLabel, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QLineEdit, QPushButton, QSplitter,
    QGroupBox, QListWidget, QListWidgetItem, QMessageBox,
    QStatusBar, QFrame,
)

from i18n.i18n import tr
from core.build_manager import BuildManager, DEFAULT_PROFILES

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


class BuildPanel(QWidget):
    """
    Widget pannello build. Viene aggiunto come dock o widget inferiore
    dalla MainWindow quando viene avviata una compilazione.
    """

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._bm = BuildManager.instance()
        self._current_profile: str = ""

        self._build_ui()
        self._connect_signals()
        # Sincronizza il profilo con il tab corrente dopo l'avvio
        QTimer.singleShot(0, self._sync_profile_to_editor)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Barra superiore: profilo attivo ───────────────────────────────────
        tb = QToolBar()
        tb.setMovable(False)

        # Etichetta profilo attivo — colorata e visibile
        self._lbl_profile = QLabel()
        self._lbl_profile.setStyleSheet(
            "font-weight: bold; padding: 2px 6px; "
            "background: #264f78; color: #9cdcfe; border-radius: 3px;"
        )
        self._lbl_profile.setToolTip(
            "Profilo selezionato automaticamente dal tipo di file.\n"
            "Puoi sovrascriverlo con il combo a destra."
        )

        # Combo override manuale
        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip(
            "Profilo automatico (da estensione file) o selezione manuale"
        )
        self._profile_combo.addItem("— automatico —", userData=None)
        for name in self._bm.get_profiles():
            self._profile_combo.addItem(name, userData=name)
        self._profile_combo.currentIndexChanged.connect(self._on_combo_changed)

        tb.addWidget(QLabel("  Profilo: "))
        tb.addWidget(self._lbl_profile)
        tb.addWidget(QLabel("  Override: "))
        tb.addWidget(self._profile_combo)
        tb.addSeparator()

        # Pulsanti azione
        self._btn_compile = QPushButton(tr("action.compile", default="Compila") + "  F6")
        self._btn_run     = QPushButton(tr("action.run",     default="Esegui") +  "  F5")
        self._btn_build   = QPushButton(tr("action.build",   default="Build") +   "  F7")
        self._btn_stop    = QPushButton(tr("action.stop_build", default="Stop"))
        self._btn_clear   = QPushButton(tr("button.clear",   default="Pulisci"))

        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet("color: #f44747;")

        self._btn_open_pdf = QPushButton("📄 PDF")
        self._btn_open_pdf.setToolTip("Apri il PDF generato nel pannello anteprima")
        self._btn_open_pdf.setEnabled(False)

        for btn in [self._btn_compile, self._btn_run,
                    self._btn_build, self._btn_stop, self._btn_clear,
                    self._btn_open_pdf]:
            tb.addWidget(btn)


        # ── Barra stato build ─────────────────────────────────────────────────
        self._status_bar = QLabel()
        self._status_bar.setStyleSheet(
            "padding: 2px 8px; font-size: 11px; "
            "background: #252526; color: #858585; border-top: 1px solid #3c3c3c;"
        )
        self._status_bar.setText("Pronto.")

        # ── Tabs: Output | Errori ─────────────────────────────────────────────
        self._tabs = QTabWidget()

        # Output
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Monospace", 10))
        self._output.setMaximumBlockCount(5000)
        self._output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                selection-background-color: #264f78;
            }
        """)
        self._tabs.addTab(self._output, tr("label.output", default="Output"))

        # Errori
        self._error_tree = QTreeWidget()
        self._error_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                alternate-background-color: #252526;
                selection-background-color: #264f78;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                padding: 3px;
            }
        """)
        self._error_tree.setAlternatingRowColors(True)
        self._error_tree.setHeaderLabels([
            tr("label.file", default="File"), "Riga",
            tr("label.message", default="Messaggio")
        ])
        self._error_tree.setColumnWidth(0, 220)
        self._error_tree.setColumnWidth(1, 60)
        self._error_tree.itemDoubleClicked.connect(self._on_error_clicked)
        self._tabs.addTab(self._error_tree,
                          tr("label.errors", default="Errori"))

        # --- AGGIUNGI QUESTA RIGA PER INCASTRARE LA BARRA A DESTRA ---
        #self._tabs.setCornerWidget(tb, Qt.Corner.TopRightCorner)
        self._tabs.setCornerWidget(tb, Qt.Corner.TopLeftCorner)

        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._status_bar)

    def _connect_signals(self) -> None:
        bm = self._bm
        bm.build_output.connect(self._append_output)
        bm.build_done.connect(self._on_build_done)
        bm.build_errors.connect(self._show_errors)

        self._btn_compile.clicked.connect(lambda: self._run_action("compile"))
        self._btn_run.clicked.connect(    lambda: self._run_action("run"))
        self._btn_build.clicked.connect(  lambda: self._run_action("build"))
        self._btn_open_pdf.clicked.connect(self._open_pdf_in_preview)
        self._btn_stop.clicked.connect(bm.stop)
        self._btn_clear.clicked.connect(self._output.clear)

        # Sincronizza il profilo quando cambia il tab nell'editor
        try:
            self._mw._tab_manager.current_editor_changed.connect(
                self._sync_profile_to_editor
            )
        except Exception:
            pass

    # ── Gestione profilo attivo ───────────────────────────────────────────────

    def _sync_profile_to_editor(self) -> None:
        """
        Aggiorna il profilo attivo in base al file aperto nell'editor corrente.
        Se l'utente ha selezionato un override manuale, lo rispetta.
        """
        # --- INIZIO AGGIUNTA: CONTROLLO PDF ESISTENTE ---
        pdf_path = self._find_generated_pdf()
        self._btn_open_pdf.setEnabled(pdf_path is not None)
        if pdf_path:
            self._btn_open_pdf.setToolTip(f"Apri: {pdf_path.name}")
        else:
            self._btn_open_pdf.setToolTip("Apri il PDF generato nel pannello anteprima")
        # --- FINE AGGIUNTA ---

        # Se c'è un override manuale (combo != "— automatico —"), non toccare
        if self._profile_combo.currentIndex() > 0:
            return

        editor = self._mw._tab_manager.current_editor()
        if editor is None:
            self._set_active_profile("")
            return

        # ... (lascia intatto il resto del codice che segue)

        path = getattr(editor, "file_path", None) or getattr(editor, "_file_path", None)
        if path is None:
            self._set_active_profile("")
            return

        name = self._bm.get_profile_for_file(path)
        self._set_active_profile(name or "")

    def _on_combo_changed(self, index: int) -> None:
        """L'utente ha scelto un profilo manuale (o resettato ad automatico)."""
        if index == 0:
            # Automatico: risincronizza dal file corrente
            self._sync_profile_to_editor()
        else:
            name = self._profile_combo.itemData(index)
            self._set_active_profile(name or "")

    def _set_active_profile(self, name: str) -> None:
        """Imposta il profilo attivo e aggiorna tutti gli elementi UI."""
        self._current_profile = name

        if name:
            self._lbl_profile.setText(f"  {name}  ")
            self._lbl_profile.setStyleSheet(
                "font-weight: bold; padding: 2px 8px; "
                "background: #264f78; color: #9cdcfe; border-radius: 3px;"
            )
        else:
            self._lbl_profile.setText("  (nessun profilo)  ")
            self._lbl_profile.setStyleSheet(
                "font-weight: bold; padding: 2px 8px; "
                "background: #3c3c3c; color: #858585; border-radius: 3px;"
            )

        # Aggiorna tooltip e stato enabled dei pulsanti
        self._update_button_states(name)

    def _update_button_states(self, profile_name: str) -> None:
        """Abilita/disabilita i pulsanti e aggiorna i tooltip con i comandi."""
        profile = self._bm.get_profiles().get(profile_name, {})

        compile_cmd = profile.get("compile", "")
        run_cmd     = profile.get("run",     "")
        build_cmd   = profile.get("build",   "")

        self._btn_compile.setEnabled(bool(compile_cmd))
        self._btn_run.setEnabled(    bool(run_cmd))
        self._btn_build.setEnabled(  bool(build_cmd))

        self._btn_compile.setToolTip(compile_cmd or "(nessun comando compile per questo profilo)")
        self._btn_run.setToolTip(    run_cmd     or "(nessun comando run per questo profilo)")
        self._btn_build.setToolTip(  build_cmd   or "(nessun comando build per questo profilo)")

        if not profile_name:
            for btn in [self._btn_compile, self._btn_run, self._btn_build]:
                btn.setEnabled(False)
                btn.setToolTip("Apri un file per attivare il profilo di compilazione")

    # ── Esecuzione ────────────────────────────────────────────────────────────

    def _run_action(self, action: str) -> None:
        """Lancia compile/run/build usando il profilo attivo."""
        editor = self._mw._tab_manager.current_editor()
        if editor is None:
            return

        # Inietta il profilo selezionato nel BuildManager se è un override manuale
        if self._profile_combo.currentIndex() > 0 and self._current_profile:
            self._bm._active_profile = self._current_profile

        started = self._bm.run(action, editor)
        if started:
            self._btn_stop.setEnabled(True)
            self._btn_compile.setEnabled(False)
            self._btn_run.setEnabled(False)
            self._btn_build.setEnabled(False)
            self._status_bar.setText(
                f"▶ {action.capitalize()} in corso — profilo: {self._current_profile} …"
            )
            self._status_bar.setStyleSheet(
                "padding: 2px 8px; font-size: 11px; "
                "background: #1e3a1e; color: #4caf50; border-top: 1px solid #3c3c3c;"
            )

    # ── Output ────────────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _append_output(self, line: str) -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        lower = line.lower()
        if "error" in lower or line.startswith("!"):
            fmt.setForeground(QColor("#f44747"))
        elif "warning" in lower:
            fmt.setForeground(QColor("#ffcc00"))
        elif line.startswith("["):
            fmt.setForeground(QColor("#9cdcfe"))
        else:
            fmt.setForeground(QColor("#d4d4d4"))

        cursor.insertText(line + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()
        self._tabs.setCurrentIndex(0)

    @pyqtSlot(bool, str)
    def _on_build_done(self, success: bool, message: str) -> None:
        # Ripristina pulsanti
        self._btn_stop.setEnabled(False)
        self._update_button_states(self._current_profile)

        color_bg  = "#1e3a1e" if success else "#3a1e1e"
        color_fg  = "#4caf50" if success else "#f44747"
        icon      = "✓" if success else "✗"

        self._output.appendHtml(
            f'<span style="color:{color_fg}"><b>{icon} {message}</b></span>'
        )
        self._status_bar.setText(f"{icon} {message}  — profilo: {self._current_profile}")
        self._status_bar.setStyleSheet(
            f"padding: 2px 8px; font-size: 11px; "
            f"background: {color_bg}; color: {color_fg}; border-top: 1px solid #3c3c3c;"
        )

        # Abilita pulsante PDF se il build è riuscito e c'è un .pdf generato
        if success:
            pdf_path = self._find_generated_pdf()
            self._btn_open_pdf.setEnabled(pdf_path is not None)
            if pdf_path:
                self._btn_open_pdf.setToolTip(f"Apri: {pdf_path.name}")
        else:
            self._btn_open_pdf.setEnabled(False)

        # Parsing errori automatico
        if not success and self._current_profile:
            output_text = self._output.toPlainText()
            errors = self._bm.parse_errors(output_text, self._current_profile)
            if errors:
                self._show_errors(errors)
                n = len(errors)
                self._tabs.setTabText(1, f"{tr('label.errors', default='Errori')} ({n})")
                self._tabs.setCurrentIndex(1)

    def _find_generated_pdf(self):
        """Trova il PDF generato dal file corrente (stesso nome, stessa directory)."""
        from pathlib import Path
        mw = self.window()
        editor = None
        if hasattr(mw, "_tab_manager"):
            editor = mw._tab_manager.current_editor()
        if not editor:
            return None
        path = getattr(editor, "file_path", None)
        if not path:
            return None
        pdf = Path(str(path)).with_suffix(".pdf")
        return pdf if pdf.exists() else None

    def _open_pdf_in_preview(self) -> None:
        """
        Mostra il PDF generato direttamente nel dock Anteprima,
        senza aprire un nuovo tab editor.
        """
        pdf_path = self._find_generated_pdf()
        if not pdf_path:
            self._status_bar.setText(f"✗  PDF non trovato  — profilo: {self._current_profile}")
            self._status_bar.setStyleSheet(
                "padding: 2px 8px; font-size: 11px; "
                "background: #3a1e1e; color: #f44747; border-top: 1px solid #3c3c3c;"
            )
            return

        mw = self.window()
        if not hasattr(mw, "_preview_dock") or not hasattr(mw, "_preview_panel_dock"):
            return

        preview = mw._preview_panel_dock

        # Mostra il dock
        mw._preview_dock.show()
        act = mw._actions.get("preview_toggle")
        if act:
            act.setChecked(True)

        # Carica il PDF direttamente nella preview tramite set_pdf_path
        # (non serve aprire un tab editor)
        preview.set_pdf_path(pdf_path)

        # Aggiorna label pulsante con nome file
        self._btn_open_pdf.setText(f"📄 {pdf_path.name}")

    @pyqtSlot(list)
    def _show_errors(self, errors: list) -> None:
        self._error_tree.clear()
        for err in errors:
            item = QTreeWidgetItem(self._error_tree, [
                str(err.get("file", "")),
                str(err.get("line", "")),
                err.get("message", "")[:200],
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, err)
            if "error" in err.get("message", "").lower():
                item.setForeground(0, QColor("#f44747"))
                item.setForeground(2, QColor("#f44747"))

    def _on_error_clicked(self, item: QTreeWidgetItem) -> None:
        err = item.data(0, Qt.ItemDataRole.UserRole)
        if not err:
            return
        line     = err.get("line", 0)
        file_ref = err.get("file", "")

        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return

        if file_ref:
            from pathlib import Path
            p = Path(file_ref)
            if not p.is_absolute() and getattr(editor, "file_path", None):
                p = editor.file_path.parent / p
            if p.exists() and (
                not editor.file_path or p.resolve() != editor.file_path.resolve()
            ):
                self._mw.open_files([p])
                editor = self._mw._tab_manager.current_editor()

        if editor and line > 0:
            editor.go_to_line(line)
            editor.setFocus()


# ─── Dialog configurazione profili ───────────────────────────────────────────

class BuildProfilesDialog(QDialog):
    """Dialog per creare/modificare/eliminare i profili di compilazione."""

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._bm = BuildManager.instance()
        self._dirty = False   # profilo corrente modificato ma non salvato

        # Determina il profilo attivo per il file corrente
        self._active_profile_name: str = ""
        editor = main_window._tab_manager.current_editor() if hasattr(main_window, '_tab_manager') else None
        if editor and getattr(editor, 'file_path', None):
            self._active_profile_name = self._bm.get_profile_for_file(editor.file_path) or ""

        self.setWindowTitle(tr("action.build_profiles", default="Profili di compilazione"))
        self.resize(800, 520)
        self._build_ui()
        self._load_profiles()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        main = QHBoxLayout()
        outer.addLayout(main, 1)

        # ── Colonna sinistra: lista profili ───────────────────────────────────
        left = QVBoxLayout()

        lbl = QLabel("Profili disponibili:")
        lbl.setStyleSheet("font-weight: bold;")
        left.addWidget(lbl)

        # Banner profilo attivo
        if self._active_profile_name:
            self._active_banner = QLabel(
                f"▶  Profilo attivo:  <b>{self._active_profile_name}</b>"
            )
            self._active_banner.setTextFormat(Qt.TextFormat.RichText)
            self._active_banner.setStyleSheet(
                "background: #264f78; color: #9cdcfe; "
                "font-size: 12px; padding: 4px 6px; border-radius: 3px;"
            )
            self._active_banner.setToolTip(
                "Profilo selezionato automaticamente in base all'estensione del file aperto"
            )
        else:
            self._active_banner = QLabel("(nessun file aperto — profilo non determinato)")
            self._active_banner.setStyleSheet(
                "color: #858585; font-size: 11px; padding: 4px 6px;"
            )
        left.addWidget(self._active_banner)

        self._profile_list = QListWidget()
        self._profile_list.currentItemChanged.connect(self._on_profile_item_changed)
        left.addWidget(self._profile_list, 1)

        btn_row = QHBoxLayout()
        self._btn_new = QPushButton(tr("button.add", default="Nuovo"))
        self._btn_del = QPushButton(tr("button.remove", default="Elimina"))
        self._btn_new.clicked.connect(self._new_profile)
        self._btn_del.clicked.connect(self._delete_profile)
        btn_row.addWidget(self._btn_new)
        btn_row.addWidget(self._btn_del)
        left.addLayout(btn_row)

        self._btn_set_active = QPushButton("▶  Imposta come attivo")
        self._btn_set_active.setToolTip(
            "Forza questo profilo come attivo per il file corrente,\n"
            "indipendentemente dall'estensione."
        )
        self._btn_set_active.setStyleSheet(
            "font-weight: bold; padding: 4px 8px; "
            "background: #264f78; color: #9cdcfe; border: 1px solid #9cdcfe;"
        )
        self._btn_set_active.clicked.connect(self._set_as_active)
        left.addWidget(self._btn_set_active)

        main.addLayout(left, 1)

        # Separatore verticale
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        main.addWidget(sep)

        # ── Colonna destra: form dettaglio ────────────────────────────────────
        right = QVBoxLayout()

        self._grp = QGroupBox("Configurazione profilo")
        form = QFormLayout(self._grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit    = QLineEdit()
        self._ext_edit     = QLineEdit()
        self._ext_edit.setPlaceholderText(".py  .pyw  (separati da spazio o ;)")
        self._compile_edit = QLineEdit()
        self._compile_edit.setPlaceholderText("vuoto = non applicabile")
        self._run_edit     = QLineEdit()
        self._run_edit.setPlaceholderText("vuoto = non applicabile")
        self._build_edit   = QLineEdit()
        self._build_edit.setPlaceholderText("vuoto = non applicabile")
        self._regex_edit   = QLineEdit()
        self._regex_edit.setPlaceholderText(r'es. File "([^"]+)", line (\d+)')

        form.addRow("Nome profilo:",                      self._name_edit)
        form.addRow("Estensioni file:",                   self._ext_edit)
        form.addRow(tr("action.compile", default="Compila") + " →", self._compile_edit)
        form.addRow(tr("action.run",     default="Esegui")  + " →", self._run_edit)
        form.addRow(tr("action.build",   default="Build")   + " →", self._build_edit)
        form.addRow("Regex errori:",                      self._regex_edit)

        var_lbl = QLabel(
            "<small><b>Variabili disponibili</b> (sintassi <code>${VAR}</code> o <code>$(VAR)</code>):<br>"
            "<table cellspacing='2'>"
            "<tr><td><code>${FILE}</code></td><td>— percorso completo del file&nbsp;&nbsp;</td>"
            "<td><i>es. /home/user/doc/main.py</i></td></tr>"
            "<tr><td><code>${DIR}</code></td><td>— directory del file</td>"
            "<td><i>es. /home/user/doc</i></td></tr>"
            "<tr><td><code>${FILENAME}</code></td><td>— nome file con estensione</td>"
            "<td><i>es. main.py</i></td></tr>"
            "<tr><td><code>${BASENAME}</code></td><td>— nome file senza estensione</td>"
            "<td><i>es. main</i></td></tr>"
            "<tr><td><code>${BASEFILE}</code></td><td>— percorso completo senza estensione</td>"
            "<td><i>es. /home/user/doc/main</i></td></tr>"
            "<tr><td><code>${EXT}</code></td><td>— estensione con punto</td>"
            "<td><i>es. .py</i></td></tr>"
            "<tr><td><code>${LINE}</code></td><td>— riga corrente del cursore</td>"
            "<td><i>es. 42</i></td></tr>"
            "<tr><td><code>${COL}</code></td><td>— colonna corrente del cursore</td>"
            "<td><i>es. 7</i></td></tr>"
            "</table></small>"
        )
        var_lbl.setTextFormat(Qt.TextFormat.RichText)
        var_lbl.setWordWrap(True)
        form.addRow("", var_lbl)

        right.addWidget(self._grp, 1)

        # Collega i campi al flag dirty
        for w in [self._name_edit, self._ext_edit, self._compile_edit,
                  self._run_edit, self._build_edit, self._regex_edit]:
            w.textChanged.connect(self._mark_dirty)

        # Barra stato salvataggio
        self._save_status = QLabel("")
        self._save_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._save_status)

        # Pulsante salva
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._btn_save = QPushButton("💾  " + tr("button.save", default="Salva profilo"))
        self._btn_save.setMinimumWidth(160)
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")
        self._btn_save.clicked.connect(self._save_current)
        save_row.addWidget(self._btn_save)
        right.addLayout(save_row)

        # Nota built-in
        self._note_builtin = QLabel(
            "ℹ  Profilo built-in: le modifiche vengono salvate come override. "
            "Premi Salva per applicarle."
        )
        self._note_builtin.setStyleSheet("color: #858585; font-size: 11px;")
        self._note_builtin.setWordWrap(True)
        self._note_builtin.setVisible(False)
        right.addWidget(self._note_builtin)

        main.addLayout(right, 2)

        # ── Pulsante Chiudi ───────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self._on_close)
        outer.addWidget(buttons)

    # ── Caricamento lista ─────────────────────────────────────────────────────

    def _load_profiles(self) -> None:
        self._profile_list.clear()
        profiles = self._bm.get_profiles()
        active_row = 0
        for i, name in enumerate(profiles):
            is_active = (name == self._active_profile_name)
            label = f"▶  {name}" if is_active else f"    {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)  # nome reale senza prefisso
            if is_active:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QColor("#9cdcfe"))
                item.setToolTip("✔ Profilo attivo per il file corrente")
                item.setBackground(QColor("#1e3a5f"))
                active_row = i
            elif name in DEFAULT_PROFILES:
                item.setForeground(QColor("#858585"))
                item.setToolTip("Profilo built-in (non eliminabile)")
            else:
                item.setForeground(QColor("#9cdcfe"))
                item.setToolTip("Profilo utente")
            self._profile_list.addItem(item)

        if self._profile_list.count() > 0:
            self._profile_list.setCurrentRow(active_row)

    def _on_profile_item_changed(self, item, _prev) -> None:
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole) or ""
        if not name:
            return
        self._on_profile_selected(name)

    def _on_profile_selected(self, name: str) -> None:
        if not name:
            return
        profile = self._bm.get_profiles().get(name, {})

        # Blocca il segnale dirty durante il caricamento
        self._dirty = False
        self._name_edit.setText(name)
        exts = profile.get("extensions", [])
        self._ext_edit.setText("  ".join(exts))
        self._compile_edit.setText(profile.get("compile", ""))
        self._run_edit.setText(    profile.get("run",     ""))
        self._build_edit.setText(  profile.get("build",   ""))
        self._regex_edit.setText(  profile.get("error_regex", ""))
        self._dirty = False

        # Mostra nota built-in
        is_builtin = name in DEFAULT_PROFILES
        self._note_builtin.setVisible(is_builtin)
        self._btn_del.setEnabled(not is_builtin)

        self._save_status.setText("")
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")

    def _mark_dirty(self) -> None:
        if self._dirty:
            return
        self._dirty = True
        self._save_status.setText("⚠  Modifiche non salvate")
        self._save_status.setStyleSheet("color: #ffcc00; font-size: 11px;")
        self._btn_save.setStyleSheet(
            "font-weight: bold; padding: 4px 12px; "
            "background: #264f78; color: #ffffff; border: 1px solid #9cdcfe;"
        )

    def _set_as_active(self) -> None:
        """Forza il profilo selezionato come attivo per il file corrente."""
        current = self._profile_list.currentItem()
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole) or ""
        if not name:
            return
        self._bm._active_profile = name
        self._active_profile_name = name

        # Aggiorna banner
        self._active_banner.setText(f"▶  Profilo attivo:  <b>{name}</b>")
        self._active_banner.setStyleSheet(
            "background: #264f78; color: #9cdcfe; "
            "font-size: 12px; padding: 4px 6px; border-radius: 3px;"
        )

        # Aggiorna lista (grassetto/colore sul profilo attivo)
        for i in range(self._profile_list.count()):
            item = self._profile_list.item(i)
            iname = item.data(Qt.ItemDataRole.UserRole) or ""
            is_active = (iname == name)
            font = item.font()
            font.setBold(is_active)
            item.setFont(font)
            if is_active:
                item.setText(f"▶  {iname}")
                item.setForeground(QColor("#9cdcfe"))
                item.setBackground(QColor("#1e3a5f"))
                item.setToolTip("✔ Profilo attivo (impostato manualmente)")
            else:
                item.setText(f"    {iname}")
                item.setBackground(QColor(0, 0, 0, 0))
                if iname in DEFAULT_PROFILES:
                    item.setForeground(QColor("#858585"))
                else:
                    item.setForeground(QColor("#9cdcfe"))

        # Notifica nel pannello build se aperto
        if hasattr(self._mw, '_build_panel') and self._mw._build_panel:
            bp = self._mw._build_panel
            if hasattr(bp, '_set_active_profile'):
                bp._set_active_profile(name)

    # ── Salvataggio ───────────────────────────────────────────────────────────

    def _save_current(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._save_status.setText("✗  Inserisci un nome per il profilo")
            self._save_status.setStyleSheet("color: #f44747; font-size: 11px;")
            return

        # Parse estensioni (accetta spazio, ; o ,)
        raw_exts = self._ext_edit.text().replace(";", " ").replace(",", " ").split()
        exts = []
        for e in raw_exts:
            e = e.strip()
            if e and not e.startswith("."):
                e = "." + e
            if e:
                exts.append(e.lower())

        profile = {
            "extensions":         exts,
            "compile":            self._compile_edit.text().strip(),
            "run":                self._run_edit.text().strip(),
            "build":              self._build_edit.text().strip(),
            "error_regex":        self._regex_edit.text().strip(),
            "error_file_group":   1,
            "error_line_group":   2,
        }
        self._bm.add_profile(name, profile)

        # Aggiorna lista se è un nome nuovo
        existing = self._find_item_by_name(name)
        if existing is None:
            label = f"▶  {name}" if name == self._active_profile_name else f"    {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setForeground(QColor("#9cdcfe"))
            item.setToolTip("Profilo utente")
            self._profile_list.addItem(item)
            self._profile_list.setCurrentItem(item)
        else:
            # Aggiorna colore (poteva essere built-in e ora è override utente)
            existing.setForeground(QColor("#9cdcfe"))

        self._dirty = False
        from core.build_manager import DEFAULT_PROFILES
        if name in DEFAULT_PROFILES:
            self._save_status.setText("✓  Override salvato (sovrascrive il built-in)")
        else:
            self._save_status.setText("✓  Profilo salvato")
        self._save_status.setStyleSheet("color: #4caf50; font-size: 11px;")
        # Aggiorna nota built-in (ora è un override, ma teniamo la nota informativa)
        self._note_builtin.setVisible(False)
        self._save_status.setStyleSheet("color: #4caf50; font-size: 11px;")
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")
        self._note_builtin.setVisible(False)

        # Resetta il messaggio dopo 3 secondi
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self._save_status.setText(""))

    # ── Nuovo / Elimina ───────────────────────────────────────────────────────

    def _new_profile(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Nuovo profilo", "Nome profilo:"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        empty = {
            "extensions": [], "compile": "", "run": "", "build": "",
            "error_regex": "", "error_file_group": 1, "error_line_group": 2,
        }
        self._bm.add_profile(name, empty)
        item = QListWidgetItem(f"    {name}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        item.setForeground(QColor("#9cdcfe"))
        item.setToolTip("Profilo utente")
        self._profile_list.addItem(item)
        self._profile_list.setCurrentItem(item)

    def _find_item_by_name(self, name: str):
        """Trova un QListWidgetItem per nome reale (UserRole)."""
        for i in range(self._profile_list.count()):
            item = self._profile_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                return item
        return None

    def _delete_profile(self) -> None:
        current = self._profile_list.currentItem()
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole) or current.text()
        if name in DEFAULT_PROFILES:
            QMessageBox.information(
                self, "Profilo built-in",
                f"Il profilo «{name}» è built-in e non può essere eliminato.\n"
                "Puoi modificarlo e salvare una copia con lo stesso nome."
            )
            return
        reply = QMessageBox.question(
            self, "Elimina profilo",
            f"Eliminare il profilo «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._bm.remove_profile(name)
            self._profile_list.takeItem(self._profile_list.currentRow())

    def _on_close(self) -> None:
        if self._dirty:
            reply = QMessageBox.question(
                self, "Modifiche non salvate",
                "Ci sono modifiche non salvate al profilo corrente. Chiudere senza salvare?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        self.accept()
