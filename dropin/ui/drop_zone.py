"""
Drag and Drop zone component for Dropin.
Provides clear visual cues, drop handling, and accessible file browsing fallback.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QAbstractAnimation, QSize
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QSizePolicy,
    QGraphicsOpacityEffect,
)

from dropin.ui.icons import icon_for


class DropZone(QFrame):
    """Interactive drag-and-drop landing area."""

    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pulse: Optional[QPropertyAnimation] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 24, 20, 24)

        self.icon_label = QLabel(self)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent;")
        self.icon_label.setPixmap(icon_for("download", size=96).pixmap(QSize(40, 40)))
        layout.addWidget(self.icon_label)

        self.primary_label = QLabel("Drop an application file here", self)
        self.primary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.primary_label.setStyleSheet(
            "font-size: 15px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(self.primary_label)

        self.sub_label = QLabel(
            "AppImage · DEB · RPM · Flatpak · portable archives", self
        )
        self.sub_label.setObjectName("mutedLabel")
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)

        self.browse_btn = QPushButton("Browse files…", self)
        self.browse_btn.setObjectName("compactBtn")
        self.browse_btn.setFixedWidth(140)
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._on_browse_clicked)
        layout.addWidget(self.browse_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _set_drag_active(self, active: bool):
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        if active:
            self._start_pulse()
            self.primary_label.setText("Release to install")
        else:
            self._stop_pulse()
            self.primary_label.setText("Drop an application file here")

    def _start_pulse(self):
        self._stop_pulse()
        effect = QGraphicsOpacityEffect(self.icon_label)
        self.icon_label.setGraphicsEffect(effect)
        self._pulse = QPropertyAnimation(effect, b"opacity", self)
        self._pulse.setDuration(700)
        self._pulse.setStartValue(0.5)
        self._pulse.setEndValue(1.0)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self._pulse.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    def _stop_pulse(self):
        if self._pulse is not None:
            self._pulse.stop()
            self._pulse = None
        self.icon_label.setGraphicsEffect(None)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                event.acceptProposedAction()
                self._set_drag_active(True)
                return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            local_path = urls[0].toLocalFile()
            event.acceptProposedAction()
            self.file_selected.emit(local_path)
        else:
            event.ignore()

    def _on_browse_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Application Package",
            str(Path.home()),
            "Supported Packages (*.AppImage *.deb *.rpm *.flatpakref *.flatpak *.tar.gz *.tar.xz *.zip);;All Files (*)",
        )
        if file_path:
            self.file_selected.emit(file_path)
