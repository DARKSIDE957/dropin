"""
Lightweight UI motion helpers for Dropin.
Uses short opacity and geometry animations — presence, not noise.
"""

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    QAbstractAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


_ACTIVE: list = []


def _track(anim) -> None:
    """Keep a reference so GC does not stop the animation mid-flight."""
    _ACTIVE.append(anim)

    def _cleanup():
        if anim in _ACTIVE:
            _ACTIVE.remove(anim)

    anim.finished.connect(_cleanup)


def fade_in(widget: QWidget, duration: int = 220, from_y: int = 8) -> None:
    """Fade a widget in with a subtle upward settle."""
    if widget is None:
        return

    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    effect.setOpacity(0.0)
    start_pos = widget.pos()
    widget.move(start_pos.x(), start_pos.y() + from_y)

    opacity = QPropertyAnimation(effect, b"opacity", widget)
    opacity.setDuration(duration)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(QEasingCurve.Type.OutCubic)

    slide = QPropertyAnimation(widget, b"pos", widget)
    slide.setDuration(duration)
    slide.setStartValue(QPoint(start_pos.x(), start_pos.y() + from_y))
    slide.setEndValue(start_pos)
    slide.setEasingCurve(QEasingCurve.Type.OutCubic)

    group = QParallelAnimationGroup(widget)
    group.addAnimation(opacity)
    group.addAnimation(slide)
    _track(group)
    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def fade_widget(widget: QWidget, duration: int = 180) -> None:
    """Simple opacity fade-in without geometry shift (safer inside layouts)."""
    if widget is None:
        return

    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    effect.setOpacity(0.05)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.05)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    _track(anim)
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def pulse_opacity(widget: QWidget, duration: int = 900) -> Optional[QPropertyAnimation]:
    """Soft looping pulse — used for progress / waiting states."""
    if widget is None:
        return None

    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.45)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)
    anim.setLoopCount(-1)
    _track(anim)
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    return anim


def stop_pulse(anim: Optional[QPropertyAnimation], widget: Optional[QWidget] = None) -> None:
    if anim is not None:
        anim.stop()
        if anim in _ACTIVE:
            _ACTIVE.remove(anim)
    if widget is not None:
        effect = widget.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(1.0)
