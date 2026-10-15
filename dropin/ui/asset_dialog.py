"""
Asset selection dialog for GitHub releases with multiple compatible packages.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)

from dropin.network.github import GitHubAsset, GitHubReleaseInfo


class AssetListItemWidget(QWidget):
    def __init__(self, asset: GitHubAsset, parent=None):
        super().__init__(parent)
        self.asset = asset
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Name & Arch
        col = QVBoxLayout()
        col.setSpacing(2)

        name_lbl = QLabel(self.asset.name, self)
        name_lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
        col.addWidget(name_lbl)

        size_mb = f"{self.asset.size_bytes / (1024*1024):.1f} MB" if self.asset.size_bytes > 0 else "Unknown size"
        sub_lbl = QLabel(f"Arch: {self.asset.architecture}  ·  Size: {size_mb}", self)
        sub_lbl.setObjectName("mutedLabel")
        col.addWidget(sub_lbl)

        layout.addLayout(col, 1)

        # Format Badge
        badge = QLabel(self.asset.format.value, self)
        badge.setObjectName("formatBadge")
        layout.addWidget(badge)


class AssetSelectionDialog(QDialog):
    def __init__(self, release_info: GitHubReleaseInfo, parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self.selected_asset: GitHubAsset = None
        self.setWindowTitle(f"Select Package — {release_info.repo} {release_info.tag_name}")
        self.setMinimumSize(480, 320)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(f"Multiple compatible packages found for {self.release_info.repo}:", self)
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(title)

        sub = QLabel("Select the package file you wish to download and install:", self)
        sub.setObjectName("mutedLabel")
        layout.addWidget(sub)

        self.list_widget = QListWidget(self)
        for asset in self.release_info.assets:
            item = QListWidgetItem(self.list_widget)
            widget = AssetListItemWidget(asset, self)
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

        self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.select_btn = QPushButton("Select & Continue", self)
        self.select_btn.setObjectName("primaryBtn")
        self.select_btn.clicked.connect(self._on_select)
        btn_row.addWidget(self.select_btn)

        layout.addLayout(btn_row)

    def _on_select(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.release_info.assets):
            self.selected_asset = self.release_info.assets[row]
            self.accept()
