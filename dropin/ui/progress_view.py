"""
Installation and download progress view for Dropin.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal, QPropertyAnimation
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QFrame,
)

from dropin.ui.animations import fade_widget, pulse_opacity, stop_pulse


class ProgressView(QWidget):
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pulse_anim: Optional[QPropertyAnimation] = None
        self._last_title = ""
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.card = QFrame(self)
        self.card.setObjectName("cardFrame")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 28, 24, 28)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("Installing Application", self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
        card_layout.addWidget(self.title_label)

        self.status_label = QLabel("Preparing installation...", self)
        self.status_label.setObjectName("subtitleLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(True)
        card_layout.addWidget(self.progress_bar)

        self.detail_label = QLabel("", self)
        self.detail_label.setObjectName("mutedLabel")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        card_layout.addWidget(self.detail_label)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setFixedWidth(110)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        card_layout.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.card)

    def set_operation(
        self,
        title: str,
        status: str,
        percent: int = 0,
        detail: str = "",
        can_cancel: bool = True,
    ):
        is_new = title != self._last_title
        self._last_title = title

        self.title_label.setText(title)
        self.status_label.setText(status)
        self.detail_label.setText(detail)

        if percent < 0:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setTextVisible(False)
            if self._pulse_anim is None:
                self._pulse_anim = pulse_opacity(self.status_label)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(max(0, min(100, percent)))
            self.progress_bar.setTextVisible(True)
            stop_pulse(self._pulse_anim, self.status_label)
            self._pulse_anim = None

        self.cancel_btn.setVisible(can_cancel)

        if is_new:
            fade_widget(self.card, 180)
