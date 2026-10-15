"""
Installation result view (Success / Failure) for Dropin.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QTextEdit,
)

from dropin.core.models import InstallResult
from dropin.ui.animations import fade_widget


class ResultView(QWidget):
    launch_requested = Signal()
    done_requested = Signal()
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result: InstallResult = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.card = QFrame(self)
        self.card.setObjectName("cardFrame")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = QLabel("✅", self)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 42px; background: transparent;")
        card_layout.addWidget(self.icon_label)

        self.title_label = QLabel("Installation Complete", self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
        card_layout.addWidget(self.title_label)

        self.message_label = QLabel("The application has been successfully installed.", self)
        self.message_label.setObjectName("subtitleLabel")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        card_layout.addWidget(self.message_label)

        self.details_btn = QPushButton("Show technical details", self)
        self.details_btn.setObjectName("compactBtn")
        self.details_btn.setCheckable(True)
        self.details_btn.setChecked(False)
        self.details_btn.setFixedWidth(190)
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_btn.clicked.connect(self._toggle_details)
        card_layout.addWidget(self.details_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.details_text = QTextEdit(self)
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(90)
        self.details_text.hide()
        card_layout.addWidget(self.details_text)

        self.btn_row = QHBoxLayout()
        self.btn_row.setSpacing(10)

        self.back_btn = QPushButton("Back", self)
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self.back_requested.emit)
        self.btn_row.addWidget(self.back_btn)

        self.launch_btn = QPushButton("Launch", self)
        self.launch_btn.setObjectName("primaryBtn")
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_btn.clicked.connect(self.launch_requested.emit)
        self.btn_row.addWidget(self.launch_btn)

        self.done_btn = QPushButton("Done", self)
        self.done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_btn.clicked.connect(self.done_requested.emit)
        self.btn_row.addWidget(self.done_btn)

        card_layout.addLayout(self.btn_row)
        layout.addWidget(self.card)

    def set_result(self, result: InstallResult, app_name: str = ""):
        self.result = result

        if result.success:
            self.icon_label.setText("✅")
            self.title_label.setText("Installation complete")
            self.title_label.setStyleSheet(
                "font-size: 16px; font-weight: 700; color: #22c55e; background: transparent;"
            )
            msg = result.message or (
                f"{app_name} was installed successfully." if app_name else "The application was installed successfully."
            )
            self.message_label.setText(msg)

            self.details_btn.hide()
            self.details_text.hide()
            self.back_btn.hide()
            self.done_btn.show()

            if result.launch_command or result.installed_path:
                self.launch_btn.show()
            else:
                self.launch_btn.hide()
        else:
            self.icon_label.setText("❌")
            self.title_label.setText("Installation failed")
            self.title_label.setStyleSheet(
                "font-size: 16px; font-weight: 700; color: #f87171; background: transparent;"
            )
            self.message_label.setText(result.message or "Something went wrong during installation.")

            if result.error_details:
                self.details_text.setPlainText(result.error_details)
                self.details_btn.show()
                self.details_btn.setChecked(False)
                self.details_text.hide()
                self.details_btn.setText("Show technical details")
            else:
                self.details_btn.hide()
                self.details_text.hide()

            self.launch_btn.hide()
            self.done_btn.hide()
            self.back_btn.show()

        fade_widget(self.card, 220)

    def _toggle_details(self):
        show = self.details_btn.isChecked()
        self.details_text.setVisible(show)
        self.details_btn.setText("Hide technical details" if show else "Show technical details")
