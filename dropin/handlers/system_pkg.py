"""
System package handler for Dropin.

Installs applications by name using the distribution's native package manager
(apt, dnf, zypper, pacman, urpmi, xbps, apk). This makes Dropin a true
universal installer: it can fetch apps from distro repositories, not just
from downloaded files.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from dropin.core.distro import get_current_distribution
from dropin.core.logger import get_logger
from dropin.core.models import (
    AppPackageInfo,
    InstalledApp,
    InstallResult,
    PackageFormat,
)
from dropin.handlers.base import BaseHandler


_PKG_MANAGERS = [
    ("apt", ["pkexec", "apt-get", "install", "-y"], ["apt-cache", "search"], ["dpkg", "-s"], ["pkexec", "apt-get", "remove", "-y"]),
    ("dnf", ["pkexec", "dnf", "install", "-y"], ["dnf", "search"], ["rpm", "-q"], ["pkexec", "dnf", "remove", "-y"]),
    ("zypper", ["pkexec", "zypper", "install", "-y"], ["zypper", "search"], ["rpm", "-q"], ["pkexec", "zypper", "remove", "-y"]),
    ("pacman", ["pkexec", "pacman", "-S", "--noconfirm"], ["pacman", "-Ss"], ["pacman", "-Q"], ["pkexec", "pacman", "-R", "--noconfirm"]),
    ("urpmi", ["pkexec", "urpmi", "--auto"], ["urpmq"], ["rpm", "-q"], ["pkexec", "urpme", "--auto"]),
    ("xbps", ["pkexec", "xbps-install", "-Sy"], ["xbps-query", "-s"], ["xbps-query", "-l"], ["pkexec", "xbps-remove", "-R"]),
    ("apk", ["pkexec", "apk", "add"], ["apk", "search"], ["apk", "info"], ["pkexec", "apk", "del"]),
]


class SystemPkgHandler(BaseHandler):
    """Handler for installing packages by name from distro repositories."""

    format = PackageFormat.SYSTEM_PKG

    def can_handle(self, file_path: Path) -> bool:
        return False

    def inspect(self, file_path: Path) -> AppPackageInfo:
        """System packages are installed by name, not from a file."""
        distro = get_current_distribution()
        return AppPackageInfo(
            name=file_path.stem if file_path else "unknown",
            version="unknown",
            format=PackageFormat.SYSTEM_PKG,
            architecture=distro.arch,
            file_path=str(file_path),
            description="System package from distribution repository",
            publisher="Distribution Repository",
            homepage="",
            size_bytes=0,
            requires_root=True,
            target_destination="System",
            can_customize_destination=False,
            compatibility_ok=True,
            compatibility_reason="",
        )

    @classmethod
    def detect_package_manager(cls) -> Optional[Dict[str, Any]]:
        distro = get_current_distribution()
        # Fedora Atomic (Bazzite, Silverblue, …): dnf refuses installs there,
        # so layer/remove with rpm-ostree. Searching is read-only, dnf is fine.
        if distro.is_atomic and shutil.which("rpm-ostree"):
            return {
                "name": "rpm-ostree",
                "install": ["pkexec", "rpm-ostree", "install", "-y"],
                "search": ["dnf", "search"],
                "query": ["rpm", "-q"],
                "remove": ["pkexec", "rpm-ostree", "uninstall", "-y"],
            }
        for name, install, search, query, remove in _PKG_MANAGERS:
            if shutil.which(name):
                return {
                    "name": name,
                    "install": install,
                    "search": search,
                    "query": query,
                    "remove": remove,
                }
        return None

    @classmethod
    def search(cls, query_str: str) -> List[Dict[str, str]]:
        """Search distro repositories for matching packages."""
        pm = cls.detect_package_manager()
        if not pm:
            return []
        try:
            proc = subprocess.run(
                pm["search"] + [query_str],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return []
            return cls._parse_search_output(pm["name"], proc.stdout)
        except Exception as e:
            get_logger().debug(f"Package search failed: {e}")
            return []

    @staticmethod
    def _parse_search_output(pm_name: str, output: str) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        if pm_name == "apt":
            for line in output.splitlines():
                if " - " in line:
                    name, desc = line.split(" - ", 1)
                    results.append({"name": name.strip(), "description": desc.strip()})
        elif pm_name == "dnf":
            for line in output.splitlines():
                parts = line.split()
                if parts:
                    results.append({"name": parts[0].strip(), "description": ""})
        elif pm_name == "zypper":
            for line in output.splitlines():
                parts = line.split()
                if parts and not line.startswith("S") and not line.startswith("#"):
                    results.append({"name": parts[0].strip(), "description": ""})
        elif pm_name == "pacman":
            for line in output.splitlines():
                if "/" in line:
                    name, rest = line.split("/", 1)
                    results.append({"name": name.strip(), "description": rest.strip()[:60]})
        elif pm_name == "xbps":
            for line in output.splitlines():
                parts = line.split()
                if parts:
                    results.append({"name": parts[0].strip(), "description": ""})
        elif pm_name == "apk":
            for line in output.splitlines():
                parts = line.split()
                if parts:
                    results.append({"name": parts[0].strip(), "description": ""})
        return results[:50]

    def install(
        self,
        info: AppPackageInfo,
        dest_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> InstallResult:
        pm = self.detect_package_manager()
        if not pm:
            return InstallResult(
                success=False,
                message="No supported package manager found on this system.",
                error_details="Install apt, dnf, zypper, pacman, urpmi, xbps, or apk.",
            )

        pkg_name = info.name or info.update_identifier or ""
        if not pkg_name:
            return InstallResult(
                success=False,
                message="No package name specified.",
            )
        # The name is typed by the user and passed to a package manager as
        # root — reject anything that is not a plain package name (spaces,
        # leading dashes that would parse as options, shell punctuation).
        import re

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+@~-]*", pkg_name):
            return InstallResult(
                success=False,
                message=f"'{pkg_name}' does not look like a package name.",
                error_details="Type a single package name, for example: firefox",
            )

        if progress_callback:
            progress_callback(10, f"Checking if {pkg_name} is installed…")

        try:
            proc = subprocess.run(
                pm["query"] + [pkg_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                return InstallResult(
                    success=True,
                    message=f"{pkg_name} is already installed.",
                    app_id=f"dropin-sys-{pkg_name}",
                    installed_path=pkg_name,
                    launch_command=pkg_name,
                )
        except Exception:
            pass

        if progress_callback:
            progress_callback(30, f"Installing {pkg_name} via {pm['name']}…")

        try:
            proc = subprocess.run(
                pm["install"] + [pkg_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return InstallResult(
                success=False,
                message=f"Installation of {pkg_name} timed out.",
                error_details="Operation took longer than 10 minutes.",
            )
        except Exception as e:
            get_logger().error(f"System package install failed: {e}")
            return InstallResult(
                success=False,
                message=f"Failed to install {pkg_name}.",
                error_details=str(e),
            )

        if progress_callback:
            progress_callback(90, "Finalising…")

        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            get_logger().error(f"System package install failed: {err}")
            return InstallResult(
                success=False,
                message=f"Failed to install {pkg_name}.",
                error_details=err,
            )

        if progress_callback:
            progress_callback(100, "Installation complete.")

        launch_cmd = pkg_name
        try:
            which_proc = subprocess.run(
                ["which", pkg_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if which_proc.returncode == 0:
                launch_cmd = which_proc.stdout.strip()
        except Exception:
            pass

        return InstallResult(
            success=True,
            message=f"Successfully installed {pkg_name} via {pm['name']}.",
            app_id=f"dropin-sys-{pkg_name}",
            installed_path=pkg_name,
            launch_command=launch_cmd,
        )

    def uninstall(self, app: InstalledApp) -> bool:
        pm = self.detect_package_manager()
        if not pm:
            return False
        pkg_name = app.update_identifier or app.name
        try:
            proc = subprocess.run(
                pm["remove"] + [pkg_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            return proc.returncode == 0
        except Exception as e:
            get_logger().error(f"System package uninstall failed: {e}")
            return False

    def check_update(self, app: InstalledApp) -> Optional[UpdateCheckResult]:
        from dropin.core.models import UpdateCheckResult
        from dropin.core.versions import is_newer_version

        pm = self.detect_package_manager()
        if not pm:
            return None

        pkg_name = app.update_identifier or app.name
        try:
            proc = subprocess.run(
                pm["query"] + [pkg_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                output = proc.stdout.strip()
                latest = ""
                for line in output.splitlines():
                    for sep in (":", " ", "/"):
                        if sep in line:
                            parts = line.split(sep)
                            for p in parts:
                                p = p.strip()
                                if p and any(c.isdigit() for c in p):
                                    latest = p
                                    break
                            if latest:
                                break
                        if latest:
                            break
                if latest:
                    newer = is_newer_version(latest, app.version)
                    return UpdateCheckResult(
                        app_id=app.id,
                        current_version=app.version,
                        latest_version=latest,
                        update_available=newer,
                        message=(
                            f"Update available for {pkg_name}: {latest}"
                            if newer
                            else f"{pkg_name} is up to date ({latest})"
                        ),
                    )
        except Exception:
            pass
        return None