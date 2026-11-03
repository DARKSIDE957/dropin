"""Unit tests for Dropin SelfUpdater and SettingsDialog self-update integration."""

import sys
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from dropin.updater.self_updater import SelfUpdater, find_local_repo, get_current_commit
from dropin.ui.settings_dialog import SettingsDialog


class TestSelfUpdater(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_get_info_structure(self):
        info = SelfUpdater.get_info()
        self.assertIn("version", info)
        self.assertIn("commit", info)
        self.assertIn("commit_full", info)
        self.assertIn("has_git_repo", info)
        self.assertIn("repo_path", info)
        self.assertTrue(info["has_git_repo"])

    def test_find_local_repo(self):
        repo = find_local_repo()
        self.assertIsNotNone(repo)
        self.assertTrue((repo / ".git").is_dir())
        self.assertTrue((repo / "install.sh").is_file())

    def test_settings_dialog_has_update_controls(self):
        dlg = SettingsDialog()
        self.assertTrue(hasattr(dlg, "dropin_version_label"))
        self.assertTrue(hasattr(dlg, "dropin_update_status"))
        self.assertTrue(hasattr(dlg, "check_dropin_btn"))
        self.assertTrue(hasattr(dlg, "update_dropin_btn"))
        self.assertIn("Dropin v", dlg.dropin_version_label.text())
        self.assertEqual(dlg.check_dropin_btn.text(), "Check for Dropin updates")
        self.assertEqual(dlg.update_dropin_btn.text(), "Update Dropin")
        dlg.close()


if __name__ == "__main__":
    unittest.main()
