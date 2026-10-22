"""
Snap (.snap) package handler for Dropin.

Installs Snaps via the `snap` CLI (Canonical's universal package format).
Snaps are confined, auto-updating, and work across many distributions.
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


class SnapHandler(BaseHandler):
    """Handler for Snap packages (.snap) installed via the snap CLI."""

    format = PackageFormat.SNAP

    def can_handle(self, file_path: Path) -> bool:
        if not file_path.is_file():
            return False
        if file_path.suffix.lower() == ".snap":
            return True
        try:
            with open(file_path, "rb") as f:
                # Snaps are squashfs images ("hsqs" little-endian magic).
                if f.read(4) == b"hsqs":
                    return True
        except Exception:
            pass
        return False

    def inspect(self, file_path: Path) -> AppPackageInfo:
        file_path = file_path.resolve()
        size = file_path.stat().st_size
        distro = get_current_distribution()

        name = file_path.stem
        version = "unknown"
        desc = "Snap package (confinement: strict)"

        meta = self._read_snap_meta(file_path)
        if meta:
            name = meta.get("name", name)
            version = meta.get("version", version)
            desc = meta.get("summary", desc)

        compat_ok = shutil.which("snap") is not None
        compat_reason = "" if compat_ok else (
            "The 'snap' command is not installed. Install snapd to use .snap packages."
        )

        return AppPackageInfo(
            name=name,
            version=version,
            format=PackageFormat.SNAP,
            architecture=distro.arch,
            file_path=str(file_path),
            description=desc,
            publisher="Snap Publisher",
            homepage="",
            size_bytes=size,
            requires_root=True,
            target_destination="System (Snap)",
            can_customize_destination=False,
            compatibility_ok=compat_ok,
            compatibility_reason=compat_reason,
        )

    def install(
        self,
        info: AppPackageInfo,
        dest_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> InstallResult:
        if not shutil.which("snap"):
            return InstallResult(
                success=False,
                message="snapd is not installed.",
                error_details="Install snapd first, then try again.",
            )

        src_path = Path(info.file_path).resolve()
        # Local .snap files are unasserted, so they need root + --dangerous,
        # the same way system package installs go through pkexec.
        if shutil.which("pkexec"):
            cmd = ["pkexec", "snap", "install", "--dangerous", str(src_path)]
        else:
            cmd = ["snap", "install", "--dangerous", str(src_path)]

        if progress_callback:
            progress_callback(10, "Starting snap install…")

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return InstallResult(
                success=False,
                message="Snap installation timed out.",
                error_details="Operation took longer than 10 minutes.",
            )
        except Exception as e:
            get_logger().error(f"Snap install failed: {e}")
            return InstallResult(
                success=False,
                message="Failed to run snap install.",
                error_details=str(e),
            )

        if progress_callback:
            progress_callback(90, "Finalising snap install…")

        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            get_logger().error(f"Snap install failed: {err}")
            return InstallResult(
                success=False,
                message="Snap installation failed.",
                error_details=err,
            )

        if progress_callback:
            progress_callback(100, "Installation complete.")

        snap_name = info.name
        launch_cmd = f"snap run {snap_name}"
        app_id = f"dropin-snap-{snap_name}"

        return InstallResult(
            success=True,
            message=f"Successfully installed Snap application {info.name}.",
            app_id=app_id,
            installed_path=f"snap:{snap_name}",
            launch_command=launch_cmd,
        )

    def uninstall(self, app: InstalledApp) -> bool:
        if not shutil.which("snap"):
            return False
        snap_name = app.update_identifier or app.name
        try:
            proc = subprocess.run(
                ["snap", "remove", snap_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            return proc.returncode == 0
        except Exception as e:
            get_logger().error(f"Snap uninstall failed: {e}")
            return False

    def check_update(self, app: InstalledApp) -> Optional[UpdateCheckResult]:
        from dropin.core.models import UpdateCheckResult
        if not shutil.which("snap"):
            return None
        snap_name = app.update_identifier or app.name
        try:
            proc = subprocess.run(
                ["snap", "list", snap_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                lines = proc.stdout.strip().splitlines()
                if len(lines) > 1:
                    parts = lines[1].split()
                    if len(parts) >= 2:
                        latest = parts[1]
                        from dropin.core.versions import is_newer_version
                        newer = is_newer_version(latest, app.version)
                        return UpdateCheckResult(
                            app_id=app.id,
                            current_version=app.version,
                            latest_version=latest,
                            update_available=newer,
                            message=(
                                f"Snap update available: {latest}"
                                if newer
                                else f"Snap is up to date ({latest})"
                            ),
                        )
        except Exception:
            pass
        return None

    def _read_snap_meta(self, file_path: Path) -> Optional[Dict[str, str]]:
        """Best-effort read of snap metadata via unsquashfs (no install side effects)."""
        if not shutil.which("unsquashfs"):
            return None
        import tempfile

        try:
            with tempfile.TemporaryDirectory(prefix="dropin-snap-") as tmp:
                proc = subprocess.run(
                    [
                        "unsquashfs", "-f", "-no-xattrs", "-d", tmp,
                        str(file_path), "meta/snap.yaml",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                if proc.returncode != 0:
                    return None
                yaml_path = Path(tmp) / "meta" / "snap.yaml"
                if yaml_path.is_file():
                    text = yaml_path.read_text(encoding="utf-8", errors="replace")
                    return self._parse_snap_yaml(text)
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_snap_yaml(text: str) -> Dict[str, str]:
        meta: Dict[str, str] = {}
        for line in text.splitlines():
            # Top-level keys only — nested app/hook entries also reuse names
            # like "summary:" and must not override the package metadata.
            if not line or line[0].isspace():
                continue
            for key in ("name:", "version:", "summary:", "description:"):
                if line.startswith(key) and key.rstrip(":") not in meta:
                    meta[key.rstrip(":")] = line.split(":", 1)[1].strip()
        return meta