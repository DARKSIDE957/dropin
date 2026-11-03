"""Version comparison and normalization helpers shared by registry, handlers, and update manager."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from packaging import version as pkg_version


_ARCH_PATTERNS = re.compile(
    r"[-_](?:x86_64|x86|amd64|aarch64|arm64|armv7l|armhf|i686|i386|noarch|all)\b",
    re.IGNORECASE,
)
_EXT_PATTERNS = re.compile(
    r"\.(?:appimage|tar\.gz|tar\.xz|tar\.bz2|tgz|zip|deb|rpm|flatpak|flatpakref|snap)$",
    re.IGNORECASE,
)
_PREFIX_PATTERNS = re.compile(
    r"^(?:version[-_.]?|release[-_.]?|rel[-_.]?|v\.|v)",
    re.IGNORECASE,
)


def clean_display_version(value: str) -> str:
    """Format a version string cleanly for UI badges without double 'v' prefixes."""
    text = (value or "").strip()
    if not text:
        return ""
    # Strip any duplicated leading 'v's (e.g. 'vv1.2.3' -> 'v1.2.3')
    cleaned = re.sub(r"^[vV]+", "v", text)
    if not cleaned.startswith("v") and cleaned[0].isdigit():
        return f"v{cleaned}"
    return cleaned


def extract_semantic_version(text: str) -> Optional[str]:
    """
    Extract a clean semantic or numeric version string from a filename, tag, or text.
    Handles semver (1.2.3), extended semver (2024.2.1.12), pre-releases (1.0.0-beta.1),
    and date versions (2024.11.03), while stripping architecture and package extensions.
    """
    if not text:
        return None
    raw = text.strip()
    # Strip known archive/package extension first
    raw = _EXT_PATTERNS.sub("", raw)
    # Strip trailing architecture indicators
    raw = _ARCH_PATTERNS.sub("", raw)

    # 1. Match standard semver with optional pre-release (e.g., 4.3.0, 1.1.9, 1.0.0-rc2)
    semver_match = re.search(
        r"(?:^|[-_vV])(\d+\.\d+(?:\.\d+)+(?:[-._]?(?:alpha|beta|rc|preview|pre|patch|dev)\d*)?)",
        raw,
        re.IGNORECASE,
    )
    if semver_match:
        return semver_match.group(1)

    # 2. Match two-part numeric version (e.g., 26.8)
    two_part = re.search(r"(?:^|[-_vV])(\d+\.\d+)(?:[-_.]|$)", raw)
    if two_part:
        return two_part.group(1)

    # 3. Match calendar/date version (e.g., 20261028 or 2026-10-28)
    date_match = re.search(r"(?:^|[-_vV])((?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2})", raw)
    if date_match:
        return date_match.group(1).replace("-", ".").replace("_", ".")

    return None


def normalize_version(value: str) -> str:
    """Strip common prefixes and trailing arch/extensions so versions compare accurately."""
    text = (value or "").strip()
    if not text:
        return ""
    # Strip extensions and arch
    text = _EXT_PATTERNS.sub("", text)
    text = _ARCH_PATTERNS.sub("", text)
    # Strip common prefixes like 'v', 'release-'
    text = _PREFIX_PATTERNS.sub("", text)
    return text.strip()


def _to_numeric_tuple(ver_str: str) -> Optional[Tuple[int, ...]]:
    """Convert a dotted version string into a numeric tuple for comparison."""
    norm = normalize_version(ver_str)
    # Find initial numeric segments (e.g. 2024.2.1)
    parts = re.findall(r"\d+", norm)
    if not parts:
        return None
    try:
        return tuple(int(p) for p in parts)
    except Exception:
        return None


def is_newer_version(latest: str, current: str) -> bool:
    """
    Return True if latest is strictly newer than current.
    Uses multi-tier comparison: PEP 440 packaging parser -> numeric tuple comparator.
    Never returns True on simple string inequality when versions cannot be parsed.
    """
    latest_n = normalize_version(latest)
    current_n = normalize_version(current)
    if not latest_n or not current_n:
        return False
    if latest_n.lower() == current_n.lower():
        return False

    # 1. Try standard PEP 440 comparison
    try:
        parsed_latest = pkg_version.parse(latest_n)
        parsed_current = pkg_version.parse(current_n)
        if parsed_latest != parsed_current:
            return parsed_latest > parsed_current
    except Exception:
        pass

    # 2. Fall back to numeric tuple comparison
    t_latest = _to_numeric_tuple(latest_n)
    t_current = _to_numeric_tuple(current_n)
    if t_latest and t_current:
        # Pad shorter tuple with zeros
        max_len = max(len(t_latest), len(t_current))
        padded_latest = t_latest + (0,) * (max_len - len(t_latest))
        padded_current = t_current + (0,) * (max_len - len(t_current))
        if padded_latest != padded_current:
            return padded_latest > padded_current

    # If completely unparseable, do not falsely claim an update
    return False
