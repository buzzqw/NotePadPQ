"""
ui/statusbar.py — Barra di stato
NotePadPQ

Mostra: riga/colonna, selezione, encoding, line ending,
        modalità INS/OVR, zoom, stato read-only, lingua file.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QStatusBar, QLabel, QFrame, QSizePolicy, QToolTip
)
from PyQt6.QtGui import QCursor

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep


class StatusBar(QStatusBar):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self._build()

    def _build(self) -> None:
        self._lbl_message  = QLabel("")
        self._lbl_message.setContentsMargins(6, 0, 6, 0)
        self._msg_timer    = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self._lbl_message.setText(""))
        self.addWidget(self._lbl_message, 1)  # stretch=1 → occupa spazio libero a sinistra

        self._lbl_cursor   = QLabel(tr("statusbar.default_cursor", default="Riga 1, Col 1"))
        self._lbl_sel      = QLabel("")
        self._lbl_encoding = QLabel("UTF-8")
        self._lbl_le       = QLabel("LF")
        self._lbl_mode     = QLabel(tr("label.insert_mode"))
        self._lbl_zoom     = QLabel("")
        self._lbl_lang     = QLabel("")
        self._lbl_readonly = QLabel("")

        for lbl in [self._lbl_cursor, self._lbl_sel, self._lbl_encoding,
                    self._lbl_le, self._lbl_mode, self._lbl_zoom,
                    self._lbl_lang, self._lbl_readonly]:
            lbl.setContentsMargins(4, 0, 4, 0)

        self._lbl_word_goal = QLabel("")
        self._lbl_word_goal.setContentsMargins(4, 0, 4, 0)
        self._lbl_word_goal.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lbl_word_goal.hide()
        self._word_goal_target: int = 0

        # Aggiunge da destra
        for widget in [
            self._lbl_readonly, _separator(),
            self._lbl_mode,     _separator(),
            self._lbl_zoom,     _separator(),
            self._lbl_le,       _separator(),
            self._lbl_encoding, _separator(),
            self._lbl_lang,     _separator(),
            self._lbl_word_goal, _separator(),
            self._lbl_sel,      _separator(),
            self._lbl_cursor,
        ]:
            self.addPermanentWidget(widget)

    # ── Aggiornamento ─────────────────────────────────────────────────────────

    def update_from_editor(self, editor: "EditorWidget") -> None:
        line, col = editor.get_cursor_position_1based()
        self.set_cursor(line, col)
        self.set_encoding(editor.encoding)
        self.set_line_ending(editor.line_ending.label())
        self.set_overwrite(False)
        self.set_zoom(editor.zoom_level)
        self._update_lang(editor)

    def set_cursor(self, line: int, col: int) -> None:
        self._lbl_cursor.setText(
            f"{tr('label.line')} {line}, {tr('label.column')} {col}"
        )

    def set_selection(self, chars: int, lines: int, byte_count: int = 0) -> None:
        if chars != 0:
            txt = f"({tr('label.selection')}: "
            if chars > 0:
                txt += f"{chars} {tr('label.chars')}"
            elif byte_count > 0:
                txt += f"{byte_count} byte"
            if chars > 0 and byte_count > 0 and byte_count != chars:
                txt += f" / {byte_count} byte"
            txt += f", {lines} {tr('label.lines_total')})"
            self._lbl_sel.setText(txt)
        else:
            self._lbl_sel.setText("")

    def set_encoding(self, encoding: str) -> None:
        self._lbl_encoding.setText(encoding)

    def set_line_ending(self, le_label: str) -> None:
        self._lbl_le.setText(le_label)

    def set_overwrite(self, overwrite: bool) -> None:
        self._lbl_mode.setText(
            tr("label.overwrite_mode") if overwrite
            else tr("label.insert_mode")
        )

    def set_zoom(self, level: int) -> None:
        if level == 0:
            self._lbl_zoom.setText("")
        else:
            sign = "+" if level > 0 else ""
            self._lbl_zoom.setText(tr("statusbar.zoom", level=f"{sign}{level}"))

    def set_read_only(self, ro: bool) -> None:
        self._lbl_readonly.setText(
            tr("label.read_only") if ro else ""
        )

    def _update_lang(self, editor: "EditorWidget") -> None:
        from editor.lexers import get_language_name
        lang = get_language_name(editor)
        self._lbl_lang.setText(lang if lang and lang != "Text" else "Text")

    def show_message(self, msg: str, timeout: int = 3000) -> None:
        self._lbl_message.setText(msg)
        self._msg_timer.start(timeout)

    def showMessage(self, msg: str, timeout: int = 0) -> None:  # type: ignore[override]
        """Override: reindirizza showMessage alla label dedicata."""
        self.show_message(msg, timeout if timeout > 0 else 4000)

    def set_word_goal(self, words: int, goal: int) -> None:
        self._word_goal_target = goal
        if goal <= 0:
            self._lbl_word_goal.hide()
            return
        pct = min(100, int(words * 100 / goal))
        if pct >= 100:
            color = "#73c991"
        elif pct >= 60:
            color = "#dcdcaa"
        else:
            color = "#888888"
        self._lbl_word_goal.setStyleSheet(f"color: {color};")
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        self._lbl_word_goal.setText(f"{words}/{goal}  {bar}")
        self._lbl_word_goal.setToolTip(f"{pct}% — {words} / {goal} {tr('label.words')}")
        self._lbl_word_goal.show()

    def hide_word_goal(self) -> None:
        self._lbl_word_goal.hide()
