"""Tests for version comparison used by the update manager."""

import unittest

from dropin.core.versions import is_newer_version, normalize_version


class TestVersions(unittest.TestCase):
    def test_normalize_strips_v_prefix(self):
        self.assertEqual(normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("1.2.3"), "1.2.3")

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version("v2.0.0", "1.9.0"))
        self.assertTrue(is_newer_version("2.0.0", "v1.9.0"))
        self.assertFalse(is_newer_version("v1.2.3", "1.2.3"))
        self.assertFalse(is_newer_version("1.2.3", "v1.2.3"))
        self.assertFalse(is_newer_version("1.0.0", "2.0.0"))


if __name__ == "__main__":
    unittest.main()
