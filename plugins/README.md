# Guida allo Sviluppo di Plugin per NotePadPQ

NotePadPQ utilizza un sistema di plugin modulare scritto in Python e basato su **PyQt6**. Ogni plugin è un file `.py` indipendente posizionato nella cartella `plugins/` che estende la classe astratta `BasePlugin`.

## 1. Struttura Base di un Plugin

Il gestore dei plugin (`PluginManager`) scansiona la cartella `plugins/` ignorando i file che iniziano con underscore (es. `__init__.py`). Cerca al loro interno una classe che erediti da `BasePlugin`.

Ecco il modello minimo obbligatorio:

```python
from plugins.base_plugin import BasePlugin
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.main_window import MainWindow

class MioPlugin(BasePlugin):
    # Metadati del plugin (obbligatori per il PluginManager)
    NAME        = "Nome del Plugin"
    VERSION     = "1.0"
    DESCRIPTION = "Cosa fa questo plugin"
    AUTHOR      = "Il tuo Nome"

    def on_load(self, main_window: "MainWindow") -> None:
        """Chiamato all'avvio o all'abilitazione del plugin."""
        super().on_load(main_window) # Salva il riferimento a main_window in self._mw
        
        # Esempio: Aggiunta di una voce di menu
        self.add_menu_action(
            main_window, 
            menu_name="plugins",     # Menu in cui inserire l'azione ("plugins", "tools", ecc.)
            action_text="Esegui Azione",
            slot=self.fai_qualcosa,  # Funzione da richiamare
            shortcut="Ctrl+Shift+X"  # Opzionale
        )

    def on_unload(self) -> None:
        """Chiamato alla disabilitazione o chiusura."""
        # Se hai creato widget o dock, liberali qui.
        super().on_unload() # Rimuove in automatico le voci di menu aggiunte con add_menu_action

    def fai_qualcosa(self) -> None:
        pass
```

## 2. Eventi (Hooks) a Disposizione

La classe `BasePlugin` fornisce dei metodi vuoti che puoi sovrascrivere (override) per reagire agli eventi globali dell'applicazione:

```python
def on_editor_changed(self, editor) -> None:
    """L'utente ha cambiato scheda (tab) attiva."""
    pass

def on_file_opened(self, path) -> None:
    """È stato appena aperto un file dal disco."""
    pass

def on_file_saved(self, path) -> None:
    """Il file corrente è stato salvato su disco."""
    pass
```

## 3. Interagire con l'Editor

La maggior parte dei plugin deve manipolare o leggere il testo aperto. Per accedere all'editor (tab) corrente, si usa il `TabManager` della `MainWindow`.

```python
def elabora_testo(self):
    # Recupera l'editor attualmente in primo piano
    editor = self._mw._tab_manager.current_editor()
    if not editor:
        return # Nessun file aperto

    # Verificare se c'è testo selezionato
    if editor.hasSelectedText():
        testo = editor.selectedText()
        # Modificare e sostituire il testo selezionato
        editor.replaceSelectedText(testo.upper())
    else:
        # Recuperare l'intero testo
        intero_testo = editor.text()
        # Inserire testo dove si trova il cursore
        editor.insert("Testo generato dal plugin!\n")
```
*L'editor di NotePadPQ è basato su QScintilla, quindi l'oggetto `editor` espone tutti i metodi tipici di `QsciScintilla`.*

## 4. Creare Interfacce Avanzate (Dock Widgets)

Se il tuo plugin richiede un'interfaccia complessa (come il *Clipboard History* o l'*FTP Browser*), la best practice è usare un `QDockWidget` ancorato ai lati della finestra principale.

```python
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QVBoxLayout, QWidget, QPushButton

class PannelloPlugin(BasePlugin):
    NAME = "Pannello Laterale"
    
    def on_load(self, main_window):
        super().on_load(main_window)
        
        # 1. Creare il widget contenuto
        self._panel = QWidget()
        layout = QVBoxLayout(self._panel)
        layout.addWidget(QPushButton("Bottone Plugin"))
        
        # 2. Creare il Dock e inserirvi il widget
        self._dock = QDockWidget("Il Mio Pannello", main_window)
        self._dock.setWidget(self._panel)
        
        # 3. Aggiungere il Dock alla finestra (es. a destra)
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
        self._dock.hide() # Nascondi di default
        
        # 4. Creare voce di menu per mostrare/nascondere il dock
        self.add_menu_action(main_window, "plugins", "Mostra Pannello", self._toggle_dock)

    def _toggle_dock(self):
        self._dock.setVisible(not self._dock.isVisible())

    def on_unload(self):
        # 5. Pulizia fondamentale per non lasciare "orfani" i dock se il plugin viene disattivato
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()
```

## 5. Richiedere Moduli Python Esterni (Dipendenze)

Se il tuo plugin richiede librerie non standard (es. `cryptography` o `paramiko`), è buona norma gestire le eccezioni in modo pulito e avvisare l'utente. NotePadPQ non blocca il programma se un plugin fallisce, ma disabilita silenziosamente l'azione.

Esempio da `encrypt_plugin.py`:
```python
def _has_cryptography() -> bool:
    try:
        import cryptography
        return True
    except ImportError:
        return False

# Puoi usare il check dentro on_load o prima di eseguire logica pesante
```

## 6. Salvare e Caricare Dati del Plugin

Se il plugin ha bisogno di configurazioni persistenti (come cronologia o profili), usa la cartella dati ufficiale dell'applicazione.

```python
import json
from core.platform import get_data_dir

class MioPluginConDati(BasePlugin):
    def salva_dati(self, dati_dict):
        file_path = get_data_dir() / "mioplugin_config.json"
        file_path.write_text(json.dumps(dati_dict))
```

## Esempio Completo (Template)

Crea un file chiamato `uppercase_plugin.py` nella cartella `plugins/`:

```python
"""
plugins/uppercase_plugin.py — Converte testo in MAIUSCOLO
"""
from plugins.base_plugin import BasePlugin

class UppercasePlugin(BasePlugin):
    NAME        = "Uppercase Tool"
    VERSION     = "1.0"
    DESCRIPTION = "Converte in maiuscolo il testo selezionato."
    AUTHOR      = "Il tuo Nome"

    def on_load(self, main_window):
        super().on_load(main_window)
        self.add_menu_action(
            main_window, 
            "tools", # Menu Strumenti
            "🔠 Converti in Maiuscolo", 
            self._converti, 
            shortcut="Ctrl+Shift+U"
        )

    def _converti(self):
        editor = self._mw._tab_manager.current_editor()
        if editor and editor.hasSelectedText():
            testo_maiuscolo = editor.selectedText().upper()
            editor.replaceSelectedText(testo_maiuscolo)
```

## Regole d'oro
1. **Chiama sempre `super().on_load()` e `super().on_unload()`** altrimenti i riferimenti della UI e i menu non verranno ripuliti correttamente.
2. **Importazioni Locali**: Per velocizzare l'avvio di NotePadPQ, importa librerie pesanti dentro i metodi (es. `def _run_algo(self): import modulo_pesante`) invece di importarle globalmente a inizio file.
3. **Gestione Errori**: Metti sotto `try/except` le chiamate critiche che interagiscono col sistema, per non crashare NotePadPQ.
4. **Nomi file**: Usa un prefisso/suffisso descrittivo e lo snake_case (`mio_plugin.py`).