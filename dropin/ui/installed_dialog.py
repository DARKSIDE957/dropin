"""
Installed application management view for Dropin.
Allows searching, launching, checking updates, and safe uninstallation of tracked apps.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QObject, QSize
from PySide6.QtGui import QPixmap, QFontMetrics
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
    QSizePolicy,
    QAbstractItemView,
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
    """Installed app row: icon, name/meta, and actions sized to fit without clipping."""

    launch_clicked = Signal(InstalledApp)
    uninstall_clicked = Signal(InstalledApp)
    update_clicked = Signal(InstalledApp)

    def __init__(self, app: InstalledApp, parent=None):
        super().__init__(parent)
        self.app = app
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._full_sub = ""
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("iconSlot")
        self.icon_label.setFixedSize(36, 36)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.app.icon_path and Path(self.app.icon_path).is_file():
            pix = QPixmap(self.app.icon_path)
            self.icon_label.setPixmap(
                pix.scaled(
                    32,
                    32,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.icon_label.setText("📦")
            self.icon_label.setStyleSheet("font-size: 16px; background: transparent;")
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(3)

        self.name_label = QLabel(self.app.name, self)
        self.name_label.setStyleSheet(
            "font-weight: 700; font-size: 13px; background: transparent; padding-bottom: 1px;"
        )
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(34)  # two lines max, then elides
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.name_label.setToolTip(self.app.name)
        info_col.addWidget(self.name_label)

        bits = [self.app.format, f"v{self.app.version}"]
        if self.app.update_available and self.app.latest_version:
            bits.append(f"update {self.app.latest_version}")
        self._full_sub = ", ".join(bits)
        self.sub_label = QLabel(self._full_sub, self)
        self.sub_label.setObjectName("mutedLabel")
        self.sub_label.setStyleSheet(
            "font-size: 11px; background: transparent; padding-bottom: 1px;"
        )
        self.sub_label.setWordWrap(True)
        self.sub_label.setMaximumHeight(24)
        self.sub_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.sub_label.setToolTip(self._full_sub)
        info_col.addWidget(self.sub_label)

        layout.addLayout(info_col, 1)
        # Stretch pushes buttons to the right edge and lets text elide/wrap
        # instead of running into the action buttons.
        layout.addStretch(1)

        btn_style = "padding: 4px 12px; font-size: 11px; min-width: 0;"

        if self.app.update_available:
            self.update_btn = QPushButton("Update", self)
            self.update_btn.setObjectName("primaryBtn")
            self.update_btn.setStyleSheet(btn_style)
            self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update_btn.setMinimumHeight(30)
            self.update_btn.clicked.connect(lambda: self.update_clicked.emit(self.app))
            layout.addWidget(self.update_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.launch_btn = QPushButton("Launch", self)
        self.launch_btn.setObjectName("compactBtn")
        self.launch_btn.setStyleSheet(btn_style)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_btn.setMinimumHeight(30)
        self.launch_btn.clicked.connect(lambda: self.launch_clicked.emit(self.app))
        layout.addWidget(self.launch_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.uninstall_btn = QPushButton("Uninstall", self)
        self.uninstall_btn.setObjectName("dangerBtn")
        self.uninstall_btn.setStyleSheet(btn_style)
        self.uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uninstall_btn.setMinimumHeight(30)
        self.uninstall_btn.clicked.connect(lambda: self.uninstall_clicked.emit(self.app))
        layout.addWidget(self.uninstall_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_row_width(self, width: int):
        """Fit labels to the list viewport width (horizontal scroll stays off)."""
        if width <= 0:
            return
        btn_w = self.launch_btn.sizeHint().width() + self.uninstall_btn.sizeHint().width()
        if self.app.update_available and hasattr(self, "update_btn"):
            btn_w += self.update_btn.sizeHint().width()
        text_w = max(80, width - 36 - btn_w - 48)
        fm_name = QFontMetrics(self.name_label.font())
        fm_sub = QFontMetrics(self.sub_label.font())
        self.name_label.setText(
            fm_name.elidedText(self.app.name, Qt.TextElideMode.ElideRight, text_w)
        )
        self.sub_label.setText(
            fm_sub.elidedText(self._full_sub, Qt.TextElideMode.ElideRight, text_w)
        )
        self.setFixedWidth(width)
        # Let height follow content so buttons and descenders are not clipped.
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.adjustSize()

    def sizeHint(self) -> QSize:
        lay = self.layout()
        h = lay.sizeHint().height() if lay is not None else 56
        return QSize(self.width() or 400, max(56, h))


class InstalledAppsDialog(QDialog):
    update_install_requested = Signal(object, str)  # InstalledApp, download_url

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installed Applications")
        self.setMinimumSize(520, 420)
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
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_widget.setSpacing(4)
        # Theme item padding shrinks the widget area and clips buttons/text;
        # rows carry their own padding instead.
        self.list_widget.setStyleSheet(
            "QListWidget::item { padding: 0px; margin: 2px 0px; }"
        )
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_row_widths()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_row_widths()

    def _clear_list_widgets(self):
        """QListWidget.clear() does not destroy setItemWidget children — remove them."""
        while self.list_widget.count() > 0:
            item = self.list_widget.takeItem(0)
            widget = self.list_widget.itemWidget(item)
            if widget is not None:
                self.list_widget.removeItemWidget(item)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            del item
        # Sweep any orphans left on the viewport from older Qt quirks.
        for orphan in list(self.list_widget.viewport().findChildren(AppItemWidget)):
            orphan.hide()
            orphan.setParent(None)
            orphan.deleteLater()

    def _fit_row_widths(self):
        viewport_w = self.list_widget.viewport().width()
        if viewport_w <= 0:
            return
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, AppItemWidget):
                widget.set_row_width(viewport_w)
                hint_h = max(56, widget.sizeHint().height())
                item.setSizeHint(QSize(viewport_w, hint_h))

    def load_apps(self):
        self._clear_list_widgets()
        search = self.search_input.text()
        apps = self.registry.list_apps(search)
        self.count_label.setText(
            f"{len(apps)} application{'s' if len(apps) != 1 else ''} tracked"
        )

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
            empty_lbl.setWordWrap(True)
            item.setSizeHint(empty_lbl.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, empty_lbl)
            return

        viewport_w = max(200, self.list_widget.viewport().width())
        for app in apps:
            item = QListWidgetItem(self.list_widget)
            widget = AppItemWidget(app, self.list_widget)
            widget.launch_clicked.connect(self._launch_app)
            widget.uninstall_clicked.connect(self._confirm_uninstall)
            widget.update_clicked.connect(self._start_update_install)
            widget.set_row_width(viewport_w)
            hint_h = max(56, widget.sizeHint().height())
            item.setSizeHint(QSize(viewport_w, hint_h))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def _launch_app(self, app: InstalledApp):
        for handler in get_handlers():
            if handler.handles_format(app.format) and handler.can_launch(app):
                if handler.launch(app):
                    return
        for handler in get_handlers():
            if handler.can_launch(app) and handler.launch(app):
                return
        QMessageBox.warning(self, "Launch failed", f"Could not launch {app.name}.")

    def _confirm_uninstall(self, app: InstalledApp):
        scope_info = (
            f"Destination: {app.file_path or 'System'}\n"
            f"Launcher: {app.launcher_path or 'Standard'}"
        )
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
        matched = False
        for handler in get_handlers():
            if handler.handles_format(app.format):
                matched = True
                success = handler.uninstall(app)
                break

        if not matched:
            for handler in get_handlers():
                if handler.uninstall(app):
                    success = True
                    break

        if success:
            self.registry.delete_app(app.id)
            self.load_apps()
            QMessageBox.information(
                self, "Uninstalled", f"{app.name} was successfully uninstalled."
            )
        else:
            # Keep the registry entry so the user can retry; refresh UI in case
            # some files were partially removed.
            self.load_apps()
            QMessageBox.warning(
                self,
                "Uninstall failed",
                f"Could not fully remove {app.name}. "
                "Could not remove all files. Check permissions and try again.",
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
