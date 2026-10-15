"""Version comparison helpers shared by registry and update manager."""

from packaging import version as pkg_version


def normalize_version(value: str) -> str:
    """Strip common prefixes so v1.2.3 and 1.2.3 compare equal."""
    text = (value or "").strip()
    if text.lower().startswith("v") and len(text) > 1 and text[1].isdigit():
        return text[1:]
    return text


def is_newer_version(latest: str, current: str) -> bool:
    """Return True if latest is a newer release than current."""
    latest_n = normalize_version(latest)
    current_n = normalize_version(current)
    if not latest_n or not current_n:
        return bool(latest_n and latest_n != current_n)
    try:
        return pkg_version.parse(latest_n) > pkg_version.parse(current_n)
    except Exception:
        return latest_n != current_n
