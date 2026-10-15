#!/usr/bin/env bash
# Remove Dropin from this user account (or system-wide with --system).
set -e

APP_ID="io.dropin.Dropin"
MODE="user"

for arg in "$@"; do
    case "$arg" in
        --system) MODE="system" ;;
        --user) MODE="user" ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [--user|--system]"
            echo "  --user    Remove the user install from ~/.local (default)"
            echo "  --system  Remove the system install from /usr/local (needs sudo)"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 1
            ;;
    esac
done

if [ "$MODE" = "system" ]; then
    PREFIX="/usr/local"
else
    PREFIX="${HOME}/.local"
fi

BIN_DIR="$PREFIX/bin"
APP_LIB_DIR="$PREFIX/share/dropin/app"
# Legacy path from older installs
ALT_LIB_DIR="$PREFIX/lib/dropin"
DESKTOP_DIR="$PREFIX/share/applications"
ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"
METAINFO_DIR="$PREFIX/share/metainfo"

echo "Removing Dropin ($MODE)…"

rm -f "$BIN_DIR/dropin"
rm -rf "$APP_LIB_DIR" "$ALT_LIB_DIR"
rm -f "$DESKTOP_DIR/$APP_ID.desktop"
rm -f "$ICON_DIR/$APP_ID.svg"
rm -f "$METAINFO_DIR/$APP_ID.metainfo.xml"
# Clean empty parent if we created it
rmdir "$PREFIX/share/dropin" 2>/dev/null || true

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true
fi

echo "Dropin has been removed."
