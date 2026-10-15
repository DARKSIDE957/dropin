"""
Security and installation audit log viewer for Dropin.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QLabel,
)

from dropin.core.registry import get_registry


class AuditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Security & Audit Logs — Dropin")
        self.resize(640, 400)
        self.registry = get_registry()
        self._init_ui()
        self.load_logs()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QLabel("Dropin Security & Installation Audit Trail", self)
        header.setStyleSheet("font-size: 14px; font-weight: 700;")
        layout.addWidget(header)

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Timestamp", "Action", "Target", "Status", "Details"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.clicked.connect(self.load_logs)
        btn_row.addWidget(self.refresh_btn)

        self.close_btn = QPushButton("Close", self)
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    def load_logs(self):
        logs = self.registry.get_audit_logs(limit=150)
        self.table.setRowCount(len(logs))
        for row, entry in enumerate(logs):
            self.table.setItem(row, 0, QTableWidgetItem(entry.get("timestamp", "")))
            self.table.setItem(row, 1, QTableWidgetItem(entry.get("action", "")))
            self.table.setItem(row, 2, QTableWidgetItem(entry.get("target", "")))
            status_item = QTableWidgetItem(entry.get("status", ""))
            if entry.get("status") == "SUCCESS":
                status_item.setForeground(Qt.GlobalColor.green)
            elif entry.get("status") == "FAILED":
                status_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 3, status_item)
            self.table.setItem(row, 4, QTableWidgetItem(entry.get("details", "")))
