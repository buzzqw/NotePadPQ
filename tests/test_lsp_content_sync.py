import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.editor_widget import EditorWidget
from ui.main_window import MainWindow


class LSPContentSyncDebounceTest(unittest.TestCase):
    """Copre il debounce di didChange (_lsp_attach_content_sync /
    _lsp_flush_content_sync in ui/main_window.py). editor.text() marshala
    l'intero documento e didChange lo rimanda per intero al server LSP:
    senza coalescing, ogni singolo carattere digitato genera un round-trip
    completo verso il server."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Shell instance: bypassa __init__ (costruzione UI pesante di
        # MainWindow) ma i metodi restano risolti normalmente tramite la
        # classe, quindi si possono esercitare in isolamento.
        self.mw = MainWindow.__new__(MainWindow)
        self.editor = EditorWidget()
        self.editor.file_path = Path("/tmp/notepadpq-lsp-sync.py")
        self.editor.setText("first")
        self.client = mock.Mock()
        self.client.next_document_version.return_value = 1
        self.editor._lsp_client = self.client

    def tearDown(self):
        MainWindow._lsp_disconnect_content_sync(self.editor)
        self.editor.deleteLater()
        self.app.processEvents()

    def test_rapid_edits_are_coalesced_into_a_single_update_file_call(self):
        self.mw._lsp_attach_content_sync(self.editor, self.client)

        for _ in range(5):
            self.editor.textChanged.emit()

        self.client.update_file.assert_not_called()
        timer = self.editor._lsp_sync_timer
        self.assertTrue(timer.isActive())

        timer.timeout.emit()
        self.assertEqual(self.client.update_file.call_count, 1)
        self.assertEqual(self.client.update_file.call_args.args[0], self.editor.file_path)

    def test_flush_sends_immediately_and_cancels_pending_timer(self):
        self.mw._lsp_attach_content_sync(self.editor, self.client)
        self.editor.textChanged.emit()
        self.assertTrue(self.editor._lsp_sync_timer.isActive())

        self.mw._lsp_flush_content_sync(self.editor, self.client)

        self.assertEqual(self.client.update_file.call_count, 1)
        self.assertFalse(self.editor._lsp_sync_timer.isActive())

    def test_disconnect_stops_and_clears_pending_timer(self):
        self.mw._lsp_attach_content_sync(self.editor, self.client)
        self.editor.textChanged.emit()
        self.assertTrue(self.editor._lsp_sync_timer.isActive())

        MainWindow._lsp_disconnect_content_sync(self.editor)

        self.assertIsNone(self.editor._lsp_sync_timer)
        self.assertIsNone(self.editor._lsp_text_changed_handler)


if __name__ == "__main__":
    unittest.main()
