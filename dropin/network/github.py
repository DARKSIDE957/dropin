"""
GitHub repository and release metadata resolver for Dropin.
Parses GitHub URLs, queries release APIs, and filters compatible assets for host architecture.
"""

import json
import re
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from dropin.core.distro import get_current_distribution
from dropin.core.logger import get_logger
from dropin.core.models import PackageFormat


@dataclass
class GitHubAsset:
    name: str
    download_url: str
    size_bytes: int
    format: PackageFormat
    architecture: str
    compatibility_score: int
    tag_name: str
    digest: str = ""  # e.g. sha256:abcd... when GitHub provides it


@dataclass
class GitHubReleaseInfo:
    owner: str
    repo: str
    tag_name: str
    release_name: str
    published_at: str
    description: str
    html_url: str
    assets: List[GitHubAsset]


class GitHubResolver:
    """Resolves GitHub repository and release URLs into installable assets."""

    GITHUB_URL_PATTERN = re.compile(
        r"^https?://(?:www\.)?github\.com/([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)(?:/(?:releases(?:/(?:tag/([^/\s]+)|latest)?)?))?/?$"
    )

    @classmethod
    def is_github_url(cls, url: str) -> bool:
        return bool(cls.GITHUB_URL_PATTERN.match(url.strip()))

    @classmethod
    def parse_url(cls, url: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """Returns (owner, repo, tag) from URL."""
        match = cls.GITHUB_URL_PATTERN.match(url.strip())
        if not match:
            return None
        owner = match.group(1)
        repo = match.group(2)
        if repo.endswith(".git"):
            repo = repo[:-4]
        tag = match.group(3)
        return (owner, repo, tag)

    def fetch_release(self, url: str) -> Tuple[Optional[GitHubReleaseInfo], str]:
        parsed = self.parse_url(url)
        if not parsed:
            return None, "Not a recognized GitHub repository or release URL."

        owner, repo, tag = parsed
        api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        if tag:
            api_url += f"/tags/{tag}"
        else:
            api_url += "/latest"

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Dropin-Installer/1.0"
        }

        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, f"No published releases found for GitHub repository '{owner}/{repo}'."
            elif e.code == 403:
                return None, "GitHub API rate limit exceeded. Please try again later."
            return None, f"GitHub API error: {e.reason} (HTTP {e.code})"
        except Exception as e:
            return None, f"Failed to connect to GitHub: {str(e)}"

        raw_assets = data.get("assets", [])
        if not raw_assets:
            return None, f"The release '{data.get('tag_name')}' does not contain any downloadable release assets."

        distro = get_current_distribution()
        assets: List[GitHubAsset] = []

        for item in raw_assets:
            name = item.get("name", "")
            dl_url = item.get("browser_download_url", "")
            size = item.get("size", 0)

            fmt = PackageFormat.from_extension(name)
            if fmt == PackageFormat.UNKNOWN:
                continue

            arch = self._detect_asset_arch(name)
            score = self._compute_compatibility_score(name, fmt, arch, distro)

            assets.append(GitHubAsset(
                name=name,
                download_url=dl_url,
                size_bytes=size,
                format=fmt,
                architecture=arch,
                compatibility_score=score,
                tag_name=data.get("tag_name", "latest"),
                digest=(item.get("digest") or "").strip(),
            ))

        # Sort assets by compatibility score descending
        assets.sort(key=lambda a: a.compatibility_score, reverse=True)

        if not assets:
            return None, (
                f"Release '{data.get('tag_name')}' found, but none of its {len(raw_assets)} assets "
                "match supported Linux package formats (AppImage, DEB, RPM, Flatpak, or portable archive)."
            )

        info = GitHubReleaseInfo(
            owner=owner,
            repo=repo,
            tag_name=data.get("tag_name", "latest"),
            release_name=data.get("name") or data.get("tag_name", "Release"),
            published_at=data.get("published_at", ""),
            description=data.get("body", "")[:300] if data.get("body") else "",
            html_url=data.get("html_url", url),
            assets=assets
        )
        return info, "Success"

    def _detect_asset_arch(self, filename: str) -> str:
        lower = filename.lower()
        if "x86_64" in lower or "amd64" in lower or "x64" in lower:
            return "x86_64"
        elif "aarch64" in lower or "arm64" in lower:
            return "aarch64"
        elif "armv7" in lower or "armhf" in lower:
            return "armv7l"
        elif "i386" in lower or "i686" in lower or "x86" in lower:
            return "i686"
        elif "all" in lower or "noarch" in lower:
            return "noarch"
        return "any"

    def _compute_compatibility_score(self, name: str, fmt: PackageFormat, arch: str, distro: Any) -> int:
        score = 0
        # Architecture match
        if arch in (distro.arch, "noarch", "any"):
            score += 50
        elif arch == "x86_64" and distro.arch == "x86_64":
            score += 50
        elif arch == "aarch64" and distro.arch == "aarch64":
            score += 50
        else:
            score -= 100  # Incompatible arch penalty

        # Format match based on distribution family
        if fmt == PackageFormat.APPIMAGE:
            score += 40  # AppImage runs universally on Linux
        elif fmt == PackageFormat.RPM and (distro.is_fedora_family or distro.is_suse_family or distro.has_dnf or distro.has_rpm):
            score += 45  # Native RPM preferred on Fedora
        elif fmt == PackageFormat.DEB and (distro.is_debian_family or distro.has_apt or distro.has_dpkg):
            score += 45  # Native DEB preferred on Debian
        elif fmt == PackageFormat.FLATPAK:
            score += 35
        elif fmt == PackageFormat.ARCHIVE:
            score += 20

        return score
