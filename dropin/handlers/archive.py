"""
Portable Archive (.tar.gz, .tar.xz, .zip) handler for Dropin.
Implements safe inspection (checking for path traversal attacks and rejecting uncompiled source archives),
extracting compiled portable binaries, desktop integration, and uninstallation.
"""

import os
import re
import shutil
import tarfile
import zipfile
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
)
from dropin.core.security import validate_archive_members, secure_file_permissions
from dropin.handlers.base import BaseHandler


class ArchiveHandler(BaseHandler):
    """Handler for compiled portable application archives."""

    format = PackageFormat.ARCHIVE
    ARCHIVE_EXTENSIONS = (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".zip")

    def can_handle(self, file_path: Path) -> bool:
        if not file_path.is_file():
            return False
        name = file_path.name.lower()
        return any(name.endswith(ext) for ext in self.ARCHIVE_EXTENSIONS)

    def inspect(self, file_path: Path) -> AppPackageInfo:
        file_path = file_path.resolve()
        size = file_path.stat().st_size
        distro = get_current_distribution()

        # Safely examine archive member names
        member_names: List[str] = []
        is_zip = file_path.name.lower().endswith(".zip")

        try:
            if is_zip:
                with zipfile.ZipFile(file_path, "r") as zf:
                    member_names = zf.namelist()
            else:
                with tarfile.open(file_path, "r:*") as tf:
                    member_names = [m.name for m in tf.getmembers()]
        except Exception as e:
            return AppPackageInfo(
                name=file_path.stem,
                version="1.0.0",
                format=PackageFormat.ARCHIVE,
                architecture=distro.arch,
                file_path=str(file_path),
                description="Damaged or unreadable archive.",
                compatibility_ok=False,
                compatibility_reason=f"Archive cannot be read: {e}"
            )

        # Check for path traversal attacks
        safe, safe_msg = validate_archive_members(member_names, Path("/tmp"))
        if not safe:
            return AppPackageInfo(
                name=file_path.stem,
                version="1.0.0",
                format=PackageFormat.ARCHIVE,
                architecture=distro.arch,
                file_path=str(file_path),
                description="Unsafe archive structure.",
                compatibility_ok=False,
                compatibility_reason=safe_msg
            )

        # Look for executable binary and .desktop file
        binaries = []
        desktop_files = []
        is_source_tree = False

        source_indicators = ["cmakelists.txt", "cmake_lists.txt", "cargo.toml", "configure.ac", "makefile", "setup.py", "pyproject.toml", "pom.xml"]
        lower_names = [m.lower() for m in member_names]

        # Check if archive looks purely like uncompiled source code
        matched_source = [ind for ind in source_indicators if any(ind in n for n in lower_names)]

        for name in member_names:
            clean = name.strip("/")
            parts = clean.split("/")
            base = parts[-1]
            if base.endswith(".desktop"):
                desktop_files.append(name)
            # Binary check: no file extension or .bin or .sh or in bin/
            if not is_zip and "/" not in clean and "." not in base and len(base) > 2:
                binaries.append(name)
            elif "bin/" in clean and "." not in base:
                binaries.append(name)

        if matched_source and not desktop_files and not binaries:
            is_source_tree = True

        compat_ok = True
        compat_reason = ""
        if is_source_tree:
            compat_ok = False
            compat_reason = (
                "This archive contains source code rather than a precompiled application. "
                "Dropin only installs compiled binaries, not uncompiled source trees."
            )
        elif not binaries and not desktop_files:
            compat_ok = False
            compat_reason = "No executable application or .desktop entry found in this archive."

        app_name = self._extract_clean_name(file_path.name)
        dest_dir = get_config().portable_dir / re.sub(r"[^\w\-.]", "_", app_name)

        return AppPackageInfo(
            name=app_name,
            version="1.0.0",
            format=PackageFormat.ARCHIVE,
            architecture=distro.arch,
            file_path=str(file_path),
            description="Portable Linux Application",
            publisher="Portable Archive Release",
            size_bytes=size,
            requires_root=False,
            target_destination=str(dest_dir),
            can_customize_destination=True,
            compatibility_ok=compat_ok,
            compatibility_reason=compat_reason,
            extra_metadata={
                "binaries": binaries,
                "desktop_files": desktop_files,
                "is_zip": is_zip
            }
        )

    def install(
        self,
        info: AppPackageInfo,
        dest_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> InstallResult:
        if not info.compatibility_ok:
            return InstallResult(
                success=False,
                message=info.compatibility_reason,
                error_details=info.compatibility_reason
            )

        src_path = Path(info.file_path).resolve()
        if not src_path.is_file():
            return InstallResult(
                success=False,
                message="Archive file does not exist.",
                error_details=str(src_path)
            )

        safe_name = re.sub(r"[^\w\-.]", "_", info.name)
        if dest_dir is None:
            dest_dir = get_config().portable_dir / safe_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(20, "Extracting portable application files safely...")

        is_zip = info.extra_metadata.get("is_zip", False)
        try:
            if is_zip:
                with zipfile.ZipFile(src_path, "r") as zf:
                    # Validate paths again before extracting
                    safe, msg = validate_archive_members(zf.namelist(), dest_dir)
                    if not safe:
                        return InstallResult(success=False, message=msg, error_details=msg)
                    zf.extractall(dest_dir)
            else:
                with tarfile.open(src_path, "r:*") as tf:
                    safe, msg = validate_archive_members([m.name for m in tf.getmembers()], dest_dir)
                    if not safe:
                        return InstallResult(success=False, message=msg, error_details=msg)
                    # Use filter='data' if available (Python 3.12+)
                    if hasattr(tarfile, "data_filter"):
                        tf.extractall(dest_dir, filter="data")
                    else:
                        tf.extractall(dest_dir)
        except Exception as e:
            return InstallResult(
                success=False,
                message="Failed to extract archive.",
                error_details=str(e)
            )

        if progress_callback:
            progress_callback(60, "Configuring executable permissions...")

        # Find executable inside extracted destination
        exec_path = self._find_primary_executable(dest_dir, info.name)
        if exec_path:
            secure_file_permissions(str(exec_path), is_executable=True)

        if progress_callback:
            progress_callback(80, "Creating desktop launcher...")

        app_id = f"dropin-archive-{safe_name.lower()}"
        launcher_path = None
        if exec_path:
            launcher_path = self._create_launcher(app_id, info.name, exec_path)

        if progress_callback:
            progress_callback(100, "Installation complete.")

        return InstallResult(
            success=True,
            message=f"Successfully extracted and installed portable app {info.name}.",
            app_id=app_id,
            installed_path=str(dest_dir),
            launcher_path=str(launcher_path) if launcher_path else None,
            launch_command=str(exec_path) if exec_path else None
        )

    def uninstall(self, app: InstalledApp) -> bool:
        get_logger().info(f"Removing portable app {app.name} at {app.file_path}")
        errors = []
        removed_any = False

        targets: list[Path] = []
        if app.file_path:
            targets.append(Path(app.file_path))

        for target in targets:
            if target.is_dir():
                try:
                    shutil.rmtree(target)
                    removed_any = True
                except Exception as e:
                    errors.append(f"Failed to remove {target}: {e}")
            elif target.is_file():
                try:
                    target.unlink()
                    removed_any = True
                except Exception as e:
                    errors.append(f"Failed to remove {target}: {e}")

        launchers: list[Path] = []
        if app.launcher_path:
            launchers.append(Path(app.launcher_path))
        if app.id:
            launchers.append(
                Path.home() / ".local" / "share" / "applications" / f"{app.id}.desktop"
            )
        for launcher in dict.fromkeys(launchers):
            if launcher.is_file():
                try:
                    launcher.unlink()
                    removed_any = True
                except Exception:
                    pass

        still_there = [str(t) for t in targets if t.exists()]
        if still_there:
            errors.append(f"Portable app still on disk: {', '.join(still_there)}")
            return False

        if not removed_any and targets and not any(t.exists() for t in targets):
            return True

        return len(errors) == 0

    def _extract_clean_name(self, filename: str) -> str:
        name = filename
        for ext in self.ARCHIVE_EXTENSIONS:
            if name.lower().endswith(ext):
                name = name[:-len(ext)]
                break
        name = re.sub(r"[-_](linux|x86_64|amd64|arm64|aarch64|bin|portable)$", "", name, flags=re.I)
        name = re.sub(r"[-_]v?\d+[\d\._\-]*$", "", name)
        name = name.replace("-", " ").replace("_", " ").strip()
        return name.title() if name else "Portable Application"

    def _find_primary_executable(self, dest_dir: Path, app_name: str) -> Optional[Path]:
        norm_name = app_name.lower().replace(" ", "")
        candidates = []
        for p in dest_dir.rglob("*"):
            if p.is_file() and not p.name.endswith((".txt", ".md", ".json", ".png", ".svg", ".h", ".c")):
                if norm_name in p.name.lower():
                    return p
                candidates.append(p)
        return candidates[0] if candidates else None

    def _create_launcher(self, app_id: str, name: str, exec_path: Path) -> Optional[Path]:
        launchers_dir = Path.home() / ".local" / "share" / "applications"
        launchers_dir.mkdir(parents=True, exist_ok=True)
        launcher_path = launchers_dir / f"{app_id}.desktop"

        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={name}\n"
            f'Exec="{exec_path}" %U\n'
            "Icon=application-x-executable\n"
            "Terminal=false\n"
            "Categories=Utility;\n"
            "X-Dropin-Managed=true\n"
        )
        try:
            launcher_path.write_text(content, encoding="utf-8")
            secure_file_permissions(str(launcher_path), is_executable=True)
            return launcher_path
        except Exception:
            return None
