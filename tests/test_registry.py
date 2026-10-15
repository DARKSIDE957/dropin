"""
Unit tests for application registry and SQLite tracking.
"""

import tempfile
import unittest
from pathlib import Path
from dropin.core.models import InstalledApp
from dropin.core.registry import AppRegistry


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_dropin.db"
        self.registry = AppRegistry(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_get_app(self):
        app = InstalledApp(
            id="dropin-appimage-testapp",
            name="Test App",
            version="1.2.3",
            format="AppImage",
            file_path="/home/user/Applications/testapp.AppImage",
            launcher_path="/home/user/.local/share/applications/dropin-appimage-testapp.desktop",
            install_date="2026-10-15 10:00:00",
            source_url="https://github.com/test/app",
            update_type="github",
            update_identifier="test/app",
            scope="user"
        )
        self.assertTrue(self.registry.add_app(app))

        retrieved = self.registry.get_app("dropin-appimage-testapp")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "Test App")
        self.assertEqual(retrieved.version, "1.2.3")
        self.assertEqual(retrieved.format, "AppImage")

    def test_list_and_search(self):
        app1 = InstalledApp(
            id="app1", name="Alpha", version="1.0", format="DEB", file_path="/usr/bin/alpha"
        )
        app2 = InstalledApp(
            id="app2", name="Beta Tool", version="2.0", format="RPM", file_path="/usr/bin/beta"
        )
        self.registry.add_app(app1)
        self.registry.add_app(app2)

        apps = self.registry.list_apps()
        self.assertEqual(len(apps), 2)

        search_res = self.registry.list_apps("Beta")
        self.assertEqual(len(search_res), 1)
        self.assertEqual(search_res[0].name, "Beta Tool")

    def test_delete_app(self):
        app = InstalledApp(id="del_me", name="Delete Me", version="1.0", format="AppImage", file_path="")
        self.registry.add_app(app)
        self.assertTrue(self.registry.delete_app("del_me"))
        self.assertIsNone(self.registry.get_app("del_me"))

    def test_audit_logs(self):
        self.registry.log_audit("TEST_ACTION", "TargetApp", "SUCCESS", "Test details")
        logs = self.registry.get_audit_logs()
        self.assertGreater(len(logs), 0)
        self.assertEqual(logs[0]["action"], "TEST_ACTION")
        self.assertEqual(logs[0]["target"], "TargetApp")


if __name__ == "__main__":
    unittest.main()
