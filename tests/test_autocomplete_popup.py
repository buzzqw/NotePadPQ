"""Regression tests for the popup-based LaTeX completion.

The native QScintilla user list is replaced by a QMenu (see
``EditorWidget.showUserList``).  These tests drive the real
``SCN_CHARADDED`` chain so that a generic popup cannot silently close the
contextual one (environments, options, labels, packages, …).
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor import autocomplete as autocomplete_module
from editor.autocomplete import AutoCompleteManager
from editor.editor_widget import EditorWidget
from editor.lexers import set_lexer_by_extension


class AutocompletePopupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._usage_cache = autocomplete_module._USAGE_COUNTS_CACHE
        autocomplete_module._USAGE_COUNTS_CACHE = {}
        self.editor = EditorWidget()
        self.editor.resize(800, 400)
        self.editor.show()
        set_lexer_by_extension(self.editor, ".tex")
        self.manager = AutoCompleteManager(self.editor)
        self.events = []
        self.editor.showUserList = (
            lambda list_id, labels: self.events.append((list_id, labels))
        )
        self.editor._hide_user_list_popup = (
            lambda: self.events.append(("hide",))
        )

    def tearDown(self):
        self.manager.shutdown()
        self.editor._hide_user_list_popup()
        self.editor.deleteLater()
        self.app.processEvents()
        autocomplete_module._USAGE_COUNTS_CACHE = self._usage_cache

    def _emit(self, text: str, char: str) -> None:
        self.editor.setText(text)
        self.editor.setCursorPosition(0, len(text))
        self.events.clear()
        self.editor.SCN_CHARADDED.emit(ord(char))

    def _last_show(self):
        shows = [event for event in self.events if event[0] != "hide"]
        return shows[-1] if shows else None

    def test_contextual_popups_are_not_closed_by_generic_completion(self):
        cases = (
            (r"\includegraphics[", "[", 10),
            (r"\begin{figure}[", "[", 10),
            (r"\begin{", "{", 3),
            (r"\begin{fig", "g", 3),
            (r"\end{fig", "g", 3),
        )
        for text, char, list_id in cases:
            with self.subTest(text=text):
                self._emit(text, char)
                last = self._last_show()
                self.assertIsNotNone(last, self.events)
                self.assertEqual(last[0], list_id)
                self.assertNotIn(("hide",), self.events)

    def test_contextual_list_is_filtered_while_typing(self):
        # Il primo carattere popola la cache ambienti, come nella digitazione
        # reale di ``\begin{``.
        self._emit(r"\begin{", "{")
        self._emit(r"\begin{fig", "g")
        self.assertEqual(self._last_show()[0], 3)
        self.assertNotIn(("hide",), self.events)
        self.assertTrue(all("fig" in item.casefold()
                            for item in self._last_show()[1]))

        self._emit(r"\cite{int", "t")
        # No bibliography cache: il contesto resta gestito e il popup
        # generico non deve apparire.
        self.assertFalse(any(event[0] == 30 for event in self.events))

    def test_labels_are_filtered_from_the_cache(self):
        self.manager._labels_cache = [
            ("sec:intro", "label"),
            ("sec:results", "label"),
        ]
        self._emit(r"\ref{", "{")
        self.assertEqual(self._last_show()[0], 5)
        self._emit(r"\ref{sec:r", "r")
        self.assertEqual(self._last_show(), (5, ["sec:results"]))

    def test_generic_completion_still_works_outside_contexts(self):
        self._emit(r"\inc", "c")
        self.assertEqual(self._last_show()[0], 30)
        self.assertTrue(self._last_show()[1])

    def test_exact_latex_command_is_offered_before_longer_variant(self):
        # Il documento contiene ``\vfill\null`` (token unico per il
        # completamento dalle parole del documento): digitando ``\vfill``
        # devono comparire entrambe le voci, con quella esatta per prima.
        autocomplete_module._USAGE_COUNTS_CACHE = {
            "cmd:\\vfill": 1,
            "cmd:\\vfill\\null": 9,
        }
        text = "\\vfill\\null"
        self.editor.setText(text)
        self.editor.setCursorPosition(0, len("\\vfill"))
        self.events.clear()
        self.editor.SCN_CHARADDED.emit(ord("l"))
        labels = self._last_show()[1]
        self.assertEqual(labels[0], "\\vfill")
        self.assertIn("\\vfill\\null", labels)

    def test_exact_latex_command_alone_does_not_open_popup(self):
        text = "\\vfill"
        self.editor.setText(text)
        self.editor.setCursorPosition(0, len(text))
        self.events.clear()
        self.editor.SCN_CHARADDED.emit(ord("l"))
        self.assertIsNone(self._last_show())

    def test_selection_places_caret_inside_braces(self):
        self.editor.setText(r"\sec")
        self.editor.setCursorPosition(0, 4)
        self.manager._on_custom_user_list_selection(30, r"\section{}")
        self.assertEqual(self.editor.text(), r"\section{}")
        self.assertEqual(self.editor.getCursorPosition(), (0, 9))

    def test_option_selection_preserves_previous_options(self):
        self.editor.setText(r"\includegraphics[width=, mo")
        self.editor.setCursorPosition(0, len(self.editor.text(0)))
        self.editor._on_user_list_selection(12, "mode=")
        self.assertEqual(
            self.editor.text(), r"\includegraphics[width=, mode="
        )

        self.editor.setText(r"\includegraphics[width=t")
        self.editor.setCursorPosition(0, len(self.editor.text(0)))
        self.editor._on_user_list_selection(12, "true")
        self.assertEqual(self.editor.text(), r"\includegraphics[width=true")

    def test_first_popup_entry_is_preselected(self):
        self.editor.setText("ab")
        self.editor.setCursorPosition(0, 2)
        # Usa l'implementazione reale, non il mock del setUp.
        EditorWidget.showUserList(self.editor, 30, ["abc", "abd"])
        self.app.processEvents()
        popup = self.editor._user_list_popup
        try:
            self.assertIsNotNone(popup)
            self.assertEqual(popup.currentRow(), 0)
            self.assertEqual(popup.currentItem().text(), "abc")
        finally:
            self.editor._hide_user_list_popup()

    def test_environment_popup_reopens_while_typing_begin(self):
        self._emit(r"\be", "e")
        self.assertEqual(self._last_show()[0], 3)
        for text, char in ((r"\beg", "g"), (r"\begi", "i"), (r"\begin", "n")):
            # Il tasto digitato chiude il popup Qt prima di arrivare all'editor:
            # il gestore deve riaprirlo a ogni lettera.
            self.editor._hide_user_list_popup()
            self._emit(text, char)
            last = self._last_show()
            self.assertIsNotNone(last, self.events)
            self.assertEqual(last[0], 3)

    def test_usage_sort_puts_most_used_first(self):
        autocomplete_module._USAGE_COUNTS_CACHE = {
            "cmd:\\section": 4,
            "cmd:\\subsection": 2,
        }
        ordered = self.manager._sort_by_usage(
            [r"\paragraph", r"\subsection", r"\section"],
            "cmd", self.manager._usage_command,
        )
        self.assertEqual(
            ordered, [r"\section", r"\subsection", r"\paragraph"]
        )

    def test_selected_completion_updates_usage_counts(self):
        class _FakeSettings:
            def __init__(self):
                self.values = {}

            def get(self, key, default=None):
                return self.values.get(key, default)

            def set(self, key, value):
                self.values[key] = value

        fake = _FakeSettings()
        import json
        with mock.patch("config.settings.Settings.instance", return_value=fake):
            self.manager._track_user_list_usage(30, r"\section{}")
            self.manager._track_user_list_usage(30, r"\section")

        self.assertEqual(
            autocomplete_module._USAGE_COUNTS_CACHE.get("cmd:\\section"), 2
        )
        stored = json.loads(fake.values["latex/completion_usage_counts"])
        self.assertEqual(stored["cmd:\\section"], 2)

    def test_option_popup_uses_usage_order(self):
        autocomplete_module._USAGE_COUNTS_CACHE = {
            "option:width=": 5,
            "option:height=": 1,
        }
        self.manager._show_option_context(
            ("option", "\\includegraphics"), 10,
            ["height=", "width=", "scale="], "",
        )
        self.assertEqual(self._last_show()[1][0], "width=")


if __name__ == "__main__":
    unittest.main()
