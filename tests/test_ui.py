"""
User interface unit tests for Dropin.
Uses Qt offscreen platform to test widgets, layout, states, and dialogs.
"""

import os
import unittest

# Ensure offscreen platform for headless/CI testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from dropin.ui.main_window import MainWindow
from dropin.ui.installed_dialog import InstalledAppsDialog
from dropin.ui.settings_dialog import SettingsDialog
from dropin.ui.audit_dialog import AuditDialog
from dropin.ui.theme import is_dark_mode, get_stylesheet


class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication([])

    def test_theme_generation(self):
        dark_qss = get_stylesheet(dark=True)
        self.assertIn("QFrame#dropZone", dark_qss)
        self.assertIn("background-color: transparent", dark_qss)
        self.assertIn("QLabel#mutedLabel", dark_qss)
        # Must use real palette-derived hex colors, not empty tokens
        self.assertRegex(dark_qss, r"background-color:\s*#[0-9a-fA-F]{6}")

        light_qss = get_stylesheet(dark=False)
        self.assertIn("QFrame#dropZone", light_qss)
        self.assertIn("QLabel#mutedLabel", light_qss)
        self.assertRegex(light_qss, r"background-color:\s*#[0-9a-fA-F]{6}")

    def test_main_window_instantiation(self):
        window = MainWindow()
        self.assertEqual(window.windowTitle(), "Dropin")
        self.assertEqual(window.stack.currentIndex(), 0)
        self.assertIsNotNone(window.drop_zone)
        self.assertIsNotNone(window.url_input)
        self.assertIsNotNone(window.install_url_btn)

    def test_settings_dialog(self):
        dlg = SettingsDialog()
        self.assertIsNotNone(dlg.appimage_input)
        self.assertIsNotNone(dlg.portable_input)
        self.assertTrue(dlg.chk_confirm.isChecked())

    def test_installed_dialog(self):
        dlg = InstalledAppsDialog()
        self.assertIsNotNone(dlg.search_input)
        self.assertIsNotNone(dlg.list_widget)

    def test_audit_dialog(self):
        dlg = AuditDialog()
        self.assertIsNotNone(dlg.table)


if __name__ == "__main__":
    unittest.main()
