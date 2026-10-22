"""
Data models for Dropin application installer and update manager.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

# Distro family groupings for package-manager compatibility (defined here to
# avoid a circular import with dropin.core.distro).
_DEBIAN_FAMILY = {"debian", "ubuntu", "pop", "mint", "elementary", "zorin", "kali", "linuxmint"}
_FEDORA_FAMILY = {"fedora", "rhel", "centos", "almalinux", "rocky", "bazzite"}
_ARCH_FAMILY = {"arch", "manjaro", "endeavouros", "garuda", "endeavour"}
_SUSE_FAMILY = {"suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed"}
_ALPINE_FAMILY = {"alpine"}
_VOID_FAMILY = {"void"}
_MAGEIA_FAMILY = {"mageia"}


class PackageFormat(str, Enum):
    APPIMAGE = "AppImage"
    DEB = "DEB"
    RPM = "RPM"
    FLATPAK = "Flatpak"
    ARCHIVE = "Archive"
    SNAP = "Snap"
    SYSTEM_PKG = "System Package"
    APPSTREAM = "AppStream"
    UNKNOWN = "Unknown"

    @classmethod
    def from_extension(cls, file_name: str) -> "PackageFormat":
        lower = file_name.lower()
        if lower.endswith(".appimage"):
            return cls.APPIMAGE
        elif lower.endswith(".deb"):
            return cls.DEB
        elif lower.endswith(".rpm"):
            return cls.RPM
        elif lower.endswith(".flatpakref") or lower.endswith(".flatpak"):
            return cls.FLATPAK
        elif lower.endswith(".snap"):
            return cls.SNAP
        elif lower.endswith(".tar.gz") or lower.endswith(".tar.xz") or lower.endswith(".tar.bz2") or lower.endswith(".zip") or lower.endswith(".tgz"):
            return cls.ARCHIVE
        return cls.UNKNOWN


@dataclass
class DistributionInfo:
    id: str
    name: str
    version: str
    id_like: List[str]
    arch: str
    has_apt: bool = False
    has_dpkg: bool = False
    has_dnf: bool = False
    has_rpm: bool = False
    has_zypper: bool = False
    has_pacman: bool = False
    has_flatpak: bool = False
    has_pkexec: bool = False
    has_snap: bool = False
    has_apk: bool = False
    has_xbps: bool = False
    has_urpmi: bool = False
    is_atomic: bool = False
    has_rpm_ostree: bool = False

    @property
    def is_debian_family(self) -> bool:
        family = [self.id.lower()] + [x.lower() for x in self.id_like]
        return (
            any(x in _DEBIAN_FAMILY for x in family)
            or self.has_apt
            or self.has_dpkg
        )

    @property
    def is_fedora_family(self) -> bool:
        family = [self.id.lower()] + [x.lower() for x in self.id_like]
        return (
            any(x in _FEDORA_FAMILY for x in family)
            or (self.has_dnf and self.has_rpm)
        )

    @property
    def is_arch_family(self) -> bool:
        family = [self.id.lower()] + [x.lower() for x in self.id_like]
        return any(x in _ARCH_FAMILY for x in family) or self.has_pacman

    @property
    def is_suse_family(self) -> bool:
        family = [self.id.lower()] + [x.lower() for x in self.id_like]
        return any(x in _SUSE_FAMILY for x in family) or self.has_zypper

    @property
    def is_alpine_family(self) -> bool:
        family = [self.id.lower()] + [x.lower() for x in self.id_like]
        return any(x in _ALPINE_FAMILY for x in family) or self.has_apk

    @property
    def is_void_family(self) -> bool:
        family = [self.id.lower()] + [x.lower() for x in self.id_like]
        return any(x in _VOID_FAMILY for x in family) or self.has_xbps

    @property
    def is_mageia_family(self) -> bool:
        family = [self.id.lower()] + [x.lower() for x in self.id_like]
        return any(x in _MAGEIA_FAMILY for x in family) or self.has_urpmi


@dataclass
class AppPackageInfo:
    name: str
    version: str
    format: PackageFormat
    architecture: str
    file_path: str
    description: str = ""
    publisher: str = "Unknown"
    homepage: str = ""
    icon_bytes: Optional[bytes] = None
    icon_path: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    size_bytes: int = 0
    requires_root: bool = False
    target_destination: str = ""
    can_customize_destination: bool = False
    compatibility_ok: bool = True
    compatibility_reason: str = ""
    sha256: str = ""
    expected_sha256: str = ""
    integrity_verified: bool = False
    integrity_message: str = ""
    content_verified: bool = False
    extra_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InstalledApp:
    id: str
    name: str
    version: str
    format: str
    file_path: str
    launcher_path: str = ""
    icon_path: str = ""
    install_date: str = ""
    source_url: str = ""
    update_type: str = "none"  # "github", "flatpak", "package_manager", "none"
    update_identifier: str = ""
    scope: str = "user"  # "user" or "system"
    last_update_check: str = ""
    update_available: bool = False
    latest_version: str = ""
    launch_command: str = ""


@dataclass
class InstallResult:
    success: bool
    message: str
    app_id: Optional[str] = None
    installed_path: Optional[str] = None
    launcher_path: Optional[str] = None
    launch_command: Optional[str] = None
    icon_path: Optional[str] = None
    error_details: Optional[str] = None


@dataclass
class UpdateCheckResult:
    app_id: str
    current_version: str
    latest_version: str
    update_available: bool
    download_url: Optional[str] = None
    changelog: Optional[str] = None
    message: str = ""
