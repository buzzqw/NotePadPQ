import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from editor.spellcheck import (
    _CHECKERS,
    HunspellBinaryBackend,
    _dictionary_prefix,
    get_spell_checker,
    iter_spell_words,
)

SAMPLE = r"""
\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\definecolor{grigio}{RGB}{1,2,3}
\begin{itemize}[leftmargin=*,topsep=2pt]
  \item \textbf{Questo} è un testo con l'articolo e dell'altro.
  \rowcolor{gray!20}
  Formula $x^2 + y^2 = z^2$ e mappa in inc/Images/mappa.pdf.
  % commento con parolainventata
  \begin{equation} E = mc^2 \end{equation}
  \section*{Introduzione all'analisi}
  \cite{rossi2020} \label{sec:intro}
  \includegraphics[width=.5\textwidth]{fig/sade.png}
  perch\'e l'Universit\`a \`E bella. Vedi ``virgolette'' e https://example.com/parola
\end{itemize}
"""


def _words(text: str) -> list[str]:
    return [word for _, _, word in iter_spell_words(text)]


class LatexSpellTokenizerTest(unittest.TestCase):
    def test_prose_is_kept_inside_text_commands(self):
        words = _words(SAMPLE)
        for expected in (
            "Questo", "testo", "articolo", "altro", "Formula", "mappa",
            "Introduzione", "analisi", "bella", "virgolette", "Vedi",
            "perché", "Università",
        ):
            self.assertIn(expected, words)

    def test_markup_keys_paths_math_and_comments_are_skipped(self):
        words = _words(SAMPLE)
        for unexpected in (
            "documentclass", "usepackage", "definecolor", "grigio",
            "itemize", "leftmargin", "topsep", "rowcolor", "gray",
            "inc", "Images", "pdf", "parolainventata", "equation",
            "section", "cite", "rossi2020", "label", "sec", "intro",
            "includegraphics", "width", "textwidth", "fig", "sade",
            "png", "example", "parola", "dell", "all",
        ):
            self.assertNotIn(unexpected, words)

    def test_offsets_always_map_to_the_original_text(self):
        for start, end, word in iter_spell_words(SAMPLE):
            self.assertGreater(end, start)
            raw = SAMPLE[start:end]
            self.assertTrue(raw)
            if raw.isalpha():
                self.assertEqual(raw, word)

    def test_latex_accents_are_recomposed(self):
        span = next(
            (start, end) for start, end, word in iter_spell_words(SAMPLE)
            if word == "perché"
        )
        self.assertEqual(SAMPLE[span[0]:span[1]], r"perch\'e")

    def test_elisions_and_closing_quotes(self):
        words = _words(r"dell'articolo quest'altra ``virgolette'' po'")
        self.assertIn("articolo", words)
        self.assertIn("altra", words)
        self.assertIn("virgolette", words)
        self.assertNotIn("dell", words)
        self.assertNotIn("quest", words)

    def test_urls_are_skipped_and_spans_survive(self):
        text = "Vedi https://example.com/una/parola e scrivi a me@example.com"
        words = _words(text)
        self.assertIn("Vedi", words)
        self.assertIn("scrivi", words)
        self.assertNotIn("example", words)
        self.assertNotIn("parola", words)
        self.assertNotIn("me", words)

    def test_word_after_a_period_without_space_is_not_skipped(self):
        self.assertIn("Vedi", _words("Fine.Vedi anche questo."))
        self.assertIn("pdf", _words("Il file mappa.pdf non esiste."))
        self.assertNotIn("pdf", _words("Il file inc/Images/mappa.pdf non esiste."))

    def test_trailing_optional_arguments_are_skipped(self):
        words = _words(r"\newcommand{\mio}[1]{testo} e \newtheorem{thm}{Teo}[section] Testo")
        self.assertIn("Testo", words)
        for unexpected in ("mio", "testo", "thm", "Teo", "section"):
            self.assertNotIn(unexpected, words)

    def test_inline_verbatim_does_not_swallow_the_rest(self):
        for text in (r"\lstinline{codice} e poi parola", r"\verb|codice| e poi parola"):
            words = _words(text)
            self.assertIn("parola", words)
            self.assertNotIn("codice", words)

    def test_percent_inside_verbatim_is_not_a_comment(self):
        words = _words(r"\verb|%| e poi parola")
        self.assertIn("parola", words)
        self.assertNotIn("verb", words)

    def test_empty_text(self):
        self.assertEqual(list(iter_spell_words("")), [])


class SpellWorkerLatexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _run_worker(self, text, personal=frozenset()):
        from editor.editor_widget import _SpellWorker

        class _Checker:
            def unknown(self, words):
                return {word for word in words if word == "parolasbagliata"}

        emitted = []
        worker = _SpellWorker(text, _Checker(), personal, 1)
        worker.done.connect(lambda generation, positions: emitted.append(positions))
        worker.run()
        return emitted[0]

    def test_latex_commands_do_not_produce_false_errors(self):
        text = r"\cite{chiave} parolasbagliata" + "\n" + r"$x + y$ \label{sec:uno}"
        positions = self._run_worker(text)
        start = text.index("parolasbagliata")
        self.assertEqual(positions, [(0, start, 0, start + len("parolasbagliata"))])

    def test_personal_dictionary_is_case_insensitive(self):
        text = "Parolasbagliata"
        self.assertEqual(self._run_worker(text, frozenset({"parolasbagliata"})), [])


class PyspellcheckerBackendTest(unittest.TestCase):
    def test_results_keep_the_original_capitalisation(self):
        from editor.spellcheck import PyspellcheckerBackend

        checker = PyspellcheckerBackend("it")
        self.assertEqual(
            checker.unknown(["Penalità", "penalità", "Xyzzy"]),
            {"Penalità", "penalità", "Xyzzy"},
        )


class HunspellBackendTest(unittest.TestCase):
    def test_hunspell_wins_when_a_dictionary_is_installed(self):
        executable = shutil.which("hunspell")
        prefix = _dictionary_prefix("it")
        if not executable or prefix is None:
            self.skipTest("Hunspell o dizionario italiano non disponibili")
        checker = HunspellBinaryBackend(executable, prefix)
        self.assertNotIn("penalità", checker.unknown(["penalità"]))
        self.assertNotIn("incantesimo", checker.unknown(["incantesimo"]))
        self.assertIn("xyzzyplugh", checker.unknown(["xyzzyplugh"]))
        self.assertTrue(checker.candidates("penalit"))

    def test_factory_prefers_hunspell_and_falls_back(self):
        prefix = _dictionary_prefix("it")
        if not shutil.which("hunspell") or prefix is None:
            self.skipTest("Hunspell o dizionario italiano non disponibili")
        with mock.patch.dict(_CHECKERS, clear=True):
            self.assertEqual(get_spell_checker("it").name, "hunspell")

        with mock.patch.dict(_CHECKERS, clear=True), \
                mock.patch("editor.spellcheck._dictionary_prefix", return_value=None):
            self.assertEqual(get_spell_checker("it").name, "pyspellchecker")

    def test_dictionaries_are_also_searched_in_the_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "hunspell"
            root.mkdir()
            for suffix in (".aff", ".dic"):
                (root / f"it_IT{suffix}").write_text("", encoding="utf-8")
            with mock.patch.dict(
                os.environ, {"NOTEPADPQ_HUNSPELL_DIR": str(root)}
            ), mock.patch("editor.spellcheck._dictionary_roots", return_value=[root]):
                self.assertEqual(_dictionary_prefix("it"), root / "it_IT")


if __name__ == "__main__":
    unittest.main()
