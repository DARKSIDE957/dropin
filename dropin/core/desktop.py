"""
Desktop integration, launcher validation, icon management, and system cache
updating helpers for Dropin.
Ensures application menus (KDE Plasma, GNOME, XFCE), task managers, and icon
caches work reliably after installing, repairing, or uninstalling an application.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from dropin.core.logger import get_logger
from dropin.core.security import secure_file_permissions


def sanitize_desktop_field(value: str) -> str:
    """Strip control characters and newlines from desktop entry values."""
    if not value:
        return ""
    cleaned = re.sub(r"[\r\n\x00-\x1f]+", " ", str(value)).strip()
    return cleaned


def quote_exec_path(exec_path: Path | str, extra_args: str = "") -> str:
    """Safely quote an executable path for a Freedesktop Exec= field."""
    raw = str(exec_path).strip().strip('"')
    escaped = raw.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    quoted = f'"{escaped}"'
    if extra_args:
        clean_args = sanitize_desktop_field(extra_args)
        if clean_args:
            return f"{quoted} {clean_args}"
    return quoted


def is_dropin_own_icon(icon_path: Optional[str | Path]) -> bool:
    """
    Return True if the given icon file is actually a copy of Dropin's own
    application icon (`io.dropin.Dropin.svg`), which was previously used by
    mistake as a fallback for unrelated third-party applications.
    """
    if not icon_path:
        return False
    p = Path(icon_path)
    if not p.is_file():
        return False
    if p.name == "io.dropin.Dropin.svg":
        return True
    dropin_svg = Path(__file__).resolve().parent.parent / "assets" / "io.dropin.Dropin.svg"
    if not dropin_svg.is_file():
        return False
    try:
        if p.stat().st_size == dropin_svg.stat().st_size:
            h1 = hashlib.sha256(p.read_bytes()).hexdigest()
            h2 = hashlib.sha256(dropin_svg.read_bytes()).hexdigest()
            if h1 == h2:
                return True
        content = p.read_text(encoding="utf-8", errors="ignore")
        if "g_bg" in content and "#0ea5e9" in content and "#2563eb" in content and "M32 16v20" in content:
            return True
    except Exception:
        pass
    return False


def detect_image_format(data: bytes) -> Optional[Tuple[str, Optional[Tuple[int, int]]]]:
    """
    Inspect raw image bytes and return (extension, (width, height) or None).
    Supports PNG, SVG, XPM, and ICO.
    """
    if not data or len(data) < 32:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        import struct

        try:
            w, h = struct.unpack(">II", data[16:24])
            if 1 <= w <= 4096 and 1 <= h <= 4096:
                return (".png", (w, h))
        except Exception:
            pass
        return (".png", None)

    head_lower = data[:1024].lower()
    if b"<svg" in head_lower:
        return (".svg", None)
    if data.startswith(b"/* XPM */"):
        return (".xpm", None)
    if data.startswith(b"\x00\x00\x01\x00"):
        return (".ico", None)
    return None


def save_application_icon(
    app_id: str,
    icon_bytes: Optional[bytes] = None,
    source_icon_path: Optional[Path | str] = None,
) -> Optional[str]:
    """
    Persist an application's own icon into the user's XDG hicolor icon theme
    directory and return the installed icon file path.
    Never falls back to Dropin's own icon.
    """
    raw_bytes = icon_bytes
    if not raw_bytes and source_icon_path:
        src = Path(source_icon_path)
        if src.is_file() and not is_dropin_own_icon(src):
            try:
                raw_bytes = src.read_bytes()
            except Exception:
                raw_bytes = None

    if not raw_bytes:
        return None

    # Guard against accidentally saving Dropin's own icon bytes for another app
    if app_id != "io.dropin.Dropin":
        dropin_svg = Path(__file__).resolve().parent.parent / "assets" / "io.dropin.Dropin.svg"
        if dropin_svg.is_file():
            try:
                if raw_bytes == dropin_svg.read_bytes():
                    return None
            except Exception:
                pass

    fmt_info = detect_image_format(raw_bytes)
    if not fmt_info:
        return None

    ext, dims = fmt_info
    base_hicolor = Path.home() / ".local" / "share" / "icons" / "hicolor"

    # Remove any stale icons for this app_id across hicolor subdirs first
    remove_application_icons(app_id)

    if ext == ".svg":
        target_dir = base_hicolor / "scalable" / "apps"
    elif ext == ".png" and dims:
        w, h = dims
        standard_sizes = (16, 22, 24, 32, 48, 64, 96, 128, 256, 512)
        if w == h and w in standard_sizes:
            size_dir = f"{w}x{h}"
        elif max(w, h) >= 384:
            size_dir = "512x512"
        elif max(w, h) >= 192:
            size_dir = "256x256"
        else:
            size_dir = "128x128"
        target_dir = base_hicolor / size_dir / "apps"
    else:
        target_dir = base_hicolor / "128x128" / "apps"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_icon = target_dir / f"{app_id}{ext}"
        target_icon.write_bytes(raw_bytes)
        secure_file_permissions(str(target_icon), is_executable=False)

        # Also place a copy in 128x128/apps if a larger PNG was saved so
        # legacy panels/taskbars looking only in 128x128 or hicolor find it.
        if ext == ".png" and target_dir.name != "128x128":
            compat_dir = base_hicolor / "128x128" / "apps"
            compat_dir.mkdir(parents=True, exist_ok=True)
            compat_icon = compat_dir / f"{app_id}{ext}"
            try:
                compat_icon.write_bytes(raw_bytes)
                secure_file_permissions(str(compat_icon), is_executable=False)
            except Exception:
                pass

        return str(target_icon)
    except Exception as e:
        get_logger().warning("Failed to save icon for %s: %s", app_id, e)
        return None


def remove_application_icons(app_id: str) -> None:
    """Remove all Dropin-installed icon files for `app_id` across hicolor."""
    if not app_id or app_id == "io.dropin.Dropin":
        return
    base_hicolor = Path.home() / ".local" / "share" / "icons" / "hicolor"
    if not base_hicolor.is_dir():
        return
    for ext in (".png", ".svg", ".xpm", ".ico"):
        for candidate in base_hicolor.glob(f"*/apps/{app_id}{ext}"):
            if candidate.is_file():
                try:
                    candidate.unlink()
                except Exception:
                    pass


def write_desktop_entry(
    app_id: str,
    name: str,
    exec_path: Path | str,
    icon_path: Optional[str] = None,
    comment: str = "",
    generic_name: str = "",
    categories: str = "Utility;",
    startup_wm_class: str = "",
    mime_types: str = "",
    terminal: bool = False,
    extra_exec_args: str = "",
) -> Optional[Path]:
    """
    Create a validated Freedesktop `.desktop` file in `~/.local/share/applications`.
    Ensures safe quoting, sanitized fields, valid Icon reference, and StartupWMClass
    for KDE Plasma / Wayland task manager window-to-icon association.
    """
    launchers_dir = Path.home() / ".local" / "share" / "applications"
    launchers_dir.mkdir(parents=True, exist_ok=True)
    launcher_path = launchers_dir / f"{app_id}.desktop"

    clean_name = sanitize_desktop_field(name) or "Application"
    clean_generic = sanitize_desktop_field(generic_name or clean_name)
    clean_comment = sanitize_desktop_field(comment or f"{clean_name} Application")
    clean_cats = sanitize_desktop_field(categories) or "Utility;"
    if not clean_cats.endswith(";"):
        clean_cats += ";"

    # Validate icon: never reference a non-existent path or Dropin's own icon
    resolved_icon = "application-x-executable"
    if icon_path:
        clean_icon = sanitize_desktop_field(icon_path)
        p_icon = Path(clean_icon)
        if p_icon.is_absolute():
            if p_icon.is_file() and (app_id == "io.dropin.Dropin" or not is_dropin_own_icon(p_icon)):
                resolved_icon = str(p_icon)
        elif clean_icon and clean_icon != "io.dropin.Dropin":
            resolved_icon = clean_icon

    exec_str = quote_exec_path(exec_path, extra_args=extra_exec_args)
    term_str = "true" if terminal else "false"

    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={clean_name}",
        f"GenericName={clean_generic}",
        f"Comment={clean_comment}",
        f"Exec={exec_str}",
        f"Icon={resolved_icon}",
        f"Terminal={term_str}",
        f"Categories={clean_cats}",
        "StartupNotify=true",
    ]

    clean_wm = sanitize_desktop_field(startup_wm_class)
    if clean_wm:
        lines.append(f"StartupWMClass={clean_wm}")

    clean_mime = sanitize_desktop_field(mime_types)
    if clean_mime:
        if not clean_mime.endswith(";"):
            clean_mime += ";"
        lines.append(f"MimeType={clean_mime}")

    lines.append("X-Dropin-Managed=true")
    content = "\n".join(lines) + "\n"

    try:
        temp_launcher = launcher_path.with_suffix(".desktop.tmp")
        temp_launcher.write_text(content, encoding="utf-8")
        secure_file_permissions(str(temp_launcher), is_executable=True)
        temp_launcher.replace(launcher_path)
        secure_file_permissions(str(launcher_path), is_executable=True)
        update_desktop_caches()
        return launcher_path
    except Exception as e:
        get_logger().error(f"Failed to write desktop launcher {launcher_path}: {e}")
        return None


def parse_desktop_entry_file(launcher_path: Path) -> Dict[str, str]:
    """Read key-value fields from `[Desktop Entry]` of an existing `.desktop` file."""
    data: Dict[str, str] = {}
    if not launcher_path.is_file():
        return data
    try:
        in_entry = False
        for raw_line in launcher_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if line == "[Desktop Entry]":
                in_entry = True
                continue
            if line.startswith("[") and line.endswith("]"):
                in_entry = False
                continue
            if in_entry and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    except Exception:
        pass
    return data


def cleanup_obsolete_dropin_launchers(valid_exec_paths: Optional[set[str]] = None) -> int:
    """
    Scan `~/.local/share/applications/dropin-*.desktop` for broken launchers
    whose `Exec=` binary no longer exists on disk, and remove them.
    """
    launchers_dir = Path.home() / ".local" / "share" / "applications"
    if not launchers_dir.is_dir():
        return 0
    removed = 0
    for desktop_file in launchers_dir.glob("dropin-*.desktop"):
        if not desktop_file.is_file():
            continue
        fields = parse_desktop_entry_file(desktop_file)
        if fields.get("X-Dropin-Managed", "").lower() != "true":
            continue
        exec_val = fields.get("Exec", "").strip()
        if not exec_val:
            continue
        # Extract binary path from Exec="path" or Exec=path
        if exec_val.startswith('"'):
            end_q = exec_val.find('"', 1)
            bin_str = exec_val[1:end_q] if end_q != -1 else exec_val.strip('"')
        else:
            bin_str = exec_val.split()[0]
        bin_str = bin_str.replace('\\"', '"').replace("\\\\", "\\")
        if bin_str.startswith("/") and not Path(bin_str).exists():
            if valid_exec_paths is None or bin_str not in valid_exec_paths:
                try:
                    desktop_file.unlink()
                    removed += 1
                except Exception:
                    pass
    if removed > 0:
        update_desktop_caches()
    return removed


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

    # 2. GTK / XDG Icon Cache (run before kbuildsycoca so icon index is fresh)
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

    # 3. KDE Plasma sycoca cache (Crucial for Bazzite / Kinoite / KDE Plasma desktops)
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


