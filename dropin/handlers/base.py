"""
Base class for package handlers in Dropin.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Callable

from dropin.core.models import AppPackageInfo, InstalledApp, InstallResult, UpdateCheckResult, PackageFormat


class BaseHandler(ABC):
    """Abstract base handler for an application packaging format."""

    format: PackageFormat = PackageFormat.UNKNOWN

    def handles_format(self, format_name: str) -> bool:
        """Return True if this handler owns the given installed-app format string."""
        return (format_name or "").strip().lower() == self.format.value.lower()

    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Return True if this handler can process the given file."""
        pass

    @abstractmethod
    def inspect(self, file_path: Path) -> AppPackageInfo:
        """Inspect and parse package metadata without installing it."""
        pass

    @abstractmethod
    def install(
        self,
        info: AppPackageInfo,
        dest_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> InstallResult:
        """Install the package and return result."""
        pass

    @abstractmethod
    def uninstall(self, app: InstalledApp) -> bool:
        """Safely uninstall the application."""
        pass

    def check_update(self, app: InstalledApp) -> Optional[UpdateCheckResult]:
        """Check for updates if a supported update mechanism exists."""
        return None

    def can_launch(self, app: InstalledApp) -> bool:
        """Check if application has a valid launch command or binary."""
        return bool(app.launch_command or (app.file_path and Path(app.file_path).is_file()))

    def launch(self, app: InstalledApp) -> bool:
        """Launch the application."""
        import subprocess
        try:
            if app.launch_command:
                # Use shlex or direct exec
                import shlex
                cmd = shlex.split(app.launch_command)
                subprocess.Popen(cmd, start_new_session=True)
                return True
            elif app.file_path and Path(app.file_path).is_file():
                subprocess.Popen([str(app.file_path)], start_new_session=True)
                return True
        except Exception:
            return False
        return False
