"""Dialog per conversioni di testo: ROT13, URL, Base64, HTML entities."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTextEdit, QPushButton, QLabel, QDialogButtonBox, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


def _mono_font() -> QFont:
    f = QFont("Monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(10)
    return f


class _ConvertTab(QWidget):
    """Tab generico con area input, bottoni encode/decode, area output."""

    def __init__(self, encode_fn, decode_fn, encode_label="Encode →", decode_label="← Decode"):
        super().__init__()
        self._encode_fn = encode_fn
        self._decode_fn = decode_fn

        vl = QVBoxLayout(self)
        vl.setSpacing(6)

        self._input = QTextEdit()
        self._input.setFont(_mono_font())
        self._input.setPlaceholderText("Testo di input…")

        btn_row = QHBoxLayout()
        btn_enc = QPushButton(encode_label)
        btn_dec = QPushButton(decode_label)
        btn_swap = QPushButton("⇅ Scambia")
        btn_copy = QPushButton("📋 Copia output")
        btn_row.addWidget(btn_enc)
        btn_row.addWidget(btn_dec)
        btn_row.addStretch()
        btn_row.addWidget(btn_swap)
        btn_row.addWidget(btn_copy)

        self._output = QTextEdit()
        self._output.setFont(_mono_font())
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("Risultato…")

        self._status = QLabel("")
        self._status.setStyleSheet("color: red;")

        vl.addWidget(QLabel("Input:"))
        vl.addWidget(self._input, 1)
        vl.addLayout(btn_row)
        vl.addWidget(QLabel("Output:"))
        vl.addWidget(self._output, 1)
        vl.addWidget(self._status)

        btn_enc.clicked.connect(self._do_encode)
        btn_dec.clicked.connect(self._do_decode)
        btn_swap.clicked.connect(self._swap)
        btn_copy.clicked.connect(self._copy_output)

    def set_input(self, text: str) -> None:
        self._input.setPlainText(text)

    def _do_encode(self) -> None:
        self._run(self._encode_fn)

    def _do_decode(self) -> None:
        self._run(self._decode_fn)

    def _run(self, fn) -> None:
        txt = self._input.toPlainText()
        self._status.setText("")
        try:
            result = fn(txt)
            self._output.setPlainText(result)
        except Exception as e:
            self._status.setText(f"Errore: {e}")
            self._output.clear()

    def _swap(self) -> None:
        out = self._output.toPlainText()
        inp = self._input.toPlainText()
        self._input.setPlainText(out)
        self._output.setPlainText(inp)

    def _copy_output(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._output.toPlainText())


# ── Funzioni di conversione ───────────────────────────────────────────────────

def _rot13_enc(text: str) -> str:
    import codecs
    return codecs.encode(text, "rot_13")

def _rot13_dec(text: str) -> str:
    return _rot13_enc(text)  # ROT13 è simmetrico

def _url_enc(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")

def _url_dec(text: str) -> str:
    from urllib.parse import unquote
    return unquote(text)

def _b64_enc(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")

def _b64_dec(text: str) -> str:
    import base64
    return base64.b64decode(text.strip()).decode("utf-8")

def _html_enc(text: str) -> str:
    import html
    return html.escape(text, quote=True)

def _html_dec(text: str) -> str:
    import html
    return html.unescape(text)

def _hex_enc(text: str) -> str:
    return text.encode("utf-8").hex()

def _hex_dec(text: str) -> str:
    return bytes.fromhex(text.replace(" ", "").replace("\n", "")).decode("utf-8")


# ── Dialog principale ─────────────────────────────────────────────────────────

class TextConverterDialog(QDialog):
    def __init__(self, parent=None, initial_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Converti testo")
        self.resize(620, 420)

        vl = QVBoxLayout(self)
        tabs = QTabWidget()

        self._tab_rot13 = _ConvertTab(_rot13_enc, _rot13_dec,
                                      "ROT13 →/←", "ROT13 →/←")
        self._tab_url   = _ConvertTab(_url_enc,   _url_dec,
                                      "URL encode →", "← URL decode")
        self._tab_b64   = _ConvertTab(_b64_enc,   _b64_dec,
                                      "Base64 encode →", "← Base64 decode")
        self._tab_html  = _ConvertTab(_html_enc,  _html_dec,
                                      "HTML escape →", "← HTML unescape")
        self._tab_hex   = _ConvertTab(_hex_enc,   _hex_dec,
                                      "HEX encode →", "← HEX decode")

        tabs.addTab(self._tab_rot13, "ROT13")
        tabs.addTab(self._tab_url,   "URL")
        tabs.addTab(self._tab_b64,   "Base64")
        tabs.addTab(self._tab_html,  "HTML entities")
        tabs.addTab(self._tab_hex,   "Hex")

        if initial_text:
            for tab in (self._tab_rot13, self._tab_url,
                        self._tab_b64, self._tab_html, self._tab_hex):
                tab.set_input(initial_text)

        vl.addWidget(tabs)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        vl.addWidget(btns)
