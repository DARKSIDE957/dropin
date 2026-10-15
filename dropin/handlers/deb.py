"""
Debian (.deb) package handler for Dropin.
Implements native Debian package inspection, architecture compatibility checks,
safe metadata extraction, and installation via apt/dpkg and pkexec.
"""

import io
import os
import re
import shutil
import subprocess
import tarfile
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


class DebHandler(BaseHandler):
    """Handler for Debian .deb packages."""

    format = PackageFormat.DEB

    def can_handle(self, file_path: Path) -> bool:
        if not file_path.is_file():
            return False

        if file_path.suffix.lower() == ".deb":
            return True

        # Check ar archive magic: "!<arch>\n"
        try:
            with open(file_path, "rb") as f:
                header = f.read(8)
                if header == b"!<arch>\n":
                    # Check next member name for debian-binary
                    next_name = f.read(16).decode("ascii", errors="ignore").strip()
                    if "debian-binary" in next_name:
                        return True
        except Exception:
            pass
        return False

    def inspect(self, file_path: Path) -> AppPackageInfo:
        file_path = file_path.resolve()
        size = file_path.stat().st_size
        distro = get_current_distribution()

        meta = self._parse_deb_control(file_path)

        pkg_name = meta.get("Package", file_path.stem)
        version = meta.get("Version", "1.0.0")
        deb_arch = meta.get("Architecture", "all")
        desc = meta.get("Description", "Debian Package")
        publisher = meta.get("Maintainer", "Debian Maintainer")
        homepage = meta.get("Homepage", "")

        depends_raw = meta.get("Depends", "")
        dependencies = [d.strip() for d in depends_raw.split(",") if d.strip()] if depends_raw else []

        # Compatibility check
        compat_ok = True
        compat_reason = ""

        if not distro.is_debian_family and not (distro.has_apt or distro.has_dpkg):
            compat_ok = False
            compat_reason = (
                f"Your distribution ({distro.name}) uses {distro.id.upper()} package management. "
                "DEB packages require a Debian/Ubuntu-compatible system with 'apt' or 'dpkg'."
            )
        else:
            # Check architecture
            normalized_sys_arch = "amd64" if distro.arch == "x86_64" else ("arm64" if distro.arch == "aarch64" else distro.arch)
            if deb_arch not in ("all", "any", normalized_sys_arch, distro.arch):
                compat_ok = False
                compat_reason = f"Package architecture '{deb_arch}' is not compatible with system architecture '{distro.arch}'."

        icon_bytes = self._extract_deb_icon(file_path)

        return AppPackageInfo(
            name=pkg_name,
            version=version,
            format=PackageFormat.DEB,
            architecture=deb_arch,
            file_path=str(file_path),
            description=desc,
            publisher=publisher,
            homepage=homepage,
            icon_bytes=icon_bytes,
            dependencies=dependencies,
            size_bytes=size,
            requires_root=True,
            target_destination="System (APT Package Manager)",
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
        if not info.compatibility_ok:
            return InstallResult(
                success=False,
                message=f"Cannot install DEB package: {info.compatibility_reason}",
                error_details=info.compatibility_reason
            )

        if not distro.has_pkexec:
            return InstallResult(
                success=False,
                message="Privilege escalation tool 'pkexec' not found.",
                error_details="Installing native packages requires administrator privileges via pkexec."
            )

        src_path = Path(info.file_path).resolve()
        if not src_path.is_file():
            return InstallResult(
                success=False,
                message="Source package file not found.",
                error_details=f"Path does not exist: {src_path}"
            )

        if progress_callback:
            progress_callback(20, "Requesting administrative privileges...")

        # Native installation via apt or dpkg
        cmd: List[str] = []
        if distro.has_apt:
            cmd = ["pkexec", "apt-get", "install", "-y", str(src_path)]
        elif distro.has_dpkg:
            cmd = ["pkexec", "dpkg", "-i", str(src_path)]
        else:
            return InstallResult(
                success=False,
                message="No compatible Debian package manager (apt/dpkg) available.",
                error_details="apt-get or dpkg is required."
            )

        if progress_callback:
            progress_callback(40, f"Installing {info.name} via native package manager...")

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300
            )
            if proc.returncode != 0:
                err_msg = proc.stderr.strip() or proc.stdout.strip()
                get_logger().error(f"DEB install failed: {err_msg}")
                return InstallResult(
                    success=False,
                    message="Package manager installation failed.",
                    error_details=err_msg
                )
        except subprocess.TimeoutExpired:
            return InstallResult(
                success=False,
                message="Installation timed out.",
                error_details="Package manager operation took longer than 5 minutes."
            )
        except Exception as e:
            return InstallResult(
                success=False,
                message="Failed to invoke package manager.",
                error_details=str(e)
            )

        if progress_callback:
            progress_callback(80, "Verifying package status...")

        # Verify installation with dpkg-query if available
        is_installed = self._verify_dpkg_installed(info.name)
        if not is_installed and distro.has_dpkg:
            return InstallResult(
                success=False,
                message="Installation verification failed.",
                error_details="dpkg did not report the package as installed."
            )

        if progress_callback:
            progress_callback(100, "Installation complete.")

        app_id = f"dropin-deb-{info.name.lower()}"
        return InstallResult(
            success=True,
            message=f"Successfully installed {info.name} v{info.version} via system package manager.",
            app_id=app_id,
            installed_path="/usr",
            launch_command=info.name
        )

    def uninstall(self, app: InstalledApp) -> bool:
        pkg_name = app.name
        distro = get_current_distribution()
        if not distro.has_pkexec:
            return False

        cmd = ["pkexec", "apt-get", "remove", "-y", pkg_name] if distro.has_apt else ["pkexec", "dpkg", "-r", pkg_name]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
            return proc.returncode == 0
        except Exception as e:
            get_logger().error(f"Failed to uninstall DEB package: {e}")
            return False

    def _verify_dpkg_installed(self, pkg_name: str) -> bool:
        if shutil.which("dpkg-query"):
            try:
                proc = subprocess.run(
                    ["dpkg-query", "-W", "-f=${Status}", pkg_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                return "install ok installed" in proc.stdout
            except Exception:
                pass
        return True

    def _parse_deb_control(self, file_path: Path) -> Dict[str, str]:
        """Extract and parse the 'control' file inside control.tar.* in pure Python."""
        meta: Dict[str, str] = {}
        try:
            with open(file_path, "rb") as f:
                magic = f.read(8)
                if magic != b"!<arch>\n":
                    return meta

                while True:
                    hdr = f.read(60)
                    if len(hdr) < 60:
                        break
                    name = hdr[:16].decode("ascii", errors="ignore").strip()
                    size_str = hdr[48:58].decode("ascii", errors="ignore").strip()
                    try:
                        member_size = int(size_str)
                    except ValueError:
                        break

                    data = f.read(member_size)
                    # Ar members are 2-byte aligned
                    if member_size % 2 != 0:
                        f.read(1)

                    if name.startswith("control.tar"):
                        # Extract control tarball
                        try:
                            tar_bytes = io.BytesIO(data)
                            with tarfile.open(fileobj=tar_bytes) as tf:
                                for member in tf.getmembers():
                                    if member.name in ("./control", "control"):
                                        f_ctrl = tf.extractfile(member)
                                        if f_ctrl:
                                            text = f_ctrl.read().decode("utf-8", errors="replace")
                                            meta = self._parse_rfc822(text)
                                            return meta
                        except Exception as e:
                            get_logger().debug(f"Error opening control.tar: {e}")
        except Exception as e:
            get_logger().debug(f"Error parsing .deb: {e}")
        return meta

    def _parse_rfc822(self, text: str) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        current_key = None
        for line in text.splitlines():
            if line.startswith(" ") or line.startswith("\t"):
                if current_key:
                    fields[current_key] += " " + line.strip()
            elif ":" in line:
                key, val = line.split(":", 1)
                current_key = key.strip()
                fields[current_key] = val.strip()
        return fields

    def _extract_deb_icon(self, file_path: Path) -> Optional[bytes]:
        """Attempt to extract icon from data.tar inside deb."""
        try:
            with open(file_path, "rb") as f:
                if f.read(8) != b"!<arch>\n":
                    return None
                while True:
                    hdr = f.read(60)
                    if len(hdr) < 60:
                        break
                    name = hdr[:16].decode("ascii", errors="ignore").strip()
                    size_str = hdr[48:58].decode("ascii", errors="ignore").strip()
                    try:
                        member_size = int(size_str)
                    except ValueError:
                        break
                    data = f.read(member_size)
                    if member_size % 2 != 0:
                        f.read(1)

                    if name.startswith("data.tar"):
                        tar_bytes = io.BytesIO(data)
                        with tarfile.open(fileobj=tar_bytes) as tf:
                            for m in tf.getmembers():
                                if ("/icons/" in m.name or "/pixmaps/" in m.name) and (m.name.endswith(".png") or m.name.endswith(".svg")):
                                    f_icon = tf.extractfile(m)
                                    if f_icon:
                                        return f_icon.read()
                        break
        except Exception:
            pass
        return None
