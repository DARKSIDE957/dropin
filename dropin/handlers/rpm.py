"""
RPM (.rpm) package handler for Dropin.
Implements RPM package metadata inspection, architecture compatibility checks,
and native package installation via dnf, zypper, or rpm using pkexec.
"""

import os
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


class RpmHandler(BaseHandler):
    """Handler for Red Hat / Fedora / openSUSE RPM packages."""

    format = PackageFormat.RPM

    def can_handle(self, file_path: Path) -> bool:
        if not file_path.is_file():
            return False

        if file_path.suffix.lower() == ".rpm":
            return True

        # Check RPM magic bytes: \xed\xab\xee\xdb
        try:
            with open(file_path, "rb") as f:
                header = f.read(4)
                if header == b"\xed\xab\xee\xdb":
                    return True
        except Exception:
            pass
        return False

    def inspect(self, file_path: Path) -> AppPackageInfo:
        file_path = file_path.resolve()
        size = file_path.stat().st_size
        distro = get_current_distribution()

        meta = self._query_rpm_metadata(file_path)

        pkg_name = meta.get("NAME") or file_path.stem
        version = meta.get("VERSION") or "1.0.0"
        if meta.get("RELEASE"):
            version += f"-{meta['RELEASE']}"
        rpm_arch = meta.get("ARCH") or "x86_64"
        desc = meta.get("SUMMARY") or "RPM Package"
        publisher = meta.get("VENDOR") or "RPM Packager"
        homepage = meta.get("URL") or ""

        # Check compatibility
        compat_ok = True
        compat_reason = ""

        if not distro.is_fedora_family and not distro.is_suse_family and not (distro.has_dnf or distro.has_rpm or distro.has_zypper):
            compat_ok = False
            compat_reason = (
                f"Your distribution ({distro.name}) does not use RPM package management. "
                "Try an AppImage or Flatpak instead."
            )
        elif distro.is_atomic and not distro.has_rpm_ostree and not shutil.which("rpm-ostree"):
            compat_ok = False
            compat_reason = (
                f"{distro.name} is a Fedora Atomic system, but rpm-ostree was not found. "
                "RPM packages can only be layered with rpm-ostree on this system."
            )
        else:
            # Check architecture
            if rpm_arch not in ("noarch", distro.arch):
                compat_ok = False
                compat_reason = f"Package architecture '{rpm_arch}' is not compatible with system architecture '{distro.arch}'."

        installed_version = self._query_installed_version(pkg_name)
        meta["already_installed"] = installed_version is not None
        meta["installed_version"] = installed_version or ""
        meta["atomic_system"] = bool(distro.is_atomic)
        meta["missing_dependencies"] = (
            self._missing_dependencies(file_path) if compat_ok else []
        )

        target = "System (RPM Package Manager)"
        if distro.is_atomic:
            target = "System (rpm-ostree layer, reboot required)"

        return AppPackageInfo(
            name=pkg_name,
            version=version,
            format=PackageFormat.RPM,
            architecture=rpm_arch,
            file_path=str(file_path),
            description=desc,
            publisher=publisher,
            homepage=homepage,
            size_bytes=size,
            requires_root=True,
            target_destination=target,
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
                message=f"Cannot install RPM package: {info.compatibility_reason}",
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

        # Refuse duplicate installs. The confirmation screen sets
        # reinstall_confirmed when the user explicitly chooses Reinstall.
        installed_version = self._query_installed_version(info.name)
        if installed_version and not info.extra_metadata.get("reinstall_confirmed"):
            return InstallResult(
                success=False,
                message=f"{info.name} is already installed.",
                error_details=(
                    f"{info.name} v{installed_version} is already installed on this system. "
                    "Installing it again would not add anything. "
                    "Choose Reinstall on the confirmation screen if you really want to install it again."
                ),
            )

        # Name missing dependencies before asking for a password. dnf and
        # rpm-ostree pull them in automatically; a bare `rpm -Uvh` cannot,
        # so on rpm-only systems fail here with the exact names.
        missing = self._missing_dependencies(src_path)
        use_atomic = bool(distro.is_atomic)
        use_dnf = bool(distro.has_dnf) and not use_atomic
        use_zypper = bool(distro.has_zypper) and not use_atomic
        if missing and not (use_atomic or use_dnf or use_zypper):
            names = ", ".join(missing)
            return InstallResult(
                success=False,
                message=f"Missing dependencies: {names}",
                error_details=(
                    f"Cannot install {info.name}: these dependencies are missing: {names}. "
                    "Install them first (for example with dnf), then try again."
                ),
            )

        if progress_callback:
            progress_callback(20, "Requesting administrative privileges...")

        # Determine native installation command. Fedora Atomic systems
        # (Bazzite, Silverblue, ...) have a read-only /usr and their dnf
        # refuses install commands, so layer with rpm-ostree instead.
        cmd: List[str] = []
        timeout = 300
        if use_atomic:
            if not distro.has_rpm_ostree and not shutil.which("rpm-ostree"):
                return InstallResult(
                    success=False,
                    message="rpm-ostree was not found.",
                    error_details=(
                        "This is a Fedora Atomic system. RPM packages are layered with "
                        "rpm-ostree, but rpm-ostree is not available."
                    ),
                )
            cmd = ["pkexec", "rpm-ostree", "install", "-y", "--idempotent", str(src_path)]
            timeout = 1800
        elif use_dnf:
            cmd = ["pkexec", "dnf", "install", "-y", str(src_path)]
        elif use_zypper:
            cmd = ["pkexec", "zypper", "--non-interactive", "install", str(src_path)]
        elif distro.has_rpm:
            cmd = ["pkexec", "rpm", "-Uvh", str(src_path)]
        else:
            return InstallResult(
                success=False,
                message="No compatible RPM package manager (dnf/zypper/rpm) found.",
                error_details="dnf or rpm is required."
            )

        if progress_callback:
            if missing and use_atomic:
                progress_callback(30, f"rpm-ostree will also install: {', '.join(missing)}")
            elif missing and use_dnf:
                progress_callback(30, f"dnf will also install: {', '.join(missing)}")
            progress_callback(40, f"Installing {info.name} via native package manager...")

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            if proc.returncode != 0:
                err_msg = proc.stderr.strip() or proc.stdout.strip()
                get_logger().error(f"RPM install failed: {err_msg}")
                return InstallResult(
                    success=False,
                    message="RPM package installation failed.",
                    error_details=err_msg
                )
        except subprocess.TimeoutExpired:
            return InstallResult(
                success=False,
                message="Installation timed out.",
                error_details=f"Package manager operation took longer than {timeout // 60} minutes."
            )
        except Exception as e:
            return InstallResult(
                success=False,
                message="Failed to invoke package manager.",
                error_details=str(e)
            )

        if use_atomic:
            if progress_callback:
                progress_callback(100, "Layered. Restart to finish installing.")
            app_id = f"dropin-rpm-{info.name.lower()}"
            return InstallResult(
                success=True,
                message=(
                    f"{info.name} v{info.version} was layered with rpm-ostree. "
                    "Restart your computer to finish installing it."
                ),
                app_id=app_id,
                installed_path="/usr",
                launch_command=info.name
            )

        if progress_callback:
            progress_callback(80, "Verifying package status...")

        # Verify with rpm -q
        is_installed = self._verify_rpm_installed(info.name)
        if not is_installed and distro.has_rpm:
            return InstallResult(
                success=False,
                message="Installation verification failed.",
                error_details="rpm did not report the package as installed."
            )

        if progress_callback:
            progress_callback(100, "Installation complete.")

        app_id = f"dropin-rpm-{info.name.lower()}"
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

        if distro.is_atomic:
            # Layered packages come off with rpm-ostree (takes effect on reboot).
            cmd = ["pkexec", "rpm-ostree", "uninstall", "-y", pkg_name]
        elif distro.has_dnf:
            cmd = ["pkexec", "dnf", "remove", "-y", pkg_name]
        elif distro.has_zypper:
            cmd = ["pkexec", "zypper", "--non-interactive", "remove", pkg_name]
        else:
            cmd = ["pkexec", "rpm", "-e", pkg_name]

        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
            return proc.returncode == 0
        except Exception as e:
            get_logger().error(f"Failed to uninstall RPM package: {e}")
            return False

    def _query_installed_version(self, pkg_name: str) -> Optional[str]:
        """Installed VERSION-RELEASE for pkg_name, or None if not installed."""
        if not shutil.which("rpm"):
            return None
        try:
            proc = subprocess.run(
                ["rpm", "-q", "--queryformat", "%{VERSION}-%{RELEASE}", pkg_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                return proc.stdout.strip() or None
        except Exception:
            get_logger().debug(
                "Failed to query installed RPM %s", pkg_name, exc_info=True
            )
        return None

    def _missing_dependencies(self, src_path: Path) -> List[str]:
        """Requirements of this RPM that nothing on the system provides.

        Uses a test transaction only — nothing is installed.
        """
        if not shutil.which("rpm"):
            return []
        try:
            proc = subprocess.run(
                ["rpm", "-U", "--test", str(src_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
        except Exception:
            get_logger().debug(
                "RPM dependency test failed for %s", src_path, exc_info=True
            )
            return []
        missing: List[str] = []
        for line in (proc.stderr or "").splitlines() + (proc.stdout or "").splitlines():
            line = line.strip()
            if " is needed by " in line:
                req = line.split(" is needed by ")[0].strip()
                if req and req not in missing:
                    missing.append(req)
        return missing

    def _verify_rpm_installed(self, pkg_name: str) -> bool:
        if shutil.which("rpm"):
            try:
                proc = subprocess.run(
                    ["rpm", "-q", pkg_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                return proc.returncode == 0
            except Exception:
                pass
        return True

    def _query_rpm_metadata(self, file_path: Path) -> Dict[str, str]:
        meta: Dict[str, str] = {}
        if shutil.which("rpm"):
            try:
                fmt = "%{NAME}@@@%{VERSION}@@@%{RELEASE}@@@%{ARCH}@@@%{SUMMARY}@@@%{URL}@@@%{VENDOR}"
                proc = subprocess.run(
                    ["rpm", "-qp", "--queryformat", fmt, str(file_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                if proc.returncode == 0 and "@@@" in proc.stdout:
                    parts = proc.stdout.strip().split("@@@")
                    if len(parts) >= 7:
                        meta["NAME"] = parts[0]
                        meta["VERSION"] = parts[1]
                        meta["RELEASE"] = parts[2]
                        meta["ARCH"] = parts[3]
                        meta["SUMMARY"] = parts[4]
                        meta["URL"] = parts[5]
                        meta["VENDOR"] = parts[6]
                        return meta
            except Exception as e:
                get_logger().debug(f"RPM tool query failed: {e}")

        # Fallback filename extraction
        name = file_path.stem
        meta["NAME"] = name.split("-")[0]
        meta["VERSION"] = "1.0.0"
        meta["ARCH"] = "x86_64"
        return meta
