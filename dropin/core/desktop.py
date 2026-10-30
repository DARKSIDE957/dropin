"""
Desktop integration and system cache updating helpers for Dropin.
Ensures application menus (KDE Plasma, GNOME, XFCE) and icon caches refresh
immediately after installing or uninstalling an application.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from dropin.core.logger import get_logger


def update_desktop_caches() -> None:
    """
    Refresh all desktop application databases, icon caches, and DE menus (KDE sycoca, XDG).
    """
    logger = get_logger()
    home = Path.home()
    user_apps = str(home / ".local" / "share" / "applications")
    user_icons = str(home / ".local" / "share" / "icons" / "hicolor")

    # 1. Standard XDG desktop database
    if shutil.which("update-desktop-database"):
        try:
            if os.path.isdir(user_apps):
                subprocess.run(
                    ["update-desktop-database", user_apps],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
        except Exception as e:
            logger.debug(f"update-desktop-database error: {e}")

    # 2. KDE Plasma sycoca cache (Crucial for Bazzite / Kinoite / KDE Plasma desktops)
    for sycoca_bin in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(sycoca_bin):
            try:
                subprocess.run(
                    [sycoca_bin, "--noincremental"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=6,
                )
                break
            except Exception as e:
                logger.debug(f"{sycoca_bin} error: {e}")

    # 3. GTK / XDG Icon Cache
    if shutil.which("gtk-update-icon-cache"):
        if os.path.isdir(user_icons):
            try:
                subprocess.run(
                    ["gtk-update-icon-cache", "-f", "-t", "-q", user_icons],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception as e:
                logger.debug(f"gtk-update-icon-cache error: {e}")

