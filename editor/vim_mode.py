"""Modal Vim opzionale per EditorWidget.

Il controller intercetta i tasti solo quando l'utente lo abilita nelle
preferenze; fuori da quel caso QScintilla conserva il comportamento nativo.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox


@dataclass
class _Range:
    start: int
    end: int


class VimMode(QObject):
    """Subset pragmatico di Vim: mode, operatori, text object e comandi ':'."""

    mode_changed = pyqtSignal(str)

    def __init__(self, editor, enabled: bool = False) -> None:
        super().__init__(editor)
        self._ed = editor
        self._enabled = enabled
        self._mode = "NORMAL" if enabled else ""
        self._pending = ""
        self._count = ""
        self._register = '"'
        self._registers: dict[str, str] = {}
        self._jumps: list[int] = []
        self._jump_index = 0
        self._last_change: tuple[str, object] | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def mode(self) -> str:
        return self._mode

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self._pending = self._count = ""
        self._set_mode("NORMAL" if enabled else "")

    def handle_key(self, event: QKeyEvent) -> bool:
        """Restituisce True se il tasto e' stato completamente gestito."""
        if not self._enabled:
            return False
        key, mods, text = event.key(), event.modifiers(), event.text()
        if self._mode == "INSERT":
            if key == Qt.Key.Key_Escape:
                self._set_mode("NORMAL")
                self._normalise_cursor()
                return True
            return False
        if key == Qt.Key.Key_Escape:
            self._pending = self._count = ""
            self._set_mode("NORMAL")
            self._ed._multicursor.clear_extra_cursors()
            self._normalise_cursor()
            return True
        if mods == Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_O:
                self._jump(-1)
                return True
            if key == Qt.Key.Key_I:
                self._jump(1)
                return True
            if key == Qt.Key.Key_R:
                self._ed.redo()
                return True
            return False
        # I comandi Vim come ':', 'G' e 'V' sono caratteri testuali generati
        # con Shift: il modificatore non deve farli passare a QScintilla.
        if mods not in (Qt.KeyboardModifier.NoModifier,
                        Qt.KeyboardModifier.ShiftModifier) or not text:
            return False
        if self._mode == "VISUAL":
            return self._visual_key(text)
        return self._normal_key(text)

    def _normal_key(self, char: str) -> bool:
        if char.isdigit() and (char != "0" or self._count):
            self._count += char
            return True
        count = int(self._count or "1")
        if self._pending == '"':
            self._register = char
            self._pending = ""
            return True
        if self._pending in {"d", "c", "y"}:
            operator, self._pending = self._pending, ""
            if char == operator:
                self._operate(operator, self._line_range(count))
            elif char in {"i", "a"}:
                self._pending = operator + char
                return True
            else:
                target = self._motion(char, count, record_jump=False)
                if target is not None:
                    self._operate(operator, _Range(self._position(), target))
            self._count = ""
            return True
        if len(self._pending) == 2 and self._pending[0] in "dcy" and self._pending[1] in "ia":
            operator, around = self._pending[0], self._pending[1] == "a"
            self._pending = self._count = ""
            rng = self._text_object(char, around)
            if rng:
                self._operate(operator, rng)
            return True
        if self._pending == "g":
            self._pending = ""
            if char == "g":
                self._goto_line(0)
            return True
        if char in "dcy":
            self._pending = char
            return True
        if char == '"':
            self._pending = char
        elif char == "g":
            self._pending = char
        elif char == ".":
            self._repeat_last_change()
        elif char == "u":
            self._ed.undo()
        elif char in "hjklwb0$G":
            target = self._motion(char, count)
            if target is not None:
                self._set_position(target)
        elif char == "x":
            start = self._position()
            self._delete(_Range(start, min(start + count, self._doc_end())))
        elif char in "iIaAoO":
            self._enter_insert(char)
        elif char == "v":
            self._set_mode("VISUAL")
            self._ed.setSelection(*self._line_col(self._position()), *self._line_col(self._position()))
        elif char == "V":
            line, _ = self._ed.getCursorPosition()
            self._ed.setSelection(line, 0, line, len(self._ed.text(line).rstrip("\r\n")))
            self._set_mode("VISUAL")
        elif char in "pP":
            self._paste(after=char == "p")
        elif char == ":":
            self._command_line()
        else:
            self._count = ""
            return False
        self._count = ""
        return True

    def _visual_key(self, char: str) -> bool:
        if char in "hjklwb0$G":
            target = self._motion(char, 1)
            if target is not None:
                line, col = self._line_col(target)
                sl, sc, _, _ = self._ed.getSelection()
                self._ed.setSelection(sl, sc, line, col)
        elif char in "ycd":
            sl, sc, el, ec = self._ed.getSelection()
            self._operate(char, _Range(self._ed.positionFromLineIndex(sl, sc), self._ed.positionFromLineIndex(el, ec)))
            self._set_mode("INSERT" if char == "c" else "NORMAL")
        else:
            return False
        return True

    def _operate(self, operator: str, rng: _Range) -> None:
        rng = _Range(min(rng.start, rng.end), max(rng.start, rng.end))
        if rng.start == rng.end:
            return
        text = self._selected_range(rng)
        if operator == "y":
            self._store_register(text)
            self._set_position(rng.start)
            return
        self._store_register(text)
        self._delete(rng)
        if operator == "c":
            self._set_mode("INSERT")

    def _delete(self, rng: _Range) -> None:
        self._select_range(rng)
        self._ed.beginUndoAction()
        try:
            self._ed.replaceSelectedText("")
        finally:
            self._ed.endUndoAction()
        self._last_change = ("delete", rng.end - rng.start)

    def _paste(self, after: bool) -> None:
        text = self._registers.get(self._register) or QApplication.clipboard().text()
        if not text:
            return
        pos = self._position()
        if after and pos < self._doc_end():
            pos += 1
        self._set_position(pos)
        self._ed.insert(text)
        self._last_change = ("insert", text)

    def _store_register(self, text: str) -> None:
        self._registers[self._register] = text
        self._registers['"'] = text
        QApplication.clipboard().setText(text)
        self._register = '"'

    def _enter_insert(self, command: str) -> None:
        line, col = self._ed.getCursorPosition()
        if command == "a": col += 1
        elif command == "A": col = len(self._ed.text(line).rstrip("\r\n"))
        elif command == "I": col = len(self._ed.text(line)) - len(self._ed.text(line).lstrip())
        elif command in "oO":
            if command == "o":
                self._ed.insertAt("\n", line, len(self._ed.text(line).rstrip("\r\n")))
                line += 1
            else:
                self._ed.insertAt("\n", line, 0)
            col = 0
        self._ed.setCursorPosition(line, col)
        self._set_mode("INSERT")

    def _motion(self, char: str, count: int, record_jump: bool = True) -> int | None:
        pos = self._position()
        line, col = self._ed.getCursorPosition()
        if char == "h": return max(0, pos - count)
        if char == "l": return min(self._doc_end(), pos + count)
        if char in "jk":
            dest = max(0, min(self._ed.lines() - 1, line + (count if char == "j" else -count)))
            return self._ed.positionFromLineIndex(dest, min(col, len(self._ed.text(dest).rstrip("\r\n"))))
        if char == "0": return self._ed.positionFromLineIndex(line, 0)
        if char == "$": return self._ed.positionFromLineIndex(line, len(self._ed.text(line).rstrip("\r\n")))
        if char == "G":
            self._remember_jump()
            return self._ed.positionFromLineIndex(self._ed.lines() - 1, 0)
        text = self._ed.text()
        if char == "w":
            match = re.search(r"\w+", text[pos + 1:])
            return min(self._doc_end(), pos + 1 + match.start()) if match else self._doc_end()
        if char == "b":
            matches = list(re.finditer(r"\w+", text[:pos]))
            return matches[-1].start() if matches else 0
        return None

    def _text_object(self, char: str, around: bool) -> _Range | None:
        pos, text = self._position(), self._ed.text()
        if char == "w":
            for match in re.finditer(r"\w+", text):
                if match.start() <= pos <= match.end():
                    return _Range(match.start(), match.end())
            return None
        pairs = {'"': ('"', '"'), "'": ("'", "'"), "(": ("(", ")"), "[": ("[", "]"), "{": ("{", "}")}
        if char not in pairs: return None
        opening, closing = pairs[char]
        left, right = text.rfind(opening, 0, pos + 1), text.find(closing, pos)
        if left < 0 or right < 0: return None
        return _Range(left if around else left + 1, right + 1 if around else right)

    def _command_line(self) -> None:
        command, ok = QInputDialog.getText(
            self._ed,
            "Vim command",
            ":  Esempi: w, q, wq, e file, set wrap, goto 42, !git status",
        )
        if ok and command.strip(): self.execute_command(command.strip())

    def execute_command(self, command: str) -> None:
        # Il prompt mostra gia' ':', ma gli utenti possono comunque digitarlo.
        # Accettiamo entrambe le forme ("!sort" e ":!sort") senza alterare
        # i percorsi o gli argomenti del comando.
        command = command.strip()
        if command.startswith(":"):
            command = command[1:].lstrip()
        window = self._ed.window()
        if command in {"w", "wq"} and hasattr(window, "action_save"):
            window.action_save()
        if command in {"q", "wq"} and hasattr(window, "_tab_manager"):
            window._tab_manager.close_current_tab()
        elif command.startswith("e ") and hasattr(window, "open_files"):
            from pathlib import Path
            window.open_files([Path(command[2:].strip()).expanduser()])
        if command.startswith("set ") and command[4:] in {"wrap", "nowrap"}:
            self._ed.set_word_wrap(command[4:] == "wrap")
        elif command.startswith("goto ") and command[5:].isdigit():
            self._goto_line(int(command[5:]) - 1)
        elif command.startswith("!"):
            self._filter_selection(command[1:].strip())

    def _filter_selection(self, command: str) -> None:
        if not self._ed.hasSelectedText():
            self._run_shell_command(command)
            return
        try:
            result = subprocess.run(command, shell=True, input=self._ed.selectedText(), text=True,
                                    capture_output=True, cwd=str(self._ed.file_path.parent) if self._ed.file_path else None,
                                    timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            QMessageBox.warning(self._ed, "Vim filter", str(exc)); return
        if result.returncode:
            QMessageBox.warning(self._ed, "Vim filter", result.stderr or f"Comando terminato con codice {result.returncode}."); return
        preview = result.stdout[:2000]
        answer = QMessageBox.question(self._ed, "Vim filter", f"Sostituire la selezione con questo output?\n\n{preview}")
        if answer == QMessageBox.StandardButton.Yes:
            self._ed.replaceSelectedText(result.stdout)
            self._last_change = ("insert", result.stdout)

    def _run_shell_command(self, command: str) -> None:
        """Esegue :!comando senza selezione e rende sempre visibile l'esito."""
        if not command:
            QMessageBox.information(self._ed, "Vim command", "Specifica un comando dopo :!.")
            return
        answer = QMessageBox.question(
            self._ed, "Esegui comando shell",
            f"Eseguire nella cartella del file corrente?\n\n{command}",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = subprocess.run(
                command, shell=True, text=True, capture_output=True,
                cwd=str(self._ed.file_path.parent) if self._ed.file_path else None,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            QMessageBox.warning(self._ed, "Vim command", str(exc))
            return
        output = (result.stdout + result.stderr).strip()
        if result.returncode:
            QMessageBox.warning(self._ed, "Vim command", output or f"Comando terminato con codice {result.returncode}.")
        else:
            QMessageBox.information(self._ed, "Vim command", output or "Comando completato.")

    def _repeat_last_change(self) -> None:
        if not self._last_change: return
        kind, value = self._last_change
        if kind == "insert": self._ed.insert(str(value))
        elif kind == "delete": self._delete(_Range(self._position(), min(self._position() + int(value), self._doc_end())))

    def _line_range(self, count: int) -> _Range:
        line, _ = self._ed.getCursorPosition()
        end_line = min(self._ed.lines() - 1, line + count - 1)
        return _Range(self._ed.positionFromLineIndex(line, 0), self._ed.positionFromLineIndex(end_line, len(self._ed.text(end_line))))

    def _goto_line(self, line: int) -> None:
        self._remember_jump(); self._ed.setCursorPosition(max(0, min(line, self._ed.lines() - 1)), 0)

    def _remember_jump(self) -> None:
        pos = self._position()
        if not self._jumps or self._jumps[-1] != pos:
            self._jumps = self._jumps[:self._jump_index + 1] + [pos]
            self._jump_index = len(self._jumps) - 1

    def _jump(self, direction: int) -> None:
        if not self._jumps: return
        self._jump_index = max(0, min(len(self._jumps) - 1, self._jump_index + direction))
        self._set_position(self._jumps[self._jump_index])

    def _set_mode(self, mode: str) -> None:
        self._mode = mode; self.mode_changed.emit(mode)

    def _position(self) -> int:
        line, col = self._ed.getCursorPosition(); return self._ed.positionFromLineIndex(line, col)

    def _set_position(self, pos: int) -> None:
        self._ed.setCursorPosition(*self._line_col(max(0, min(pos, self._doc_end()))))

    def _line_col(self, pos: int) -> tuple[int, int]: return self._ed.lineIndexFromPosition(pos)
    def _doc_end(self) -> int: return len(self._ed.text())
    def _select_range(self, rng: _Range) -> None: self._ed.setSelection(*self._line_col(rng.start), *self._line_col(rng.end))
    def _selected_range(self, rng: _Range) -> str: self._select_range(rng); return self._ed.selectedText()
    def _normalise_cursor(self) -> None:
        line, col = self._ed.getCursorPosition()
        self._ed.setCursorPosition(line, max(0, min(col, len(self._ed.text(line).rstrip("\r\n")) - 1)))
