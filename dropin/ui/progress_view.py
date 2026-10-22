"""
Installation and download progress view for Dropin.

Compact single-view layout: package identity on top, 1–100% bar below.
Sized to fit the main window without horizontal scrolling. No opacity
graphics effects (those blanked this page on Wayland during install).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QFrame,
    QSizePolicy,
)

from dropin.core.models import AppPackageInfo


def _format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "Unknown size"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def _short_path(path_str: str, max_len: int = 42) -> str:
    """Compact path for display; full string stays in tooltip."""
    if len(path_str) <= max_len:
        return path_str
    p = Path(path_str)
    name = p.name
    parent = str(p.parent)
    keep = max_len - len(name) - 5
    if keep < 8:
        return f"…/{name}"
    return f"{parent[: keep // 2]}…{parent[-(keep // 2) :]}/{name}"


class ProgressView(QWidget):
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._package: Optional[AppPackageInfo] = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("cardFrame")
        self.card.setGraphicsEffect(None)
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        # Name
        self.name_label = QLabel("Installing…", self.card)
        self.name_label.setWordWrap(True)
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.name_label.setStyleSheet(
            "font-size: 14px; font-weight: 700; background: transparent;"
        )
        card_layout.addWidget(self.name_label)

        # Badges + size on one wrapping row — wrap instead of overflowing.
        badges = QHBoxLayout()
        badges.setContentsMargins(0, 0, 0, 0)
        badges.setSpacing(4)
        self.version_label = QLabel("", self.card)
        self.version_label.setObjectName("versionBadge")
        self.version_label.setWordWrap(True)
        badges.addWidget(self.version_label)
        self.format_label = QLabel("", self.card)
        self.format_label.setObjectName("formatBadge")
        self.format_label.setWordWrap(True)
        badges.addWidget(self.format_label)
        self.arch_label = QLabel("", self.card)
        self.arch_label.setObjectName("versionBadge")
        self.arch_label.setWordWrap(True)
        badges.addWidget(self.arch_label)
        self.size_label = QLabel("", self.card)
        self.size_label.setObjectName("mutedLabel")
        self.size_label.setStyleSheet("font-size: 11px; background: transparent;")
        self.size_label.setWordWrap(True)
        badges.addWidget(self.size_label)
        badges.addStretch(1)
        card_layout.addLayout(badges)

        # Path (wrapped / shortened — no horizontal scroll)
        self.meta_label = QLabel("", self.card)
        self.meta_label.setObjectName("mutedLabel")
        self.meta_label.setWordWrap(True)
        self.meta_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.meta_label.setStyleSheet("font-size: 10px; background: transparent;")
        self.meta_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        card_layout.addWidget(self.meta_label)

        # Status
        self.status_label = QLabel("Preparing…", self.card)
        self.status_label.setObjectName("subtitleLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.status_label.setStyleSheet("font-size: 12px; background: transparent;")
        card_layout.addWidget(self.status_label)

        # Bar + percent
        pct_row = QHBoxLayout()
        pct_row.setContentsMargins(0, 0, 0, 0)
        pct_row.setSpacing(6)
        self.progress_bar = QProgressBar(self.card)
        self.progress_bar.setRange(1, 100)
        self.progress_bar.setValue(1)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        pct_row.addWidget(self.progress_bar, 1)

        self.percent_label = QLabel("1%", self.card)
        self.percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.percent_label.setFixedWidth(40)
        self.percent_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; background: transparent;"
        )
        pct_row.addWidget(self.percent_label)
        card_layout.addLayout(pct_row)

        self.detail_label = QLabel("", self.card)
        self.detail_label.setObjectName("mutedLabel")
        self.detail_label.setWordWrap(True)
        self.detail_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.detail_label.setStyleSheet("font-size: 10px; background: transparent;")
        card_layout.addWidget(self.detail_label)

        self.cancel_btn = QPushButton("Cancel", self.card)
        self.cancel_btn.setObjectName("compactBtn")
        self.cancel_btn.setFixedHeight(28)
        self.cancel_btn.setFixedWidth(88)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        card_layout.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self.title_label = self.name_label
        layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)

    def sizeHint(self) -> QSize:
        return QSize(440, 320)

    def set_package(self, info: Optional[AppPackageInfo]) -> None:
        """Bind package identity shown above the progress bar."""
        self._package = info
        if info is None:
            self.name_label.setText("Working…")
            for lbl in (
                self.version_label,
                self.format_label,
                self.arch_label,
                self.size_label,
                self.meta_label,
            ):
                lbl.setText("")
                lbl.hide()
            return

        self.name_label.setText(info.name or "Application")
        self.version_label.setText(f"v{info.version}" if info.version else "")
        self.version_label.setVisible(bool(info.version))
        self.format_label.setText(info.format.value if info.format else "")
        self.format_label.setVisible(bool(info.format))
        self.arch_label.setText(info.architecture or "")
        self.arch_label.setVisible(bool(info.architecture))

        size_txt = _format_size(info.size_bytes)
        self.size_label.setText(f"· {size_txt}")
        self.size_label.setVisible(True)

        path_str = info.file_path or info.target_destination or ""
        if path_str:
            short = _short_path(path_str)
            self.meta_label.setText(short)
            self.meta_label.setToolTip(path_str)
            self.meta_label.setVisible(True)
        else:
            self.meta_label.setText("")
            self.meta_label.setToolTip("")
            self.meta_label.hide()

        self.card.setGraphicsEffect(None)
        self.setGraphicsEffect(None)
        self.update()

    def set_operation(
        self,
        title: str,
        status: str,
        percent: int = 0,
        detail: str = "",
        can_cancel: bool = True,
        package: Optional[AppPackageInfo] = None,
    ):
        """Update progress; percent is always shown as 1–100."""
        if package is not None:
            self.set_package(package)
        elif title and not (self._package and self._package.name):
            clean = title.replace("Installing ", "").replace("Downloading ", "")
            if clean and clean != self.name_label.text():
                self.name_label.setText(clean)

        self.status_label.setText(status or "")
        self.detail_label.setText(detail or "")
        self.detail_label.setVisible(bool(detail))

        shown = 1 if percent < 1 else min(100, int(percent))
        self.progress_bar.setRange(1, 100)
        self.progress_bar.setValue(shown)
        self.progress_bar.setTextVisible(False)
        self.percent_label.setText(f"{shown}%")

        self.cancel_btn.setVisible(can_cancel)
        self.card.setGraphicsEffect(None)
        self.setGraphicsEffect(None)
        self.repaint()
