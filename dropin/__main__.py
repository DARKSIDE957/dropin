"""
Dropin application entry point.
"""

import sys
import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

from dropin import __version__, __app_name__, __app_id__
from dropin.core.logger import get_logger
from dropin.ui.main_window import MainWindow
from dropin.ui.theme import apply_system_theme


def main():
    parser = argparse.ArgumentParser(
        prog="dropin",
        description="Dropin — Universal Linux Application Installer & Update Manager"
    )
    parser.add_argument(
        "--version", action="version", version=f"{__app_name__} {__version__}"
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Optional path to package file (.AppImage, .deb, .rpm, .flatpakref) or URL to install"
    )

    args = parser.parse_args()

    # Enable high DPI scaling attributes if available
    QApplication.setApplicationName(__app_name__)
    QApplication.setApplicationVersion(__version__)
    QApplication.setOrganizationDomain("dropin.io")
    QApplication.setOrganizationName("Dropin")
    QApplication.setDesktopFileName(f"{__app_id__}.desktop")

    app = QApplication(sys.argv)
    apply_system_theme(app)

    # Set Application Icon
    icon_path = Path(__file__).resolve().parent / "assets" / "io.dropin.Dropin.svg"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()

    # Keep Dropin in sync when the desktop theme/palette changes
    def _on_palette_changed(*_args):
        apply_system_theme(app)
        apply_system_theme(window)

    try:
        app.paletteChanged.connect(_on_palette_changed)
    except Exception:
        pass
    try:
        if hasattr(app.styleHints(), "colorSchemeChanged"):
            app.styleHints().colorSchemeChanged.connect(_on_palette_changed)
    except Exception:
        pass

    # If target passed via CLI
    if args.target:
        target_str = args.target.strip()
        if target_str.startswith("http://") or target_str.startswith("https://"):
            window.url_input.setText(target_str)
            window._handle_url_input()
        elif Path(target_str).is_file():
            window._handle_file_input(target_str)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
