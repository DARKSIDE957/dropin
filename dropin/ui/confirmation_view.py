"""
Installation confirmation view for Dropin.
Displays application metadata, security considerations, destination, and permissions.
"""

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)

from dropin.core.models import AppPackageInfo
from dropin.ui.animations import fade_widget


class ConfirmationView(QWidget):
    confirmed = Signal(AppPackageInfo)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.info: AppPackageInfo = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        self.card = QFrame(self)
        self.card.setObjectName("cardFrame")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("iconSlot")
        self.icon_label.setFixedSize(52, 52)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.icon_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(4)

        self.name_label = QLabel("Application Name", self)
        self.name_label.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
        self.name_label.setWordWrap(True)
        title_box.addWidget(self.name_label)

        badges_row = QHBoxLayout()
        badges_row.setSpacing(6)

        self.format_badge = QLabel("AppImage", self)
        self.format_badge.setObjectName("formatBadge")
        badges_row.addWidget(self.format_badge)

        self.version_badge = QLabel("v1.0.0", self)
        self.version_badge.setObjectName("versionBadge")
        badges_row.addWidget(self.version_badge)

        self.arch_badge = QLabel("x86_64", self)
        self.arch_badge.setObjectName("versionBadge")
        badges_row.addWidget(self.arch_badge)

        badges_row.addStretch()
        title_box.addLayout(badges_row)

        top_row.addLayout(title_box, 1)
        card_layout.addLayout(top_row)

        self.warning_banner = QLabel(self)
        self.warning_banner.setObjectName("warningBanner")
        self.warning_banner.setWordWrap(True)
        self.warning_banner.hide()
        card_layout.addWidget(self.warning_banner)

        self.meta_frame = QFrame(self)
        meta_layout = QVBoxLayout(self.meta_frame)
        meta_layout.setContentsMargins(0, 2, 0, 2)
        meta_layout.setSpacing(8)

        self.publisher_row = self._create_info_row("Source")
        self.dest_row = self._create_info_row("Destination")
        self.perms_row = self._create_info_row("Permissions")
        self.size_row = self._create_info_row("Package size")
        self.integrity_row = self._create_info_row("Integrity (SHA-256)")
        self.content_row = self._create_info_row("Content check")

        for row in (
            self.publisher_row,
            self.dest_row,
            self.perms_row,
            self.size_row,
            self.integrity_row,
            self.content_row,
        ):
            meta_layout.addLayout(row[0])

        card_layout.addWidget(self.meta_frame)
        main_layout.addWidget(self.card, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        btn_layout.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Install", self)
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.clicked.connect(self._on_install_clicked)
        btn_layout.addWidget(self.install_btn)

        main_layout.addLayout(btn_layout)

    def _create_info_row(self, label_text: str):
        """Stacked key/value rows so labels never collide horizontally."""
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        lbl = QLabel(label_text, self)
        lbl.setObjectName("metaKey")
        val = QLabel("", self)
        val.setObjectName("metaValue")
        val.setWordWrap(True)
        val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        col.addWidget(lbl)
        col.addWidget(val)
        return (col, lbl, val)

    def set_package_info(self, info: AppPackageInfo):
        self.info = info

        self.name_label.setText(info.name)
        self.format_badge.setText(info.format.value)
        self.version_badge.setText(f"v{info.version}")
        self.arch_badge.setText(info.architecture)

        pixmap = None
        if info.icon_bytes:
            pixmap = QPixmap()
            pixmap.loadFromData(info.icon_bytes)
        elif info.icon_path and Path(info.icon_path).is_file():
            pixmap = QPixmap(str(info.icon_path))

        if pixmap and not pixmap.isNull():
            self.icon_label.setStyleSheet("")
            self.icon_label.setPixmap(
                pixmap.scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.icon_label.setText("")
        else:
            symbols = {
                "AppImage": "🚀",
                "DEB": "📦",
                "RPM": "📦",
                "Flatpak": "🌐",
                "Archive": "📁",
                "Unknown": "❓",
            }
            self.icon_label.clear()
            self.icon_label.setText(symbols.get(info.format.value, "📦"))
            self.icon_label.setStyleSheet("font-size: 28px; background: transparent;")

        self.publisher_row[2].setText(info.publisher or "Independent publisher")
        self.dest_row[2].setText(info.target_destination or "~/Applications")

        if info.requires_root:
            perm_text = "Administrator privileges (system package manager)"
        else:
            perm_text = "Standard user — no administrator rights needed"
        self.perms_row[2].setText(perm_text)

        size_mb = f"{info.size_bytes / (1024 * 1024):.1f} MB" if info.size_bytes > 0 else "Unknown"
        self.size_row[2].setText(size_mb)

        if info.sha256:
            short = f"{info.sha256[:16]}…{info.sha256[-8:]}"
            if info.integrity_verified:
                self.integrity_row[2].setText(f"Verified against upstream digest — {short}")
            elif info.expected_sha256:
                self.integrity_row[2].setText(info.integrity_message or f"Computed {short}")
            else:
                self.integrity_row[2].setText(
                    f"Computed {short} (no upstream digest published — hash shown for your records)"
                )
        else:
            self.integrity_row[2].setText("Not computed (local file)")

        if info.content_verified:
            self.content_row[2].setText(info.integrity_message or "Package magic bytes match expected format")
        elif info.sha256:
            self.content_row[2].setText("Pending / skipped")
        else:
            self.content_row[2].setText("Local file — content inspected by handler")

        if not info.compatibility_ok:
            self.warning_banner.setText(f"⚠️  {info.compatibility_reason}")
            self.warning_banner.show()
            self.install_btn.setEnabled(False)
            self.install_btn.setText("Incompatible")
        else:
            self.warning_banner.hide()
            self.install_btn.setEnabled(True)
            self.install_btn.setText("Install")

        fade_widget(self.card, 200)

    def _on_install_clicked(self):
        if self.info and self.info.compatibility_ok:
            self.confirmed.emit(self.info)
