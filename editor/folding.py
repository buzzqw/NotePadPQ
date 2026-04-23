"""
editor/folding.py — Code Folding
NotePadPQ

Gestisce gli stili di folding, i shortcut e le operazioni
di piega/espandi per l'editor QScintilla.
Applicato automaticamente quando si imposta un lexer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.Qsci import QsciScintilla

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


# Stili di folding disponibili
FOLD_STYLES = {
    "none":        QsciScintilla.FoldStyle.NoFoldStyle,
    "plain":       QsciScintilla.FoldStyle.PlainFoldStyle,
    "circled":     QsciScintilla.FoldStyle.CircledFoldStyle,
    "boxed":       QsciScintilla.FoldStyle.BoxedFoldStyle,
    "circled_tree":QsciScintilla.FoldStyle.CircledTreeFoldStyle,
    "boxed_tree":  QsciScintilla.FoldStyle.BoxedTreeFoldStyle,
}

DEFAULT_STYLE = "boxed_tree"
MARGIN_FOLD   = 1   # stesso valore di editor_widget.MARGIN_FOLD


def apply_folding(editor: "EditorWidget",
                  style: str = DEFAULT_STYLE) -> None:
    """
    Applica la configurazione di folding all'editor.
    Chiamato da lexers.py dopo aver impostato il lexer.
    """
    qsci_style = FOLD_STYLES.get(style, FOLD_STYLES[DEFAULT_STYLE])
    editor.setFolding(qsci_style, MARGIN_FOLD)

    # Colori margine fold coerenti con il tema
    from config.themes import ThemeManager
    tm = ThemeManager.instance()
    theme = tm.get_theme(tm.active_name())
    if theme:
        ui = theme.get("ui", {})
        fg = ui.get("fold_fg", "#c5c5c5")
        bg = ui.get("fold_bg", "#37373d")
        from PyQt6.QtGui import QColor
        editor.setFoldMarginColors(QColor(bg), QColor(fg))


def fold_all(editor: "EditorWidget") -> None:
    """Piega tutti i blocchi foldabili."""
    editor.foldAll(True)


def unfold_all(editor: "EditorWidget") -> None:
    """Espande tutti i blocchi foldabili."""
    editor.foldAll(False)


def toggle_fold_at_line(editor: "EditorWidget", line: int) -> None:
    """Piega/espande il blocco alla riga indicata (0-based)."""
    editor.foldLine(line)


def fold_level(editor: "EditorWidget", level: int) -> None:
    """
    Piega tutti i blocchi fino al livello specificato.
    level=1 → piega solo il livello più esterno
    level=2 → piega fino al secondo livello, ecc.
    """
    total_lines = editor.lines()
    for line in range(total_lines):
        fold_level_line = (
            editor.SendScintilla(QsciScintilla.SCI_GETFOLDLEVEL, line)
            & QsciScintilla.SC_FOLDLEVELNUMBERMASK
        )
        base = QsciScintilla.SC_FOLDLEVELBASE
        if fold_level_line - base < level:
            header = editor.SendScintilla(
                QsciScintilla.SCI_GETFOLDLEVEL, line
            ) & QsciScintilla.SC_FOLDLEVELHEADERFLAG
            if header:
                expanded = editor.SendScintilla(
                    QsciScintilla.SCI_GETFOLDEXPANDED, line
                )
                if expanded:
                    editor.SendScintilla(
                        QsciScintilla.SCI_FOLDLINE, line,
                        QsciScintilla.SC_FOLDACTION_CONTRACT
                    )


def get_fold_state(editor: "EditorWidget") -> dict[int, bool]:
    """
    Restituisce lo stato corrente di tutti i fold.
    {line_number: is_expanded}
    Usato da session.py per salvare e ripristinare lo stato.
    """
    state = {}
    for line in range(editor.lines()):
        level = editor.SendScintilla(QsciScintilla.SCI_GETFOLDLEVEL, line)
        if level & QsciScintilla.SC_FOLDLEVELHEADERFLAG:
            expanded = bool(
                editor.SendScintilla(QsciScintilla.SCI_GETFOLDEXPANDED, line)
            )
            state[line] = expanded
    return state


def restore_fold_state(editor: "EditorWidget",
                       state: dict[int, bool]) -> None:
    """Ripristina lo stato dei fold salvato da get_fold_state."""
    for line, expanded in state.items():
        current = bool(
            editor.SendScintilla(QsciScintilla.SCI_GETFOLDEXPANDED, line)
        )
        if current != expanded:
            editor.SendScintilla(
                QsciScintilla.SCI_FOLDLINE, line,
                QsciScintilla.SC_FOLDACTION_TOGGLE
            )
