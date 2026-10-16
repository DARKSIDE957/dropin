"""
Main Window for Dropin — Universal Linux Application Installer & Update Manager.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QFrame,
    QMessageBox,
)

from dropin.core.config import get_config
from dropin.core.logger import get_logger
from dropin.core.models import AppPackageInfo, InstalledApp, InstallResult, PackageFormat, UpdateCheckResult
from dropin.core.registry import get_registry
from dropin.handlers import detect_and_inspect, get_handler_for_file
from dropin.network.downloader import DownloadWorker
from dropin.network.url_resolver import UrlResolver, UrlTargetType, ResolvedUrlInfo
from dropin.ui.drop_zone import DropZone, classify_drop_mime
from dropin.ui.confirmation_view import ConfirmationView
from dropin.ui.progress_view import ProgressView
from dropin.ui.result_view import ResultView
from dropin.ui.installed_dialog import InstalledAppsDialog
from dropin.ui.pick_file_dialog import PickInstallFileDialog
from dropin.ui.settings_dialog import SettingsDialog
from dropin.ui.asset_dialog import AssetSelectionDialog
from dropin.ui.theme import apply_system_theme
from dropin.ui.animations import fade_widget
from dropin.ui.icons import apply_icon
from dropin.updater.manager import UpdateManager


class InstallWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(InstallResult)

    def __init__(self, handler, package_info: AppPackageInfo, dest_dir: Optional[Path] = None):
        super().__init__()
        self.handler = handler
        self.package_info = package_info
        self.dest_dir = dest_dir

    def run(self):
        try:
            result = self.handler.install(
                self.package_info,
                dest_dir=self.dest_dir,
                progress_callback=lambda pct, msg: self.progress.emit(pct, msg)
            )
            self.finished.emit(result)
        except Exception as e:
            get_logger().error(f"Install worker exception: {e}")
            self.finished.emit(InstallResult(
                success=False,
                message="An unexpected error occurred during installation.",
                error_details=str(e)
            ))


class InspectWorker(QObject):
    """Inspect a local package off the UI thread (large archives can take seconds)."""

    finished = Signal(object)  # AppPackageInfo
    error = Signal(str)

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            info = detect_and_inspect(Path(self.file_path))
            self.finished.emit(info)
        except Exception as e:
            get_logger().error(f"Failed to inspect package {self.file_path}: {e}")
            self.error.emit(str(e))


class ResolveWorker(QObject):
    finished = Signal(object)  # ResolvedUrlInfo
    error = Signal(str)

    def __init__(self, url: str, resolver: UrlResolver):
        super().__init__()
        self.url = url
        self.resolver = resolver

    def run(self):
        try:
            resolved = self.resolver.resolve(self.url)
            self.finished.emit(resolved)
        except Exception as e:
            get_logger().error(f"URL resolve failed: {e}")
            self.error.emit(str(e))


class UpdateCheckWorker(QObject):
    finished = Signal(object)  # List[UpdateCheckResult]

    def run(self):
        results = []
        try:
            results = UpdateManager().check_all_updates() or []
        except Exception as e:
            try:
                get_logger().error(f"Startup update check failed: {e}")
            except Exception:
                pass
        self.finished.emit(results)


def local_path_from_input(text: str) -> Optional[str]:
    """
    If text is a local filesystem path or file:// URL, return the path.
    Otherwise return None.
    """
    text = (text or "").strip()
    if not text:
        return None

    if text.startswith("file:"):
        qurl = QUrl(text)
        if qurl.isLocalFile():
            path = qurl.toLocalFile()
            return path or None
        parsed = urlparse(text)
        path = unquote(parsed.path or "")
        return path or None

    # Absolute or home-relative path that exists as a file
    expanded = os.path.expanduser(text)
    if expanded.startswith("/") or (len(expanded) > 1 and expanded[1] == ":"):
        p = Path(expanded)
        if p.is_file():
            return str(p)

    return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dropin")
        self.resize(480, 410)
        self.setMinimumSize(440, 370)

        self.registry = get_registry()
        self.url_resolver = UrlResolver()

        self._current_package_info: Optional[AppPackageInfo] = None
        self._current_install_result: Optional[InstallResult] = None
        self._source_url: str = ""
        self._update_type: str = "none"
        self._update_id: str = ""
        self._expected_sha256: str = ""
        self._expected_format: Optional[PackageFormat] = None

        # Background worker threads
        self._download_thread: Optional[QThread] = None
        self._download_worker: Optional[DownloadWorker] = None
        self._install_thread: Optional[QThread] = None
        self._install_worker: Optional[InstallWorker] = None
        self._resolve_thread: Optional[QThread] = None
        self._resolve_worker: Optional[ResolveWorker] = None
        self._inspect_thread: Optional[QThread] = None
        self._inspect_worker: Optional[InspectWorker] = None
        self._update_thread: Optional[QThread] = None
        self._update_worker: Optional[UpdateCheckWorker] = None
        self._parked_threads: list = []

        self._init_ui()
        self._update_installed_badge()
        # Skip background update thread under automated E2E (DROPIN_E2E=1).
        if os.environ.get("DROPIN_E2E") != "1":
            QTimer.singleShot(800, self._maybe_check_updates_on_startup)

    def _init_ui(self):
        # Apply system theme automatically
        apply_system_theme(self)

        # Main widget & layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Header
        header = self._create_header()
        main_layout.addWidget(header)

        # 2. Stacked Pages
        self.stack = QStackedWidget(self)

        # Page 0: Main Landing (Drop Zone + URL Input)
        self.landing_page = self._create_landing_page()
        self.stack.addWidget(self.landing_page)

        # Page 1: Confirmation
        self.confirmation_view = ConfirmationView(self)
        self.confirmation_view.confirmed.connect(self._on_install_confirmed)
        self.confirmation_view.cancelled.connect(self._return_to_landing)
        self.stack.addWidget(self.confirmation_view)

        # Page 2: Progress
        self.progress_view = ProgressView(self)
        self.progress_view.cancelled.connect(self._on_operation_cancelled)
        self.stack.addWidget(self.progress_view)

        # Page 3: Result
        self.result_view = ResultView(self)
        self.result_view.launch_requested.connect(self._on_launch_requested)
        self.result_view.done_requested.connect(self._return_to_landing)
        self.result_view.back_requested.connect(self._return_to_landing)
        self.stack.addWidget(self.result_view)

        main_layout.addWidget(self.stack, 1)

    def _create_header(self) -> QFrame:
        """Action bar only — logo/name stay in the system window title bar."""
        header_frame = QFrame(self)
        header_frame.setObjectName("headerFrame")
        layout = QHBoxLayout(header_frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        layout.addStretch()

        # 1) Discover — scan the PC for installable packages (with logos)
        self.pick_file_btn = QPushButton("Discover", self)
        self.pick_file_btn.setObjectName("headerBtn")
        self.pick_file_btn.setToolTip(
            "Find installable packages on this computer and install one"
        )
        self.pick_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_file_btn.setAccessibleName("Discover packages to install")
        apply_icon(self.pick_file_btn, "folder", size=16, clear_text=False)
        self.pick_file_btn.clicked.connect(self._open_pick_file_dialog)
        layout.addWidget(self.pick_file_btn)

        # 2) Installed apps
        self.installed_btn = QPushButton(self)
        self.installed_btn.setObjectName("iconBtn")
        self.installed_btn.setToolTip("Installed apps")
        self.installed_btn.setFixedSize(34, 34)
        self.installed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.installed_btn.setAccessibleName("Installed apps")
        apply_icon(self.installed_btn, "apps", size=18)
        self.installed_btn.clicked.connect(self._open_installed_dialog)
        layout.addWidget(self.installed_btn)

        # 3) Settings
        self.settings_btn = QPushButton(self)
        self.settings_btn.setObjectName("iconBtn")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFixedSize(34, 34)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setAccessibleName("Settings")
        apply_icon(self.settings_btn, "settings", size=18)
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        layout.addWidget(self.settings_btn)
        return header_frame

    def _create_landing_page(self) -> QWidget:
        page = QWidget(self)
        page.setAcceptDrops(True)
        # Route drop events on the landing page itself (header/url row area).
        page.dragEnterEvent = self._landing_drag_enter  # type: ignore[method-assign]
        page.dragLeaveEvent = self._landing_drag_leave  # type: ignore[method-assign]
        page.dropEvent = self._landing_drop  # type: ignore[method-assign]

        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Drag & Drop Zone
        self.drop_zone = DropZone(page)
        self.drop_zone.file_selected.connect(self._handle_file_input)
        self.drop_zone.url_dropped.connect(self._handle_url_dropped)
        self.drop_zone.drop_rejected.connect(self._on_drop_rejected)
        layout.addWidget(self.drop_zone, 1)

        # URL Input Row
        url_frame = QFrame(page)
        url_layout = QHBoxLayout(url_frame)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(8)

        self.url_input = QLineEdit(page)
        self.url_input.setPlaceholderText("Paste a download or GitHub release URL...")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._handle_url_input)
        url_layout.addWidget(self.url_input, 1)

        self.install_url_btn = QPushButton("Install", page)
        self.install_url_btn.setObjectName("primaryBtn")
        self.install_url_btn.setFixedWidth(88)
        self.install_url_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_url_btn.clicked.connect(self._handle_url_input)
        url_layout.addWidget(self.install_url_btn)

        layout.addWidget(url_frame)
        return page

    def _landing_drag_enter(self, event: QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
            self.drop_zone._set_drag_active(True)
        else:
            event.ignore()

    def _landing_drag_leave(self, event: QDragLeaveEvent):
        self.drop_zone._set_drag_active(False)
        event.accept()

    def _landing_drop(self, event: QDropEvent):
        self.drop_zone._set_drag_active(False)
        kind, value = classify_drop_mime(event.mimeData())
        event.acceptProposedAction()
        if kind == "file":
            self._handle_file_input(value)
        elif kind == "url":
            self._handle_url_dropped(value)
        else:
            self._on_drop_rejected(value)

    def _handle_url_dropped(self, url: str):
        self.url_input.setText(url)
        self._handle_url_input()

    def _on_drop_rejected(self, reason: str):
        QMessageBox.information(self, "Can’t use that drop", reason)

    def _update_installed_badge(self):
        count = len(self.registry.list_apps())
        self.installed_btn.setToolTip(
            f"Installed apps ({count})" if count else "Installed apps"
        )

    def _show_page(self, index: int, animate: bool = True):
        self.stack.setCurrentIndex(index)
        page = self.stack.widget(index)
        if animate:
            if page is not None:
                fade_widget(page, 180)

    def _return_to_landing(self):
        self._show_page(0, animate=False)
        self.url_input.clear()
        self._update_installed_badge()

    def _park_thread(self, thread: Optional[QThread]) -> None:
        """Keep a still-running QThread alive so GC does not ABRT Qt."""
        if thread is None:
            return
        try:
            if thread.isRunning():
                self._parked_threads.append(thread)
                get_logger().warning("Parking still-running worker thread until it finishes")
        except RuntimeError:
            pass

    def closeEvent(self, event):
        for cleaner in (
            self._clean_download_thread,
            self._clean_resolve_thread,
            self._clean_inspect_thread,
        ):
            try:
                cleaner()
            except Exception:
                pass
        if self._install_thread and self._install_thread.isRunning():
            self._install_thread.quit()
            if not self._install_thread.wait(3000):
                self._park_thread(self._install_thread)
                self._install_thread = None
                self._install_worker = None
        super().closeEvent(event)

    def _open_pick_file_dialog(self):
        """Show local installable packages; click one to start install."""
        dlg = PickInstallFileDialog(self)
        apply_system_theme(dlg)
        dlg.file_chosen.connect(self._handle_file_input)
        dlg.exec()

    def _open_installed_dialog(self):
        dlg = InstalledAppsDialog(self)
        apply_system_theme(dlg)
        dlg.update_install_requested.connect(self._on_update_install_requested)
        dlg.exec()
        self._update_installed_badge()

    def _on_update_install_requested(self, app: InstalledApp, download_url: str):
        """Install a newer release found by the update manager."""
        self._source_url = download_url
        self._update_type = app.update_type or "github"
        self._update_id = app.update_identifier or ""
        self._expected_sha256 = ""
        self._expected_format = PackageFormat.from_extension(download_url.split("?")[0])
        filename = download_url.rstrip("/").split("/")[-1] or f"{app.name}-update"
        self._start_download(download_url, filename)

    def _open_settings_dialog(self):
        dlg = SettingsDialog(self)
        apply_system_theme(dlg)
        dlg.exec()

    # --- STARTUP UPDATES ---

    def _maybe_check_updates_on_startup(self):
        cfg = get_config()
        if not cfg.get("check_updates_on_startup", True):
            return
        if not self.registry.list_apps():
            return
        if getattr(self, "_update_check_running", False):
            return

        # Use a Python thread + queued Qt signal instead of QThread.
        # QThread teardown under PySide6/Python 3.14 was aborting on startup.
        import threading

        self._update_check_running = True
        notifier = UpdateCheckWorker(self)
        self._update_worker = notifier
        notifier.finished.connect(self._on_startup_updates_finished)

        def _run():
            results = []
            try:
                results = UpdateManager().check_all_updates() or []
            except Exception as e:
                try:
                    get_logger().error(f"Startup update check failed: {e}")
                except Exception:
                    pass
            notifier.finished.emit(results)

        threading.Thread(target=_run, name="dropin-update-check", daemon=True).start()

    def _on_startup_updates_finished(self, results: object):
        self._update_check_running = False
        self._update_worker = None

        if not isinstance(results, list):
            return
        updates = [r for r in results if isinstance(r, UpdateCheckResult) and r.update_available]
        if not updates:
            return
        if not get_config().get("notify_updates", True):
            return

        display_names = []
        for r in updates[:5]:
            app = self.registry.get_app(r.app_id)
            display_names.append(app.name if app else r.app_id)
        names = ", ".join(display_names)
        extra = f" (+{len(updates) - 5} more)" if len(updates) > 5 else ""

        def _show():
            if not self.isVisible():
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("Updates available")
            box.setText(
                f"Dropin found updates for {len(updates)} app"
                f"{'s' if len(updates) != 1 else ''}:\n{names}{extra}"
            )
            box.setInformativeText("Open Installed apps to review and update.")
            open_btn = box.addButton("Open Apps", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() == open_btn:
                self._open_installed_dialog()

        QTimer.singleShot(0, _show)

    # --- INPUT HANDLING ---

    def _proceed_after_inspect(self, info: AppPackageInfo):
        """Show confirmation, or install immediately if confirmation is disabled."""
        self._current_package_info = info
        if get_config().get("confirm_installations", True):
            self.confirmation_view.set_package_info(info)
            # No page fade — opacity effects here blanked the details card.
            self._show_page(1, animate=False)
        else:
            self._on_install_confirmed(info)

    def _handle_file_input(self, file_path_str: str):
        path = Path(file_path_str)
        if not path.is_file():
            QMessageBox.warning(
                self,
                "Invalid File",
                f"The selected path is not a valid file:\n{file_path_str}",
            )
            return

        if self._inspect_thread and self._inspect_thread.isRunning():
            return

        self._source_url = "local_file"
        self._update_type = "none"
        self._update_id = ""

        # Show progress immediately; inspect large archives off the UI thread.
        self.progress_view.set_package(None)
        self.progress_view.set_operation(
            title="Reading package",
            status="Inspecting file…",
            percent=1,
            detail=path.name,
            can_cancel=False,
        )
        self._show_page(2, animate=False)
        QApplication.processEvents()

        self._inspect_thread = QThread()
        self._inspect_worker = InspectWorker(str(path))
        self._inspect_worker.moveToThread(self._inspect_thread)
        self._inspect_worker.finished.connect(self._on_inspect_finished)
        self._inspect_worker.error.connect(self._on_inspect_error)
        self._inspect_thread.started.connect(self._inspect_worker.run)
        self._inspect_thread.start()

    def _clean_inspect_thread(self):
        if self._inspect_thread is None:
            return
        if self._inspect_thread.isRunning():
            self._inspect_thread.quit()
            if not self._inspect_thread.wait(2000):
                self._park_thread(self._inspect_thread)
                self._inspect_thread = None
                self._inspect_worker = None
                return
        self._inspect_thread = None
        self._inspect_worker = None

    def _on_inspect_finished(self, info: AppPackageInfo):
        self._clean_inspect_thread()
        path_name = Path(info.file_path).name if info.file_path else "package"

        if info.format == PackageFormat.UNKNOWN:
            self._return_to_landing()
            reason = info.compatibility_reason or (
                f"“{path_name}” isn’t a supported application package."
            )
            QMessageBox.warning(self, "Unsupported file", reason)
            return

        self._proceed_after_inspect(info)

    def _on_inspect_error(self, message: str):
        self._clean_inspect_thread()
        self._return_to_landing()
        QMessageBox.warning(
            self,
            "Couldn’t read file",
            f"Dropin couldn’t inspect this file.\n\n{message}",
        )

    def _handle_url_input(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.information(
                self,
                "URL required",
                "Paste a download link or GitHub release URL, then click Install.",
            )
            self.url_input.setFocus()
            return

        local = local_path_from_input(url)
        if local:
            self._handle_file_input(local)
            return

        if self._resolve_thread and self._resolve_thread.isRunning():
            return

        self.install_url_btn.setEnabled(False)
        self.install_url_btn.setText("…")
        self.progress_view.set_package(None)
        self.progress_view.set_operation(
            title="Looking up URL",
            status="Resolving download or GitHub release…",
            percent=1,
            detail=url[:80] + ("…" if len(url) > 80 else ""),
            can_cancel=False,
        )
        self._show_page(2, animate=False)

        self._resolve_thread = QThread()
        self._resolve_worker = ResolveWorker(url, self.url_resolver)
        self._resolve_worker.moveToThread(self._resolve_thread)
        self._resolve_worker.finished.connect(self._on_resolve_finished)
        self._resolve_worker.error.connect(self._on_resolve_error)
        self._resolve_thread.started.connect(self._resolve_worker.run)
        self._resolve_thread.start()

    def _clean_resolve_thread(self):
        if self._resolve_thread and self._resolve_thread.isRunning():
            self._resolve_thread.quit()
            self._resolve_thread.wait()
        self._resolve_thread = None
        self._resolve_worker = None
        self.install_url_btn.setEnabled(True)
        self.install_url_btn.setText("Install")

    def _on_resolve_finished(self, resolved: object):
        self._clean_resolve_thread()
        if not isinstance(resolved, ResolvedUrlInfo):
            self._return_to_landing()
            QMessageBox.warning(self, "Invalid URL", "Could not resolve that URL.")
            return
        self._process_resolved_url(resolved)

    def _on_resolve_error(self, error_message: str):
        self._clean_resolve_thread()
        self._return_to_landing()
        QMessageBox.warning(
            self,
            "Couldn’t look up URL",
            f"Dropin couldn’t resolve that link:\n{error_message}",
        )

    def _process_resolved_url(self, resolved: ResolvedUrlInfo):
        if resolved.target_type == UrlTargetType.UNSUPPORTED:
            self._return_to_landing()
            QMessageBox.warning(self, "Invalid URL", resolved.error_message)
            return

        if resolved.target_type == UrlTargetType.GITHUB_RELEASE:
            release_info = resolved.github_info
            if not release_info.assets:
                self._return_to_landing()
                QMessageBox.warning(self, "No Assets", f"No compatible release assets found for {release_info.repo}.")
                return

            selected_asset = release_info.assets[0]
            # If multiple assets, let user select
            if len(release_info.assets) > 1:
                dlg = AssetSelectionDialog(release_info, self)
                apply_system_theme(dlg)
                if dlg.exec() != AssetSelectionDialog.DialogCode.Accepted or not dlg.selected_asset:
                    self._return_to_landing()
                    return
                selected_asset = dlg.selected_asset

            self._source_url = selected_asset.download_url
            self._update_type = "github"
            self._update_id = f"{release_info.owner}/{release_info.repo}"
            self._expected_sha256 = selected_asset.digest or ""
            self._expected_format = selected_asset.format
            self._start_download(
                selected_asset.download_url,
                selected_asset.name,
                expected_sha256=selected_asset.digest,
                expected_format=selected_asset.format,
            )

        elif resolved.target_type == UrlTargetType.DIRECT_DOWNLOAD:
            self._source_url = resolved.url
            self._update_type = "none"
            self._update_id = ""
            self._expected_sha256 = ""
            self._expected_format = PackageFormat.from_extension(resolved.suggested_name or resolved.url)
            self._start_download(
                resolved.url,
                resolved.suggested_name,
                expected_format=self._expected_format,
            )

    # --- ASYNCHRONOUS DOWNLOAD ---

    def _start_download(
        self,
        url: str,
        filename: str,
        expected_sha256: str = "",
        expected_format: Optional[PackageFormat] = None,
    ):
        self.progress_view.set_package(None)
        self.progress_view.set_operation(
            title=f"Downloading {filename}",
            status="Connecting securely…",
            percent=1,
            detail="Validating URL, HTTPS, and redirect safety…",
            can_cancel=True,
        )
        self._show_page(2, animate=False)

        self._download_thread = QThread()
        self._download_worker = DownloadWorker(
            url,
            suggested_filename=filename,
            expected_sha256=expected_sha256 or None,
            expected_format=expected_format,
        )
        self._download_worker.moveToThread(self._download_thread)

        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)

        self._download_thread.started.connect(self._download_worker.run)
        self._download_thread.start()

    def _on_download_progress(self, percent: int, speed_kb_s: float, downloaded: int, total: int):
        dl_mb = downloaded / (1024 * 1024)
        tot_mb = total / (1024 * 1024) if total > 0 else 0
        speed_mb = speed_kb_s / 1024.0

        if tot_mb > 0:
            detail = f"{dl_mb:.1f} MB of {tot_mb:.1f} MB ({speed_mb:.1f} MB/s)"
        else:
            detail = f"{dl_mb:.1f} MB downloaded ({speed_mb:.1f} MB/s)"

        self.progress_view.set_operation(
            title="Downloading Application",
            status="Receiving package data...",
            percent=percent,
            detail=detail,
            can_cancel=True
        )

    def _on_download_finished(self, temp_file_path: str, filename: str, sha256: str = ""):
        self._clean_download_thread()

        self.progress_view.set_operation(
            title="Reading package",
            status="Inspecting downloaded file…",
            percent=1,
            detail=filename,
            can_cancel=False,
        )
        QApplication.processEvents()

        path = Path(temp_file_path)
        try:
            info = detect_and_inspect(path)
        except Exception as e:
            get_logger().error(f"Failed to inspect download {filename}: {e}")
            self.result_view.set_result(InstallResult(
                success=False,
                message="Download finished, but the package couldn’t be read.",
                error_details=str(e),
            ))
            self._show_page(3)
            return

        if info.name == path.name:
            info.name = filename.split(".")[0]

        info.sha256 = sha256 or ""
        info.expected_sha256 = self._expected_sha256 or ""
        if self._expected_sha256 and sha256:
            from dropin.core.security import normalize_sha256
            exp = normalize_sha256(self._expected_sha256)
            info.integrity_verified = bool(exp and exp == sha256)
            info.integrity_message = (
                "SHA-256 matches GitHub release digest"
                if info.integrity_verified
                else "SHA-256 computed"
            )
        info.content_verified = True
        if not info.integrity_message:
            info.integrity_message = "Package content signature (magic bytes) verified"

        self._proceed_after_inspect(info)

    def _on_download_error(self, error_message: str):
        self._clean_download_thread()
        self.result_view.set_result(InstallResult(
            success=False,
            message="Download failed.",
            error_details=error_message
        ))
        self._show_page(3)

    def _clean_download_thread(self):
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.quit()
            self._download_thread.wait()
        self._download_thread = None
        self._download_worker = None

    def _on_operation_cancelled(self):
        if self._download_worker:
            self._download_worker.cancel()
        self._clean_download_thread()
        self._clean_resolve_thread()
        self._return_to_landing()

    # --- INSTALLATION EXECUTION ---

    def _on_install_confirmed(self, info: AppPackageInfo):
        handler = get_handler_for_file(Path(info.file_path))
        if not handler:
            QMessageBox.critical(self, "Error", f"No handler found for format: {info.format.value}")
            return

        # Per-install folder from confirmation (None → handler uses Settings default).
        dest_override = self.confirmation_view.destination_override
        if dest_override is not None:
            info.target_destination = str(dest_override)

        self.progress_view.set_package(info)
        self.progress_view.set_operation(
            title=f"Installing {info.name}",
            status="Starting installation…",
            percent=1,
            detail=(
                f"Installing to {dest_override}…"
                if dest_override
                else "Setting up permissions and desktop integration…"
            ),
            can_cancel=False,
            package=info,
        )
        self._show_page(2, animate=False)
        # Force a paint before the worker starts so Wayland shows the page.
        self.progress_view.repaint()
        QApplication.processEvents()

        self._install_thread = QThread()
        self._install_worker = InstallWorker(handler, info, dest_dir=dest_override)
        self._install_worker.moveToThread(self._install_thread)

        self._install_worker.progress.connect(self._on_install_progress)
        self._install_worker.finished.connect(self._on_install_finished)

        self._install_thread.started.connect(self._install_worker.run)
        self._install_thread.start()

    def _on_install_progress(self, percent: int, message: str):
        info = self._current_package_info
        self.progress_view.set_operation(
            title=f"Installing {info.name if info else 'application'}",
            status=message,
            percent=max(1, percent),
            detail="",
            can_cancel=False,
            package=info,
        )


    def _on_install_finished(self, result: InstallResult):
        if self._install_thread and self._install_thread.isRunning():
            self._install_thread.quit()
            self._install_thread.wait()
        self._install_thread = None
        self._install_worker = None

        self._current_install_result = result

        if result.success and self._current_package_info:
            # Register in SQLite database
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            icon = (
                result.icon_path
                or self._current_package_info.icon_path
                or ""
            )
            app_record = InstalledApp(
                id=result.app_id or f"dropin-{self._current_package_info.name.lower()}",
                name=self._current_package_info.name,
                version=self._current_package_info.version,
                format=self._current_package_info.format.value,
                file_path=result.installed_path or self._current_package_info.file_path,
                launcher_path=result.launcher_path or "",
                icon_path=icon,
                install_date=now_str,
                source_url=self._source_url,
                update_type=self._update_type,
                update_identifier=self._update_id,
                scope="user" if not self._current_package_info.requires_root else "system",
                last_update_check=now_str,
                latest_version=self._current_package_info.version,
                launch_command=result.launch_command or ""
            )
            self.registry.add_app(app_record)

        self.result_view.set_result(result, app_name=self._current_package_info.name if self._current_package_info else "")
        self._show_page(3)

    def _on_launch_requested(self):
        if self._current_install_result and self._current_install_result.launch_command:
            cmd = self._current_install_result.launch_command
            try:
                import shlex
                subprocess.Popen(shlex.split(cmd), start_new_session=True)
                self._return_to_landing()
            except Exception as e:
                QMessageBox.warning(self, "Launch Failed", f"Could not launch application:\n{e}")
        elif self._current_install_result and self._current_install_result.installed_path:
            p = self._current_install_result.installed_path
            try:
                subprocess.Popen([p], start_new_session=True)
                self._return_to_landing()
            except Exception as e:
                QMessageBox.warning(self, "Launch Failed", f"Could not launch application:\n{e}")
