import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.Qsci import QsciScintilla
from PyQt6.QtWidgets import QApplication

from editor.latex_checker import _CheckWorker
from editor.latex_support import LaTeXSupport, strip_latex_comments
from editor.lexer_latex_custom import S_DEFAULT, S_MATH, LaTeXLexer


class _DollarEditor:
    def __init__(self, text, col):
        self._text = text
        self._col = col

    def getCursorPosition(self):
        return 0, self._col

    def text(self, line):
        return self._text

    def beginUndoAction(self):
        pass

    def endUndoAction(self):
        pass

    def insert(self, value):
        self._text = self._text[:self._col] + value + self._text[self._col:]

    def setCursorPosition(self, line, col):
        self._col = col


class LatexSupportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_comment_escaping_uses_backslash_parity(self):
        text = "one \\% two\ntwo \\\\% three\n"
        self.assertEqual(strip_latex_comments(text), "one \\% two\n" + "two " + "\\\\" + "\n")

    def test_dollar_handler_ignores_escaped_and_existing_closer(self):
        escaped = _DollarEditor(r"\$", 2)
        LaTeXSupport._handle_dollar(escaped)
        self.assertEqual(escaped._text, r"\$")

        existing = _DollarEditor("$|$".replace("|", ""), 1)
        LaTeXSupport._handle_dollar(existing)
        self.assertEqual(existing._text, "$$")

        opening = _DollarEditor("$", 1)
        LaTeXSupport._handle_dollar(opening)
        self.assertEqual(opening._text, "$$")

    def test_environment_balance_is_source_ordered_without_pop_cascade(self):
        errors = LaTeXSupport.check_environment_balance(
            r"\begin{a} \begin{b} \end{a} \end{b}"
        )
        self.assertEqual(len(errors), 2)
        self.assertIn("closes 'b'", errors[0]["msg"])
        self.assertIn("a} not closed", errors[1]["msg"])

    def test_math_mode_handles_delimiters_and_math_environments(self):
        text = "text \\(a $ b\n c\\) text \\[d\\] \\begin{align}x\n y\\end{align}"
        self.assertTrue(LaTeXSupport.is_in_math_mode(text, text.index("c")))
        self.assertTrue(LaTeXSupport.is_in_math_mode(text, text.index("y")))
        self.assertFalse(LaTeXSupport.is_in_math_mode(text, len(text)))

    def test_table_count_ignores_escaped_and_nested_separators(self):
        self.assertEqual(_CheckWorker._count_row_cols(r"a \& b & c"), 2)
        self.assertEqual(
            _CheckWorker._count_row_cols(r"a & \multicolumn{2}{c}{x & y} & z"),
            4,
        )
        self.assertEqual(_CheckWorker._count_tabular_cols(r"*{2}{c}"), 2)
        self.assertEqual(
            _CheckWorker._count_tabular_cols(r">{\raggedright}p{2cm}X"), 2
        )

    def test_collect_project_files_supports_two_argument_imports_and_cycles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "chapters" / "nested").mkdir(parents=True)
            main = root / "main.tex"
            one = root / "chapters" / "one.tex"
            two = root / "chapters" / "two.tex"
            three = root / "chapters" / "nested" / "three.tex"
            main.write_text(r"\import{chapters}{one}\subimport{chapters}{two}")
            one.write_text(r"\includefrom{../}{main}\subinputfrom{nested}{three}")
            two.write_text("two")
            three.write_text("three")

            files = LaTeXSupport.collect_project_files(main)
            self.assertEqual(files, [main.resolve(), one.resolve(),
                                     three.resolve(), two.resolve()])

    def test_bibtex_keys_include_current_bib_text_and_referenced_files(self):
        current = "@article{current, title={Now}}\n% @book{ignored, title={No}}"
        self.assertEqual(LaTeXSupport.extract_bibtex_keys(current), ["current"])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tex = root / "main.tex"
            bib = root / "refs.bib"
            tex.write_text(r"\addbibresource{refs}")
            bib.write_text("@book{saved, title={Saved}}")
            self.assertEqual(
                LaTeXSupport.extract_bibtex_keys(
                    r"\addbibresource{refs}", tex
                ),
                ["saved"],
            )

    def test_dynamic_api_and_environment_list_include_included_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            child = root / "child.tex"
            main.write_text(r"\input{child}")
            child.write_text(
                r"\usepackage{listings}\newenvironment{customenv}{}{}"
            )

            api = LaTeXSupport.build_dynamic_api("", main)
            self.assertIn(r"\begin{customenv}", api)
            self.assertIn(r"\lstinline{}", api)
            self.assertIn("lstlisting", LaTeXSupport.get_all_environments("", main))

    def test_lexer_preserves_math_state_between_style_chunks(self):
        lexer = LaTeXLexer()
        lexer.startStyling = mock.Mock()
        lexer.setStyling = mock.Mock()
        text = b"$$a\nb$$\n"
        lexer._style_with_state(0, 4, text)
        lexer.setStyling.reset_mock()
        lexer._style_with_state(4, len(text), text)
        styles = [call.args[1] for call in lexer.setStyling.call_args_list]
        self.assertIn(S_MATH, styles)
        self.assertEqual(lexer._state_at(text, len(text))[0], "default")

    def test_lexer_recognizes_all_multiline_math_delimiters(self):
        lexer = LaTeXLexer()
        for text in (b"\\(x\ny\\)", b"\\[x\ny\\]",
                     b"\\begin{gather}x\ny\\end{gather}"):
            lexer._state_cache = {0: ("default", ())}
            self.assertEqual(lexer._state_at(text, len(text))[0], "default")


class LaTeXLexerIncrementalCacheTest(unittest.TestCase):
    """Copre la potatura incrementale della cache di stato (SCN_MODIFIED +
    bisect) introdotta per eliminare il freeze multi-secondo per keystroke.

    I test in LatexSupportTest istanziano LaTeXLexer(parent=None) (SCN_MODIFIED
    non è mai collegato) e mutano _state_cache direttamente bypassando
    _cache_state/_invalidate_state_from: la logica di potatura non era
    esercitata da nessun test."""

    @staticmethod
    def _expand_styles(setStyling_mock) -> list[int]:
        out: list[int] = []
        for call in setStyling_mock.call_args_list:
            count, style = call.args
            out.extend([style] * count)
        return out

    def _styled_lexer(self, text_b: bytes, start: int, end: int) -> tuple[LaTeXLexer, int, list[int]]:
        lexer = LaTeXLexer()
        lexer.startStyling = mock.Mock()
        lexer.setStyling = mock.Mock()
        lexer._style_with_state(start, end, text_b)
        safe = lexer.startStyling.call_args.args[0]
        return lexer, safe, self._expand_styles(lexer.setStyling)

    def test_invalidate_state_from_keeps_prefix_and_boundary(self):
        lexer = LaTeXLexer()
        lexer._state_cache = {
            0: ("default", ()), 5: ("dollar", ()),
            10: ("default", ()), 20: ("environment", ("equation",)),
        }
        lexer._state_cache_order = [0, 5, 10, 20]

        lexer._invalidate_state_from(10)

        # L'entry esattamente sulla posizione dell'edit descrive il testo
        # PRIMA dell'edit e resta valida (bisect_right, non bisect_left).
        self.assertEqual(lexer._state_cache_order, [0, 5, 10])
        self.assertEqual(set(lexer._state_cache), {0, 5, 10})
        self.assertEqual(lexer._state_cache[10], ("default", ()))

    def test_invalidate_state_from_no_op_when_edit_after_all_checkpoints(self):
        lexer = LaTeXLexer()
        lexer._state_cache = {0: ("default", ()), 5: ("dollar", ())}
        lexer._state_cache_order = [0, 5]

        lexer._invalidate_state_from(100)

        self.assertEqual(lexer._state_cache_order, [0, 5])
        self.assertEqual(set(lexer._state_cache), {0, 5})

    def test_on_scn_modified_ignores_style_only_notifications(self):
        lexer = LaTeXLexer()
        lexer._state_cache = {0: ("default", ()), 5: ("dollar", ())}
        lexer._state_cache_order = [0, 5]

        # SC_MOD_CHANGESTYLE è la nostra stessa setStyling(): se invalidasse
        # la cache si tornerebbe al bug originale (rescan completo ad ogni
        # styleText invece che ad ogni vera modifica di testo).
        lexer._on_scn_modified(0, QsciScintilla.SC_MOD_CHANGESTYLE,
                                b"", 0, 0, 0, 0, 0, 0, 0)

        self.assertEqual(lexer._state_cache_order, [0, 5])
        self.assertEqual(set(lexer._state_cache), {0, 5})

    def test_on_scn_modified_prunes_on_insert_and_delete(self):
        for mod_type in (QsciScintilla.SC_MOD_INSERTTEXT, QsciScintilla.SC_MOD_DELETETEXT):
            with self.subTest(mod_type=mod_type):
                lexer = LaTeXLexer()
                lexer._state_cache = {0: ("default", ()), 5: ("dollar", ()), 12: ("default", ())}
                lexer._state_cache_order = [0, 5, 12]

                lexer._on_scn_modified(5, mod_type, b"x", 1, 0, 0, 0, 0, 0, 0)

                self.assertEqual(lexer._state_cache_order, [0, 5])
                self.assertEqual(set(lexer._state_cache), {0, 5})

    def test_incremental_restyle_after_deleting_math_delimiter_matches_full_rescan(self):
        """Il caso reale del bug: documento con molte righe, edit vicino alla
        fine che cambia lo stato (chiude/apre il math mode). L'highlighting
        prodotto riusando la cache potata a partire dal punto di edit deve
        essere IDENTICO a quello di una riscansione completa dallo zero —
        la potatura non deve lasciare stato stantio dopo il punto di edit."""
        lines = [r"\documentclass{article}", r"\begin{document}"]
        for i in range(40):
            lines.append(f"Text line {i} with $m_{i}$ math end.")
        lines.append(r"\end{document}")
        before_text = ("\n".join(lines) + "\n").encode("ascii")

        # Rimuove il '$' di chiusura sulla riga "Text line 35": da lì in poi
        # il documento resta in modalità 'dollar' aperta fino a EOF, quindi
        # tutte le righe successive vanno reinterpretate diversamente.
        after_lines = list(lines)
        after_lines[37] = after_lines[37].replace("$m_35$", "$m_35", 1)
        after_text = ("\n".join(after_lines) + "\n").encode("ascii")
        self.assertNotEqual(before_text, after_text)

        prefix_len = 0
        limit = min(len(before_text), len(after_text))
        while prefix_len < limit and before_text[prefix_len] == after_text[prefix_len]:
            prefix_len += 1
        edit_position = prefix_len
        self.assertGreater(edit_position, 0)

        lexer = LaTeXLexer()
        lexer.startStyling = mock.Mock()
        lexer.setStyling = mock.Mock()
        lexer._style_with_state(0, len(before_text), before_text)

        # Sanity: sono stati cachati molti checkpoint (uno per riga), non solo
        # {0: default} — altrimenti il test non eserciterebbe davvero la cache.
        self.assertGreater(len(lexer._state_cache), 30)
        checkpoints_before_edit = {p for p in lexer._state_cache if p <= edit_position}
        self.assertGreater(len(checkpoints_before_edit), 5)

        lexer._on_scn_modified(edit_position, QsciScintilla.SC_MOD_DELETETEXT,
                                b"$", 1, 0, 0, 0, 0, 0, 0)
        lexer._on_text_changed()

        # I checkpoint precedenti l'edit sopravvivono intatti...
        self.assertEqual({p for p in lexer._state_cache if p <= edit_position},
                          checkpoints_before_edit)
        # ...quelli successivi sono stati scartati.
        self.assertTrue(all(p <= edit_position for p in lexer._state_cache))

        lexer.setStyling.reset_mock()
        lexer.startStyling.reset_mock()
        lexer._style_with_state(edit_position, len(after_text), after_text)
        safe = lexer.startStyling.call_args.args[0]
        incremental_styles = self._expand_styles(lexer.setStyling)

        _, safe_gt, ground_styles = self._styled_lexer(after_text, 0, len(after_text))
        self.assertEqual(safe_gt, 0)

        region = ground_styles[safe:safe + len(incremental_styles)]
        self.assertEqual(
            incremental_styles, region,
            "la potatura incrementale della cache produce un highlighting diverso "
            "da una riscansione completa: dopo l'edit la cache contiene stato stantio",
        )


class LaTeXLexerVerbatimTest(unittest.TestCase):
    """Copre il trattamento come testo letterale di verbatim/lstlisting/
    minted e \\verb. Prima di questo fix il lexer interpretava sempre %, $
    e i comandi anche dentro questi blocchi, producendo highlighting (e
    stato residuo) sbagliato per il resto del documento."""

    @staticmethod
    def _painted_styles(lexer) -> list[int]:
        out: list[int] = []
        for call in lexer.setStyling.call_args_list:
            count, style = call.args
            out.extend([style] * count)
        return out

    def _style(self, text: bytes) -> tuple[LaTeXLexer, list[int]]:
        lexer = LaTeXLexer()
        lexer.startStyling = mock.Mock()
        lexer.setStyling = mock.Mock()
        lexer._style_with_state(0, len(text), text)
        return lexer, self._painted_styles(lexer)

    def test_percent_and_dollar_are_literal_inside_verbatim(self):
        text = (b"\\begin{verbatim}\n"
                b"50% not a comment, $not math$\n"
                b"\\end{verbatim}\n")
        lexer, styles = self._style(text)
        self.assertEqual(styles[text.index(b"%")], S_DEFAULT)
        self.assertEqual(styles[text.index(b"$")], S_DEFAULT)
        self.assertEqual(lexer._state_at(text, len(text))[0], "default")

    def test_percent_at_start_of_verbatim_line_is_not_a_comment(self):
        # Il bulk-skip di verbatim salta da un backslash/newline al
        # successivo senza mai "visitare" un '%' isolato in mezzo alla riga
        # — ma se il '%' è il PRIMO byte dopo un a-capo, `safe` (inizio
        # riga) coincide con la sua posizione e il controllo di riga in
        # cima al loop lo vede direttamente: qui il guard mode!='verbatim'
        # è l'unica cosa che impedisce di colorarlo come inizio commento.
        text = b"\\begin{verbatim}\n%starts with percent\n\\end{verbatim}\n"
        lexer, styles = self._style(text)
        self.assertEqual(styles[text.index(b"%")], S_DEFAULT)

    def test_state_inside_verbatim_block_is_verbatim(self):
        text = b"\\begin{verbatim}\nhello\n\\end{verbatim}\n"
        lexer, _ = self._style(text)
        self.assertEqual(lexer._state_at(text, text.index(b"hello"))[0], "verbatim")

    def test_mismatched_end_does_not_close_verbatim(self):
        text = (b"\\begin{verbatim}\n"
                b"\\end{other}\n"
                b"still literal\n"
                b"\\end{verbatim}\n"
                b"after\n")
        lexer, _ = self._style(text)
        self.assertEqual(
            lexer._state_at(text, text.index(b"still literal"))[0], "verbatim")
        self.assertEqual(lexer._state_at(text, text.index(b"after"))[0], "default")

    def test_lstlisting_and_minted_and_capitalized_verbatim_are_literal(self):
        for env in (b"lstlisting", b"minted", b"Verbatim"):
            with self.subTest(env=env):
                text = (b"\\begin{" + env + b"}\n"
                        b"$x$ % not math or comment\n"
                        b"\\end{" + env + b"}\n")
                lexer, _ = self._style(text)
                self.assertEqual(lexer._state_at(text, len(text))[0], "default")

    def test_verb_inline_with_dollar_delimiter_has_no_side_effects(self):
        # \verb usa '$' come delimitatore: senza il fix, quel '$' verrebbe
        # interpretato come apertura di math mode e romperebbe il resto
        # della riga (compreso il $real math$ vero che segue).
        text = b"Command \\verb$a%b$ then $real math$ here.\n"
        lexer, styles = self._style(text)
        self.assertEqual(lexer._state_at(text, len(text))[0], "default")
        self.assertEqual(styles[text.index(b"$real")], S_MATH)

    def test_verb_star_variant_with_pipe_delimiter(self):
        text = b"See \\verb*|literal|text after.\n"
        lexer, _ = self._style(text)
        self.assertEqual(lexer._state_at(text, len(text))[0], "default")

    def test_verbatim_like_prefix_is_not_mistaken_for_verb_command(self):
        # \verbatim e \verbose iniziano per "verb" ma non sono \verb: il
        # carattere seguente deve essere un delimitatore non alfabetico,
        # altrimenti è un comando normale (o l'ambiente verbatim stesso).
        self.assertIsNone(LaTeXLexer._verb_inline_span(b"\\verbatim{x}", 0))
        self.assertIsNone(LaTeXLexer._verb_inline_span(b"\\verbose text", 0))


if __name__ == "__main__":
    unittest.main()
