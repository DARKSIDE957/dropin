"""
Unit tests for dropin.core.desktop cache synchronization.
"""

import unittest
from unittest.mock import patch, MagicMock

from dropin.core.desktop import update_desktop_caches


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


if __name__ == "__main__":
    unittest.main()
