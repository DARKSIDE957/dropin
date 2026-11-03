"""Tests for version comparison and normalization helpers."""

import unittest

from dropin.core.versions import (
    clean_display_version,
    extract_semantic_version,
    is_newer_version,
    normalize_version,
)


class TestVersions(unittest.TestCase):
    def test_normalize_strips_v_and_release_prefixes(self):
        self.assertEqual(normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("V1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("release-1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("version-1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("1.2.3"), "1.2.3")

    def test_clean_display_version(self):
        self.assertEqual(clean_display_version("1.2.3"), "v1.2.3")
        self.assertEqual(clean_display_version("v1.2.3"), "v1.2.3")
        self.assertEqual(clean_display_version("vv1.2.3"), "v1.2.3")
        self.assertEqual(clean_display_version("V1.2.3"), "v1.2.3")
        self.assertEqual(clean_display_version(""), "")

    def test_extract_semantic_version(self):
        self.assertEqual(
            extract_semantic_version("ALCOM-1.1.9-x86_64.AppImage"), "1.1.9"
        )
        self.assertEqual(
            extract_semantic_version("SteaMidra-6.6.6-x86_64.AppImage"), "6.6.6"
        )
        self.assertEqual(
            extract_semantic_version("android-studio-2024.2.1.12-linux.tar.gz"),
            "2024.2.1.12",
        )
        self.assertEqual(
            extract_semantic_version("Hydra-4.3.0.AppImage"), "4.3.0"
        )
        self.assertEqual(
            extract_semantic_version("Obsidian-1.7.7-amd64.AppImage"), "1.7.7"
        )

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version("v2.0.0", "1.9.0"))
        self.assertTrue(is_newer_version("2.0.0", "v1.9.0"))
        self.assertTrue(is_newer_version("release-2.0.0", "1.9.0"))
        self.assertTrue(is_newer_version("2024.2.1.12", "2024.1.0"))
        self.assertFalse(is_newer_version("v1.2.3", "1.2.3"))
        self.assertFalse(is_newer_version("1.2.3", "v1.2.3"))
        self.assertFalse(is_newer_version("1.0.0", "2.0.0"))
        self.assertFalse(is_newer_version("1.0.0", "1.0.0"))
        self.assertFalse(is_newer_version("unknown", "unknown"))

    def test_github_resolver_release_download_url(self):
        from dropin.network.github import GitHubResolver

        resolver = GitHubResolver()
        url = "https://github.com/hydralauncher/hydra/releases/download/v4.3.0/hydra-4.3.0.AppImage"
        self.assertTrue(resolver.is_github_url(url))
        owner, repo, tag = resolver.parse_url(url)
        self.assertEqual(owner, "hydralauncher")
        self.assertEqual(repo, "hydra")
        self.assertEqual(tag, "v4.3.0")
        self.assertEqual(resolver.parse_release_asset_filename(url), "hydra-4.3.0.AppImage")

    def test_appimage_desktop_spec_version_vs_app_version(self):
        from dropin.handlers.appimage import AppImageHandler

        handler = AppImageHandler()
        desktop_content = """[Desktop Entry]
Name=TestApp
Exec=testapp
Version=1.0
X-AppImage-Version=3.5.2
X-AppImage-UpdateInformation=gh-releases-zsync|testowner|testrepo|latest|*.AppImage.zsync
"""
        meta = handler._parse_desktop_file_text(desktop_content)
        self.assertEqual(meta.get("desktop_spec_version"), "1.0")
        self.assertIsNone(meta.get("desktop_version"))
        self.assertEqual(meta.get("app_version"), "3.5.2")
        self.assertEqual(meta.get("update_type"), "github")
        self.assertEqual(meta.get("update_identifier"), "testowner/testrepo")


if __name__ == "__main__":
    unittest.main()
