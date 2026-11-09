"""
Unit tests for dropin.core.desktop cache synchronization.
"""

import unittest
from unittest.mock import patch, MagicMock

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from dropin.core.desktop import (
    cleanup_obsolete_dropin_launchers,
    detect_image_format,
    is_dropin_own_icon,
    quote_exec_path,
    remove_application_icons,
    sanitize_desktop_field,
    save_application_icon,
    update_desktop_caches,
    write_desktop_entry,
)


class TestDesktop(unittest.TestCase):
    @patch("shutil.which")
    @patch("subprocess.run")
    def test_update_desktop_caches_invocations(self, mock_run, mock_which):
        def fake_which(cmd):
            return f"/usr/bin/{cmd}"

        mock_which.side_effect = fake_which
        mock_run.return_value = MagicMock(returncode=0)

        # Ensure call runs without error
        update_desktop_caches()
        self.assertTrue(mock_run.called)

    def test_detect_image_format(self):
        # 1. Valid 64x64 PNG header
        png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00@\x00\x00\x00@\x08\x06\x00\x00\x00" + b"\x00" * 32
        fmt = detect_image_format(png_data)
        self.assertIsNotNone(fmt)
        self.assertEqual(fmt[0], ".png")
        self.assertEqual(fmt[1], (64, 64))

        # 2. Valid SVG header
        svg_data = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40"/></svg>'
        fmt_svg = detect_image_format(svg_data)
        self.assertIsNotNone(fmt_svg)
        self.assertEqual(fmt_svg[0], ".svg")

        # 3. Invalid random data
        self.assertIsNone(detect_image_format(b"hello world random text"))

    def test_is_dropin_own_icon_detection(self):
        dropin_svg = Path(__file__).resolve().parent.parent / "dropin" / "assets" / "io.dropin.Dropin.svg"
        self.assertTrue(dropin_svg.is_file())
        self.assertTrue(is_dropin_own_icon(dropin_svg))

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Copy Dropin icon to another file name
            leaked_copy = tmp_path / "dropin-appimage-someapp.svg"
            leaked_copy.write_bytes(dropin_svg.read_bytes())
            self.assertTrue(is_dropin_own_icon(leaked_copy))

            # Different SVG
            custom_svg = tmp_path / "custom.svg"
            custom_svg.write_text('<svg><rect width="50" height="50" fill="red"/></svg>', encoding="utf-8")
            self.assertFalse(is_dropin_own_icon(custom_svg))

    def test_save_application_icon_rejects_dropin_icon_for_other_apps(self):
        dropin_svg = Path(__file__).resolve().parent.parent / "dropin" / "assets" / "io.dropin.Dropin.svg"
        dropin_bytes = dropin_svg.read_bytes()

        # Should refuse to save Dropin's icon for third-party application
        saved = save_application_icon("dropin-appimage-thirdparty", icon_bytes=dropin_bytes)
        self.assertIsNone(saved)

    def test_quote_exec_path(self):
        p = Path("/home/user/My Apps/App.AppImage")
        quoted = quote_exec_path(p)
        self.assertEqual(quoted, '"/home/user/My Apps/App.AppImage"')

        quoted_args = quote_exec_path(p, extra_args="--flag %U")
        self.assertEqual(quoted_args, '"/home/user/My Apps/App.AppImage" --flag %U')

    def test_write_desktop_entry_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            with patch("pathlib.Path.home", return_value=home):
                app_id = "dropin-appimage-testdemo"
                binary = home / "testdemo.AppImage"
                binary.touch()

                launcher = write_desktop_entry(
                    app_id=app_id,
                    name="Test Demo",
                    exec_path=binary,
                    icon_path=None,
                    comment="Demo application",
                    categories="Utility;",
                    startup_wm_class="TestDemo",
                )
                self.assertIsNotNone(launcher)
                self.assertTrue(launcher.is_file())

                content = launcher.read_text(encoding="utf-8")
                self.assertIn("Name=Test Demo", content)
                self.assertIn(f'Exec="{binary}"', content)
                self.assertIn("Icon=application-x-executable", content)
                self.assertIn("StartupWMClass=TestDemo", content)
                self.assertIn("X-Dropin-Managed=true", content)

                # Now remove the binary and test cleanup
                binary.unlink()
                removed = cleanup_obsolete_dropin_launchers()
                self.assertEqual(removed, 1)
                self.assertFalse(launcher.exists())


if __name__ == "__main__":
    unittest.main()
