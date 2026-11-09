"""
Application registry and audit database using SQLite.
Stores tracked applications and installation audit logs.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from dropin.core.models import InstalledApp
from dropin.core.logger import get_logger


def get_data_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        path = Path(xdg_data_home) / "dropin"
    else:
        path = Path.home() / ".local" / "share" / "dropin"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback = Path(f"/tmp/dropin_data_{os.getuid() if hasattr(os, 'getuid') else 'user'}")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    return path


class AppRegistry:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            self.db_path = get_data_dir() / "dropin.db"
        else:
            self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS installed_apps (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT,
                format TEXT NOT NULL,
                file_path TEXT,
                launcher_path TEXT,
                icon_path TEXT,
                install_date TEXT,
                source_url TEXT,
                update_type TEXT,
                update_identifier TEXT,
                scope TEXT,
                last_update_check TEXT,
                latest_version TEXT,
                launch_command TEXT
            )
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT
            )
            """)
            conn.commit()

        # Automatically repair and synchronize any legacy/stale registry records
        self.sync_and_repair_installed_apps()

    def sync_and_repair_installed_apps(self) -> int:
        """
        Repairs stale or corrupt metadata:
        1. Fixes applications previously installed with Dropin's own icon (Priority 1).
        2. Cleans up stale registry records whose files no longer exist on disk.
        3. Synchronizes semantic version strings and GitHub update identifiers.
        4. Cleans up orphan desktop launchers and refreshes KDE / XDG desktop caches.
        """
        repaired = 0
        needs_cache_update = False
        try:
            from dropin.handlers.appimage import AppImageHandler
            from dropin.handlers.archive import ArchiveHandler
            from dropin.core.desktop import (
                is_dropin_own_icon,
                save_application_icon,
                update_desktop_caches,
                write_desktop_entry,
                cleanup_obsolete_dropin_launchers,
            )
            from dropin.core.versions import normalize_version

            appimage_handler = AppImageHandler()
            archive_handler = ArchiveHandler()

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, name, version, format, file_path, launcher_path, icon_path,
                           update_type, update_identifier, launch_command
                    FROM installed_apps
                """)
                rows = cursor.fetchall()

                valid_exec_paths = set()

                for row in rows:
                    app_id = row["id"]
                    name = row["name"]
                    version = row["version"] or ""
                    fmt = row["format"] or ""
                    file_path = row["file_path"] or ""
                    launcher_path = row["launcher_path"] or ""
                    icon_path = row["icon_path"] or ""
                    up_type = row["update_type"] or "none"
                    up_id = row["update_identifier"] or ""
                    launch_cmd = row["launch_command"] or ""

                    p = Path(file_path) if file_path else None

                    # 1. Clean up stale registry records when portable binary was deleted outside Dropin
                    if fmt in ("AppImage", "Archive") and p:
                        if not p.exists():
                            if launcher_path and Path(launcher_path).is_file():
                                try:
                                    Path(launcher_path).unlink()
                                except Exception:
                                    pass
                            cursor.execute("DELETE FROM installed_apps WHERE id = ?", (app_id,))
                            cursor.execute("""
                                INSERT INTO audit_logs (timestamp, action, target, status, details)
                                VALUES (?, 'CLEANUP', ?, 'SUCCESS', 'Removed stale registry entry (binary no longer on disk)')
                            """, (datetime.now().isoformat(), name))
                            repaired += 1
                            needs_cache_update = True
                            continue

                    if p and p.exists():
                        valid_exec_paths.add(str(p))

                    # 2. Repair applications suffering from the Icon Bug (received Dropin's own icon or missing icon)
                    needs_icon_repair = False
                    if not icon_path or not Path(icon_path).is_file():
                        needs_icon_repair = True
                    elif is_dropin_own_icon(icon_path):
                        needs_icon_repair = True

                    if needs_icon_repair and p and p.exists():
                        new_icon_path = None
                        if fmt == "AppImage" and p.is_file():
                            meta = appimage_handler._extract_appimage_metadata(p)
                            if meta.get("icon_bytes"):
                                new_icon_path = save_application_icon(app_id, meta["icon_bytes"])
                        elif fmt == "Archive" and p.is_dir():
                            found_icon = archive_handler._find_icon(p, Path(launch_cmd) if launch_cmd else None)
                            if found_icon:
                                new_icon_path = save_application_icon(app_id, source_icon_path=found_icon)

                        if new_icon_path:
                            target_launcher = (
                                Path(launcher_path)
                                if launcher_path and Path(launcher_path).is_file()
                                else Path.home() / ".local" / "share" / "applications" / f"{app_id}.desktop"
                            )
                            if target_launcher.is_file():
                                try:
                                    lines = []
                                    for l in target_launcher.read_text(encoding="utf-8").splitlines():
                                        if l.startswith("Icon="):
                                            lines.append(f"Icon={new_icon_path}")
                                        else:
                                            lines.append(l)
                                    target_launcher.write_text("\n".join(lines) + "\n", encoding="utf-8")
                                except Exception as e:
                                    get_logger().warning("Failed to update launcher icon: %s", e)
                            else:
                                write_desktop_entry(
                                    app_id=app_id,
                                    name=name,
                                    exec_path=p,
                                    icon_path=new_icon_path,
                                    comment=f"{name} Application",
                                    generic_name=name,
                                )

                            cursor.execute(
                                "UPDATE installed_apps SET icon_path = ?, launcher_path = ? WHERE id = ?",
                                (new_icon_path, str(target_launcher), app_id)
                            )
                            cursor.execute("""
                                INSERT INTO audit_logs (timestamp, action, target, status, details)
                                VALUES (?, 'REPAIR_ICON', ?, 'SUCCESS', ?)
                            """, (datetime.now().isoformat(), name, f"Repaired application icon: {new_icon_path}"))
                            repaired += 1
                            needs_cache_update = True
                            icon_path = new_icon_path

                    # 3. Synchronize version and update metadata
                    new_version = version
                    new_up_type = up_type
                    new_up_id = up_id

                    if fmt == "AppImage" and p and p.is_file():
                        info = appimage_handler.inspect(p)
                        if info.version and info.version != "1.0.0":
                            new_version = info.version
                        elif version.endswith("-x86"):
                            new_version = version[:-4]

                        if (not up_id or up_type == "none") and info.extra_metadata.get("update_identifier"):
                            new_up_type = info.extra_metadata.get("update_type", "none")
                            new_up_id = info.extra_metadata.get("update_identifier", "")

                    elif fmt == "Archive" and p and p.is_dir():
                        detected = archive_handler._detect_version_from_extracted_dir(p)
                        if detected:
                            new_version = normalize_version(detected) or detected

                    if version.endswith("-x86"):
                        new_version = version[:-4]

                    if new_version != version or new_up_type != up_type or new_up_id != up_id:
                        cursor.execute(
                            "UPDATE installed_apps SET version = ?, latest_version = ?, update_type = ?, update_identifier = ? WHERE id = ?",
                            (new_version, new_version, new_up_type, new_up_id, app_id)
                        )
                        repaired += 1

                # 4. Clean up any broken desktop files whose binaries no longer exist
                cleanup_obsolete_dropin_launchers(valid_exec_paths)

                if repaired > 0:
                    conn.commit()
                    get_logger().info(f"Synchronized and repaired {repaired} application registry records.")

            if needs_cache_update:
                update_desktop_caches()
        except Exception as e:
            get_logger().warning(f"Registry repair encountered error: {e}", exc_info=True)
        return repaired

    def add_app(self, app: InstalledApp) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR REPLACE INTO installed_apps (
                    id, name, version, format, file_path, launcher_path, icon_path,
                    install_date, source_url, update_type, update_identifier,
                    scope, last_update_check, latest_version, launch_command
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    app.id, app.name, app.version, app.format, app.file_path,
                    app.launcher_path, app.icon_path, app.install_date,
                    app.source_url, app.update_type, app.update_identifier,
                    app.scope, app.last_update_check, app.latest_version,
                    app.launch_command
                ))
                conn.commit()
            self.log_audit("INSTALL", app.name, "SUCCESS", f"Installed {app.name} v{app.version} ({app.format})")
            return True
        except Exception as e:
            get_logger().error(f"Failed to record app in registry: {e}")
            return False

    def get_app(self, app_id: str) -> Optional[InstalledApp]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM installed_apps WHERE id = ?", (app_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_app(row)
        except Exception as e:
            get_logger().error(f"Error fetching app {app_id}: {e}")
        return None

    def list_apps(self, search: str = "") -> List[InstalledApp]:
        apps = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if search.strip():
                    pattern = f"%{search.strip()}%"
                    cursor.execute("""
                    SELECT * FROM installed_apps 
                    WHERE name LIKE ? OR format LIKE ? OR id LIKE ?
                    ORDER BY name COLLATE NOCASE ASC
                    """, (pattern, pattern, pattern))
                else:
                    cursor.execute("SELECT * FROM installed_apps ORDER BY name COLLATE NOCASE ASC")
                for row in cursor.fetchall():
                    apps.append(self._row_to_app(row))
        except Exception as e:
            get_logger().error(f"Error listing apps: {e}")
        return apps

    def update_app_version(self, app_id: str, new_version: str, new_file_path: Optional[str] = None) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if new_file_path:
                    cursor.execute("""
                    UPDATE installed_apps 
                    SET version = ?, file_path = ?, latest_version = ?
                    WHERE id = ?
                    """, (new_version, new_file_path, new_version, app_id))
                else:
                    cursor.execute("""
                    UPDATE installed_apps 
                    SET version = ?, latest_version = ?
                    WHERE id = ?
                    """, (new_version, new_version, app_id))
                conn.commit()
            return True
        except Exception as e:
            get_logger().error(f"Failed to update app version {app_id}: {e}")
            return False

    def update_check_status(self, app_id: str, latest_version: str) -> None:
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                UPDATE installed_apps 
                SET last_update_check = ?, latest_version = ?
                WHERE id = ?
                """, (now_str, latest_version, app_id))
                conn.commit()
        except Exception as e:
            get_logger().error(f"Failed to update check status: {e}")

    def delete_app(self, app_id: str) -> bool:
        try:
            app = self.get_app(app_id)
            app_name = app.name if app else app_id
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM installed_apps WHERE id = ?", (app_id,))
                conn.commit()
            self.log_audit("UNINSTALL", app_name, "SUCCESS", f"Removed {app_name} from registry")
            return True
        except Exception as e:
            get_logger().error(f"Failed to delete app {app_id}: {e}")
            return False

    def log_audit(self, action: str, target: str, status: str, details: str = "") -> None:
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO audit_logs (timestamp, action, target, status, details)
                VALUES (?, ?, ?, ?, ?)
                """, (now_str, action, target, status, details))
                conn.commit()
        except Exception as e:
            get_logger().error(f"Failed to write audit log: {e}")

    def get_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        logs = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                SELECT timestamp, action, target, status, details 
                FROM audit_logs ORDER BY id DESC LIMIT ?
                """, (limit,))
                for row in cursor.fetchall():
                    logs.append({
                        "timestamp": row["timestamp"],
                        "action": row["action"],
                        "target": row["target"],
                        "status": row["status"],
                        "details": row["details"]
                    })
        except Exception as e:
            get_logger().error(f"Failed to read audit logs: {e}")
        return logs

    def _row_to_app(self, row: sqlite3.Row) -> InstalledApp:
        from dropin.core.versions import is_newer_version

        installed_ver = row["version"] or ""
        latest_ver = row["latest_version"] or installed_ver
        update_avail = bool(
            latest_ver and installed_ver and is_newer_version(latest_ver, installed_ver)
        )

        return InstalledApp(
            id=row["id"],
            name=row["name"],
            version=installed_ver,
            format=row["format"],
            file_path=row["file_path"] or "",
            launcher_path=row["launcher_path"] or "",
            icon_path=row["icon_path"] or "",
            install_date=row["install_date"] or "",
            source_url=row["source_url"] or "",
            update_type=row["update_type"] or "none",
            update_identifier=row["update_identifier"] or "",
            scope=row["scope"] or "user",
            last_update_check=row["last_update_check"] or "",
            update_available=update_avail,
            latest_version=latest_ver,
            launch_command=row["launch_command"] or ""
        )


_REGISTRY_INSTANCE = None


def get_registry() -> AppRegistry:
    global _REGISTRY_INSTANCE
    if _REGISTRY_INSTANCE is None:
        _REGISTRY_INSTANCE = AppRegistry()
    return _REGISTRY_INSTANCE
