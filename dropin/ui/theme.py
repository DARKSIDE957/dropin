"""
Theme manager for Dropin.

Builds styles from the live Qt/system palette so Dropin matches the
desktop appearance exactly (Breeze, Adwaita, etc.) — no custom black/white
overrides that look darker or lighter than the system.
"""

from __future__ import annotations

import os
import subprocess
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette


def _hex(color: QColor) -> str:
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Blend color a toward b by t (0..1)."""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _with_alpha_over(fg: QColor, bg: QColor, alpha: float) -> QColor:
    """Approximate fg painted over bg at given alpha."""
    return _mix(bg, fg, alpha)


def is_dark_mode() -> bool:
    """Detect whether system theme is currently dark."""
    app = QGuiApplication.instance()
    if app:
        try:
            hints = app.styleHints()
            if hasattr(hints, "colorScheme"):
                scheme = hints.colorScheme()
                if scheme == Qt.ColorScheme.Dark:
                    return True
                if scheme == Qt.ColorScheme.Light:
                    return False
        except Exception:
            pass

        bg_lum = app.palette().color(QPalette.ColorRole.Window).lightness()
        if bg_lum < 128:
            return True
        if bg_lum > 180:
            return False

    kdeglobals = os.path.expanduser("~/.config/kdeglobals")
    if os.path.isfile(kdeglobals):
        try:
            with open(kdeglobals, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if "ColorScheme=BreezeDark" in content or "ColorScheme=Breeze-Dark" in content:
                    return True
                if "ColorScheme=BreezeLight" in content:
                    return False
        except Exception:
            pass

    try:
        proc = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1,
        )
        out = proc.stdout.lower()
        if "prefer-dark" in out or out.strip() == "'dark'":
            return True
        if "prefer-light" in out:
            return False
    except Exception:
        pass

    return True


def _palette_colors(palette: QPalette | None = None) -> Dict[str, str]:
    """Derive stylesheet tokens from the active system palette."""
    app = QGuiApplication.instance()
    pal = palette or (app.palette() if app else QPalette())

    window = pal.color(QPalette.ColorRole.Window)
    window_text = pal.color(QPalette.ColorRole.WindowText)
    base = pal.color(QPalette.ColorRole.Base)
    alt_base = pal.color(QPalette.ColorRole.AlternateBase)
    text = pal.color(QPalette.ColorRole.Text)
    button = pal.color(QPalette.ColorRole.Button)
    button_text = pal.color(QPalette.ColorRole.ButtonText)
    highlight = pal.color(QPalette.ColorRole.Highlight)
    highlighted_text = pal.color(QPalette.ColorRole.HighlightedText)
    mid = pal.color(QPalette.ColorRole.Mid)
    midlight = pal.color(QPalette.ColorRole.Midlight)
    light = pal.color(QPalette.ColorRole.Light)
    dark = pal.color(QPalette.ColorRole.Dark)
    link = pal.color(QPalette.ColorRole.Link)
    placeholder = pal.color(QPalette.ColorRole.PlaceholderText)

    dark_mode = window.lightness() < 128

    # Borders / hover from real palette midtones — not inventing black.
    border = midlight if dark_mode else _mix(mid, window_text, 0.15)
    border_strong = light if dark_mode else mid
    hover = midlight if dark_mode else _mix(button, window_text, 0.06)
    pressed = mid if dark_mode else _mix(button, window_text, 0.12)
    muted = placeholder if placeholder.isValid() and placeholder.alpha() > 0 else _mix(window_text, window, 0.45)

    # Large surfaces use Window (system chrome gray), never Base/Dark.
    # In Breeze dark, Base (#141618) is nearly black and looks wrong for panels.
    surface = window
    card = window
    drop = window
    drop_active = _with_alpha_over(highlight, window, 0.18)
    list_bg = window
    list_hover = button
    list_selected = _with_alpha_over(highlight, window, 0.28)
    # Inputs/elevated chips sit slightly above the window surface (Button).
    input_bg = button
    header = button

    # Semantic colors kept readable on system surfaces
    if dark_mode:
        danger = QColor("#e74c3c")
        danger_hover = QColor("#c0392b")
        warning_bg = _with_alpha_over(QColor("#e74c3c"), window, 0.18)
        warning_fg = QColor("#f5c6c2")
        warning_border = QColor("#a93226")
        update_bg = _with_alpha_over(QColor("#27ae60"), window, 0.22)
        update_fg = QColor("#a8e6c3")
        format_bg = _with_alpha_over(highlight, window, 0.22)
        format_fg = _mix(highlighted_text, highlight, 0.15)
        details_bg = button
        details_fg = QColor("#f5b7b1")
        success = QColor("#2ecc71")
        fail = QColor("#e74c3c")
    else:
        danger = QColor("#dc2626")
        danger_hover = QColor("#b91c1c")
        warning_bg = QColor("#fef2f2")
        warning_fg = QColor("#991b1b")
        warning_border = QColor("#fca5a5")
        update_bg = QColor("#d1fae5")
        update_fg = QColor("#065f46")
        format_bg = _with_alpha_over(highlight, window, 0.16)
        format_fg = _mix(highlight, QColor("#000000"), 0.45)
        details_bg = QColor("#fff1f2")
        details_fg = QColor("#9f1239")
        success = QColor("#16a34a")
        fail = QColor("#dc2626")

    primary = highlight
    primary_hover = _mix(highlight, QColor("#000000") if not dark_mode else QColor("#ffffff"), 0.12)
    primary_pressed = _mix(highlight, QColor("#000000") if not dark_mode else QColor("#ffffff"), 0.22)
    primary_disabled = _mix(button, muted, 0.5)

    chunk_end = link if link.isValid() else _mix(highlight, QColor("#ffffff"), 0.25)

    return {
        "window": _hex(window),
        "window_text": _hex(window_text),
        "base": _hex(base),
        "alt_base": _hex(alt_base),
        "text": _hex(text),
        "button": _hex(button),
        "button_text": _hex(button_text),
        "highlight": _hex(highlight),
        "highlighted_text": _hex(highlighted_text),
        "border": _hex(border),
        "border_strong": _hex(border_strong),
        "hover": _hex(hover),
        "pressed": _hex(pressed),
        "muted": _hex(muted),
        "card": _hex(card),
        "drop": _hex(drop),
        "drop_active": _hex(drop_active),
        "list_bg": _hex(list_bg),
        "list_hover": _hex(list_hover),
        "list_selected": _hex(list_selected),
        "primary": _hex(primary),
        "primary_hover": _hex(primary_hover),
        "primary_pressed": _hex(primary_pressed),
        "primary_disabled": _hex(primary_disabled),
        "danger": _hex(danger),
        "danger_hover": _hex(danger_hover),
        "warning_bg": _hex(warning_bg),
        "warning_fg": _hex(warning_fg),
        "warning_border": _hex(warning_border),
        "update_bg": _hex(update_bg),
        "update_fg": _hex(update_fg),
        "format_bg": _hex(format_bg),
        "format_fg": _hex(format_fg),
        "details_bg": _hex(details_bg),
        "details_fg": _hex(details_fg),
        "success": _hex(success),
        "fail": _hex(fail),
        "chunk_end": _hex(chunk_end),
        "surface": _hex(surface),
        "header": _hex(header),
        "input_bg": _hex(input_bg),
        "tab_bg": _hex(button),
        "tab_selected": _hex(window),
        "scrollbar": _hex(midlight),
    }


def get_stylesheet(dark: bool | None = None, palette: QPalette | None = None) -> str:
    """
    Stylesheet keyed off the real system palette.

    `dark` is kept for API compatibility with tests; when omitted, darkness
    is inferred from the palette itself.
    """
    c = _palette_colors(palette)
    if dark is None:
        app = QGuiApplication.instance()
        dark = (
            app.palette().color(QPalette.ColorRole.Window).lightness() < 128
            if app
            else True
        )

    # Font stack prefers the desktop's usual UI fonts without forcing a look.
    return f"""
        /* Match Plasma/Breeze window chrome — Window gray, never Base black. */
        QMainWindow, QDialog, QStackedWidget {{
            background-color: {c['window']};
            color: {c['window_text']};
            font-size: 13px;
        }}
        /* Central pane / dialog body must be opaque window gray (transparent = black void). */
        QMainWindow > QWidget, QDialog > QWidget {{
            background-color: {c['window']};
            color: {c['window_text']};
        }}
        QWidget {{
            color: {c['window_text']};
            font-size: 13px;
            background-color: transparent;
        }}
        QLabel {{
            background-color: transparent;
            color: {c['window_text']};
        }}
        QLabel#mutedLabel {{
            color: {c['muted']};
        }}
        QLabel#subtitleLabel {{
            color: {c['muted']};
            font-size: 12px;
        }}
        QLabel#metaKey {{
            color: {c['muted']};
            font-size: 11px;
        }}
        QLabel#metaValue {{
            color: {c['window_text']};
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel#appTitle {{
            font-size: 16px;
            font-weight: 700;
            color: {c['window_text']};
            letter-spacing: 0.3px;
            background: transparent;
        }}
        QLabel#versionBadge {{
            background-color: {c['button']};
            color: {c['muted']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel#formatBadge {{
            background-color: {c['format_bg']};
            color: {c['format_fg']};
            border-radius: 4px;
            padding: 2px 8px;
            font-weight: 600;
            font-size: 11px;
        }}
        QLabel#warningBanner {{
            background-color: {c['warning_bg']};
            color: {c['warning_fg']};
            border: 1px solid {c['warning_border']};
            border-radius: 6px;
            padding: 8px;
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel#updateBadge {{
            background-color: {c['update_bg']};
            color: {c['update_fg']};
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 10px;
            font-weight: bold;
        }}
        QLabel#iconSlot {{
            background-color: {c['button']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            color: {c['window_text']};
        }}

        QFrame#headerFrame {{
            background-color: {c['header']};
            border-bottom: 1px solid {c['border']};
        }}
        QFrame#dropZone {{
            background-color: {c['drop']};
            border: 2px dashed {c['border_strong']};
            border-radius: 12px;
        }}
        QFrame#dropZone[dragActive="true"] {{
            border: 2px dashed {c['highlight']};
            background-color: {c['drop_active']};
        }}
        QFrame#cardFrame {{
            background-color: {c['card']};
            border: 1px solid {c['border']};
            border-radius: 10px;
        }}

        QPushButton {{
            background-color: {c['button']};
            color: {c['button_text']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 7px 14px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {c['hover']};
            border-color: {c['border_strong']};
        }}
        QPushButton:pressed {{
            background-color: {c['pressed']};
        }}
        QPushButton:disabled {{
            background-color: {c['button']};
            color: {c['muted']};
            border-color: {c['border']};
        }}
        QPushButton#primaryBtn {{
            background-color: {c['primary']};
            color: {c['highlighted_text']};
            border: 1px solid {c['primary']};
        }}
        QPushButton#primaryBtn:hover {{
            background-color: {c['primary_hover']};
        }}
        QPushButton#primaryBtn:pressed {{
            background-color: {c['primary_pressed']};
        }}
        QPushButton#primaryBtn:disabled {{
            background-color: {c['primary_disabled']};
            color: {c['muted']};
            border-color: {c['border']};
        }}
        QPushButton#dangerBtn {{
            background-color: {c['danger']};
            color: #ffffff;
            border: 1px solid {c['danger']};
        }}
        QPushButton#dangerBtn:hover {{
            background-color: {c['danger_hover']};
        }}
        QPushButton#headerBtn {{
            padding: 5px 10px;
            font-size: 11px;
        }}
        QPushButton#iconBtn {{
            padding: 0px;
            min-width: 34px;
            min-height: 34px;
            border-radius: 8px;
            background-color: transparent;
            border: 1px solid transparent;
        }}
        QPushButton#iconBtn:hover {{
            background-color: {c['hover']};
            border-color: {c['border']};
        }}
        QPushButton#iconBtn:pressed {{
            background-color: {c['pressed']};
        }}
        QPushButton#compactBtn {{
            padding: 4px 10px;
            font-size: 11px;
        }}

        QLineEdit, QSpinBox {{
            background-color: {c['input_bg']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 6px 10px;
            min-height: 28px;
            selection-background-color: {c['highlight']};
            selection-color: {c['highlighted_text']};
        }}
        QLineEdit:focus, QSpinBox:focus {{
            border: 1px solid {c['highlight']};
            background-color: {c['input_bg']};
        }}

        QProgressBar {{
            background-color: {c['button']};
            border: 1px solid {c['border']};
            border-radius: 5px;
            text-align: center;
            height: 12px;
            color: {c['window_text']};
            font-size: 11px;
            font-weight: 600;
        }}
        QProgressBar::chunk {{
            background-color: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['highlight']},
                stop:1 {c['chunk_end']}
            );
            border-radius: 4px;
        }}

        QListWidget {{
            background-color: {c['list_bg']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            padding: 4px;
            outline: none;
            color: {c['text']};
        }}
        QListWidget::item {{
            border-radius: 6px;
            padding: 4px;
            margin: 2px 0px;
            background: transparent;
        }}
        QListWidget::item:hover {{
            background-color: {c['list_hover']};
        }}
        QListWidget::item:selected {{
            background-color: {c['list_selected']};
            color: {c['window_text']};
        }}

        QTabWidget::pane {{
            border: 1px solid {c['border']};
            border-radius: 8px;
            background-color: {c['window']};
            padding: 10px;
            top: -1px;
        }}
        QTabBar::tab {{
            background: {c['tab_bg']};
            color: {c['muted']};
            padding: 8px 14px;
            margin-right: 4px;
            min-height: 20px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            border: 1px solid {c['border']};
            border-bottom: none;
        }}
        QTabBar::tab:selected {{
            background: {c['tab_selected']};
            color: {c['window_text']};
            font-weight: bold;
        }}
        QTabBar::tab:hover:!selected {{
            color: {c['window_text']};
        }}

        QCheckBox, QRadioButton {{
            color: {c['window_text']};
            spacing: 8px;
            background: transparent;
            min-height: 22px;
            padding: 2px 0px;
        }}
        /* Do not restyle indicator geometry — that clips Breeze radio/checkbox glyphs. */

        QTextEdit {{
            background-color: {c['details_bg']};
            color: {c['details_fg']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            font-family: monospace;
            font-size: 10px;
        }}

        QTableWidget {{
            background-color: {c['list_bg']};
            alternate-background-color: {c['alt_base']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 8px;
            gridline-color: {c['border']};
        }}
        QHeaderView::section {{
            background-color: {c['button']};
            color: {c['window_text']};
            padding: 6px 8px;
            border: none;
            border-right: 1px solid {c['border']};
            border-bottom: 1px solid {c['border']};
            font-weight: 600;
        }}

        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {c['scrollbar']};
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}

        QMessageBox {{
            background-color: {c['window']};
            color: {c['window_text']};
        }}
        QToolTip {{
            background-color: {c['button']};
            color: {c['window_text']};
            border: 1px solid {c['border']};
            padding: 4px 8px;
        }}
    """


def apply_system_theme(widget) -> None:
    """Apply a stylesheet derived from the current system palette."""
    app = QGuiApplication.instance()
    palette = app.palette() if app else None
    dark = is_dark_mode()
    widget.setStyleSheet(get_stylesheet(dark=dark, palette=palette))
