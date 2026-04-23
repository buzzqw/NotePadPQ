"""
editor/synctex.py - Supporto SyncTeX bidirezionale
NotePadPQ

Implementa la navigazione bidirezionale tra sorgente .tex e PDF compilato
usando il tool CLI `synctex` (incluso in TeX Live).

Direzioni:
  tex -> pdf : dato riga/colonna nel .tex, trova pagina+coordinate nel PDF
  pdf -> tex : dato pagina+x+y nel PDF, trova file+riga nel sorgente .tex

Uso:
    sx = SyncTeX("/path/to/file.tex", "/path/to/file.pdf")
    result = sx.tex_to_pdf(line=10, col=1)
    # result = {"page": 1, "x": 171.1, "y": 134.7}

    result = sx.pdf_to_tex(page=1, x=171.1, y=134.7)
    # result = {"file": "/path/to/file.tex", "line": 10}
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional


class SyncTeX:
    """
    Wrapper attorno al CLI `synctex`.
    Una istanza per coppia (tex_path, pdf_path).
    """

    def __init__(self, tex_path: Path, pdf_path: Path):
        self.tex_path = Path(tex_path)
        self.pdf_path = Path(pdf_path)
        self._available: Optional[bool] = None

    # ── Disponibilità ─────────────────────────────────────────────────────────

    @staticmethod
    def is_available() -> bool:
        """Verifica che il CLI synctex sia nel PATH."""
        try:
            r = subprocess.run(
                ["synctex", "help"],
                capture_output=True, timeout=3
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def has_synctex_file(self) -> bool:
        """Controlla se esiste il file .synctex.gz per il PDF corrente."""
        synctex_gz = self.pdf_path.with_suffix(".synctex.gz")
        synctex    = self.pdf_path.with_suffix(".synctex")
        return synctex_gz.exists() or synctex.exists()

    # ── tex -> pdf ────────────────────────────────────────────────────────────

    def tex_to_pdf(self, line: int, col: int = 1) -> Optional[dict]:
        """
        Dato riga/colonna nel .tex, restituisce pagina e coordinate nel PDF.
        Ritorna: {"page": int, "x": float, "y": float} oppure None.
        """
        if not self.has_synctex_file():
            return None
        try:
            cmd = [
                "synctex", "view",
                "-i", f"{line}:{col}:{self.tex_path}",
                "-o", str(self.pdf_path),
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5
            )
            return self._parse_view(r.stdout)
        except Exception:
            return None

    def _parse_view(self, output: str) -> Optional[dict]:
        """Parsa l'output di `synctex view`."""
        if "SyncTeX result begin" not in output:
            return None
        result = {}
        for line in output.splitlines():
            if line.startswith("Page:"):
                try:
                    result["page"] = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("x:"):
                try:
                    result["x"] = float(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("y:"):
                try:
                    result["y"] = float(line.split(":")[1].strip())
                except ValueError:
                    pass
        return result if "page" in result else None

    # ── pdf -> tex ────────────────────────────────────────────────────────────

    def pdf_to_tex(self, page: int, x: float, y: float) -> Optional[dict]:
        """
        Dato pagina e coordinate nel PDF, restituisce file e riga nel sorgente.
        Ritorna: {"file": str, "line": int} oppure None.
        """
        if not self.has_synctex_file():
            return None
        try:
            cmd = [
                "synctex", "edit",
                "-o", f"{page}:{x:.1f}:{y:.1f}:{self.pdf_path}",
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5
            )
            return self._parse_edit(r.stdout)
        except Exception:
            return None

    def _parse_edit(self, output: str) -> Optional[dict]:
        """Parsa l'output di `synctex edit`."""
        if "SyncTeX result begin" not in output:
            return None
        result = {}
        for line in output.splitlines():
            if line.startswith("Input:"):
                # Normalizza il path (synctex può aggiungere "./" o simili)
                raw = line.split(":", 1)[1].strip()
                result["file"] = str(Path(raw).resolve())
            elif line.startswith("Line:"):
                try:
                    result["line"] = int(line.split(":")[1].strip())
                except ValueError:
                    pass
        return result if "line" in result else None

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def find_pdf_for_tex(tex_path: Path) -> Optional[Path]:
        """Cerca il PDF corrispondente al file .tex (stesso nome, stessa dir)."""
        pdf = tex_path.with_suffix(".pdf")
        return pdf if pdf.exists() else None

    @staticmethod
    def pdf_coords_from_mouse(
        widget_x: float, widget_y: float,
        pixmap_width: int, pixmap_height: int,
        page_width_pt: float, page_height_pt: float,
    ) -> tuple[float, float]:
        """
        Converte coordinate pixel del widget in coordinate PDF (punti tipografici).
        Necessario perché PyMuPDF rasterizza in pixel ma synctex usa punti PDF.
        """
        pdf_x = (widget_x / pixmap_width)  * page_width_pt
        pdf_y = (widget_y / pixmap_height) * page_height_pt
        return pdf_x, pdf_y
