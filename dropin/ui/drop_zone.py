"""
Drag and Drop zone component for Dropin.
Provides clear visual cues, drop handling, and accessible file browsing fallback.
"""

from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QAbstractAnimation, QSize, QUrl
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


def _http_url_from_qurl(url: QUrl) -> Optional[str]:
    """Return an http(s) URL string, or None."""
    if not url.isValid() or url.isEmpty():
        return None
    if url.isLocalFile():
        return None
    scheme = (url.scheme() or "").lower()
    if scheme in ("http", "https"):
        return url.toString()
    return None


def _http_url_from_text(text: str) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None
    # Browsers sometimes drop a bare URL or one wrapped in whitespace/newlines.
    first = text.split()[0] if text.split() else text
    parsed = urlparse(first)
    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
        return first
    return None


def classify_drop_mime(mime) -> Tuple[str, str]:
    """
    Classify drag/drop mime data.

    Returns (kind, value) where kind is:
      - "file": local filesystem path
      - "url": http(s) URL string
      - "reject": human-readable reason
    """
    if mime.hasUrls():
        urls = mime.urls()
        if urls:
            qurl = urls[0]
            if qurl.isLocalFile():
                return "file", qurl.toLocalFile()
            http = _http_url_from_qurl(qurl)
            if http:
                return "url", http
            scheme = (qurl.scheme() or "").lower()
            if scheme == "file":
                # Rare non-local file URL — try toLocalFile / path
                path = qurl.toLocalFile() or unquote(qurl.path())
                if path:
                    return "file", path
            if scheme:
                return (
                    "reject",
                    f"Dropin can’t install from “{scheme}://” links. "
                    "Drop a package file, or use an https:// download / GitHub URL.",
                )
            return (
                "reject",
                "That drop isn’t a package file or download link Dropin can use.",
            )

    if mime.hasText():
        http = _http_url_from_text(mime.text())
        if http:
            return "url", http
        text = (mime.text() or "").strip()
        if text.startswith("/") and Path(text.split("\n", 1)[0].strip()).is_file():
            return "file", text.split("\n", 1)[0].strip()
        if text:
            return (
                "reject",
                "Drop a package file (.AppImage, .deb, .rpm, Flatpak) "
                "or an https:// download / GitHub URL.",
            )

    return (
        "reject",
        "Drop a package file or paste an https:// download / GitHub URL.",
    )


class DropZone(QFrame):
    """Interactive drag-and-drop landing area."""

    file_selected = Signal(str)
    url_dropped = Signal(str)
    drop_rejected = Signal(str)

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
            "AppImage · DEB · RPM · Flatpak · portable archives · or a download URL",
            self,
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
        effect = self.icon_label.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self.icon_label)
            self.icon_label.setGraphicsEffect(effect)
        effect.setOpacity(0.5)
        self._pulse = QPropertyAnimation(effect, b"opacity", self)
        self._pulse.setDuration(700)
        self._pulse.setStartValue(0.5)
        self._pulse.setEndValue(1.0)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self._pulse.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    def _stop_pulse(self):
        # Stop the animation before touching the graphics effect. Clearing the
        # effect while a QPropertyAnimation still owns it can native-crash Qt
        # (common when the user drops a file right after a drag-enter pulse).
        anim = self._pulse
        self._pulse = None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        effect = self.icon_label.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(1.0)

    def _drop_is_acceptable(self, mime) -> bool:
        kind, _ = classify_drop_mime(mime)
        return kind in ("file", "url")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._drop_is_acceptable(event.mimeData()):
            event.acceptProposedAction()
            self._set_drag_active(True)
            return
        # Accept so dropEvent can show feedback instead of a silent ignore.
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
            self._set_drag_active(True)
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self._set_drag_active(False)
        kind, value = classify_drop_mime(event.mimeData())
        if kind == "file":
            event.acceptProposedAction()
            self.file_selected.emit(value)
        elif kind == "url":
            event.acceptProposedAction()
            self.url_dropped.emit(value)
        else:
            event.acceptProposedAction()
            self.drop_rejected.emit(value)

    def _on_browse_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Application Package",
            str(Path.home()),
            "Supported Packages (*.AppImage *.deb *.rpm *.flatpakref *.flatpak *.tar.gz *.tar.xz *.zip);;All Files (*)",
        )
        if file_path:
            self.file_selected.emit(file_path)
