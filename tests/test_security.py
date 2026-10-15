"""
Unit tests for Dropin security validation.
"""

import tempfile
import unittest
from pathlib import Path

from dropin.core.models import PackageFormat
from dropin.core.security import (
    compute_file_sha256,
    normalize_sha256,
    validate_archive_members,
    validate_final_url,
    validate_url,
    verify_package_magic,
    verify_sha256,
)


class TestSecurity(unittest.TestCase):
    def test_url_allowed_schemes(self):
        ok, msg = validate_url("https://example.com/app.AppImage")
        self.assertTrue(ok)

        ok, msg = validate_url("http://example.com/app.deb", require_https=False)
        self.assertTrue(ok)

        ok, msg = validate_url("http://example.com/app.deb", require_https=True)
        self.assertFalse(ok)
        self.assertIn("HTTPS", msg)

    def test_url_reject_unsafe_schemes(self):
        ok, msg = validate_url("file:///etc/passwd")
        self.assertFalse(ok)
        self.assertIn("Unsupported protocol", msg)

        ok, msg = validate_url("ftp://example.com/app.rpm")
        self.assertFalse(ok)

        ok, msg = validate_url("javascript:alert(1)")
        self.assertFalse(ok)

    def test_url_reject_ssrf_and_loopback(self):
        ok, msg = validate_url("http://127.0.0.1:8080/evil.deb", require_https=False)
        self.assertFalse(ok)
        self.assertIn("private or local network", msg)

        ok, msg = validate_url("http://localhost/app.AppImage", require_https=False)
        self.assertFalse(ok)

        ok, msg = validate_url("http://192.168.1.100/package.rpm", require_https=False)
        self.assertFalse(ok)

        ok, msg = validate_url("http://10.0.0.1/package.deb", require_https=False)
        self.assertFalse(ok)

    def test_redirect_https_downgrade_blocked(self):
        ok, msg = validate_final_url(
            "https://cdn.example.com/a.AppImage",
            "http://cdn.example.com/a.AppImage",
            require_https=True,
        )
        self.assertFalse(ok)

    def test_archive_path_traversal_detection(self):
        dest_dir = Path("/home/user/apps")

        safe_members = ["bin/myapp", "share/icons/myapp.png", "myapp.desktop"]
        ok, msg = validate_archive_members(safe_members, dest_dir)
        self.assertTrue(ok)

        unsafe_members = ["bin/myapp", "../../../etc/shadow"]
        ok, msg = validate_archive_members(unsafe_members, dest_dir)
        self.assertFalse(ok)
        self.assertIn("unsafe path traversal", msg)

        abs_members = ["/usr/bin/malicious"]
        ok, msg = validate_archive_members(abs_members, dest_dir)
        self.assertFalse(ok)
        self.assertIn("unsafe absolute path", msg)

    def test_sha256_roundtrip(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"dropin-integrity-test")
            path = Path(tmp.name)
        try:
            digest = compute_file_sha256(path)
            self.assertEqual(len(digest), 64)
            self.assertEqual(normalize_sha256(f"sha256:{digest}"), digest)
            ok, msg = verify_sha256(path, digest)
            self.assertTrue(ok)
            ok, msg = verify_sha256(path, "0" * 64)
            self.assertFalse(ok)
            self.assertIn("Integrity check failed", msg)
        finally:
            path.unlink(missing_ok=True)

    def test_package_magic_rejects_html(self):
        with tempfile.NamedTemporaryFile(suffix=".AppImage", delete=False) as tmp:
            tmp.write(b"<!DOCTYPE html><html><body>not a package</body></html>")
            path = Path(tmp.name)
        try:
            ok, msg, detected = verify_package_magic(path, PackageFormat.APPIMAGE)
            self.assertFalse(ok)
            self.assertIn("HTML", msg)
        finally:
            path.unlink(missing_ok=True)

    def test_package_magic_accepts_elf(self):
        with tempfile.NamedTemporaryFile(suffix=".AppImage", delete=False) as tmp:
            tmp.write(b"\x7fELF" + b"\x00" * 64)
            path = Path(tmp.name)
        try:
            ok, msg, detected = verify_package_magic(path, PackageFormat.APPIMAGE)
            self.assertTrue(ok)
            self.assertEqual(detected, PackageFormat.APPIMAGE)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
