"""
Secure, asynchronous streaming file downloader for Dropin.

Validates URLs (including redirect targets), prefers HTTPS, computes SHA-256,
and verifies package magic bytes — not just file size.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from dropin.core.config import get_config
from dropin.core.models import PackageFormat
from dropin.core.security import (
    normalize_sha256,
    validate_final_url,
    validate_url,
    verify_package_magic,
    verify_sha256,
)


class DownloadWorker(QObject):
    progress = Signal(int, float, int, int)  # percent, speed_kB_s, downloaded, total
    finished = Signal(str, str, str)  # temp_file_path, filename, sha256
    error = Signal(str)

    def __init__(
        self,
        url: str,
        suggested_filename: Optional[str] = None,
        expected_sha256: Optional[str] = None,
        expected_format: Optional[PackageFormat] = None,
        resume_path: Optional[Path] = None,
    ):
        super().__init__()
        self.url = url
        self.suggested_filename = suggested_filename
        self.expected_sha256 = normalize_sha256(expected_sha256 or "") or None
        self.expected_format = expected_format
        self._is_cancelled = False
        self._temp_path: Optional[Path] = None
        # Optional path to an existing partial download to resume into.
        self.resume_path = resume_path

    def cancel(self) -> None:
        self._is_cancelled = True
        if self._temp_path and self._temp_path.is_file():
            try:
                self._temp_path.unlink()
            except Exception:
                pass

    def run(self) -> None:
        cfg = get_config()
        require_https = bool(cfg.get("require_https", True))
        verify_content = bool(cfg.get("verify_package_content", True))
        verify_digest = bool(cfg.get("verify_release_digest", True))
        max_size_mb = int(cfg.get("max_download_size_mb", 32768))
        max_bytes = max_size_mb * 1024 * 1024

        is_valid, reason = validate_url(self.url, require_https=require_https)
        if not is_valid:
            self.error.emit(f"Security validation failed: {reason}")
            return

        # Retry transient network errors (DNS, connect, timeouts, 5xx).
        last_error = ""
        for attempt in range(3):
            try:
                self._attempt_download(
                    attempt,
                    require_https,
                    verify_content,
                    verify_digest,
                    max_bytes,
                    max_size_mb,
                )
                return  # success
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404, 429):
                    self.error.emit(f"HTTP Error {e.code}: {e.reason}")
                    return
                last_error = f"HTTP Error {e.code}: {e.reason}"
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                self.error.emit(last_error)
                return
            except urllib.error.URLError as e:
                last_error = f"Connection failed: {e.reason}"
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                self.error.emit(last_error)
                return
            except Exception as e:
                last_error = f"Download failed: {str(e)}"
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                self.error.emit(last_error)
                return

    def _attempt_download(
        self,
        attempt: int,
        require_https: bool,
        verify_content: bool,
        verify_digest: bool,
        max_bytes: int,
        max_size_mb: int = 32768,
    ) -> None:
        import urllib.request

        headers = {
            "User-Agent": "Dropin-Linux-Installer/1.0 (+https://github.com/DARKSIDE957/dropin)",
            "Accept": "*/*",
        }

        # Resume support: if resuming into an existing partial file, send a Range header.
        resume_from = 0
        if self.resume_path and self.resume_path.is_file():
            resume_from = self.resume_path.stat().st_size
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"

        req = urllib.request.Request(self.url, headers=headers)

        with urllib.request.urlopen(req, timeout=45) as response:
            status = response.getstatus()
            if status not in (200, 206):
                raise urllib.error.HTTPError(self.url, status, f"HTTP {status}", response.headers, None)

            final_url = response.geturl()
            ok_redir, redir_msg = validate_final_url(
                self.url, final_url, require_https=require_https
            )
            if not ok_redir:
                self.error.emit(f"Security validation failed: {redir_msg}")
                return

            # Resume only counts if the server honoured the Range request
            # (206). A 200 means it sent the whole file again — appending
            # that to the partial would corrupt the download.
            if resume_from > 0 and status != 206:
                resume_from = 0

            content_len = response.headers.get("Content-Length")
            total_bytes = int(content_len) if content_len and content_len.isdigit() else 0
            total_bytes += resume_from

            if total_bytes > max_bytes:
                self.error.emit(
                    f"Download size ({total_bytes // (1024 * 1024)} MB) exceeds "
                    f"the disk-safety limit of {max_size_mb} MB "
                    f"(Settings → Destinations). Raise the limit if you trust this package."
                )
                return

            filename = self.suggested_filename
            if not filename:
                disp = response.headers.get("Content-Disposition", "")
                if "filename=" in disp:
                    part = disp.split("filename=")[-1].strip().strip('"').strip("'")
                    if part:
                        filename = os.path.basename(part)

            if not filename:
                parsed_path = urllib.parse.urlparse(final_url).path
                filename = os.path.basename(parsed_path) or "downloaded_package"

            if self.resume_path and resume_from > 0 and self.resume_path.is_file():
                self._temp_path = self.resume_path
            else:
                fd, temp_file = tempfile.mkstemp(prefix="dropin_", suffix=f"_{filename}")
                os.close(fd)
                self._temp_path = Path(temp_file)
                self._temp_path.chmod(0o600)

            downloaded = resume_from
            chunk_size = 64 * 1024
            start_time = time.time()
            last_update_time = start_time
            hasher = hashlib.sha256()

            if resume_from > 0 and self._temp_path.is_file():
                with open(self._temp_path, "rb") as f_existing:
                    while True:
                        chunk = f_existing.read(chunk_size)
                        if not chunk:
                            break
                        hasher.update(chunk)

            mode = "ab" if resume_from > 0 else "wb"
            with open(self._temp_path, mode) as f_out:
                while True:
                    if self._is_cancelled:
                        self.error.emit("Download cancelled by user.")
                        return

                    chunk = response.read(chunk_size)
                    if not chunk:
                        break

                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        self.error.emit(
                            f"Download exceeded disk-safety limit of {max_size_mb} MB."
                        )
                        return

                    f_out.write(chunk)
                    hasher.update(chunk)

                    now = time.time()
                    if now - last_update_time >= 0.15:
                        duration = now - start_time
                        speed = (downloaded / 1024.0) / (duration if duration > 0 else 0.001)
                        percent = int((downloaded / total_bytes) * 100) if total_bytes > 0 else 0
                        self.progress.emit(percent, speed, downloaded, total_bytes)
                        last_update_time = now

            sha256 = hasher.hexdigest()

            if verify_digest and self.expected_sha256:
                ok_hash, hash_msg = verify_sha256(self._temp_path, self.expected_sha256)
                if not ok_hash:
                    self.error.emit(hash_msg)
                    return

            if verify_content:
                ok_magic, magic_msg, _detected = verify_package_magic(
                    self._temp_path, self.expected_format
                )
                if not ok_magic:
                    self.error.emit(magic_msg)
                    return

            duration = time.time() - start_time
            speed = (downloaded / 1024.0) / (duration if duration > 0 else 0.001)
            self.progress.emit(100, speed, downloaded, downloaded)
            self.finished.emit(str(self._temp_path), filename, sha256)
