import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.editor_widget import (
    EditorWidget,
    _load_persisted_personal_words,
    _persist_personal_word,
)


class PersonalDictPersistenceTest(unittest.TestCase):
    """_load_persisted_personal_words / _persist_personal_word: il
    dizionario personale "permanente" per lingua, distinto dalle parole
    ignorate solo per la sessione corrente."""

    def test_roundtrip_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("editor.editor_widget.get_data_dir", return_value=Path(tmp)):
                self.assertEqual(_load_persisted_personal_words("it"), set())

                _persist_personal_word("it", "notaparola")
                _persist_personal_word("it", "notaparola")  # dedup, non duplica la riga
                _persist_personal_word("it", "altratermine")

                words = _load_persisted_personal_words("it")
                self.assertEqual(words, {"notaparola", "altratermine"})

                path = Path(tmp) / "spellcheck" / "it.txt"
                self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

    def test_languages_are_kept_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("editor.editor_widget.get_data_dir", return_value=Path(tmp)):
                _persist_personal_word("it", "solo_italiano")
                _persist_personal_word("en", "english_only")

                self.assertEqual(_load_persisted_personal_words("it"), {"solo_italiano"})
                self.assertEqual(_load_persisted_personal_words("en"), {"english_only"})


class SpellCheckMenuActionsTest(unittest.TestCase):
    """Copre la distinzione reale tra "Aggiungi al dizionario" (persistito,
    letto anche da editor/sessioni future) e "Ignora tutto" (solo in memoria
    per questa sessione). Prima del fix entrambe le voci di menu chiamavano
    lo stesso identico handler: erano indistinguibili."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_add_to_dictionary_persists_ignore_all_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("editor.editor_widget.get_data_dir", return_value=Path(tmp)):
                editor = EditorWidget()
                editor.set_spellcheck_enabled(True, "it")
                self.addCleanup(editor.deleteLater)

                editor._spell_add_to_dictionary("permanentword")
                editor._spell_add_to_personal("sessiononlyword")

                self.assertIn("permanentword", editor._spell_personal)
                self.assertIn("sessiononlyword", editor._spell_personal)
                # Solo la parola aggiunta al dizionario finisce su disco.
                self.assertEqual(
                    _load_persisted_personal_words("it"), {"permanentword"}
                )

    def test_new_editor_session_inherits_only_the_persisted_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("editor.editor_widget.get_data_dir", return_value=Path(tmp)):
                first = EditorWidget()
                first.set_spellcheck_enabled(True, "it")
                self.addCleanup(first.deleteLater)
                first._spell_add_to_dictionary("permanentword")
                first._spell_add_to_personal("sessiononlyword")

                second = EditorWidget()
                second.set_spellcheck_enabled(True, "it")
                self.addCleanup(second.deleteLater)

                self.assertIn("permanentword", second._spell_personal)
                self.assertNotIn("sessiononlyword", second._spell_personal)


if __name__ == "__main__":
    unittest.main()
