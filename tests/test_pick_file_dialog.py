"""Tests for local installable-package scanning."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dropin.core.models import PackageFormat
from dropin.ui.pick_file_dialog import (
    _format_compatible_here,
    scan_installable_files,
)


class ScanInstallableFilesTests(unittest.TestCase):
    def test_finds_supported_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.AppImage").write_bytes(b"x")
            (root / "pkg.deb").write_bytes(b"x")
            (root / "notes.txt").write_bytes(b"x")
            nested = root / "inbox"
            nested.mkdir()
            (root / "inbox" / "tool.rpm").write_bytes(b"x")

            found = scan_installable_files([(root, 1)])
            names = {p.name for p in found}
            self.assertIn("app.AppImage", names)
            self.assertNotIn("notes.txt", names)
            if _format_compatible_here(PackageFormat.DEB):
                self.assertIn("pkg.deb", names)
            else:
                self.assertNotIn("pkg.deb", names)
            if _format_compatible_here(PackageFormat.RPM):
                self.assertIn("tool.rpm", names)
            else:
                self.assertNotIn("tool.rpm", names)

    def test_depth_zero_skips_subfolders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.AppImage").write_bytes(b"x")
            (root / "sub").mkdir()
            (root / "sub" / "hidden.deb").write_bytes(b"x")

            found = scan_installable_files([(root, 0)])
            names = {p.name for p in found}
            self.assertEqual(names, {"top.AppImage"})


class DiscoverIconPipelineTests(unittest.TestCase):
    """Offscreen: refresh clears the stop latch and starts icon workers."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        import sys

        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_refresh_starts_icon_pipeline(self):
        from dropin.ui.pick_file_dialog import PickInstallFileDialog

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Sample.AppImage").write_bytes(b"\x7fELF" + b"\x00" * 32)

            dlg = PickInstallFileDialog()
            with mock.patch(
                "dropin.ui.pick_file_dialog.scan_installable_files",
                return_value=[root / "Sample.AppImage"],
            ):
                dlg.refresh()

            self.assertFalse(dlg._icons_stopping)
            self.assertGreater(
                dlg._icons_inflight + len(dlg._icon_queue),
                0,
                "icon pipeline should have work after refresh",
            )
            dlg._stop_icon_workers()
            dlg.close()


if __name__ == "__main__":
    unittest.main()
