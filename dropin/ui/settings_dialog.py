"""
Settings dialog for Dropin.
Allows configuring storage destinations, update preferences, security checks, and startup.
"""

from __future__ import annotations

from typing import Callable, Tuple

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QRadioButton,
    QButtonGroup,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QFrame,
)

from dropin.core.config import get_config, DEFAULT_CONFIG
from dropin.updater.self_updater import (
    SelfUpdater,
    CheckDropinUpdateWorker,
    PerformDropinUpdateWorker,
)
from dropin.ui.audit_dialog import AuditDialog
from dropin.ui.theme import apply_system_theme
from dropin.ui.animations import fade_widget


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(640, 480)
        self.resize(720, 540)
        self.cfg = get_config()
        self._check_thread = None
        self._check_worker = None
        self._update_thread = None
        self._update_worker = None
        self._init_ui()
        self.load_values()
        fade_widget(self, 160)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        self.tabs = QTabWidget(self)

        self.dest_tab = self._wrap_scroll(self._build_dest_tab())
        self.tabs.addTab(self.dest_tab, "Destinations")

        self.updates_tab = self._wrap_scroll(self._build_updates_tab())
        self.tabs.addTab(self.updates_tab, "Updates")

        self.security_tab = self._wrap_scroll(self._build_security_tab())
        self.tabs.addTab(self.security_tab, "Security")

        main_layout.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        self.reset_all_btn = QPushButton("Restore All Defaults", self)
        self.reset_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_all_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(self.reset_all_btn)

        btn_row.addStretch()

        # Avoid "&" — Qt treats it as a mnemonic and hides the character ("Save Close").
        self.save_btn = QPushButton("Save and Close", self)
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(self.save_btn)

        main_layout.addLayout(btn_row)

    def _wrap_scroll(self, content: QWidget) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _make_section_label(self, text: str, parent: QWidget) -> QLabel:
        lbl = QLabel(text, parent)
        lbl.setStyleSheet("font-weight: 600; background: transparent;")
        lbl.setWordWrap(True)
        return lbl

    def _make_path_field(self, parent: QWidget) -> QLineEdit:
        edit = QLineEdit(parent)
        edit.setMinimumHeight(34)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        edit.setToolTip("Full path is shown here; scroll or resize if needed.")
        return edit

    def _path_block(
        self,
        parent: QWidget,
        title: str,
        browse_cb: Callable,
        reset_cb: Callable,
    ) -> Tuple[QVBoxLayout, QLineEdit]:
        """Path on its own row; Browse/Reset below so text never clips beside buttons."""
        group = QVBoxLayout()
        group.setSpacing(6)

        group.addWidget(self._make_section_label(title, parent))

        edit = self._make_path_field(parent)
        group.addWidget(edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        browse = QPushButton("Browse…", parent)
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(browse_cb)
        reset = QPushButton("Reset", parent)
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(reset_cb)
        btn_row.addWidget(browse)
        btn_row.addWidget(reset)
        btn_row.addStretch()
        group.addLayout(btn_row)

        return group, edit

    def _build_dest_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(16)

        hint = QLabel(
            "These are the default folders for new installs. On the confirm screen "
            "you can optionally choose a different folder for that install only; "
            "if you skip it, Dropin uses the defaults below.",
            page,
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        appimage_group, self.appimage_input = self._path_block(
            page,
            "AppImage Storage Directory (default)",
            self._browse_appimage_dir,
            lambda: self.appimage_input.setText(DEFAULT_CONFIG["appimage_dir"]),
        )
        layout.addLayout(appimage_group)

        port_group, self.portable_input = self._path_block(
            page,
            "Portable Applications Directory (default)",
            self._browse_portable_dir,
            lambda: self.portable_input.setText(DEFAULT_CONFIG["portable_dir"]),
        )
        layout.addLayout(port_group)

        layout.addWidget(self._make_section_label("Flatpak Installation Scope", page))

        self.flatpak_user_rb = QRadioButton(
            "User installation (~/.local/share/flatpak), recommended",
            page,
        )
        self.flatpak_system_rb = QRadioButton(
            "System-wide (/var/lib/flatpak), requires administrator",
            page,
        )
        for rb in (self.flatpak_user_rb, self.flatpak_system_rb):
            rb.setMinimumHeight(24)
            rb.setStyleSheet("background: transparent;")

        self.flatpak_btn_group = QButtonGroup(page)
        self.flatpak_btn_group.addButton(self.flatpak_user_rb)
        self.flatpak_btn_group.addButton(self.flatpak_system_rb)
        layout.addWidget(self.flatpak_user_rb)
        layout.addWidget(self.flatpak_system_rb)

        note = QLabel(
            "Note: Native packages (.deb, .rpm) are managed by your system package manager "
            "and cannot be redirected to arbitrary folders.",
            page,
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch()
        return page

    def _build_updates_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(14)

        self.chk_startup = QCheckBox("Check for updates when Dropin starts", page)
        self.chk_startup.setMinimumHeight(24)
        layout.addWidget(self.chk_startup)

        self.chk_notify = QCheckBox(
            "Show desktop notifications when application updates are found",
            page,
        )
        self.chk_notify.setMinimumHeight(24)
        self.chk_notify.setStyleSheet("background: transparent;")
        layout.addWidget(self.chk_notify)

        interval_box = QHBoxLayout()
        lbl = QLabel("Update check frequency (hours):", page)
        lbl.setWordWrap(True)
        self.spin_interval = QSpinBox(page)
        self.spin_interval.setRange(1, 168)
        self.spin_interval.setValue(24)
        self.spin_interval.setMinimumHeight(34)
        self.spin_interval.setMinimumWidth(80)
        interval_box.addWidget(lbl, 1)
        interval_box.addWidget(self.spin_interval)
        layout.addLayout(interval_box)

        note = QLabel(
            "Dropin discovers updates through verified upstream sources "
            "(GitHub Releases, Flatpak remotes, or native repositories). "
            "It never silently executes untrusted software.",
            page,
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        # --- DROPIN APPLICATION SELF-UPDATE SECTION ---
        layout.addWidget(self._make_section_label("Dropin Application Update", page))

        dropin_card = QFrame(page)
        dropin_card.setObjectName("dropinUpdateCard")
        dropin_card.setStyleSheet("""
            QFrame#dropinUpdateCard {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        card_layout = QVBoxLayout(dropin_card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        info = SelfUpdater.get_info()
        ver_text = f"Dropin v{info['version']}"
        if info.get("commit"):
            ver_text += f" (commit {info['commit']})"

        self.dropin_version_label = QLabel(ver_text, dropin_card)
        self.dropin_version_label.setStyleSheet("font-weight: 600; font-size: 13px; background: transparent;")
        card_layout.addWidget(self.dropin_version_label)

        self.dropin_update_status = QLabel(
            "Check GitHub for the latest releases, improvements, and fixes for Dropin.",
            dropin_card,
        )
        self.dropin_update_status.setObjectName("mutedLabel")
        self.dropin_update_status.setWordWrap(True)
        self.dropin_update_status.setStyleSheet("background: transparent; font-size: 12px;")
        card_layout.addWidget(self.dropin_update_status)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.check_dropin_btn = QPushButton("Check for Dropin updates", dropin_card)
        self.check_dropin_btn.setMinimumHeight(36)
        self.check_dropin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_dropin_btn.clicked.connect(self._check_dropin_update)
        action_row.addWidget(self.check_dropin_btn)

        self.update_dropin_btn = QPushButton("Update Dropin", dropin_card)
        self.update_dropin_btn.setObjectName("primaryBtn")
        self.update_dropin_btn.setMinimumHeight(36)
        self.update_dropin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_dropin_btn.clicked.connect(self._perform_dropin_update)
        action_row.addWidget(self.update_dropin_btn)

        action_row.addStretch()
        card_layout.addLayout(action_row)

        layout.addWidget(dropin_card)

        layout.addStretch()
        return page

    def _build_security_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(14)

        intro = QLabel(
            "These controls protect against real threats: cleartext downloads, "
            "redirects to private networks, spoofed HTML “packages”, and tampered files.",
            page,
        )
        intro.setObjectName("mutedLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.chk_https = QCheckBox("Require HTTPS for downloads (block cleartext HTTP)", page)
        self.chk_https.setMinimumHeight(24)
        layout.addWidget(self.chk_https)

        self.chk_content = QCheckBox(
            "Verify package content (reject HTML or API error pages)",
            page,
        )
        self.chk_content.setMinimumHeight(24)
        layout.addWidget(self.chk_content)

        self.chk_digest = QCheckBox(
            "Verify GitHub release SHA-256 digests when the publisher provides them",
            page,
        )
        self.chk_digest.setMinimumHeight(24)
        layout.addWidget(self.chk_digest)

        self.chk_confirm = QCheckBox(
            "Always require confirmation screen before installing",
            page,
        )
        self.chk_confirm.setMinimumHeight(24)
        layout.addWidget(self.chk_confirm)

        size_note = QLabel(
            "Disk safety (not security): very large downloads can fill the disk. "
            "Raise this freely for big, trusted packages.",
            page,
        )
        size_note.setObjectName("mutedLabel")
        size_note.setWordWrap(True)
        layout.addWidget(size_note)

        size_box = QHBoxLayout()
        lbl_size = QLabel("Maximum download size (MB):", page)
        lbl_size.setWordWrap(True)
        self.spin_size = QSpinBox(page)
        self.spin_size.setRange(100, 65536)
        self.spin_size.setValue(32768)
        self.spin_size.setMinimumHeight(34)
        self.spin_size.setMinimumWidth(100)
        size_box.addWidget(lbl_size, 1)
        size_box.addWidget(self.spin_size)
        layout.addLayout(size_box)

        audit_btn = QPushButton("View security and installation history…", page)
        audit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        audit_btn.clicked.connect(self._open_audit_dialog)
        layout.addWidget(audit_btn)

        layout.addStretch()
        return page

    def load_values(self):
        self.appimage_input.setText(self.cfg.get("appimage_dir", DEFAULT_CONFIG["appimage_dir"]))
        self.portable_input.setText(self.cfg.get("portable_dir", DEFAULT_CONFIG["portable_dir"]))

        scope = self.cfg.get("flatpak_scope", "user")
        if scope == "system":
            self.flatpak_system_rb.setChecked(True)
        else:
            self.flatpak_user_rb.setChecked(True)

        self.chk_startup.setChecked(self.cfg.get("check_updates_on_startup", True))
        self.chk_notify.setChecked(self.cfg.get("notify_updates", True))
        self.spin_interval.setValue(self.cfg.get("update_check_interval_hours", 24))

        self.chk_https.setChecked(self.cfg.get("require_https", True))
        self.chk_content.setChecked(self.cfg.get("verify_package_content", True))
        self.chk_digest.setChecked(self.cfg.get("verify_release_digest", True))
        self.chk_confirm.setChecked(self.cfg.get("confirm_installations", True))
        self.spin_size.setValue(self.cfg.get("max_download_size_mb", 32768))

    def _browse_appimage_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select AppImage Storage Directory", self.appimage_input.text()
        )
        if folder:
            self.appimage_input.setText(folder)

    def _browse_portable_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Portable Storage Directory", self.portable_input.text()
        )
        if folder:
            self.portable_input.setText(folder)

    def _open_audit_dialog(self):
        dlg = AuditDialog(self)
        apply_system_theme(dlg)
        dlg.exec()

    def _reset_defaults(self):
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to restore all settings to default values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.cfg.reset_defaults()
            self.load_values()

    def _save_and_close(self):
        self.cfg.set("appimage_dir", self.appimage_input.text().strip())
        self.cfg.set("portable_dir", self.portable_input.text().strip())
        self.cfg.set("flatpak_scope", "system" if self.flatpak_system_rb.isChecked() else "user")
        self.cfg.set("check_updates_on_startup", self.chk_startup.isChecked())
        self.cfg.set("notify_updates", self.chk_notify.isChecked())
        self.cfg.set("update_check_interval_hours", self.spin_interval.value())
        self.cfg.set("require_https", self.chk_https.isChecked())
        self.cfg.set("verify_package_content", self.chk_content.isChecked())
        self.cfg.set("verify_release_digest", self.chk_digest.isChecked())
        self.cfg.set("confirm_installations", self.chk_confirm.isChecked())
        self.cfg.set("max_download_size_mb", self.spin_size.value())
        self.accept()

    def _check_dropin_update(self):
        self.check_dropin_btn.setEnabled(False)
        self.check_dropin_btn.setText("Checking GitHub…")
        self.dropin_update_status.setText("Connecting to GitHub to check for updates…")

        self._check_thread = QThread(self)
        self._check_worker = CheckDropinUpdateWorker()
        self._check_worker.moveToThread(self._check_thread)

        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.finished.connect(self._on_check_dropin_finished)
        self._check_worker.error.connect(self._on_check_dropin_error)
        self._check_thread.start()

    def _on_check_dropin_finished(self, has_update: bool, msg: str, info: dict):
        self._clean_check_thread()
        self.check_dropin_btn.setEnabled(True)
        self.check_dropin_btn.setText("Check for Dropin updates")
        self.dropin_update_status.setText(msg)

        if has_update:
            self.update_dropin_btn.setEnabled(True)
            self.update_dropin_btn.setText("Update Dropin Now")
        else:
            self.update_dropin_btn.setText("Update Dropin")

    def _on_check_dropin_error(self, err_msg: str):
        self._clean_check_thread()
        self.check_dropin_btn.setEnabled(True)
        self.check_dropin_btn.setText("Check for Dropin updates")
        self.dropin_update_status.setText(f"Update check failed: {err_msg}")

    def _perform_dropin_update(self):
        reply = QMessageBox.question(
            self,
            "Update Dropin",
            "Do you want to update Dropin to the latest version from GitHub now?\n\n"
            "This will download and install the latest updates. You will be prompted to restart Dropin when complete.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.update_dropin_btn.setEnabled(False)
        self.update_dropin_btn.setText("Updating Dropin…")
        self.check_dropin_btn.setEnabled(False)
        self.dropin_update_status.setText("Starting Dropin update…")

        self._update_thread = QThread(self)
        self._update_worker = PerformDropinUpdateWorker()
        self._update_worker.moveToThread(self._update_thread)

        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.progress.connect(self._on_update_progress)
        self._update_worker.finished.connect(self._on_update_dropin_finished)
        self._update_thread.start()

    def _on_update_progress(self, pct: int, status_msg: str):
        self.dropin_update_status.setText(f"{status_msg} ({pct}%)")

    def _on_update_dropin_finished(self, success: bool, msg: str):
        self._clean_update_thread()
        self.update_dropin_btn.setEnabled(True)
        self.update_dropin_btn.setText("Update Dropin")
        self.check_dropin_btn.setEnabled(True)

        if success:
            self.dropin_update_status.setText(msg)
            info = SelfUpdater.get_info()
            ver_text = f"Dropin v{info['version']}"
            if info.get("commit"):
                ver_text += f" (commit {info['commit']})"
            self.dropin_version_label.setText(ver_text)
            QMessageBox.information(self, "Update Complete", msg)
        else:
            self.dropin_update_status.setText(f"Update failed: {msg}")
            QMessageBox.warning(self, "Update Failed", f"Could not complete Dropin update:\n{msg}")

    def _clean_check_thread(self):
        if self._check_thread and self._check_thread.isRunning():
            self._check_thread.quit()
            self._check_thread.wait()
        self._check_thread = None
        self._check_worker = None

    def _clean_update_thread(self):
        if self._update_thread and self._update_thread.isRunning():
            self._update_thread.quit()
            self._update_thread.wait()
        self._update_thread = None
        self._update_worker = None

    def closeEvent(self, event):
        self._clean_check_thread()
        self._clean_update_thread()
        super().closeEvent(event)
