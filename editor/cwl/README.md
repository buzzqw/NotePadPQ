# NotePadPQ LaTeX completion data

These `.cwl` files are **original NotePadPQ data**, written and maintained by
the NotePadPQ project. They are not copies of TeXstudio or of any other
editor's completion database.

The format is intentionally small and readable. Each line is one completion:

```text
\command[optional]{argument}#D{Human-readable description}
\begin{environment}#D{Human-readable description}
```

Supported metadata:

- `#D{...}` — description shown next to the completion
- `#S` — hide the entry from the completion popup
- `#N{n}` — declare `n` arguments when the signature has no groups
- `#include:file` — include another `.cwl` by file stem
- `#keyvals:\command` … `#endkeyvals` — option/value suggestions
- `#ifoption:name` / `#else` / `#endif` — conditional includes

Files can be added without touching Python. Put personal files in the user
configuration directory (`<config>/cwl`) or in a project-level `cwl/`
directory; NotePadPQ also accepts extra directories from
`latex/cwl_directories` and from `NOTEPADPQ_CWL_DIRS`.

## Bundled packages

The built-in set covers the packages used most often in everyday documents:

- **Math**: `amsmath`, `amssymb`, `amsthm`, `mathtools`, `bm`, `physics`,
  `unicode-math`, `mhchem`, `textcomp`
- **Layout and text**: `geometry`, `fancyhdr`, `titlesec`, `tocloft`,
  `setspace`, `microtype`, `csquotes`, `babel`, `polyglossia`, `fontenc`,
  `inputenc`, `fontspec`
- **Tables and lists**: `booktabs`, `tabularray`, `tabularx`, `array`,
  `longtable`, `xltabular`, `multirow`, `multicol`, `multicoltab`, `makecell`,
  `threeparttable`, `colortbl`, `hhline`, `enumitem`, `tasks`, `paralist`
- **Floats and figures**: `graphicx`, `caption`, `subcaption`, `float`,
  `wrapfig`, `rotating`, `pdflscape`, `placeins`, `pdfpages`
- **References**: `hyperref`, `biblatex`, `natbib`, `cleveref`, `varioref`,
  `glossaries`, `imakeidx`, `appendix`
- **Code and algorithms**: `listings`, `minted`, `fancyvrb`, `algorithm2e`,
  `algpseudocode`
- **Graphics and diagrams**: `tikz`, `pgfplots`, `tikz-cd`, `forest`
- **Boxes and notes**: `tcolorbox`, `todonotes`, `soul`, `ulem`
- **Presentations**: `beamer`
- **Programming helpers**: `etoolbox`, `xparse`

`multicoltab` is authored by Andres Zanzani; its completion file follows the
public package documentation and is maintained here with the rest of the set.

License: EUPL-1.2, the same license as NotePadPQ.
