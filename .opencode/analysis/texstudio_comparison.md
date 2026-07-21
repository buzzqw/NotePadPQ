# Analisi comparativa NotePadPQ vs TeXstudio
# Data: 2026-07-21

## Panoramica

NotePadPQ (v1.6.7) è un editor avanzato open-source Python/PyQt6/QScintilla con funzionalità LaTeX estese.
TeXstudio (v4.9.5) è l'editor LaTeX di riferimento, C++/Qt, con oltre 15 anni di sviluppo focalizzato su LaTeX.

## Feature già presenti in NotePadPQ

| Feature TeXstudio | File NotePadPQ | Note |
|---|---|---|
| Syntax highlighting LaTeX | editor/lexer_latex_custom.py | 9 stili, byte-level scanning |
| Structure view | ui/latex_minimap.py | Albero part/chapter/section/... |
| Syntax checker LaTeX | editor/latex_checker.py | \begin/\end, \ref, \cite in background |
| Tooltip comandi | editor/latex_tooltips.py | 2423+ righe di comandi |
| Wizard LaTeX | editor/latex_wizard.py | Tabelle, formule, ambienti |
| SyncTeX | editor/synctex.py | Bidirezionale editor↔PDF |
| Menu LaTeX dinamico | ui/latex_menu.py | Appare solo per file .tex |
| Build profiles | core/build_manager.py | pdflatex, xelatex, lualatex, latexmk |
| Preview PDF live | ui/preview_panel.py, ui/pdf_viewer_widget.py | PyMuPDF + fallback WebEngine |
| LSP texlab | editor/lsp_client.py | Diagnostica real-time |
| Spell checking | ui/spell_check_dialog.py | IT, EN, DE, FR, ES |
| Multi-cursor | editor/multicursor.py | Ctrl+D, Ctrl+Shift+D |
| Code folding | editor/folding.py | Supporto nativo QScintilla |
| Bookmarks | ui/bookmarks.py | Ctrl+F2 |
| Git integration | plugins/git_plugin.py | Panel con status, log, diff, branch, PR |
| AI assistant | plugins/ai_plugin.py | Claude, OpenAI, Gemini, Ollama |
| Macro | core/macro.py | Record/playback |
| Project manager | ui/project_manager.py | File .npqproj |
| Image insertion | ui/latex_insert_image_dialog.py | Dialog con opzioni |
| Auto-close env | editor/latex_support.py | \begin → \end, suggerimenti popup |
| Hover math preview | editor/latex_support.py | Matplotlib per $...$, $$...$$ |
| Markup shortcuts | editor/editor_widget.py | Ctrl+B → \textbf{} etc. |
| Table alignment | editor/table_editor.py | Markdown e LaTeX tabular |

## Gap identificati vs TeXstudio

### CRITICI
1. **CWL System** - Completamento per-package mancante
2. **Inline formula preview** - Solo hover, non inline nell'editor

### ALTI
3. **Link overlay** - Ctrl+click su \ref/\cite/\input non navigabile
4. **Grammar checker (LanguageTool)** - Assente
5. **Interattività reference checker** - Background, non inline interattivo

### MEDI
6. **Pannello simboli matematici** - 1000+ simboli organizzati per categoria
7. **Manipolazione tabelle** - Aggiungi/rimuovi colonne, auto-formatter
8. **Drag & drop immagini** - Wizard automatico al drop
9. **Editing collaborativo** - teamtype peer-to-peer

### MEDIO-BASSI
10. **Wizard avvio rapido / Template**
11. **Auto-detect multi-run LaTeX**
12. **BibTeX avanzato** - Completamento chiavi, auto-esecuzione bibtex/biber
13. **Global TOC + file caching**

### BASSI
14. **Expl3 highlighting**
15. **Indent guides + rainbow braces**
16. **Text selection in PDF viewer**
17. **Macro repository online**

## Tecnologie chiave TeXstudio da studiare
- CWL parser: file .cwl definiscono comandi, argomenti, key-value, classificazioni
- LanguageTool HTTP API: controllo grammaticale via server locale
- teamtype: protocollo peer-to-peer per editing collaborativo
- Poppler: rendering PDF nativo (vs PyMuPDF in NotePadPQ)
