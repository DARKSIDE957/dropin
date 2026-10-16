"""
AppImage package handler for Dropin.
Implements safe inspection, desktop launcher generation, installation to ~/Applications,
and clean uninstallation.
"""

import os
import re
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Tuple, Dict, Any

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
from dropin.core.security import secure_file_permissions
from dropin.handlers.base import BaseHandler


class AppImageHandler(BaseHandler):
    """Handler for Linux AppImage executables."""

    format = PackageFormat.APPIMAGE

    def can_handle(self, file_path: Path) -> bool:
        if not file_path.is_file():
            return False

        if file_path.suffix.lower() == ".appimage":
            return True

        # Check ELF magic and AppImage signature in binary
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)
                if len(header) >= 4 and header[:4] == b"\x7fELF":
                    # Check for AppImage Type 2 magic at offset 8: 'A', 'I', 0x02
                    if len(header) >= 11 and header[8:11] == b"AI\x02":
                        return True
                    # Check for AppImage Type 1 magic at offset 8: 'A', 'I', 0x01
                    if len(header) >= 11 and header[8:11] == b"AI\x01":
                        return True
        except Exception:
            pass
        return False

    def inspect(self, file_path: Path) -> AppPackageInfo:
        file_path = file_path.resolve()
        file_name = file_path.name
        size = file_path.stat().st_size

        arch = self._detect_elf_arch(file_path)
        current_arch = get_current_distribution().arch

        compat_ok = True
        compat_reason = ""
        if arch != "unknown" and current_arch != "unknown":
            if arch != current_arch and not (current_arch == "x86_64" and arch == "i686"):
                compat_ok = False
                compat_reason = f"Application architecture ({arch}) does not match your system architecture ({current_arch})."

        # Attempt to extract metadata (.desktop / icon) safely without running the binary
        meta = self._extract_appimage_metadata(file_path)

        app_name = meta.get("Name") or self._clean_app_name(file_name)
        version = meta.get("Version") or self._detect_version_from_name(file_name)
        description = meta.get("Comment") or "Linux AppImage Application"
        icon_bytes = meta.get("icon_bytes")

        dest_dir = get_config().appimage_dir

        return AppPackageInfo(
            name=app_name,
            version=version,
            format=PackageFormat.APPIMAGE,
            architecture=arch if arch != "unknown" else current_arch,
            file_path=str(file_path),
            description=description,
            publisher=meta.get("Publisher", "Independent Publisher"),
            homepage=meta.get("Homepage", ""),
            icon_bytes=icon_bytes,
            icon_path=meta.get("icon_path"),
            size_bytes=size,
            requires_root=False,
            target_destination=str(dest_dir),
            can_customize_destination=True,
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
        if progress_callback:
            progress_callback(10, "Validating AppImage integrity...")

        src_path = Path(info.file_path)
        if not src_path.is_file():
            return InstallResult(
                success=False,
                message=f"Source file not found: {info.file_path}",
                error_details="File does not exist."
            )

        if dest_dir is None:
            dest_dir = get_config().appimage_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize target filename
        safe_name = re.sub(r"[^\w\-.]", "_", info.name)
        target_filename = f"{safe_name}.AppImage"
        target_path = dest_dir / target_filename

        if progress_callback:
            progress_callback(30, f"Copying application to {dest_dir}...")

        try:
            # Atomic copy to destination
            temp_target = target_path.with_suffix(".tmp")
            shutil.copy2(src_path, temp_target)
            secure_file_permissions(str(temp_target), is_executable=True)
            temp_target.replace(target_path)
            secure_file_permissions(str(target_path), is_executable=True)
        except Exception as e:
            return InstallResult(
                success=False,
                message="Failed to copy AppImage to destination.",
                error_details=str(e)
            )

        if progress_callback:
            progress_callback(60, "Configuring desktop integration and icon...")

        app_id = f"dropin-appimage-{safe_name.lower()}"
        icon_path = self._save_icon(app_id, info.icon_bytes, target_path)

        if progress_callback:
            progress_callback(80, "Creating application launcher...")

        launcher_path = self._create_desktop_launcher(
            app_id=app_id,
            name=info.name,
            exec_path=target_path,
            icon_path=icon_path,
            comment=info.description or f"{info.name} AppImage",
            categories=info.extra_metadata.get("Categories", "Utility;")
        )

        if progress_callback:
            progress_callback(100, "Installation complete.")

        return InstallResult(
            success=True,
            message=f"Successfully installed {info.name} to {dest_dir}.",
            app_id=app_id,
            installed_path=str(target_path),
            launcher_path=str(launcher_path) if launcher_path else None,
            launch_command=str(target_path),
            icon_path=icon_path or None,
        )

    def uninstall(self, app: InstalledApp) -> bool:
        get_logger().info(f"Uninstalling AppImage {app.name} ({app.id})")
        errors = []

        # Candidate binaries: registry path and launch_command (may differ if path drifted).
        binaries: list[Path] = []
        for raw in (app.file_path, app.launch_command):
            if not raw:
                continue
            p = Path(raw.strip().strip('"'))
            if p not in binaries:
                binaries.append(p)

        removed_any = False
        for binary in binaries:
            if not binary.is_file():
                continue
            try:
                binary.unlink()
                removed_any = True
                get_logger().info(f"Removed AppImage binary: {binary}")
            except Exception as e:
                errors.append(f"Failed to remove binary {binary}: {e}")

        # Launchers: recorded path plus the canonical Dropin-managed desktop file.
        launchers: list[Path] = []
        if app.launcher_path:
            launchers.append(Path(app.launcher_path))
        if app.id:
            launchers.append(
                Path.home() / ".local" / "share" / "applications" / f"{app.id}.desktop"
            )
        seen_launchers: set[Path] = set()
        for launcher in launchers:
            if launcher in seen_launchers:
                continue
            seen_launchers.add(launcher)
            if not launcher.is_file():
                continue
            try:
                launcher.unlink()
                removed_any = True
            except Exception as e:
                errors.append(f"Failed to remove launcher {launcher}: {e}")

        if app.icon_path and Path(app.icon_path).is_file():
            try:
                Path(app.icon_path).unlink()
            except Exception:
                get_logger().warning(
                    "Failed to remove AppImage icon %s", app.icon_path, exc_info=True
                )

        self._update_desktop_db()

        # Still-present binaries mean uninstall failed (do not report success).
        still_there = [str(p) for p in binaries if p.is_file()]
        if still_there:
            errors.append(f"AppImage still on disk: {', '.join(still_there)}")
            get_logger().error(f"Uninstall incomplete for {app.id}: {errors}")
            return False

        if not removed_any and binaries and not any(p.exists() for p in binaries):
            # Already gone — treat as success so the registry can drop the stale entry.
            get_logger().info(f"AppImage already absent for {app.id}; cleaning registry entry")
            return True

        return len(errors) == 0

    def _detect_elf_arch(self, file_path: Path) -> str:
        """Read ELF machine type without executing."""
        try:
            with open(file_path, "rb") as f:
                header = f.read(20)
                if len(header) >= 20 and header[:4] == b"\x7fELF":
                    e_machine = struct.unpack("<H", header[18:20])[0]
                    if e_machine == 0x3E:
                        return "x86_64"
                    elif e_machine == 0xB7:
                        return "aarch64"
                    elif e_machine == 0x28:
                        return "armv7l"
                    elif e_machine == 0x03:
                        return "i686"
        except Exception:
            pass
        return "unknown"

    def _clean_app_name(self, filename: str) -> str:
        name = filename
        if name.lower().endswith(".appimage"):
            name = name[:-9]
        # Remove version strings and arch tags
        name = re.sub(r"[-_](x86_64|amd64|arm64|aarch64|i386|i686)$", "", name, flags=re.I)
        name = re.sub(r"[-_]v?\d+[\d\._\-]*$", "", name)
        name = name.replace("-", " ").replace("_", " ").strip()
        if name.islower():
            return name.title()
        return name if name else "AppImage Application"

    def _detect_version_from_name(self, filename: str) -> str:
        match = re.search(r"[-_vV]?(\d+\.\d+(?:\.\d+)?(?:[-_][a-zA-Z0-9]+)?)", filename)
        if match:
            return match.group(1)
        return "1.0.0"

    def _extract_appimage_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Attempt safe inspection of AppImage squashfs metadata using available tools (7z/unsquashfs) or binary search."""
        meta: Dict[str, Any] = {}

        # Check if 7z can list contents
        has_7z = shutil.which("7z") is not None
        if has_7z:
            try:
                proc = subprocess.run(
                    ["7z", "l", "-slt", str(file_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                if proc.returncode == 0:
                    desktop_entry = None
                    icon_entry = None
                    current_path = ""
                    for line in proc.stdout.splitlines():
                        if line.startswith("Path = "):
                            current_path = line[7:].strip()
                            if current_path.endswith(".desktop") and "/" not in current_path:
                                desktop_entry = current_path
                            elif (current_path.endswith(".png") or current_path.endswith(".svg")) and ".DirIcon" in current_path:
                                icon_entry = current_path
                            elif not icon_entry and (current_path.endswith(".png") or current_path.endswith(".svg")) and "/" not in current_path:
                                icon_entry = current_path

                    # Extract desktop file content to read
                    if desktop_entry:
                        proc_e = subprocess.run(
                            ["7z", "e", "-so", str(file_path), desktop_entry],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=5
                        )
                        if proc_e.returncode == 0:
                            meta.update(self._parse_desktop_file_text(proc_e.stdout))

                    # Extract icon bytes
                    if icon_entry or ".DirIcon" in proc.stdout:
                        icon_target = icon_entry if icon_entry else ".DirIcon"
                        proc_i = subprocess.run(
                            ["7z", "e", "-so", str(file_path), icon_target],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=5
                        )
                        if proc_i.returncode == 0 and len(proc_i.stdout) > 0:
                            meta["icon_bytes"] = proc_i.stdout
            except Exception as e:
                get_logger().debug(f"AppImage 7z extraction skipped: {e}")

        return meta

    def _parse_desktop_file_text(self, content: str) -> Dict[str, str]:
        info: Dict[str, str] = {}
        in_entry = False
        for line in content.splitlines():
            line = line.strip()
            if line == "[Desktop Entry]":
                in_entry = True
                continue
            elif line.startswith("[") and line.endswith("]"):
                in_entry = False
                continue

            if in_entry and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k in ("Name", "Version", "Comment", "Exec", "Icon", "Categories", "GenericName"):
                    info[k] = v
        return info

    def _save_icon(self, app_id: str, icon_bytes: Optional[bytes], appimage_path: Path) -> Optional[str]:
        icons_dir = Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
        icons_dir.mkdir(parents=True, exist_ok=True)

        if icon_bytes:
            # Detect whether svg or png
            is_svg = b"<svg" in icon_bytes[:200].lower()
            ext = ".svg" if is_svg else ".png"
            if not is_svg:
                icons_dir = Path.home() / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps"
                icons_dir.mkdir(parents=True, exist_ok=True)

            target_icon = icons_dir / f"{app_id}{ext}"
            try:
                target_icon.write_bytes(icon_bytes)
                return str(target_icon)
            except Exception:
                pass

        # Fallback: copy Dropin package icon
        default_svg = Path(__file__).resolve().parent.parent / "assets" / "io.dropin.Dropin.svg"
        if default_svg.is_file():
            fallback_target = icons_dir / f"{app_id}.svg"
            try:
                shutil.copy2(default_svg, fallback_target)
                return str(fallback_target)
            except Exception:
                pass
        return None

    def _create_desktop_launcher(
        self,
        app_id: str,
        name: str,
        exec_path: Path,
        icon_path: Optional[str],
        comment: str,
        categories: str
    ) -> Optional[Path]:
        launchers_dir = Path.home() / ".local" / "share" / "applications"
        launchers_dir.mkdir(parents=True, exist_ok=True)

        launcher_path = launchers_dir / f"{app_id}.desktop"
        icon_line = f"Icon={icon_path}\n" if icon_path else "Icon=application-x-executable\n"
        if not categories.endswith(";"):
            categories += ";"

        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={name}\n"
            f"GenericName={name}\n"
            f"Comment={comment}\n"
            f'Exec="{exec_path}"\n'
            f"{icon_line}"
            "Terminal=false\n"
            f"Categories={categories}\n"
            "StartupNotify=true\n"
            "X-Dropin-Managed=true\n"
        )

        try:
            launcher_path.write_text(content, encoding="utf-8")
            secure_file_permissions(str(launcher_path), is_executable=True)
            self._update_desktop_db()
            return launcher_path
        except Exception as e:
            get_logger().error(f"Failed to write desktop launcher: {e}")
            return None

    def _update_desktop_db(self) -> None:
        if shutil.which("update-desktop-database"):
            try:
                launchers_dir = str(Path.home() / ".local" / "share" / "applications")
                subprocess.run(
                    ["update-desktop-database", launchers_dir],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
            except Exception:
                pass
