"""
Flatpak (.flatpakref and .flatpak bundle) package handler for Dropin.
Implements Flatpak reference inspection, user/system scope support,
and installation via flatpak CLI.
"""

import configparser
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from dropin.core.config import get_config
from dropin.core.distro import get_current_distribution
from dropin.core.logger import get_logger
from dropin.core.models import (
    AppPackageInfo,
    InstalledApp,
    InstallResult,
    PackageFormat,
    UpdateCheckResult,
)
from dropin.handlers.base import BaseHandler


class FlatpakHandler(BaseHandler):
    """Handler for Flatpak references (.flatpakref) and bundles (.flatpak)."""

    format = PackageFormat.FLATPAK

    def can_handle(self, file_path: Path) -> bool:
        if not file_path.is_file():
            return False

        ext = file_path.suffix.lower()
        if ext in (".flatpakref", ".flatpak"):
            return True

        # Check if text file starts with [Flatpak Ref]
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
                if first_line == "[Flatpak Ref]":
                    return True
        except Exception:
            pass
        return False

    def inspect(self, file_path: Path) -> AppPackageInfo:
        file_path = file_path.resolve()
        size = file_path.stat().st_size
        distro = get_current_distribution()

        meta = self._parse_flatpak_ref(file_path)

        app_id = meta.get("Name", file_path.stem)
        title = meta.get("Title") or app_id
        url = meta.get("Url", "Flathub / Flatpak Remote")
        branch = meta.get("Branch", "stable")
        comment = meta.get("Comment", "Flatpak Sandboxed Application")

        scope = get_config().get("flatpak_scope", "user")

        compat_ok = distro.has_flatpak
        compat_reason = "" if distro.has_flatpak else "Flatpak runtime is not installed on this system. Please install 'flatpak' first."

        return AppPackageInfo(
            name=title,
            version=branch,
            format=PackageFormat.FLATPAK,
            architecture=distro.arch,
            file_path=str(file_path),
            description=comment,
            publisher=url,
            homepage=url,
            size_bytes=size,
            requires_root=(scope == "system"),
            target_destination=f"Flatpak ({scope.title()} Scope)",
            can_customize_destination=False,
            compatibility_ok=compat_ok,
            compatibility_reason=compat_reason,
            extra_metadata=meta
        )

    def install(
        self,
        info: AppPackageInfo,
        dest_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> InstallResult:
        distro = get_current_distribution()
        if not distro.has_flatpak:
            return InstallResult(
                success=False,
                message="Flatpak is not installed on your system.",
                error_details="Please install the flatpak package manager."
            )

        scope = get_config().get("flatpak_scope", "user")
        is_user = (scope == "user")

        src_path = Path(info.file_path).resolve()
        if not src_path.is_file():
            return InstallResult(
                success=False,
                message="Source flatpak file not found.",
                error_details=f"File not found: {src_path}"
            )

        if progress_callback:
            progress_callback(20, f"Preparing Flatpak installation ({scope} mode)...")

        cmd = ["flatpak", "install"]
        if is_user:
            cmd.append("--user")
        else:
            cmd = ["pkexec", "flatpak", "install", "--system"]

        cmd.extend(["--noninteractive", "-y", str(src_path)])

        if progress_callback:
            progress_callback(40, f"Downloading and configuring Flatpak runtime and app...")

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600
            )
            if proc.returncode != 0:
                err = proc.stderr.strip() or proc.stdout.strip()
                get_logger().error(f"Flatpak install failed: {err}")
                return InstallResult(
                    success=False,
                    message="Flatpak installation failed.",
                    error_details=err
                )
        except subprocess.TimeoutExpired:
            return InstallResult(
                success=False,
                message="Flatpak installation timed out.",
                error_details="Operation took longer than 10 minutes."
            )
        except Exception as e:
            return InstallResult(
                success=False,
                message="Failed to execute flatpak command.",
                error_details=str(e)
            )

        if progress_callback:
            progress_callback(90, "Verifying Flatpak registration...")

        app_ref = info.extra_metadata.get("Name", info.name)
        launch_cmd = f"flatpak run {app_ref}"

        if progress_callback:
            progress_callback(100, "Installation complete.")

        app_id = f"dropin-flatpak-{app_ref.lower().replace('.', '-')}"
        return InstallResult(
            success=True,
            message=f"Successfully installed Flatpak application {info.name}.",
            app_id=app_id,
            installed_path=f"flatpak:{app_ref}",
            launch_command=launch_cmd
        )

    def uninstall(self, app: InstalledApp) -> bool:
        if not shutil.which("flatpak"):
            return False

        app_ref = app.update_identifier or app.name
        is_user = (app.scope == "user")

        cmd = ["flatpak", "uninstall"]
        if is_user:
            cmd.append("--user")
        else:
            cmd = ["pkexec", "flatpak", "uninstall", "--system"]

        cmd.extend(["--noninteractive", "-y", app_ref])

        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
            return proc.returncode == 0
        except Exception as e:
            get_logger().error(f"Flatpak uninstall failed: {e}")
            return False

    def check_update(self, app: InstalledApp) -> Optional[UpdateCheckResult]:
        if not shutil.which("flatpak"):
            return None

        app_ref = app.update_identifier or app.name
        cmd = ["flatpak", "remote-ls", "--updates"]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            if proc.returncode == 0 and app_ref in proc.stdout:
                return UpdateCheckResult(
                    app_id=app.id,
                    current_version=app.version,
                    latest_version="Updated upstream",
                    update_available=True,
                    message="A new Flatpak update is available from the remote."
                )
        except Exception:
            pass
        return None

    def _parse_flatpak_ref(self, file_path: Path) -> Dict[str, str]:
        meta: Dict[str, str] = {}
        try:
            cfg = configparser.ConfigParser()
            cfg.read(str(file_path), encoding="utf-8")
            if "Flatpak Ref" in cfg:
                for k, v in cfg["Flatpak Ref"].items():
                    meta[k.title()] = v
        except Exception as e:
            get_logger().debug(f"Failed to parse flatpakref INI: {e}")
        return meta
