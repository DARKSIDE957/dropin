"""
Linux distribution and environment detection.
"""

import os
import platform
import shutil
from typing import Dict, List, Optional
from dropin.core.models import DistributionInfo


def _read_os_release() -> Dict[str, str]:
    """Parse /etc/os-release or /usr/lib/os-release."""
    data: Dict[str, str] = {}
    paths = ["/etc/os-release", "/usr/lib/os-release"]
    for path in paths:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            data[k] = v
                break
            except Exception:
                pass
    return data


def detect_architecture() -> str:
    """Return normalized system CPU architecture."""
    arch = platform.machine().lower()
    if arch in ["x86_64", "amd64"]:
        return "x86_64"
    elif arch in ["aarch64", "arm64"]:
        return "aarch64"
    elif arch in ["armv7l", "armhf", "arm"]:
        return "armv7l"
    elif arch in ["i386", "i686", "x86"]:
        return "i686"
    return arch


def detect_distribution() -> DistributionInfo:
    """Inspect and return current distribution details."""
    data = _read_os_release()
    distro_id = data.get("ID", "linux").lower()
    name = data.get("PRETTY_NAME", data.get("NAME", "Linux Desktop"))
    version = data.get("VERSION_ID", data.get("VERSION", "unknown"))
    
    id_like_str = data.get("ID_LIKE", "")
    id_like = [x.strip().lower() for x in id_like_str.split()] if id_like_str else []

    arch = detect_architecture()

    return DistributionInfo(
        id=distro_id,
        name=name,
        version=version,
        id_like=id_like,
        arch=arch,
        has_apt=shutil.which("apt") is not None or shutil.which("apt-get") is not None,
        has_dpkg=shutil.which("dpkg") is not None,
        has_dnf=shutil.which("dnf") is not None,
        has_rpm=shutil.which("rpm") is not None,
        has_zypper=shutil.which("zypper") is not None,
        has_pacman=shutil.which("pacman") is not None,
        has_flatpak=shutil.which("flatpak") is not None,
        has_pkexec=shutil.which("pkexec") is not None,
    )


# Singleton for fast reuse
_CURRENT_DISTRO: Optional[DistributionInfo] = None


def get_current_distribution() -> DistributionInfo:
    global _CURRENT_DISTRO
    if _CURRENT_DISTRO is None:
        _CURRENT_DISTRO = detect_distribution()
    return _CURRENT_DISTRO
