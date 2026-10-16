"""
Portable Archive (.tar.gz, .tar.xz, .zip) handler for Dropin.
Implements safe inspection (checking for path traversal attacks and rejecting uncompiled source archives),
extracting compiled portable binaries, desktop integration, and uninstallation.
"""

import os
import re
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from dropin.core.config import get_config
from dropin.core.distro import get_current_distribution
from dropin.core.logger import get_logger
from dropin.core.models import (
    AppPackageInfo,
    InstalledApp,
    InstallResult,
    PackageFormat,
)
from dropin.core.security import validate_archive_members, secure_file_permissions
from dropin.handlers.base import BaseHandler


class ArchiveHandler(BaseHandler):
    """Handler for compiled portable application archives."""

    format = PackageFormat.ARCHIVE
    ARCHIVE_EXTENSIONS = (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".zip")
    # Cap inspect member walks so multi-GB tars do not materialize every TarInfo.
    _INSPECT_MEMBER_CAP = 20_000
    _SAMPLE_BINARIES = 32
    _SAMPLE_DESKTOPS = 16
    _EXTRACT_PROGRESS_EVERY = 50
    _SOURCE_INDICATORS = (
        "cmakelists.txt",
        "cmake_lists.txt",
        "cargo.toml",
        "configure.ac",
        "makefile",
        "setup.py",
        "pyproject.toml",
        "pom.xml",
    )

    def can_handle(self, file_path: Path) -> bool:
        if not file_path.is_file():
            return False
        name = file_path.name.lower()
        return any(name.endswith(ext) for ext in self.ARCHIVE_EXTENSIONS)

    @staticmethod
    def _member_looks_binary(name: str, is_zip: bool) -> bool:
        clean = name.strip("/")
        parts = clean.split("/")
        base = parts[-1]
        if not is_zip and "/" not in clean and "." not in base and len(base) > 2:
            return True
        return "bin/" in clean and "." not in base

    def _scan_archive_for_inspect(self, file_path: Path, is_zip: bool) -> Dict[str, Any]:
        """
        Stream member names once (capped). Validate paths incrementally and keep
        only small samples — never retain a full getmembers() list.
        """
        binaries: List[str] = []
        desktop_files: List[str] = []
        matched_source: List[str] = []
        scanned = 0
        capped = False
        probe_dest = Path("/tmp")

        def _consume(name: str) -> Optional[str]:
            nonlocal scanned, capped
            scanned += 1
            safe, safe_msg = validate_archive_members([name], probe_dest)
            if not safe:
                return safe_msg
            lower = name.lower()
            base = name.strip("/").split("/")[-1]
            if base.endswith(".desktop") and len(desktop_files) < self._SAMPLE_DESKTOPS:
                desktop_files.append(name)
            if (
                self._member_looks_binary(name, is_zip)
                and len(binaries) < self._SAMPLE_BINARIES
            ):
                binaries.append(name)
            for ind in self._SOURCE_INDICATORS:
                if ind in lower and ind not in matched_source:
                    matched_source.append(ind)
            if scanned >= self._INSPECT_MEMBER_CAP:
                capped = True
            return None

        if is_zip:
            with zipfile.ZipFile(file_path, "r") as zf:
                # namelist() is string-only (cheap vs TarInfo). Still cap work.
                for name in zf.namelist():
                    err = _consume(name)
                    if err:
                        return {"error": err, "unsafe": True}
                    if capped:
                        break
        else:
            with tarfile.open(file_path, "r:*") as tf:
                for member in tf:
                    err = _consume(member.name)
                    if err:
                        return {"error": err, "unsafe": True}
                    # Enough signal for confirm UI — stop early to spare RAM/CPU.
                    if binaries and desktop_files and scanned >= 256:
                        break
                    if capped:
                        break

        return {
            "binaries": binaries,
            "desktop_files": desktop_files,
            "matched_source": matched_source,
            "scanned": scanned,
            "capped": capped,
        }

    def _extract_archive(
        self,
        src_path: Path,
        dest_dir: Path,
        is_zip: bool,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> tuple[bool, str]:
        """Validate + extract in one streaming pass (no double getmembers() lists)."""
        extracted = 0

        def _tick() -> None:
            nonlocal extracted
            extracted += 1
            if progress_callback and extracted % self._EXTRACT_PROGRESS_EVERY == 0:
                # Keep progress in the extract band (20–55%).
                pct = min(55, 20 + (extracted // self._EXTRACT_PROGRESS_EVERY))
                progress_callback(pct, f"Extracting… ({extracted} files)")

        if is_zip:
            with zipfile.ZipFile(src_path, "r") as zf:
                names = zf.namelist()
                for name in names:
                    safe, msg = validate_archive_members([name], dest_dir)
                    if not safe:
                        return False, msg
                for name in names:
                    zf.extract(name, dest_dir)
                    _tick()
            return True, ""

        with tarfile.open(src_path, "r:*") as tf:
            use_filter = hasattr(tarfile, "data_filter")
            for member in tf:
                safe, msg = validate_archive_members([member.name], dest_dir)
                if not safe:
                    return False, msg
                if use_filter:
                    tf.extract(member, dest_dir, filter="data")
                else:
                    tf.extract(member, dest_dir)
                _tick()
        return True, ""

    def inspect(self, file_path: Path) -> AppPackageInfo:
        file_path = file_path.resolve()
        size = file_path.stat().st_size
        distro = get_current_distribution()
        is_zip = file_path.name.lower().endswith(".zip")

        try:
            scan = self._scan_archive_for_inspect(file_path, is_zip)
        except Exception as e:
            return AppPackageInfo(
                name=file_path.stem,
                version="1.0.0",
                format=PackageFormat.ARCHIVE,
                architecture=distro.arch,
                file_path=str(file_path),
                description="Damaged or unreadable archive.",
                compatibility_ok=False,
                compatibility_reason=f"Archive cannot be read: {e}"
            )

        if scan.get("unsafe"):
            return AppPackageInfo(
                name=file_path.stem,
                version="1.0.0",
                format=PackageFormat.ARCHIVE,
                architecture=distro.arch,
                file_path=str(file_path),
                description="Unsafe archive structure.",
                compatibility_ok=False,
                compatibility_reason=scan.get("error") or "Unsafe archive structure.",
            )

        binaries = scan["binaries"]
        desktop_files = scan["desktop_files"]
        matched_source = scan["matched_source"]
        is_source_tree = bool(matched_source and not desktop_files and not binaries)

        compat_ok = True
        compat_reason = ""
        if is_source_tree:
            compat_ok = False
            compat_reason = (
                "This archive contains source code rather than a precompiled application. "
                "Dropin only installs compiled binaries, not uncompiled source trees."
            )
        elif not binaries and not desktop_files:
            compat_ok = False
            compat_reason = "No executable application or .desktop entry found in this archive."

        app_name = self._extract_clean_name(file_path.name)
        dest_dir = get_config().portable_dir / re.sub(r"[^\w\-.]", "_", app_name)

        return AppPackageInfo(
            name=app_name,
            version="1.0.0",
            format=PackageFormat.ARCHIVE,
            architecture=distro.arch,
            file_path=str(file_path),
            description="Portable Linux Application",
            publisher="Portable Archive Release",
            size_bytes=size,
            requires_root=False,
            target_destination=str(dest_dir),
            can_customize_destination=True,
            compatibility_ok=compat_ok,
            compatibility_reason=compat_reason,
            extra_metadata={
                "binaries": binaries,
                "desktop_files": desktop_files,
                "is_zip": is_zip,
                "members_scanned": scan["scanned"],
                "members_capped": scan["capped"],
            }
        )

    def install(
        self,
        info: AppPackageInfo,
        dest_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> InstallResult:
        if not info.compatibility_ok:
            return InstallResult(
                success=False,
                message=info.compatibility_reason,
                error_details=info.compatibility_reason
            )

        src_path = Path(info.file_path).resolve()
        if not src_path.is_file():
            return InstallResult(
                success=False,
                message="Archive file does not exist.",
                error_details=str(src_path)
            )

        safe_name = re.sub(r"[^\w\-.]", "_", info.name)
        if dest_dir is None:
            dest_dir = get_config().portable_dir / safe_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(20, "Extracting portable application files safely...")

        is_zip = info.extra_metadata.get("is_zip", src_path.name.lower().endswith(".zip"))
        try:
            ok, msg = self._extract_archive(src_path, dest_dir, is_zip, progress_callback)
            if not ok:
                return InstallResult(success=False, message=msg, error_details=msg)
        except Exception as e:
            return InstallResult(
                success=False,
                message="Failed to extract archive.",
                error_details=str(e)
            )

        if progress_callback:
            progress_callback(60, "Configuring executable permissions...")

        # Find executable inside extracted destination
        exec_path = self._find_primary_executable(dest_dir, info.name)
        if exec_path:
            secure_file_permissions(str(exec_path), is_executable=True)
        else:
            return InstallResult(
                success=False,
                message="Could not find a launchable application inside this archive.",
                error_details=f"Extracted to {dest_dir}, but no suitable executable was found.",
            )

        if progress_callback:
            progress_callback(80, "Creating desktop launcher...")

        app_id = f"dropin-archive-{safe_name.lower()}"
        icon_path = self._find_icon(dest_dir, exec_path)
        launcher_path = self._create_launcher(
            app_id, info.name, exec_path, icon_path=icon_path
        )

        if progress_callback:
            progress_callback(100, "Installation complete.")

        return InstallResult(
            success=True,
            message=f"Successfully extracted and installed portable app {info.name}.",
            app_id=app_id,
            installed_path=str(dest_dir),
            launcher_path=str(launcher_path) if launcher_path else None,
            launch_command=str(exec_path),
            icon_path=icon_path,
        )

    def uninstall(self, app: InstalledApp) -> bool:
        get_logger().info(f"Removing portable app {app.name} at {app.file_path}")
        errors = []
        removed_any = False

        targets: list[Path] = []
        if app.file_path:
            targets.append(Path(app.file_path))

        for target in targets:
            if target.is_dir():
                try:
                    shutil.rmtree(target)
                    removed_any = True
                except Exception as e:
                    errors.append(f"Failed to remove {target}: {e}")
            elif target.is_file():
                try:
                    target.unlink()
                    removed_any = True
                except Exception as e:
                    errors.append(f"Failed to remove {target}: {e}")

        launchers: list[Path] = []
        if app.launcher_path:
            launchers.append(Path(app.launcher_path))
        if app.id:
            launchers.append(
                Path.home() / ".local" / "share" / "applications" / f"{app.id}.desktop"
            )
        for launcher in dict.fromkeys(launchers):
            if launcher.is_file():
                try:
                    launcher.unlink()
                    removed_any = True
                except Exception:
                    get_logger().warning(
                        "Failed to remove archive launcher %s", launcher, exc_info=True
                    )

        still_there = [str(t) for t in targets if t.exists()]
        if still_there:
            errors.append(f"Portable app still on disk: {', '.join(still_there)}")
            return False

        if not removed_any and targets and not any(t.exists() for t in targets):
            return True

        return len(errors) == 0

    def _extract_clean_name(self, filename: str) -> str:
        name = filename
        for ext in self.ARCHIVE_EXTENSIONS:
            if name.lower().endswith(ext):
                name = name[:-len(ext)]
                break
        name = re.sub(r"[-_](linux|x86_64|amd64|arm64|aarch64|bin|portable)$", "", name, flags=re.I)
        name = re.sub(r"[-_]v?\d+[\d\._\-]*$", "", name)
        name = name.replace("-", " ").replace("_", " ").strip()
        return name.title() if name else "Portable Application"

    # Helper/tool scripts that live next to the real app launcher (e.g. JetBrains).
    _UTILITY_SCRIPT_NAMES = frozenset({
        "format.sh",
        "inspect.sh",
        "ltedit.sh",
        "profiler.sh",
        "game-tools.sh",
        "fsnotifier",
        "restarter",
        "appletviewer.policy",
    })

    # Well-known primary launchers for common portable Linux apps.
    _PREFERRED_LAUNCHER_NAMES = (
        "studio.sh",
        "idea.sh",
        "clion.sh",
        "pycharm.sh",
        "webstorm.sh",
        "phpstorm.sh",
        "rider.sh",
        "goland.sh",
        "rubymine.sh",
        "datagrip.sh",
        "appimage",
        "AppRun",
    )

    def _find_primary_executable(self, dest_dir: Path, app_name: str) -> Optional[Path]:
        """Pick the real app launcher, not the first random file in the tree."""
        skip_suffixes = (
            ".txt", ".md", ".json", ".png", ".svg", ".h", ".c", ".jar", ".so",
            ".dylib", ".dll", ".properties", ".xml", ".html", ".css", ".js",
            ".py", ".pyc", ".class", ".o", ".a", ".db", ".vmoptions", ".policy",
            ".ico", ".icns", ".gif", ".jpg", ".jpeg", ".webp", ".ttf", ".otf",
        )
        tokens = [t for t in re.split(r"[\s_\-]+", app_name.lower()) if len(t) > 2]
        # Drop noisy release tokens so "Android Studio Rabbit1" still matches studio.sh
        noise = {"linux", "win", "windows", "mac", "macos", "portable", "bin", "x86", "amd64"}
        tokens = [t for t in tokens if t not in noise and not t[0].isdigit()]

        scored: List[tuple[int, Path]] = []
        for p in dest_dir.rglob("*"):
            if not p.is_file():
                continue
            name = p.name
            lower = name.lower()
            if lower in self._UTILITY_SCRIPT_NAMES:
                continue
            if any(lower.endswith(suf) for suf in skip_suffixes):
                continue
            # Skip deep plugin/tool trees; prefer top-level bin/ launchers.
            parts_lower = [x.lower() for x in p.parts]
            if any(x in parts_lower for x in ("plugins", "lib", "jbr", "jre", "helpers", "lldb")):
                # Still allow a preferred launcher if somehow nested; otherwise skip.
                if lower not in {n.lower() for n in self._PREFERRED_LAUNCHER_NAMES}:
                    continue

            score = 0
            if lower in {n.lower() for n in self._PREFERRED_LAUNCHER_NAMES}:
                score += 100
            if lower.endswith(".sh"):
                score += 40
            # Executable bit
            try:
                if os.access(p, os.X_OK):
                    score += 25
            except OSError:
                pass
            # Lives in a bin/ directory (Android Studio, many portables)
            if len(p.parts) >= 2 and p.parts[-2].lower() == "bin":
                score += 30
            # Name shares tokens with the app (studio ↔ Android Studio)
            stem = Path(lower).stem.replace("-", "").replace("_", "")
            for tok in tokens:
                tok_c = tok.replace("-", "").replace("_", "")
                if tok_c and tok_c in stem:
                    score += 20
            # Bare binary named like the product (e.g. bin/studio)
            if "." not in name and any(tok in lower for tok in tokens):
                score += 15
            # Prefer shallower paths
            depth = len(p.relative_to(dest_dir).parts)
            score -= min(depth, 8)

            if score > 0:
                scored.append((score, p))

        if not scored:
            # Last resort: any executable script/binary under bin/, excluding utilities.
            for p in dest_dir.rglob("*"):
                if not p.is_file():
                    continue
                lower = p.name.lower()
                if lower in self._UTILITY_SCRIPT_NAMES:
                    continue
                if any(lower.endswith(suf) for suf in skip_suffixes):
                    continue
                try:
                    if os.access(p, os.X_OK) and (
                        lower.endswith(".sh") or "." not in p.name
                    ):
                        scored.append((1, p))
                except OSError:
                    continue

        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        chosen = scored[0][1]
        get_logger().info(f"Selected portable launcher: {chosen} (score={scored[0][0]})")
        return chosen

    def _find_icon(self, dest_dir: Path, exec_path: Optional[Path]) -> Optional[str]:
        """Prefer a product icon next to the launcher (e.g. studio.svg)."""
        search_roots = []
        if exec_path is not None:
            search_roots.append(exec_path.parent)
        search_roots.append(dest_dir)
        names = ("studio.svg", "idea.svg", "icon.svg", "icon.png", "studio.png")
        for root in search_roots:
            for name in names:
                candidate = root / name
                if candidate.is_file():
                    return str(candidate)
            # Generic: any svg/png beside the launcher with product-ish name
            if root.is_dir():
                for p in root.iterdir():
                    if p.suffix.lower() in {".svg", ".png"} and p.is_file():
                        return str(p)
        return None

    def _create_launcher(
        self,
        app_id: str,
        name: str,
        exec_path: Path,
        icon_path: Optional[str] = None,
    ) -> Optional[Path]:
        launchers_dir = Path.home() / ".local" / "share" / "applications"
        launchers_dir.mkdir(parents=True, exist_ok=True)
        launcher_path = launchers_dir / f"{app_id}.desktop"
        icon = icon_path or "application-x-executable"

        # No %U/%F field codes: JetBrains helper scripts treat extra args as
        # CLI modes (e.g. format.sh → "format"), which looks like a crash.
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={name}\n"
            f'Exec="{exec_path}"\n'
            f"Icon={icon}\n"
            "Terminal=false\n"
            "StartupNotify=true\n"
            "Categories=Development;IDE;Utility;\n"
            "X-Dropin-Managed=true\n"
        )
        try:
            launcher_path.write_text(content, encoding="utf-8")
            secure_file_permissions(str(launcher_path), is_executable=True)
            return launcher_path
        except Exception:
            get_logger().warning(
                "Failed to write archive desktop launcher for %s", name, exc_info=True
            )
            return None
