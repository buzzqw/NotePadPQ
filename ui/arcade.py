from pathlib import Path
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl

class ArcadeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NotePadPQ Arcade")
        self.resize(1000, 750)
        
        # Rimuoviamo i margini per un effetto full-screen
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.webview = QWebEngineView()
        layout.addWidget(self.webview)
        
        # 1. Legge il tuo file games.js
        js_path = Path(__file__).parent / "games.js"
        js_code = ""
        if js_path.exists():
            js_code = js_path.read_text(encoding="utf-8")
        else:
            js_code = "alert('File games.js non trovato!');"
            
        # 2. Crea l'HTML e inietta il codice
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ margin: 0; background: #02060e; color: white; overflow: hidden; height: 100vh; width: 100vw; }}
            </style>
        </head>
        <body>
            <script>
            // Inietta l'intero codice originale intatto
            {js_code}
            </script>
            
            <script>
            // Attendiamo che la pagina sia completamente caricata
            window.onload = () => {{
                setTimeout(() => {{
                    // TRUCCO MAGICO: Simuliamo 3 click velocissimi nell'angolo in alto a 
                    // sinistra (x=50, y=50) per innescare il tuo fallback originale!
                    for(let i=0; i<3; i++) {{
                        document.dispatchEvent(new MouseEvent('click', {{
                            clientX: 50, 
                            clientY: 50, 
                            bubbles: true 
                        }}));
                    }}
                }}, 150);
            }};
            </script>
        </body>
        </html>
        """
        
        # 3. Carica il gioco
        self.webview.setHtml(html, QUrl("qrc:/"))