"""
Unit tests for GitHub URL parsing and asset filtering.
"""

import unittest
from dropin.core.models import PackageFormat
from dropin.network.github import GitHubResolver


class TestGitHubResolver(unittest.TestCase):
    def test_github_url_detection(self):
        urls = [
            "https://github.com/balena-io/etcher",
            "https://github.com/Obsidian-Tasks-Group/obsidian-tasks/releases",
            "https://github.com/jgraph/drawio-desktop/releases/tag/v24.7.17",
            "https://github.com/alacritty/alacritty/releases/latest"
        ]
        for url in urls:
            self.assertTrue(GitHubResolver.is_github_url(url), f"Failed for {url}")

    def test_github_url_parsing(self):
        parsed = GitHubResolver.parse_url("https://github.com/flameshot-org/flameshot")
        self.assertEqual(parsed, ("flameshot-org", "flameshot", None))

        parsed_tag = GitHubResolver.parse_url("https://github.com/flameshot-org/flameshot/releases/tag/v12.1.0")
        self.assertEqual(parsed_tag, ("flameshot-org", "flameshot", "v12.1.0"))

    def test_asset_arch_detection(self):
        resolver = GitHubResolver()
        self.assertEqual(resolver._detect_asset_arch("App-1.0-x86_64.AppImage"), "x86_64")
        self.assertEqual(resolver._detect_asset_arch("app_1.0_amd64.deb"), "x86_64")
        self.assertEqual(resolver._detect_asset_arch("app-1.0-aarch64.rpm"), "aarch64")
        self.assertEqual(resolver._detect_asset_arch("app_1.0_arm64.deb"), "aarch64")
        self.assertEqual(resolver._detect_asset_arch("app_all.deb"), "noarch")


if __name__ == "__main__":
    unittest.main()
