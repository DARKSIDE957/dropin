"""
Unit tests for Linux distribution detection.
"""

import unittest
from dropin.core.distro import (
    _detect_atomic,
    detect_distribution,
    detect_architecture,
    get_current_distribution,
)


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

    def test_atomic_ids_detected(self):
        for distro_id in ("bazzite", "silverblue", "kinoite", "bluefin"):
            self.assertTrue(_detect_atomic(distro_id), distro_id)
        self.assertTrue(_detect_atomic("fedora", ["bazzite"]))

    def test_distro_has_atomic_fields(self):
        distro = detect_distribution()
        self.assertIsInstance(distro.is_atomic, bool)
        self.assertIsInstance(distro.has_rpm_ostree, bool)


if __name__ == "__main__":
    unittest.main()
