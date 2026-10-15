"""
Unit tests for configuration management.
"""

import tempfile
import unittest
from pathlib import Path
from dropin.core.config import ConfigManager, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_values(self):
        cfg = ConfigManager(self.config_dir)
        self.assertEqual(cfg.get("check_updates_on_startup"), DEFAULT_CONFIG["check_updates_on_startup"])
        self.assertEqual(cfg.get("max_download_size_mb"), DEFAULT_CONFIG["max_download_size_mb"])
        self.assertTrue(cfg.get("require_https"))
        self.assertTrue(cfg.get("verify_package_content"))
        self.assertTrue(cfg.get("verify_release_digest"))

    def test_persistence_and_update(self):
        cfg = ConfigManager(self.config_dir)
        cfg.set("max_download_size_mb", 2048)
        cfg.set("appimage_dir", "/custom/path/applications")

        # Reload from disk
        cfg2 = ConfigManager(self.config_dir)
        self.assertEqual(cfg2.get("max_download_size_mb"), 2048)
        self.assertEqual(cfg2.get("appimage_dir"), "/custom/path/applications")

    def test_reset_defaults(self):
        cfg = ConfigManager(self.config_dir)
        cfg.set("max_download_size_mb", 100)
        cfg.reset_defaults()
        self.assertEqual(cfg.get("max_download_size_mb"), DEFAULT_CONFIG["max_download_size_mb"])


if __name__ == "__main__":
    unittest.main()
