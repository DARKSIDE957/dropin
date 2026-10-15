#!/usr/bin/env bash
# Install Dropin for the current user (or system-wide with --system).
# Installs Python dependencies from requirements.txt, copies the app, and
# registers the desktop entry so Dropin appears in the app menu.
set -e

APP_NAME="Dropin"
APP_ID="io.dropin.Dropin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

MODE="user"

for arg in "$@"; do
    case "$arg" in
        --system) MODE="system" ;;
        --user) MODE="user" ;;
        --help|-h)
            echo "Usage: ./install.sh [--user|--system]"
            echo ""
            echo "What this does:"
            echo "  1. Checks for Python 3"
            echo "  2. Installs dependencies from requirements.txt (PySide6, packaging)"
            echo "  3. Copies Dropin into ~/.local (or /usr/local with --system)"
            echo "  4. Adds a launcher so Dropin appears in your app menu"
            echo ""
            echo "Options:"
            echo "  --user    Install for your account only (default, no root)"
            echo "  --system  Install for all users (needs sudo)"
            echo ""
            echo "To remove Dropin later, run: ./uninstall.sh"
            exit 0
            ;;
        --uninstall)
            echo -e "${YELLOW}Uninstall moved to a separate script.${NC}"
            echo "Run: ./uninstall.sh"
            exit 1
            ;;
        *)
            echo -e "${RED}Unknown option: $arg${NC}" >&2
            echo "Try: ./install.sh --help"
            exit 1
            ;;
    esac
done

if [ "$MODE" = "system" ]; then
    PREFIX="/usr/local"
    BIN_DIR="$PREFIX/bin"
    APP_LIB_DIR="$PREFIX/lib/dropin"
    DESKTOP_DIR="$PREFIX/share/applications"
    ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"
    METAINFO_DIR="$PREFIX/share/metainfo"
else
    PREFIX="$HOME/.local"
    BIN_DIR="$PREFIX/bin"
    APP_LIB_DIR="$PREFIX/share/dropin/app"
    DESKTOP_DIR="$PREFIX/share/applications"
    ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"
    METAINFO_DIR="$PREFIX/share/metainfo"
fi

echo -e "${CYAN}${BOLD}"
echo "  Dropin installer"
echo -e "${NC}"

echo -e "${BLUE}1/4  Checking Python…${NC}"
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}Python 3 is required but was not found.${NC}"
    echo "Install python3 with your distribution’s package manager, then run this again."
    exit 1
fi
PY_VER=$(python3 -c "import sys; print('.'.join(map(str, sys.version_info[:2])))")
echo "     Python $PY_VER"

echo -e "${BLUE}2/4  Installing requirements…${NC}"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    echo -e "${RED}requirements.txt not found next to install.sh${NC}"
    exit 1
fi

PIP_CMD=()
if python3 -m pip --version >/dev/null 2>&1; then
    PIP_CMD=(python3 -m pip)
elif command -v pip3 >/dev/null 2>&1; then
    PIP_CMD=(pip3)
else
    echo -e "${RED}pip is not available.${NC}"
    echo "Install python3-pip, then run ./install.sh again."
    exit 1
fi

PIP_FLAGS=(install)
if [ "$MODE" = "user" ]; then
    PIP_FLAGS+=(--user)
fi
PIP_FLAGS+=(-r "$REQ_FILE")

if ! "${PIP_CMD[@]}" "${PIP_FLAGS[@]}"; then
    echo -e "${YELLOW}pip install failed. Trying distribution packages as a fallback…${NC}"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y python3-pyside6.qtwidgets python3-packaging 2>/dev/null \
            || sudo apt-get install -y python3-pyside6 python3-packaging || true
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3-pyside6 python3-packaging || true
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm python-pyside6 python-packaging || true
    fi
fi

if ! python3 -c "import PySide6" >/dev/null 2>&1; then
    echo -e "${RED}Could not install PySide6 automatically.${NC}"
    echo "Install it with your package manager, for example:"
    echo "  Debian/Ubuntu:  sudo apt install python3-pyside6"
    echo "  Fedora:         sudo dnf install python3-pyside6"
    echo "  Arch:           sudo pacman -S python-pyside6"
    exit 1
fi
echo "     Dependencies ready"

echo -e "${BLUE}3/4  Copying Dropin…${NC}"
mkdir -p "$BIN_DIR" "$APP_LIB_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$METAINFO_DIR"
rm -rf "$APP_LIB_DIR/dropin"
cp -r "$SCRIPT_DIR/dropin" "$APP_LIB_DIR/"

cat << 'EOF' > "$BIN_DIR/dropin"
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../lib/dropin" 2>/dev/null || cd "$SCRIPT_DIR/../share/dropin/app" 2>/dev/null && pwd)"
if [ -d "$APP_DIR" ]; then
    export PYTHONPATH="$APP_DIR:$PYTHONPATH"
fi
exec python3 -m dropin "$@"
EOF
chmod +x "$BIN_DIR/dropin"

echo -e "${BLUE}4/4  Registering app menu entry…${NC}"
cp "$SCRIPT_DIR/io.dropin.Dropin.desktop" "$DESKTOP_DIR/$APP_ID.desktop"
chmod 644 "$DESKTOP_DIR/$APP_ID.desktop"
cp "$SCRIPT_DIR/dropin/assets/io.dropin.Dropin.svg" "$ICON_DIR/$APP_ID.svg"
chmod 644 "$ICON_DIR/$APP_ID.svg"
cp "$SCRIPT_DIR/io.dropin.Dropin.metainfo.xml" "$METAINFO_DIR/$APP_ID.metainfo.xml"
chmod 644 "$METAINFO_DIR/$APP_ID.metainfo.xml"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true
fi

echo -e "\n${GREEN}${BOLD}Dropin is installed.${NC}"
echo -e "Open it from your app menu, or run: ${CYAN}dropin${NC}"
echo -e "To remove it later: ${CYAN}./uninstall.sh${NC}\n"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo -e "${YELLOW}Note: $BIN_DIR is not in your PATH yet.${NC}"
        echo "The app menu still works. For the terminal command:"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac
