import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialogButtonBox, QPushButton, QSpinBox

from ui.preferences import PreferencesDialog


class PreferencesTooltipsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = PreferencesDialog()

    def tearDown(self):
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_preference_controls_have_explanatory_tooltips(self):
        controls = [
            *self.dialog.findChildren(QCheckBox),
            *self.dialog.findChildren(QComboBox),
            *self.dialog.findChildren(QSpinBox),
            self.dialog._autobackup_dir,
            self.dialog._cwl_dirs,
            self.dialog._preview_external_viewer,
            self.dialog._terminal_custom,
            self.dialog._fl_preset_list,
        ]
        controls.extend(
            button for button in self.dialog.findChildren(QPushButton)
            if not isinstance(button.parent(), QDialogButtonBox)
        )

        missing = [control for control in controls if not control.toolTip().strip()]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
