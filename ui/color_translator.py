"""
ui/color_translator.py — Traduttore colori HTML/CSS (stile PSPad)
NotePadPQ

Mostra un colore selezionato in diversi formati:
- Nome HTML/CSS (se riconosciuto)
- Barra del colore (anteprima visiva)
- Hex maiuscolo: #RRGGBB
- Hex minuscolo: #rrggbb
- RGB decimale:  rgb(r, g, b)
- RGB percentuale: rgb(r%, g%, b%)
- HSL:           hsl(h, s%, l%)
"""

from __future__ import annotations

import colorsys
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QClipboard
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QColorDialog, QApplication,
    QSizePolicy,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# ── Dizionario colori CSS nominati ────────────────────────────────────────────
# Mappa nome → (r, g, b) per i 148 colori CSS standard
_CSS_COLORS: dict[str, tuple[int, int, int]] = {
    "aliceblue": (240, 248, 255), "antiquewhite": (250, 235, 215),
    "aqua": (0, 255, 255), "aquamarine": (127, 255, 212),
    "azure": (240, 255, 255), "beige": (245, 245, 220),
    "bisque": (255, 228, 196), "black": (0, 0, 0),
    "blanchedalmond": (255, 235, 205), "blue": (0, 0, 255),
    "blueviolet": (138, 43, 226), "brown": (165, 42, 42),
    "burlywood": (222, 184, 135), "cadetblue": (95, 158, 160),
    "chartreuse": (127, 255, 0), "chocolate": (210, 105, 30),
    "coral": (255, 127, 80), "cornflowerblue": (100, 149, 237),
    "cornsilk": (255, 248, 220), "crimson": (220, 20, 60),
    "cyan": (0, 255, 255), "darkblue": (0, 0, 139),
    "darkcyan": (0, 139, 139), "darkgoldenrod": (184, 134, 11),
    "darkgray": (169, 169, 169), "darkgreen": (0, 100, 0),
    "darkkhaki": (189, 183, 107), "darkmagenta": (139, 0, 139),
    "darkolivegreen": (85, 107, 47), "darkorange": (255, 140, 0),
    "darkorchid": (153, 50, 204), "darkred": (139, 0, 0),
    "darksalmon": (233, 150, 122), "darkseagreen": (143, 188, 143),
    "darkslateblue": (72, 61, 139), "darkslategray": (47, 79, 79),
    "darkturquoise": (0, 206, 209), "darkviolet": (148, 0, 211),
    "deeppink": (255, 20, 147), "deepskyblue": (0, 191, 255),
    "dimgray": (105, 105, 105), "dodgerblue": (30, 144, 255),
    "firebrick": (178, 34, 34), "floralwhite": (255, 250, 240),
    "forestgreen": (34, 139, 34), "fuchsia": (255, 0, 255),
    "gainsboro": (220, 220, 220), "ghostwhite": (248, 248, 255),
    "gold": (255, 215, 0), "goldenrod": (218, 165, 32),
    "gray": (128, 128, 128), "green": (0, 128, 0),
    "greenyellow": (173, 255, 47), "honeydew": (240, 255, 240),
    "hotpink": (255, 105, 180), "indianred": (205, 92, 92),
    "indigo": (75, 0, 130), "ivory": (255, 255, 240),
    "khaki": (240, 230, 140), "lavender": (230, 230, 250),
    "lavenderblush": (255, 240, 245), "lawngreen": (124, 252, 0),
    "lemonchiffon": (255, 250, 205), "lightblue": (173, 216, 230),
    "lightcoral": (240, 128, 128), "lightcyan": (224, 255, 255),
    "lightgoldenrodyellow": (250, 250, 210), "lightgray": (211, 211, 211),
    "lightgreen": (144, 238, 144), "lightpink": (255, 182, 193),
    "lightsalmon": (255, 160, 122), "lightseagreen": (32, 178, 170),
    "lightskyblue": (135, 206, 250), "lightslategray": (119, 136, 153),
    "lightsteelblue": (176, 196, 222), "lightyellow": (255, 255, 224),
    "lime": (0, 255, 0), "limegreen": (50, 205, 50),
    "linen": (250, 240, 230), "magenta": (255, 0, 255),
    "maroon": (128, 0, 0), "mediumaquamarine": (102, 205, 170),
    "mediumblue": (0, 0, 205), "mediumorchid": (186, 85, 211),
    "mediumpurple": (147, 112, 219), "mediumseagreen": (60, 179, 113),
    "mediumslateblue": (123, 104, 238), "mediumspringgreen": (0, 250, 154),
    "mediumturquoise": (72, 209, 204), "mediumvioletred": (199, 21, 133),
    "midnightblue": (25, 25, 112), "mintcream": (245, 255, 250),
    "mistyrose": (255, 228, 225), "moccasin": (255, 228, 181),
    "navajowhite": (255, 222, 173), "navy": (0, 0, 128),
    "oldlace": (253, 245, 230), "olive": (128, 128, 0),
    "olivedrab": (107, 142, 35), "orange": (255, 165, 0),
    "orangered": (255, 69, 0), "orchid": (218, 112, 214),
    "palegoldenrod": (238, 232, 170), "palegreen": (152, 251, 152),
    "paleturquoise": (175, 238, 238), "palevioletred": (219, 112, 147),
    "papayawhip": (255, 239, 213), "peachpuff": (255, 218, 185),
    "peru": (205, 133, 63), "pink": (255, 192, 203),
    "plum": (221, 160, 221), "powderblue": (176, 224, 230),
    "purple": (128, 0, 128), "rebeccapurple": (102, 51, 153),
    "red": (255, 0, 0), "rosybrown": (188, 143, 143),
    "royalblue": (65, 105, 225), "saddlebrown": (139, 69, 19),
    "salmon": (250, 128, 114), "sandybrown": (244, 164, 96),
    "seagreen": (46, 139, 87), "seashell": (255, 245, 238),
    "sienna": (160, 82, 45), "silver": (192, 192, 192),
    "skyblue": (135, 206, 235), "slateblue": (106, 90, 205),
    "slategray": (112, 128, 144), "snow": (255, 250, 250),
    "springgreen": (0, 255, 127), "steelblue": (70, 130, 180),
    "tan": (210, 180, 140), "teal": (0, 128, 128),
    "thistle": (216, 191, 216), "tomato": (255, 99, 71),
    "turquoise": (64, 224, 208), "violet": (238, 130, 238),
    "wheat": (245, 222, 179), "white": (255, 255, 255),
    "whitesmoke": (245, 245, 245), "yellow": (255, 255, 0),
    "yellowgreen": (154, 205, 50),
}

# Mappa inversa (r,g,b) → nome
_RGB_TO_NAME: dict[tuple[int, int, int], str] = {v: k for k, v in _CSS_COLORS.items()}


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return round(h * 360), round(s * 100), round(l * 100)


class ColorTranslatorDialog(QDialog):
    """Dialog traduttore colori stile PSPad."""

    def __init__(self, main_window: "MainWindow", initial: Optional[QColor] = None):
        super().__init__(main_window)
        self._mw = main_window
        self._color = initial or QColor("#3399ff")
        self.setWindowTitle("Traduttore colori")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._update_display()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        # Riga picker + barra del colore
        top = QHBoxLayout()
        pick_btn = QPushButton("Scegli colore…")
        pick_btn.clicked.connect(self._pick_color)
        pick_btn.setFixedHeight(32)
        top.addWidget(pick_btn)

        self._bar = QFrame()
        self._bar.setFixedHeight(32)
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bar.setFrameShape(QFrame.Shape.Box)
        top.addWidget(self._bar)
        vl.addLayout(top)

        # Griglia formati
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        self._fields: dict[str, QLineEdit] = {}

        rows = [
            ("nome",   "Nome HTML/CSS:"),
            ("hex_up", "Hex MAIUSC:"),
            ("hex_lo", "Hex minusc:"),
            ("rgb",    "RGB decimale:"),
            ("rgbp",   "RGB %:"),
            ("hsl",    "HSL:"),
        ]

        for i, (key, label) in enumerate(rows):
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(lbl, i, 0)

            field = QLineEdit()
            field.setReadOnly(True)
            self._fields[key] = field
            grid.addWidget(field, i, 1)

            ins_btn = QPushButton("Inserisci")
            ins_btn.setFixedWidth(76)
            ins_btn.clicked.connect(lambda _, k=key: self._insert(k))
            grid.addWidget(ins_btn, i, 2)

            cpy_btn = QPushButton("Copia")
            cpy_btn.setFixedWidth(60)
            cpy_btn.clicked.connect(lambda _, k=key: self._copy(k))
            grid.addWidget(cpy_btn, i, 3)

        vl.addLayout(grid)

        # Riga inferiore
        bot = QHBoxLayout()
        bot.addStretch()
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.accept)
        bot.addWidget(close_btn)
        vl.addLayout(bot)

    # ── Logica ────────────────────────────────────────────────────────────────

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self._color, self, "Seleziona colore")
        if c.isValid():
            self._color = c
            self._update_display()

    def _update_display(self) -> None:
        c = self._color
        r, g, b = c.red(), c.green(), c.blue()
        h, s, l = _rgb_to_hsl(r, g, b)

        self._bar.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #888;"
        )

        name = _RGB_TO_NAME.get((r, g, b), "")
        self._fields["nome"].setText(name)
        self._fields["hex_up"].setText(f"#{r:02X}{g:02X}{b:02X}")
        self._fields["hex_lo"].setText(f"#{r:02x}{g:02x}{b:02x}")
        self._fields["rgb"].setText(f"rgb({r}, {g}, {b})")
        rp = round(r / 255 * 100)
        gp = round(g / 255 * 100)
        bp = round(b / 255 * 100)
        self._fields["rgbp"].setText(f"rgb({rp}%, {gp}%, {bp}%)")
        self._fields["hsl"].setText(f"hsl({h}, {s}%, {l}%)")

    def _insert(self, key: str) -> None:
        text = self._fields[key].text()
        if not text:
            return
        editor = self._mw._current_editor()
        if editor:
            editor.insert(text)
            editor.setFocus()

    def _copy(self, key: str) -> None:
        text = self._fields[key].text()
        if text:
            QApplication.clipboard().setText(text)
