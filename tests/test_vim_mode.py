import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication
from PyQt6.Qsci import QsciScintilla

from editor.editor_widget import EditorWidget


def key(char: str) -> QKeyEvent:
    return QKeyEvent(QKeyEvent.Type.KeyPress, ord(char.upper()), Qt.KeyboardModifier.NoModifier, char)


class VimModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = EditorWidget()
        self.editor._vim_mode.set_enabled(True)

    def tearDown(self):
        self.editor.deleteLater()
        self.app.processEvents()

    def press(self, chars: str):
        for char in chars:
            self.editor.keyPressEvent(key(char))

    def test_disabled_mode_does_not_consume_standard_typing(self):
        self.editor._vim_mode.set_enabled(False)
        self.press("a")
        self.assertEqual(self.editor.text(), "a")

    def test_insert_normal_and_motion(self):
        self.press("iabc")
        self.editor.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.press("h")
        self.assertEqual(self.editor.text(), "abc")
        self.assertEqual(self.editor.getCursorPosition(), (0, 1))

    def test_delete_and_yank_line(self):
        self.editor.setText("one\ntwo\n")
        self.editor.setCursorPosition(0, 0)
        self.press("dd")
        self.assertEqual(self.editor.text(), "two\n")
        self.press("yy")
        self.assertEqual(self.editor._vim_mode._registers['"'], "two\n")

    def test_text_object_change_word(self):
        self.editor.setText("hello world")
        self.editor.setCursorPosition(0, 0)
        self.press("ciwX")
        self.editor.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.editor.text(), "X world")

    def test_colon_set_wrap_and_goto(self):
        self.editor.setText("a\nb\nc")
        self.editor._vim_mode.execute_command("set wrap")
        self.editor._vim_mode.execute_command("goto 3")
        self.assertTrue(self.editor.SendScintilla(QsciScintilla.SCI_GETWRAPMODE))
        self.assertEqual(self.editor.getCursorPosition(), (2, 0))

    def test_command_accepts_an_optional_leading_colon(self):
        self.editor.setText("b\na\n")
        self.editor.setSelection(0, 0, 1, 0)
        with patch.object(self.editor._vim_mode, "_filter_selection") as filter_selection:
            self.editor._vim_mode.execute_command(":!sort")
        filter_selection.assert_called_once_with("sort")

    def test_shifted_colon_opens_the_vim_command_prompt(self):
        with patch.object(self.editor._vim_mode, "_command_line") as command_line:
            event = QKeyEvent(
                QKeyEvent.Type.KeyPress, Qt.Key.Key_Colon,
                Qt.KeyboardModifier.ShiftModifier, ":",
            )
            self.editor.keyPressEvent(event)
        command_line.assert_called_once()
