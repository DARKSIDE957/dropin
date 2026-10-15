"""
Automatic update management subsystem for Dropin.
Coordinates update discovery across GitHub releases, Flatpak, and native package managers.
"""

from __future__ import annotations

from typing import List, Optional

from dropin.core.logger import get_logger
from dropin.core.models import InstalledApp, UpdateCheckResult
from dropin.core.registry import get_registry
from dropin.core.versions import is_newer_version
from dropin.network.github import GitHubResolver


class UpdateManager:
    """Manages update checks for Dropin-tracked applications."""

    def __init__(self):
        self.registry = get_registry()
        self.github_resolver = GitHubResolver()

    def check_app_update(self, app_id: str) -> Optional[UpdateCheckResult]:
        app = self.registry.get_app(app_id)
        if not app:
            return None

        if app.update_type == "github" and app.update_identifier:
            return self._check_github_update(app)
        if app.format == "Flatpak":
            return self._check_flatpak_update(app)

        result = UpdateCheckResult(
            app_id=app.id,
            current_version=app.version,
            latest_version=app.version,
            update_available=False,
            message=(
                "No automatic upstream is linked for this app. "
                "GitHub-installed apps and Flatpaks can be checked automatically."
            ),
        )
        self.registry.update_check_status(app.id, app.version)
        self.registry.log_audit(
            "UPDATE_CHECK",
            app.name,
            "INFO",
            result.message,
        )
        return result

    def check_all_updates(self) -> List[UpdateCheckResult]:
        results: List[UpdateCheckResult] = []
        apps = self.registry.list_apps()
        for app in apps:
            try:
                res = self.check_app_update(app.id)
                if res:
                    results.append(res)
            except Exception as e:
                get_logger().error(f"Failed to check update for {app.name}: {e}")
                self.registry.log_audit(
                    "UPDATE_CHECK",
                    app.name,
                    "FAILED",
                    str(e),
                )
        return results

    def _check_github_update(self, app: InstalledApp) -> UpdateCheckResult:
        url = app.update_identifier
        if not url.startswith("http"):
            url = f"https://github.com/{url}"

        info, msg = self.github_resolver.fetch_release(url)
        if not info:
            self.registry.log_audit("UPDATE_CHECK", app.name, "FAILED", msg)
            return UpdateCheckResult(
                app_id=app.id,
                current_version=app.version,
                latest_version=app.version,
                update_available=False,
                message=f"Update check failed: {msg}",
            )

        is_newer = is_newer_version(info.tag_name, app.version)
        best_asset = info.assets[0] if info.assets else None
        download_url = best_asset.download_url if (best_asset and is_newer) else None

        # Persist latest tag (normalized comparison happens when reading)
        self.registry.update_check_status(app.id, info.tag_name)

        result = UpdateCheckResult(
            app_id=app.id,
            current_version=app.version,
            latest_version=info.tag_name,
            update_available=is_newer,
            download_url=download_url,
            changelog=info.description,
            message=(
                f"Update available from GitHub ({info.owner}/{info.repo}): {info.tag_name}"
                if is_newer
                else f"Up to date with GitHub ({info.owner}/{info.repo}) — {info.tag_name}"
            ),
        )
        self.registry.log_audit(
            "UPDATE_CHECK",
            app.name,
            "SUCCESS",
            result.message,
        )
        return result

    def _check_flatpak_update(self, app: InstalledApp) -> UpdateCheckResult:
        from dropin.handlers.flatpak import FlatpakHandler

        handler = FlatpakHandler()
        res = handler.check_update(app)
        if res:
            self.registry.update_check_status(
                app.id, res.latest_version or app.version
            )
            self.registry.log_audit(
                "UPDATE_CHECK",
                app.name,
                "SUCCESS",
                res.message or ("Update available" if res.update_available else "Up to date"),
            )
            return res

        self.registry.update_check_status(app.id, app.version)
        result = UpdateCheckResult(
            app_id=app.id,
            current_version=app.version,
            latest_version=app.version,
            update_available=False,
            message="Flatpak application is up to date.",
        )
        self.registry.log_audit("UPDATE_CHECK", app.name, "SUCCESS", result.message)
        return result
