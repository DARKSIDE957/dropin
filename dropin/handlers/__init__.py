"""
Handler registry and format dispatcher for Dropin.
"""

from pathlib import Path
from typing import List, Optional

from dropin.core.distro import get_current_distribution
from dropin.core.models import AppPackageInfo, PackageFormat
from dropin.handlers.base import BaseHandler
from dropin.handlers.appimage import AppImageHandler
from dropin.handlers.deb import DebHandler
from dropin.handlers.rpm import RpmHandler
from dropin.handlers.flatpak import FlatpakHandler
from dropin.handlers.archive import ArchiveHandler
from dropin.handlers.snap import SnapHandler
from dropin.handlers.system_pkg import SystemPkgHandler


_HANDLERS: Optional[List[BaseHandler]] = None


def get_handlers() -> List[BaseHandler]:
    global _HANDLERS
    if _HANDLERS is None:
        _HANDLERS = [
            AppImageHandler(),
            DebHandler(),
            RpmHandler(),
            FlatpakHandler(),
            ArchiveHandler(),
            SnapHandler(),
            SystemPkgHandler(),
        ]
    return _HANDLERS


def get_handler_for_file(file_path: Path) -> Optional[BaseHandler]:
    for handler in get_handlers():
        if handler.can_handle(file_path):
            return handler
    return None


def detect_and_inspect(file_path: Path) -> AppPackageInfo:
    handler = get_handler_for_file(file_path)
    if handler:
        return handler.inspect(file_path)

    # Unknown file format
    distro = get_current_distribution()
    return AppPackageInfo(
        name=file_path.name,
        version="unknown",
        format=PackageFormat.UNKNOWN,
        architecture=distro.arch,
        file_path=str(file_path),
        description="Unsupported application package format.",
        compatibility_ok=False,
        compatibility_reason=(
            f"The file '{file_path.name}' is not in a supported format. "
            "Dropin supports AppImage (.AppImage), Debian packages (.deb), "
            "RPM packages (.rpm), Flatpak references (.flatpakref/.flatpak), "
            "portable archives (.tar.gz, .tar.xz, .zip), and Snap packages (.snap)."
        )
    )
