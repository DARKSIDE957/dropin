"""
Installed application management view for Dropin.
Allows searching, launching, checking updates, and safe uninstallation of tracked apps.
"""

from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QLabel,
    QPushButton,
    QMessageBox,
)

from dropin.core.models import InstalledApp
from dropin.core.registry import get_registry
from dropin.handlers import get_handlers
from dropin.updater.manager import UpdateManager
from dropin.ui.animations import fade_widget


class UpdateCheckWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, manager: UpdateManager):
        super().__init__()
        self.manager = manager

    def run(self):
        try:
            results = self.manager.check_all_updates()
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class AppItemWidget(QWidget):
    launch_clicked = Signal(InstalledApp)
    uninstall_clicked = Signal(InstalledApp)
    update_clicked = Signal(InstalledApp)

    def __init__(self, app: InstalledApp, parent=None):
        super().__init__(parent)
        self.app = app
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("iconSlot")
        self.icon_label.setFixedSize(36, 36)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.app.icon_path and Path(self.app.icon_path).is_file():
            pix = QPixmap(self.app.icon_path)
            self.icon_label.setPixmap(
                pix.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.icon_label.setText("📦")
            self.icon_label.setStyleSheet("font-size: 18px; background: transparent;")
        layout.addWidget(self.icon_label)

        info_col = QVBoxLayout()
        info_col.setSpacing(3)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)

        self.name_label = QLabel(self.app.name, self)
        self.name_label.setStyleSheet("font-weight: 700; font-size: 13px; background: transparent;")
        self.name_label.setWordWrap(False)
        name_row.addWidget(self.name_label)

        self.format_badge = QLabel(self.app.format, self)
        self.format_badge.setObjectName("formatBadge")
        name_row.addWidget(self.format_badge)

        if self.app.update_available:
            self.upd_badge = QLabel(f"→ {self.app.latest_version}", self)
            self.upd_badge.setObjectName("updateBadge")
            name_row.addWidget(self.upd_badge)

        name_row.addStretch()
        info_col.addLayout(name_row)

        checked = f"  ·  Checked {self.app.last_update_check}" if self.app.last_update_check else ""
        sub_text = f"v{self.app.version}  ·  Installed {self.app.install_date or 'recently'}{checked}"
        self.sub_label = QLabel(sub_text, self)
        self.sub_label.setObjectName("mutedLabel")
        info_col.addWidget(self.sub_label)

        layout.addLayout(info_col, 1)

        if self.app.update_available:
            self.update_btn = QPushButton("Update", self)
            self.update_btn.setObjectName("primaryBtn")
            self.update_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
            self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update_btn.clicked.connect(lambda: self.update_clicked.emit(self.app))
            layout.addWidget(self.update_btn)

        self.launch_btn = QPushButton("Launch", self)
        self.launch_btn.setObjectName("compactBtn")
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_btn.clicked.connect(lambda: self.launch_clicked.emit(self.app))
        layout.addWidget(self.launch_btn)

        self.uninstall_btn = QPushButton("Uninstall", self)
        self.uninstall_btn.setObjectName("dangerBtn")
        self.uninstall_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uninstall_btn.clicked.connect(lambda: self.uninstall_clicked.emit(self.app))
        layout.addWidget(self.uninstall_btn)


class InstalledAppsDialog(QDialog):
    update_install_requested = Signal(object, str)  # InstalledApp, download_url

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installed Applications — Dropin")
        self.setMinimumSize(560, 460)
        self.registry = get_registry()
        self.update_manager = UpdateManager()
        self._update_thread = None
        self._update_worker = None
        self._last_results = {}  # app_id -> UpdateCheckResult
        self._init_ui()
        self.load_apps()
        fade_widget(self, 160)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search installed applications…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.load_apps)
        top_row.addWidget(self.search_input, 1)

        self.check_updates_btn = QPushButton("Check updates", self)
        self.check_updates_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_updates_btn.clicked.connect(self._check_updates)
        top_row.addWidget(self.check_updates_btn)

        layout.addLayout(top_row)

        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget, 1)

        bottom_row = QHBoxLayout()
        self.count_label = QLabel("0 applications tracked", self)
        self.count_label.setObjectName("mutedLabel")
        bottom_row.addWidget(self.count_label)
        bottom_row.addStretch()

        self.close_btn = QPushButton("Close", self)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(self.close_btn)

        layout.addLayout(bottom_row)

    def load_apps(self):
        self.list_widget.clear()
        search = self.search_input.text()
        apps = self.registry.list_apps(search)
        self.count_label.setText(f"{len(apps)} application{'s' if len(apps) != 1 else ''} tracked")

        if not apps:
            item = QListWidgetItem(self.list_widget)
            empty_lbl = QLabel(
                "No installed applications tracked yet.\n"
                "Drag a package or paste a URL in the main window to install.",
                self,
            )
            empty_lbl.setObjectName("mutedLabel")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("padding: 36px; font-size: 12px;")
            item.setSizeHint(empty_lbl.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, empty_lbl)
            return

        for app in apps:
            item = QListWidgetItem(self.list_widget)
            widget = AppItemWidget(app, self)
            widget.launch_clicked.connect(self._launch_app)
            widget.uninstall_clicked.connect(self._confirm_uninstall)
            widget.update_clicked.connect(self._start_update_install)
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def _launch_app(self, app: InstalledApp):
        for handler in get_handlers():
            if handler.handles_format(app.format) and handler.can_launch(app):
                if handler.launch(app):
                    return
        # Fallback: any handler that can launch
        for handler in get_handlers():
            if handler.can_launch(app) and handler.launch(app):
                return
        QMessageBox.warning(self, "Launch failed", f"Could not launch {app.name}.")

    def _confirm_uninstall(self, app: InstalledApp):
        scope_info = f"Destination: {app.file_path or 'System'}\nLauncher: {app.launcher_path or 'Standard'}"
        msg = (
            f"Uninstall {app.name} (v{app.version})?\n\n"
            f"{scope_info}\n\n"
            "This removes the application and its desktop launcher. "
            "Unrelated personal files are left untouched."
        )
        reply = QMessageBox.question(
            self,
            f"Uninstall {app.name}",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._uninstall_app(app)

    def _uninstall_app(self, app: InstalledApp):
        success = False
        for handler in get_handlers():
            if handler.handles_format(app.format):
                success = handler.uninstall(app)
                break

        if not success:
            for handler in get_handlers():
                if handler.uninstall(app):
                    success = True
                    break

        self.registry.delete_app(app.id)
        self.load_apps()
        if success:
            QMessageBox.information(self, "Uninstalled", f"{app.name} was successfully uninstalled.")
        else:
            QMessageBox.warning(
                self,
                "Partial removal",
                f"{app.name} was removed from Dropin’s list, but some files may need manual review.",
            )

    def _check_updates(self):
        if self._update_thread and self._update_thread.isRunning():
            return

        self.check_updates_btn.setEnabled(False)
        self.check_updates_btn.setText("Checking…")

        self._update_thread = QThread(self)
        self._update_worker = UpdateCheckWorker(self.update_manager)
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.finished.connect(self._on_updates_finished)
        self._update_worker.error.connect(self._on_updates_error)
        self._update_worker.finished.connect(self._update_thread.quit)
        self._update_worker.error.connect(self._update_thread.quit)
        self._update_thread.finished.connect(self._cleanup_update_thread)
        self._update_thread.start()

    def _on_updates_finished(self, results):
        self._last_results = {r.app_id: r for r in results}
        upd_count = sum(1 for r in results if r.update_available)
        self.load_apps()
        self.check_updates_btn.setEnabled(True)
        self.check_updates_btn.setText("Check updates")

        lines = []
        for r in results:
            mark = "UPDATE" if r.update_available else "OK"
            lines.append(f"[{mark}] {r.message}")
        detail = "\n".join(lines) if lines else "No tracked applications."

        if upd_count > 0:
            QMessageBox.information(
                self,
                "Updates found",
                f"Found {upd_count} update(s).\n\n{detail}\n\n"
                "Use the Update button on an app to download and install it.\n"
                "Each check is also recorded in Settings → Security → Audit Logs.",
            )
        else:
            QMessageBox.information(
                self,
                "Up to date",
                f"No newer releases found.\n\n{detail}\n\n"
                "Tip: automatic checks work for apps installed from GitHub or Flatpak. "
                "Results are written to the security audit log.",
            )

    def _start_update_install(self, app: InstalledApp):
        result = self._last_results.get(app.id)
        url = result.download_url if result else None
        if not url:
            # Re-check this single app to obtain a download URL
            result = self.update_manager.check_app_update(app.id)
            url = result.download_url if result else None
        if not url:
            QMessageBox.warning(
                self,
                "Update unavailable",
                f"No download URL was returned for {app.name}. "
                "Try Check updates again, or install the newer release manually via URL.",
            )
            return
        self.update_install_requested.emit(app, url)
        self.accept()

    def _on_updates_error(self, message: str):
        self.check_updates_btn.setEnabled(True)
        self.check_updates_btn.setText("Check updates")
        QMessageBox.warning(self, "Update check failed", message)

    def _cleanup_update_thread(self):
        self._update_thread = None
        self._update_worker = None
