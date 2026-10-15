"""
Unit tests for Linux distribution detection.
"""

import unittest
from dropin.core.distro import detect_distribution, detect_architecture, get_current_distribution


class TestDistroDetection(unittest.TestCase):
    def test_architecture_detection(self):
        arch = detect_architecture()
        self.assertIn(arch, ["x86_64", "aarch64", "armv7l", "i686"])

    def test_distro_detection_fields(self):
        distro = detect_distribution()
        self.assertIsNotNone(distro.id)
        self.assertIsNotNone(distro.name)
        self.assertIsNotNone(distro.arch)
        self.assertIsInstance(distro.id_like, list)

    def test_singleton(self):
        d1 = get_current_distribution()
        d2 = get_current_distribution()
        self.assertIs(d1, d2)


if __name__ == "__main__":
    unittest.main()
