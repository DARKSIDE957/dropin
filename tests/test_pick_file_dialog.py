"""Tests for local installable-package scanning."""

import tempfile
import unittest
from pathlib import Path

from dropin.ui.pick_file_dialog import scan_installable_files


class ScanInstallableFilesTests(unittest.TestCase):
    def test_finds_supported_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.AppImage").write_bytes(b"x")
            (root / "pkg.deb").write_bytes(b"x")
            (root / "notes.txt").write_bytes(b"x")
            nested = root / "inbox"
            nested.mkdir()
            (nested / "tool.rpm").write_bytes(b"x")

            found = scan_installable_files([(root, 1)])
            names = {p.name for p in found}
            self.assertIn("app.AppImage", names)
            self.assertIn("pkg.deb", names)
            self.assertIn("tool.rpm", names)
            self.assertNotIn("notes.txt", names)

    def test_depth_zero_skips_subfolders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.AppImage").write_bytes(b"x")
            (root / "sub").mkdir()
            (root / "sub" / "hidden.deb").write_bytes(b"x")

            found = scan_installable_files([(root, 0)])
            names = {p.name for p in found}
            self.assertEqual(names, {"top.AppImage"})


if __name__ == "__main__":
    unittest.main()
