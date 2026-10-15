"""
Simple line icons for Dropin header actions.

Drawn with QPainter (no emoji, no decorative gradients) so they match
the system text color and stay readable in light and dark themes.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)


def _ink_color() -> QColor:
    app = QGuiApplication.instance()
    if app is not None:
        return app.palette().color(QPalette.ColorRole.WindowText)
    return QColor("#1c1c1c")


def _pen(color: QColor, width: float = 1.8) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _paint_settings(painter: QPainter, color: QColor, size: int) -> None:
    """Compact gear: ring, hub, and six short teeth."""
    cx = cy = size / 2.0
    stroke = max(1.4, size * 0.075)
    painter.setPen(_pen(color, stroke))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    ring_r = size * 0.22
    hub_r = size * 0.08
    painter.drawEllipse(QPointF(cx, cy), ring_r, ring_r)
    painter.drawEllipse(QPointF(cx, cy), hub_r, hub_r)

    tooth_w = size * 0.1
    tooth_h = size * 0.12
    tooth_y = cy - ring_r - tooth_h + stroke * 0.3
    for i in range(6):
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(i * 60)
        painter.translate(-cx, -cy)
        painter.drawRoundedRect(
            QRectF(cx - tooth_w / 2, tooth_y, tooth_w, tooth_h),
            stroke * 0.4,
            stroke * 0.4,
        )
        painter.restore()


def _paint_apps(painter: QPainter, color: QColor, size: int) -> None:
    """2×2 app grid — opens the installed apps list."""
    painter.setPen(_pen(color, size * 0.07))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pad = size * 0.22
    gap = size * 0.1
    cell = (size - 2 * pad - gap) / 2
    radius = size * 0.06
    for row in range(2):
        for col in range(2):
            x = pad + col * (cell + gap)
            y = pad + row * (cell + gap)
            painter.drawRoundedRect(QRectF(x, y, cell, cell), radius, radius)


def _paint_download(painter: QPainter, color: QColor, size: int) -> None:
    """Tray + arrow for the drop zone."""
    painter.setPen(_pen(color, size * 0.08))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = size / 2
    top = size * 0.22
    tip = size * 0.58
    painter.drawLine(QPointF(cx, top), QPointF(cx, tip))
    painter.drawLine(QPointF(cx - size * 0.14, tip - size * 0.14), QPointF(cx, tip))
    painter.drawLine(QPointF(cx + size * 0.14, tip - size * 0.14), QPointF(cx, tip))
    y = size * 0.72
    path = QPainterPath()
    path.moveTo(size * 0.28, y)
    path.lineTo(size * 0.28, size * 0.82)
    path.lineTo(size * 0.72, size * 0.82)
    path.lineTo(size * 0.72, y)
    painter.drawPath(path)


def _paint_folder(painter: QPainter, color: QColor, size: int) -> None:
    """Folder icon — open list of installable local app files."""
    painter.setPen(_pen(color, size * 0.07))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Tab
    tab = QPainterPath()
    tab.moveTo(size * 0.18, size * 0.32)
    tab.lineTo(size * 0.18, size * 0.28)
    tab.lineTo(size * 0.38, size * 0.28)
    tab.lineTo(size * 0.44, size * 0.34)
    painter.drawPath(tab)
    # Body
    painter.drawRoundedRect(
        QRectF(size * 0.18, size * 0.34, size * 0.64, size * 0.42),
        size * 0.04,
        size * 0.04,
    )


def _render(paint_fn, color: QColor, size: int) -> QPixmap:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint_fn(painter, color, size)
    painter.end()
    return QPixmap.fromImage(image)


def icon_for(name: str, color: QColor | None = None, size: int = 64) -> QIcon:
    """Return a QIcon by name: settings | apps | download | folder."""
    ink = color or _ink_color()
    painters = {
        "settings": _paint_settings,
        "apps": _paint_apps,
        "download": _paint_download,
        "folder": _paint_folder,
    }
    paint_fn = painters.get(name)
    if paint_fn is None:
        return QIcon()

    icon = QIcon()
    for px in sorted({16, 20, 24, 32, 48, 64, size}):
        icon.addPixmap(_render(paint_fn, ink, px))
    return icon


def apply_icon(button, name: str, size: int = 18, *, clear_text: bool = True) -> None:
    """Set a themed line icon on a QAbstractButton."""
    if clear_text:
        button.setText("")
    button.setIcon(icon_for(name, size=max(32, size * 2)))
    button.setIconSize(QSize(size, size))