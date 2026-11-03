"""
Self-update manager for Dropin.
Allows checking for upstream Dropin updates on GitHub and updating the application in-place.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Callable

from PySide6.QtCore import QObject, Signal

from dropin import __version__, __app_name__
from dropin.core.desktop import update_desktop_caches
from dropin.core.logger import get_logger

DROPIN_REPO_OWNER = "DARKSIDE957"
DROPIN_REPO_NAME = "dropin"
DROPIN_GITHUB_API_COMMITS = f"https://api.github.com/repos/{DROPIN_REPO_OWNER}/{DROPIN_REPO_NAME}/commits/main"
DROPIN_GITHUB_API_RELEASES = f"https://api.github.com/repos/{DROPIN_REPO_OWNER}/{DROPIN_REPO_NAME}/releases/latest"
DROPIN_GITHUB_TARBALL = f"https://github.com/{DROPIN_REPO_OWNER}/{DROPIN_REPO_NAME}/archive/refs/heads/main.tar.gz"


def find_local_repo() -> Optional[Path]:
    """Find local git repository for Dropin if running from or beside a clone."""
    # 1. Check parent directory of this module
    here = Path(__file__).resolve()
    # /path/to/dropin/dropin/updater/self_updater.py -> parents[2] is root
    for candidate in [here.parents[2], Path.home() / "dropin", Path.cwd()]:
        if (candidate / ".git").is_dir() and (candidate / "dropin").is_dir() and (candidate / "install.sh").is_file():
            return candidate
    return None


def get_current_commit() -> str:
    """Get the current commit hash of the installed Dropin or git repo."""
    repo = find_local_repo()
    if repo:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass

    # Check commit.txt in installed application folder
    commit_file = Path.home() / ".local" / "share" / "dropin" / "app" / "commit.txt"
    if commit_file.is_file():
        try:
            return commit_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    return ""


class SelfUpdater:
    """Handles checking for Dropin application updates and updating the local installation."""

    @classmethod
    def get_info(cls) -> Dict[str, Any]:
        commit = get_current_commit()
        repo = find_local_repo()
        return {
            "version": __version__,
            "commit": commit[:7] if commit else "",
            "commit_full": commit,
            "has_git_repo": bool(repo),
            "repo_path": str(repo) if repo else "",
        }

    @classmethod
    def check_for_updates(cls) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check GitHub for the latest commit or release of Dropin.
        Returns: (update_available, message, update_info)
        """
        current_info = cls.get_info()
        current_commit = current_info.get("commit_full", "")

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Dropin-Installer/1.0",
        }

        # 1. Check GitHub API for the latest commit on main
        try:
            req = urllib.request.Request(DROPIN_GITHUB_API_COMMITS, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return False, "GitHub API rate limit exceeded. Please try again later.", current_info
            return False, f"GitHub API error (HTTP {e.code}): {e.reason}", current_info
        except Exception as e:
            return False, f"Failed to connect to GitHub: {e}", current_info

        latest_sha = data.get("sha", "")
        commit_data = data.get("commit", {})
        commit_msg = commit_data.get("message", "").splitlines()[0] if commit_data.get("message") else "Update"
        commit_date = commit_data.get("author", {}).get("date", "")[:10]

        update_info = {
            **current_info,
            "latest_sha": latest_sha,
            "latest_sha_short": latest_sha[:7] if latest_sha else "",
            "commit_msg": commit_msg,
            "commit_date": commit_date,
        }

        if current_commit:
            if current_commit.lower() == latest_sha.lower():
                return False, f"Dropin is up to date (commit {latest_sha[:7]} · v{__version__}).", update_info
            else:
                return True, f"New version available: {latest_sha[:7]} ({commit_date}) — {commit_msg}", update_info

        # If local commit is not known, offer update to the latest GitHub commit
        return True, f"Latest version available on GitHub: {latest_sha[:7]} ({commit_date}) — {commit_msg}", update_info

    @classmethod
    def perform_update(cls, progress_callback: Optional[Callable[[int, str], None]] = None) -> Tuple[bool, str]:
        """
        Performs the update of Dropin.
        If a local git clone exists, runs 'git pull origin main' and './install.sh --user'.
        Otherwise, downloads the main archive from GitHub and installs into ~/.local/share/dropin/app.
        """
        repo = find_local_repo()

        if repo:
            if progress_callback:
                progress_callback(20, "Pulling latest changes from GitHub…")

            try:
                proc_pull = subprocess.run(
                    ["git", "pull", "origin", "main"],
                    cwd=str(repo),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=60,
                )
                if proc_pull.returncode != 0:
                    err = proc_pull.stderr.strip() or proc_pull.stdout.strip()
                    return False, f"Git pull failed: {err}"
            except Exception as e:
                return False, f"Failed to execute git pull: {e}"

            if progress_callback:
                progress_callback(60, "Running installer…")

            install_script = repo / "install.sh"
            if install_script.is_file():
                try:
                    proc_inst = subprocess.run(
                        ["bash", str(install_script), "--user"],
                        cwd=str(repo),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=90,
                    )
                    if proc_inst.returncode != 0:
                        err = proc_inst.stderr.strip() or proc_inst.stdout.strip()
                        return False, f"Installation script failed: {err}"
                except Exception as e:
                    return False, f"Failed to run install.sh: {e}"

            if progress_callback:
                progress_callback(100, "Update complete.")

            update_desktop_caches()
            return True, "Dropin was successfully updated to the latest version! Please restart Dropin."

        # Standalone / archive fallback update
        if progress_callback:
            progress_callback(20, "Downloading latest Dropin package from GitHub…")

        headers = {
            "Accept": "*/*",
            "User-Agent": "Dropin-Installer/1.0",
        }

        try:
            req = urllib.request.Request(DROPIN_GITHUB_TARBALL, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                tarball_bytes = resp.read()
        except Exception as e:
            return False, f"Failed to download Dropin update archive: {e}"

        if progress_callback:
            progress_callback(50, "Extracting updated files…")

        with tempfile.TemporaryDirectory(prefix="dropin_update_") as tmpdir:
            tmppath = Path(tmpdir)
            try:
                with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tf:
                    tf.extractall(tmppath)
            except Exception as e:
                return False, f"Failed to unpack update archive: {e}"

            # Locate extracted source root
            subdirs = [p for p in tmppath.iterdir() if p.is_dir()]
            extracted_root = subdirs[0] if subdirs else tmppath

            if progress_callback:
                progress_callback(80, "Installing updated files…")

            install_script = extracted_root / "install.sh"
            if install_script.is_file():
                try:
                    proc_inst = subprocess.run(
                        ["bash", str(install_script), "--user"],
                        cwd=str(extracted_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=90,
                    )
                    if proc_inst.returncode != 0:
                        err = proc_inst.stderr.strip() or proc_inst.stdout.strip()
                        return False, f"Installation script failed: {err}"
                except Exception as e:
                    return False, f"Failed to execute installer: {e}"
            else:
                # Direct file copy
                target_app_dir = Path.home() / ".local" / "share" / "dropin" / "app" / "dropin"
                src_dropin = extracted_root / "dropin"
                if src_dropin.is_dir():
                    shutil.rmtree(target_app_dir, ignore_errors=True)
                    shutil.copytree(src_dropin, target_app_dir)

        if progress_callback:
            progress_callback(100, "Update complete.")

        update_desktop_caches()
        return True, "Dropin was successfully updated to the latest version! Please restart Dropin."


class CheckDropinUpdateWorker(QObject):
    finished = Signal(bool, str, dict)  # update_available, message, update_info
    error = Signal(str)

    def run(self):
        try:
            has_update, msg, info = SelfUpdater.check_for_updates()
            self.finished.emit(has_update, msg, info)
        except Exception as e:
            self.error.emit(str(e))


class PerformDropinUpdateWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def run(self):
        try:
            ok, msg = SelfUpdater.perform_update(progress_callback=self._on_progress)
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))

    def _on_progress(self, pct: int, status: str):
        self.progress.emit(pct, status)
