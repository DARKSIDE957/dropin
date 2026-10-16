"""
Lightweight UI motion helpers for Dropin.

Opacity-based QGraphicsOpacityEffect fades are disabled: on Wayland/KWin they
leave windows blank (QPainter "not active" / stacked painter errors) and
previously blanked the confirmation card. Helpers still exist as no-ops so
call sites keep working.
"""

from typing import Optional

from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


_ACTIVE: list = []


def _clear_opacity_effect(widget: QWidget) -> None:
    """Ensure the widget paints at full opacity with no graphics effect."""
    if widget is None:
        return
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        effect.setOpacity(1.0)
    # Removing the effect avoids Wayland blank-window / QPainter bugs.
    widget.setGraphicsEffect(None)


def fade_in(widget: QWidget, duration: int = 220, from_y: int = 8) -> None:
    """No-op fade — show at full opacity (Wayland-safe)."""
    _clear_opacity_effect(widget)


def fade_widget(widget: QWidget, duration: int = 180) -> None:
    """No-op fade — show at full opacity (Wayland-safe)."""
    _clear_opacity_effect(widget)


def pulse_opacity(widget: QWidget, duration: int = 900) -> Optional[object]:
    """Disabled on this platform — opacity pulses blanked labels."""
    _clear_opacity_effect(widget)
    return None


def stop_pulse(anim: Optional[object] = None, widget: Optional[QWidget] = None) -> None:
    if widget is not None:
        _clear_opacity_effect(widget)
