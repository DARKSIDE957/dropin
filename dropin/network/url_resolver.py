"""
Unified URL resolver for Dropin.
Coordinates GitHub release resolution and direct package download links.
"""

import urllib.parse
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple

from dropin.core.config import get_config
from dropin.core.models import PackageFormat
from dropin.core.security import validate_url
from dropin.network.github import GitHubResolver, GitHubReleaseInfo, GitHubAsset


class UrlTargetType(str, Enum):
    DIRECT_DOWNLOAD = "direct_download"
    GITHUB_RELEASE = "github_release"
    UNSUPPORTED = "unsupported"


@dataclass
class ResolvedUrlInfo:
    target_type: UrlTargetType
    url: str
    suggested_name: str
    format: PackageFormat
    github_info: Optional[GitHubReleaseInfo] = None
    assets: List[GitHubAsset] = None
    error_message: str = ""


class UrlResolver:
    """Dispatches external URLs to appropriate handlers."""

    def __init__(self):
        self.github_resolver = GitHubResolver()

    def resolve(self, url_str: str) -> ResolvedUrlInfo:
        url_str = url_str.strip()
        require_https = bool(get_config().get("require_https", True))
        is_valid, reason = validate_url(url_str, require_https=require_https)
        if not is_valid:
            return ResolvedUrlInfo(
                target_type=UrlTargetType.UNSUPPORTED,
                url=url_str,
                suggested_name="",
                format=PackageFormat.UNKNOWN,
                error_message=reason
            )

        # 1. Check if it's a GitHub URL
        if self.github_resolver.is_github_url(url_str):
            info, msg = self.github_resolver.fetch_release(url_str)
            if not info:
                return ResolvedUrlInfo(
                    target_type=UrlTargetType.UNSUPPORTED,
                    url=url_str,
                    suggested_name="",
                    format=PackageFormat.UNKNOWN,
                    error_message=msg
                )
            
            # Found release assets
            best_asset = info.assets[0] if info.assets else None
            return ResolvedUrlInfo(
                target_type=UrlTargetType.GITHUB_RELEASE,
                url=url_str,
                suggested_name=info.repo,
                format=best_asset.format if best_asset else PackageFormat.UNKNOWN,
                github_info=info,
                assets=info.assets
            )

        # 2. Check if it's a direct file download link
        parsed = urllib.parse.urlparse(url_str)
        path = parsed.path.rstrip("/")
        filename = path.split("/")[-1] if "/" in path else ""
        fmt = PackageFormat.from_extension(filename)

        if fmt != PackageFormat.UNKNOWN:
            return ResolvedUrlInfo(
                target_type=UrlTargetType.DIRECT_DOWNLOAD,
                url=url_str,
                suggested_name=filename,
                format=fmt
            )

        # 3. Flathub or other known download providers
        if "flathub.org" in parsed.netloc and ".flatpakref" in url_str:
            return ResolvedUrlInfo(
                target_type=UrlTargetType.DIRECT_DOWNLOAD,
                url=url_str,
                suggested_name=filename or "app.flatpakref",
                format=PackageFormat.FLATPAK
            )

        return ResolvedUrlInfo(
            target_type=UrlTargetType.UNSUPPORTED,
            url=url_str,
            suggested_name=filename,
            format=PackageFormat.UNKNOWN,
            error_message=(
                "The provided URL does not point to a supported package file "
                "(.AppImage, .deb, .rpm, .flatpakref, .tar.gz) or a recognized GitHub repository."
            )
        )
