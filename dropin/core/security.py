"""
Security architecture and validation for Dropin.

Focuses on real threats: SSRF, unsafe protocols, path traversal, download
redirect abuse, package content spoofing, and integrity (SHA-256) — not
arbitrary size limits as a substitute for security.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import urllib.parse
from pathlib import Path
from typing import List, Optional, Tuple

from dropin.core.models import PackageFormat


class SecurityError(Exception):
    """Raised when an operation violates Dropin security policy."""
    pass


_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def normalize_sha256(value: str) -> Optional[str]:
    """Return lowercase 64-char hex digest, or None if invalid."""
    if not value:
        return None
    match = _SHA256_RE.match(value.strip())
    if not match:
        return None
    return match.group(1).lower()


def compute_file_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Stream a file and return its SHA-256 hex digest."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(file_path: Path, expected: str) -> Tuple[bool, str]:
    """Compare file digest to an expected SHA-256 (with optional sha256: prefix)."""
    expected_norm = normalize_sha256(expected)
    if not expected_norm:
        return False, "Expected digest is not a valid SHA-256 value."
    actual = compute_file_sha256(file_path)
    if actual != expected_norm:
        return False, (
            f"Integrity check failed. Expected {expected_norm[:12]}…, "
            f"got {actual[:12]}… — the file may be corrupted or tampered with."
        )
    return True, actual


def validate_url(url_str: str, require_https: bool = False) -> Tuple[bool, str]:
    """
    Validate an external download URL.
    Enforces HTTP(S), rejects local file URLs, SSRF targets, loopbacks, and private IPs.
    """
    url_str = (url_str or "").strip()
    if not url_str:
        return False, "URL cannot be empty."

    try:
        parsed = urllib.parse.urlparse(url_str)
    except Exception as e:
        return False, f"Malformed URL format: {e}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("https", "http"):
        return False, f"Unsupported protocol '{parsed.scheme}'. Only HTTPS and HTTP are permitted."

    if require_https and scheme != "https":
        return False, (
            "Cleartext HTTP is blocked. Enable only trusted HTTPS sources "
            "(Settings → Security), or use an https:// URL."
        )

    hostname = parsed.hostname
    if not hostname:
        return False, "URL does not specify a valid host."

    lower_host = hostname.lower()
    if lower_host in ("localhost", "localhost.localdomain", "broadcasthost", "metadata", "metadata.google.internal"):
        return False, "Access to localhost or cloud metadata hosts is prohibited."

    try:
        ip_obj = ipaddress.ip_address(hostname)
        if (
            ip_obj.is_loopback
            or ip_obj.is_private
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            return False, f"Access to private or local network address ({hostname}) is forbidden."
    except ValueError:
        try:
            resolved_ips = socket.getaddrinfo(hostname, None)
            for item in resolved_ips:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                if (
                    ip_obj.is_loopback
                    or ip_obj.is_private
                    or ip_obj.is_link_local
                    or ip_obj.is_reserved
                    or ip_obj.is_unspecified
                ):
                    return False, (
                        f"Hostname '{hostname}' resolves to private address ({ip_str}), "
                        "which is blocked for security."
                    )
        except socket.gaierror:
            pass

    return True, "URL is valid."


def validate_final_url(original_url: str, final_url: str, require_https: bool = False) -> Tuple[bool, str]:
    """Re-validate the URL after HTTP redirects (prevents redirect-to-SSRF)."""
    ok, msg = validate_url(final_url, require_https=require_https)
    if not ok:
        return False, f"Redirect target blocked: {msg}"

    try:
        orig = urllib.parse.urlparse(original_url)
        final = urllib.parse.urlparse(final_url)
        if (orig.scheme or "").lower() == "https" and (final.scheme or "").lower() != "https":
            return False, "HTTPS download redirected to insecure HTTP — blocked."
    except Exception:
        pass

    return True, "Redirect target is valid."


def verify_package_magic(file_path: Path, expected_format: Optional[PackageFormat] = None) -> Tuple[bool, str, Optional[PackageFormat]]:
    """
    Verify the file content matches a real package format (not HTML/phishing pages).
    Returns (ok, message, detected_format).
    """
    if not file_path.is_file():
        return False, "Downloaded path is not a file.", None

    try:
        size = file_path.stat().st_size
    except OSError as e:
        return False, f"Cannot read file: {e}", None

    if size < 4:
        return False, "File is too small to be a valid package.", None

    with open(file_path, "rb") as handle:
        header = handle.read(512)

    # Reject obvious non-packages (HTML error pages, JSON API errors, etc.)
    head_lower = header[:64].lstrip().lower()
    if head_lower.startswith(b"<!doctype") or head_lower.startswith(b"<html") or head_lower.startswith(b"<html"):
        return False, "Download looks like an HTML page, not a package. Installation blocked.", None
    if head_lower.startswith(b"{") and b"\"message\"" in header[:200]:
        return False, "Download looks like an API error response, not a package.", None

    detected: Optional[PackageFormat] = None
    name = file_path.name.lower()

    if header.startswith(b"\x7fELF"):
        # ELF: AppImage or portable binary (often shipped as .AppImage)
        if name.endswith(".appimage") or b"AppImage" in header or b"AI\x02" in header[:32]:
            detected = PackageFormat.APPIMAGE
        else:
            detected = PackageFormat.APPIMAGE if "appimage" in name else PackageFormat.ARCHIVE
    elif header.startswith(b"!<arch>\n"):
        detected = PackageFormat.DEB
    elif header.startswith(b"\xed\xab\xee\xdb"):
        detected = PackageFormat.RPM
    elif header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06"):
        if name.endswith(".flatpak"):
            detected = PackageFormat.FLATPAK
        else:
            detected = PackageFormat.ARCHIVE
    elif header.startswith(b"\x1f\x8b") or header.startswith(b"\xfd7zXZ\x00") or header.startswith(b"BZh"):
        detected = PackageFormat.ARCHIVE
    elif b"[Flatpak Ref]" in header[:200] or name.endswith(".flatpakref"):
        detected = PackageFormat.FLATPAK
    else:
        # Extension fallback only when content is ambiguous but not clearly hostile
        detected = PackageFormat.from_extension(file_path.name)
        if detected == PackageFormat.UNKNOWN:
            return False, (
                "File content does not match a known Linux package format "
                "(AppImage/ELF, DEB, RPM, Flatpak, or archive). Installation blocked."
            ), None

    if expected_format and expected_format != PackageFormat.UNKNOWN and detected != expected_format:
        # Allow ARCHIVE vs APPIMAGE ambiguity for ELF payloads
        loose = {
            (PackageFormat.APPIMAGE, PackageFormat.ARCHIVE),
            (PackageFormat.ARCHIVE, PackageFormat.APPIMAGE),
        }
        if (expected_format, detected) not in loose:
            return False, (
                f"File type mismatch: expected {expected_format.value}, "
                f"detected {detected.value}. Installation blocked."
            ), detected

    return True, f"Package content verified as {detected.value}.", detected


def is_safe_extract_path(dest_dir: Path, target_path: Path) -> bool:
    """Ensure that the resolved target path lies strictly inside the destination directory."""
    try:
        resolved_dest = dest_dir.resolve()
        resolved_target = target_path.resolve()
        return resolved_dest in resolved_target.parents or resolved_target == resolved_dest
    except Exception:
        return False


def validate_archive_members(member_names: List[str], dest_dir: Path) -> Tuple[bool, str]:
    """
    Check archive member paths for traversal (e.g. '../') and absolute paths.
    """
    dest_path = dest_dir.resolve()
    for name in member_names:
        if os.path.isabs(name) or name.startswith("/") or name.startswith("\\"):
            return False, f"Archive contains unsafe absolute path: {name}"

        target = (dest_path / name).resolve()
        if not is_safe_extract_path(dest_path, target):
            return False, f"Archive contains unsafe path traversal sequence: {name}"

    return True, "Archive paths verified safe."


def secure_file_permissions(file_path: str, is_executable: bool = True) -> None:
    """Apply secure file permissions (0755 for executables, 0644 for normal files)."""
    try:
        mode = 0o755 if is_executable else 0o644
        os.chmod(file_path, mode)
    except Exception:
        pass
