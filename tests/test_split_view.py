import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.split_view import SplitViewManager


class SplitViewZoomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sync_zoom_copies_primary_level_when_split_is_created(self):
        manager = SplitViewManager()
        self.addCleanup(manager.deleteLater)

        primary = manager._primary.tab_manager.new_tab()
        primary.zoomTo(4)
        manager.set_sync_zoom(True)
        manager.split(clone_current=True)

        secondary = manager._secondary.tab_manager.current_editor()
        self.assertIsNotNone(secondary)
        self.assertEqual(secondary.zoom_level, primary.zoom_level)


if __name__ == "__main__":
    unittest.main()
