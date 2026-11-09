"""
AppImage package handler for Dropin.
Implements safe inspection, desktop launcher generation, installation to ~/Applications,
and clean uninstallation.
"""

import json
import os
import re
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Tuple, Dict, Any

from dropin.core.config import get_config
from dropin.core.desktop import (
    detect_image_format,
    remove_application_icons,
    save_application_icon,
    update_desktop_caches,
    write_desktop_entry,
)
from dropin.core.distro import get_current_distribution
from dropin.core.logger import get_logger
from dropin.core.models import (
    AppPackageInfo,
    InstalledApp,
    InstallResult,
    PackageFormat,
    UpdateCheckResult,
)
from dropin.core.security import (
    check_directory_writable,
    check_disk_space,
    secure_file_permissions,
)
from dropin.core.versions import extract_semantic_version, is_newer_version, normalize_version
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

        # Attempt to extract metadata (.desktop / icon / appstream / electron / update info) safely
        meta = self._extract_appimage_metadata(file_path)

        app_name = meta.get("Name") or meta.get("package_json_name") or self._clean_app_name(file_name)
        raw_version = (
            meta.get("app_version")
            or meta.get("appstream_version")
            or meta.get("package_json_version")
            or meta.get("tauri_version")
            or self._detect_version_from_name(file_name)
            or meta.get("desktop_version")
            or meta.get("desktop_spec_version")
            or "1.0.0"
        )
        version = normalize_version(raw_version) or "1.0.0"
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

        ok_write, write_msg = check_directory_writable(dest_dir)
        if not ok_write:
            return InstallResult(
                success=False,
                message=write_msg,
                error_details=write_msg,
            )

        src_size = src_path.stat().st_size
        ok_space, space_msg = check_disk_space(dest_dir, src_size, safety_multiplier=1.1)
        if not ok_space:
            return InstallResult(
                success=False,
                message=space_msg,
                error_details=space_msg,
            )

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize target filename
        safe_name = re.sub(r"[^\w\-.]", "_", info.name)
        target_filename = f"{safe_name}.AppImage"
        target_path = dest_dir / target_filename

        if progress_callback:
            progress_callback(30, f"Copying application to {dest_dir}...")

        temp_target = target_path.with_suffix(".tmp")
        try:
            if src_path.resolve() != target_path.resolve():
                # Atomic copy to destination
                shutil.copy2(src_path, temp_target)
                secure_file_permissions(str(temp_target), is_executable=True)
                temp_target.replace(target_path)
            secure_file_permissions(str(target_path), is_executable=True)
        except Exception as e:
            if temp_target.exists():
                try:
                    temp_target.unlink()
                except Exception:
                    pass
            return InstallResult(
                success=False,
                message="Failed to copy AppImage to destination.",
                error_details=str(e)
            )

        if progress_callback:
            progress_callback(60, "Configuring desktop integration and icon...")

        app_id = f"dropin-appimage-{safe_name.lower()}"
        icon_bytes = info.icon_bytes
        if not icon_bytes:
            # Re-probe installed binary if inspect occurred before full metadata extraction
            fresh_meta = self._extract_appimage_metadata(target_path)
            icon_bytes = fresh_meta.get("icon_bytes")
            if fresh_meta and not info.extra_metadata:
                info.extra_metadata = fresh_meta

        icon_path = self._save_icon(app_id, icon_bytes, target_path)

        if progress_callback:
            progress_callback(80, "Creating application launcher...")

        meta = info.extra_metadata or {}
        launcher_path = self._create_desktop_launcher(
            app_id=app_id,
            name=info.name,
            exec_path=target_path,
            icon_path=icon_path,
            comment=info.description or f"{info.name} AppImage",
            categories=meta.get("Categories", "Utility;"),
            startup_wm_class=meta.get("StartupWMClass", ""),
            mime_types=meta.get("MimeType", ""),
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
        if app.id:
            remove_application_icons(app.id)

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

    def _detect_version_from_name(self, filename: str) -> Optional[str]:
        return extract_semantic_version(filename)

    def _extract_appimage_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Attempt safe inspection of AppImage squashfs metadata using available tools (7z/unsquashfs/readelf) or binary search."""
        meta: Dict[str, Any] = {}

        # 1. Check embedded ELF .upd_info section for upstream update target
        if shutil.which("readelf"):
            try:
                re_proc = subprocess.run(
                    ["readelf", "-p", ".upd_info", str(file_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if re_proc.returncode == 0:
                    for rline in re_proc.stdout.splitlines():
                        if "gh-releases-zsync|" in rline:
                            payload = rline.split("gh-releases-zsync|", 1)[1].strip()
                            parts = payload.split("|")
                            if len(parts) >= 2 and parts[0] and parts[1]:
                                meta["update_type"] = "github"
                                meta["update_identifier"] = f"{parts[0]}/{parts[1]}"
                        elif "zsync|" in rline:
                            meta["zsync_url"] = rline.split("zsync|", 1)[1].strip()
            except Exception as e:
                get_logger().debug(f"AppImage readelf .upd_info check skipped: {e}")

        # 2. Check if 7z can list squashfs contents
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
                    all_archive_paths: list[str] = []
                    desktop_entry = None
                    icon_entry = None
                    app_update_entry = None
                    pkg_entry = None
                    appstream_entry = None
                    binary_entry = None

                    for line in proc.stdout.splitlines():
                        if line.startswith("Path = "):
                            current_path = line[7:].strip()
                            all_archive_paths.append(current_path)
                            clean_lower = current_path.lower()
                            if clean_lower.endswith(".desktop"):
                                if not desktop_entry or "/" not in current_path:
                                    desktop_entry = current_path
                            elif clean_lower.endswith("app-update.yml"):
                                app_update_entry = current_path
                            elif clean_lower.endswith("package.json") and ("resources/app/" in clean_lower or clean_lower == "package.json"):
                                if not pkg_entry or "resources/app/package.json" in clean_lower:
                                    pkg_entry = current_path
                            elif clean_lower.endswith(".metainfo.xml") or clean_lower.endswith(".appdata.xml"):
                                appstream_entry = current_path
                            elif (clean_lower.endswith(".png") or clean_lower.endswith(".svg")) and ".diricon" in clean_lower:
                                icon_entry = current_path
                            elif not icon_entry and (clean_lower.endswith(".png") or clean_lower.endswith(".svg")) and "/" not in current_path:
                                icon_entry = current_path
                            elif not binary_entry and ("usr/bin/" in current_path or current_path == "AppRun") and "." not in current_path.split("/")[-1]:
                                if current_path != "AppRun":
                                    binary_entry = current_path

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

                    # Extract app-update.yml for Electron apps (e.g. Hydra)
                    if app_update_entry and not meta.get("update_identifier"):
                        try:
                            proc_u = subprocess.run(
                                ["7z", "e", "-so", str(file_path), app_update_entry],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                timeout=5,
                            )
                            if proc_u.returncode == 0:
                                owner, repo = None, None
                                for uline in proc_u.stdout.splitlines():
                                    if "owner:" in uline:
                                        owner = uline.split(":", 1)[1].strip().strip('"').strip("'")
                                    elif "repo:" in uline:
                                        repo = uline.split(":", 1)[1].strip().strip('"').strip("'")
                                if owner and repo:
                                    meta["update_type"] = "github"
                                    meta["update_identifier"] = f"{owner}/{repo}"
                        except Exception:
                            pass

                    # Extract package.json for Electron / Node apps (e.g. Cursor)
                    if pkg_entry and not meta.get("app_version"):
                        try:
                            proc_p = subprocess.run(
                                ["7z", "e", "-so", str(file_path), pkg_entry],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                timeout=5,
                            )
                            if proc_p.returncode == 0:
                                pkg_data = json.loads(proc_p.stdout)
                                if "version" in pkg_data and pkg_data["version"]:
                                    meta["package_json_version"] = str(pkg_data["version"])
                                if "name" in pkg_data and pkg_data["name"]:
                                    meta["package_json_name"] = str(pkg_data["name"])
                        except Exception:
                            pass

                    # Extract AppStream metainfo for Linux native apps
                    if appstream_entry and not meta.get("app_version") and not meta.get("package_json_version"):
                        try:
                            proc_a = subprocess.run(
                                ["7z", "e", "-so", str(file_path), appstream_entry],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                timeout=5,
                            )
                            if proc_a.returncode == 0:
                                m = re.search(r'<release\s+[^>]*version=["\']([^"\']+)["\']', proc_a.stdout)
                                if m:
                                    meta["appstream_version"] = m.group(1)
                        except Exception:
                            pass

                    # Extract version from Tauri / Rust binary strings if still not found
                    if (
                        not meta.get("app_version")
                        and not meta.get("package_json_version")
                        and not meta.get("appstream_version")
                        and binary_entry
                    ):
                        try:
                            proc_b = subprocess.run(
                                ["7z", "e", "-so", str(file_path), binary_entry],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=5,
                            )
                            if proc_b.returncode == 0:
                                m_tauri = re.search(
                                    rb'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?)(?:Unsloth AI|Unsloth Desktop|[A-Z][a-zA-Z0-9]+ (?:AI|Desktop|App))',
                                    proc_b.stdout
                                )
                                if m_tauri:
                                    meta["tauri_version"] = m_tauri.group(1).decode("utf-8")
                        except Exception:
                            pass

                    def _is_valid_image(data: bytes) -> bool:
                        if not data or len(data) < 32:
                            return False
                        return detect_image_format(data) is not None

                    # Build prioritized icon search list
                    icon_candidates: list[str] = []
                    if ".DirIcon" in all_archive_paths:
                        icon_candidates.append(".DirIcon")
                    if icon_entry and icon_entry not in icon_candidates:
                        icon_candidates.append(icon_entry)

                    meta_icon = (meta.get("Icon") or "").strip().lower()
                    if meta_icon:
                        for p in all_archive_paths:
                            p_lower = p.lower()
                            if p_lower.endswith(f"/{meta_icon}.png") or p_lower.endswith(f"/{meta_icon}.svg") or p_lower == f"{meta_icon}.png" or p_lower == f"{meta_icon}.svg":
                                if p not in icon_candidates:
                                    icon_candidates.append(p)

                    # Add standard hicolor paths by resolution preference
                    for size in ("512x512", "256x256", "128x128", "scalable", "96x96", "64x64", "48x48", "32x32"):
                        for p in all_archive_paths:
                            p_lower = p.lower()
                            if f"/icons/hicolor/{size}/" in p_lower and (p_lower.endswith(".png") or p_lower.endswith(".svg")):
                                if p not in icon_candidates:
                                    icon_candidates.append(p)

                    # Add any remaining png or svg in the archive
                    for p in all_archive_paths:
                        p_lower = p.lower()
                        if (p_lower.endswith(".png") or p_lower.endswith(".svg")) and p not in icon_candidates:
                            icon_candidates.append(p)

                    valid_icon = False
                    for target in icon_candidates:
                        try:
                            proc_i = subprocess.run(
                                ["7z", "e", "-so", str(file_path), target],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=5,
                            )
                            if proc_i.returncode == 0:
                                data = proc_i.stdout
                                if _is_valid_image(data):
                                    meta["icon_bytes"] = data
                                    valid_icon = True
                                    break
                                # If payload is text pointing to a symlink destination
                                if 0 < len(data) < 1024 and b"\x00" not in data:
                                    sym_target = data.decode("utf-8", errors="ignore").strip().lstrip("./")
                                    matched_target = None
                                    for ap in all_archive_paths:
                                        if ap == sym_target or ap.endswith(sym_target):
                                            matched_target = ap
                                            break
                                    if matched_target:
                                        proc_sym = subprocess.run(
                                            ["7z", "e", "-so", str(file_path), matched_target],
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE,
                                            timeout=5,
                                        )
                                        if proc_sym.returncode == 0 and _is_valid_image(proc_sym.stdout):
                                            meta["icon_bytes"] = proc_sym.stdout
                                            valid_icon = True
                                            break
                        except Exception:
                            continue
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
                if k in ("Name", "Comment", "Exec", "Icon", "Categories", "GenericName"):
                    info[k] = v
                elif k in ("X-AppImage-Version", "X-AppImageKit-Version", "X-Version"):
                    info["app_version"] = v
                elif k == "Version":
                    # Freedesktop specification version (1.0, 1.1) vs application version
                    if v in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5"):
                        info["desktop_spec_version"] = v
                    else:
                        info["desktop_version"] = v
                elif k == "X-AppImage-UpdateInformation":
                    info["update_information"] = v
                    if v.startswith("gh-releases-zsync|"):
                        parts = v.split("|")
                        if len(parts) >= 3 and parts[1] and parts[2]:
                            info["update_type"] = "github"
                            info["update_identifier"] = f"{parts[1]}/{parts[2]}"
                    elif v.startswith("zsync|"):
                        info["zsync_url"] = v.split("zsync|", 1)[1].strip()
        return info

    def check_update(self, app: InstalledApp) -> Optional[UpdateCheckResult]:
        from dropin.network.github import GitHubResolver

        update_type = app.update_type
        update_id = app.update_identifier

        # If not recorded yet in registry, try inspecting the installed binary on disk
        if (not update_id or update_type == "none") and app.file_path and Path(app.file_path).is_file():
            try:
                meta = self._extract_appimage_metadata(Path(app.file_path))
                if meta.get("update_type") and meta.get("update_identifier"):
                    update_type = meta["update_type"]
                    update_id = meta["update_identifier"]
            except Exception:
                pass

        if update_type == "github" and update_id:
            resolver = GitHubResolver()
            url = f"https://github.com/{update_id}" if not update_id.startswith("http") else update_id
            info, msg = resolver.fetch_release(url)
            if not info:
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

            return UpdateCheckResult(
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
        return None

    def _save_icon(self, app_id: str, icon_bytes: Optional[bytes], appimage_path: Path) -> Optional[str]:
        if not icon_bytes:
            return None
        return save_application_icon(app_id=app_id, icon_bytes=icon_bytes)

    def _create_desktop_launcher(
        self,
        app_id: str,
        name: str,
        exec_path: Path,
        icon_path: Optional[str],
        comment: str,
        categories: str,
        startup_wm_class: str = "",
        mime_types: str = "",
    ) -> Optional[Path]:
        return write_desktop_entry(
            app_id=app_id,
            name=name,
            exec_path=exec_path,
            icon_path=icon_path,
            comment=comment,
            generic_name=name,
            categories=categories,
            startup_wm_class=startup_wm_class,
            mime_types=mime_types,
        )

    def _update_desktop_db(self) -> None:
        from dropin.core.desktop import update_desktop_caches
        update_desktop_caches()
