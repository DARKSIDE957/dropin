"""
Configuration and settings management for Dropin.
Complies with the XDG Base Directory Specification.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "appimage_dir": str(Path.home() / "Applications"),
    "portable_dir": str(Path.home() / ".local" / "share" / "dropin" / "portable"),
    "check_updates_on_startup": True,
    "background_update_check": False,
    "update_check_interval_hours": 24,
    "notify_updates": True,
    "confirm_installations": True,
    # Disk safety only (not a security control). Large modern packages are allowed.
    "max_download_size_mb": 32768,
    "require_https": True,
    "verify_package_content": True,
    "verify_release_digest": True,
    "flatpak_scope": "user",  # "user" or "system"
    "autostart": False,
}


class ConfigManager:
    def __init__(self, config_dir: Path = None):
        if config_dir is None:
            xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config_home:
                self.config_dir = Path(xdg_config_home) / "dropin"
            else:
                self.config_dir = Path.home() / ".config" / "dropin"
        else:
            self.config_dir = config_dir

        self.config_file = self.config_dir / "settings.json"
        self._data: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        """Load settings from disk or initialize with defaults."""
        if not self.config_file.is_file():
            self._data = dict(DEFAULT_CONFIG)
            self.save()
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    # Merge defaults with saved values for forward compatibility
                    merged = dict(DEFAULT_CONFIG)
                    merged.update(saved)
                    self._data = merged
                else:
                    self._data = dict(DEFAULT_CONFIG)
        except Exception:
            # Corrupted file, fallback safely
            self._data = dict(DEFAULT_CONFIG)

    def save(self) -> bool:
        """Save current configuration to disk."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            temp_file = self.config_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            temp_file.replace(self.config_file)
            return True
        except Exception:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULT_CONFIG.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def reset_defaults(self) -> None:
        self._data = dict(DEFAULT_CONFIG)
        self.save()

    @property
    def appimage_dir(self) -> Path:
        p = Path(os.path.expanduser(self.get("appimage_dir", DEFAULT_CONFIG["appimage_dir"])))
        return p

    @property
    def portable_dir(self) -> Path:
        p = Path(os.path.expanduser(self.get("portable_dir", DEFAULT_CONFIG["portable_dir"])))
        return p


_CONFIG_INSTANCE = None


def get_config() -> ConfigManager:
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = ConfigManager()
    return _CONFIG_INSTANCE
