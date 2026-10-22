"""
Download resume support for Dropin.

Supports resuming interrupted downloads via HTTP Range requests, with
integrity verification on completion.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple

from dropin.core.security import validate_url, verify_sha256, verify_package_magic
from dropin.core.models import PackageFormat


def resume_download(
    url: str,
    dest_path: Path,
    expected_sha256: Optional[str] = None,
    expected_format: Optional[PackageFormat] = None,
    chunk_size: int = 64 * 1024,
    timeout: int = 45,
) -> Tuple[bool, str, str]:
    """
    Download a file with resume support.

    Returns (ok, message, sha256_hex).
    """
    import urllib.request
    import urllib.error

    is_valid, reason = validate_url(url)
    if not is_valid:
        return False, f"Security validation failed: {reason}", ""

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # If a partial file exists, resume from where we left off.
    resume_from = 0
    if dest_path.is_file():
        resume_from = dest_path.stat().st_size

    headers = {
        "User-Agent": "Dropin-Linux-Installer/1.0 (+https://github.com/DARKSIDE957/dropin)",
        "Accept": "*/*",
    }
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getstatus()
            if status not in (200, 206):
                return False, f"Unexpected HTTP status {status}", ""

            # Resume only counts if the server honoured the Range request
            # (206). A 200 means it sent the whole file again — appending
            # that to the partial would corrupt the download.
            if resume_from > 0 and status != 206:
                resume_from = 0

            total_bytes = int(response.headers.get("Content-Length", "0") or "0")
            if resume_from > 0:
                total_bytes += resume_from

            mode = "ab" if resume_from > 0 else "wb"
            hasher = hashlib.sha256()
            downloaded = resume_from

            # The returned digest must cover the whole file, not just the
            # resumed tail.
            if resume_from > 0 and dest_path.is_file():
                with open(dest_path, "rb") as f_existing:
                    while True:
                        existing = f_existing.read(chunk_size)
                        if not existing:
                            break
                        hasher.update(existing)

            with open(dest_path, mode) as f_out:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)

            sha256 = hasher.hexdigest()

        # Verify integrity if expected digest provided.
        if expected_sha256:
            ok_hash, hash_msg = verify_sha256(dest_path, expected_sha256)
            if not ok_hash:
                return False, hash_msg, ""

        # Verify package magic bytes.
        if expected_format is not None:
            ok_magic, magic_msg, _ = verify_package_magic(dest_path, expected_format)
            if not ok_magic:
                return False, magic_msg, ""

        return True, "Download complete", sha256

    except urllib.error.HTTPError as e:
        return False, f"HTTP Error {e.code}: {e.reason}", ""
    except urllib.error.URLError as e:
        return False, f"Connection failed: {e.reason}", ""
    except Exception as e:
        return False, f"Download failed: {str(e)}", ""