#!/bin/bash
# ==============================================================================
# Batocera OGST N64 Front LCD Installer
# Target: Odroid-XU4 running Batocera Linux
# Repository: https://github.com/tuefekci/batocera-ogst-xu4
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}=====================================================${NC}"
echo -e "${BLUE}   Batocera OGST Display Driver & Daemon Installer   ${NC}"
echo -e "${BLUE}   Hardware: Odroid XU4 in OGST N64 Console Case     ${NC}"
echo -e "${BLUE}=====================================================${NC}"

# Check for root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR] Please run this installer as root (e.g., via SSH as root).${NC}"
    exit 1
fi

# Check architecture
ARCH=$(uname -m)
if [ "$ARCH" != "armv7l" ]; then
    echo -e "${RED}[ERROR] Unsupported architecture: $ARCH (expected armv7l on Odroid-XU4).${NC}"
    exit 1
fi

REPO="tuefekci/batocera-ogst-xu4"
TMP_DIR="/tmp/ogst_install"
MODULES_DIR="/userdata/system/modules"
ES_SCRIPTS="/userdata/system/configs/emulationstation/scripts"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR" "$MODULES_DIR" "$ES_SCRIPTS/system-selected" "$ES_SCRIPTS/game-selected" "$ES_SCRIPTS/screensaver-start" /userdata/system/scripts

echo -e "\n${YELLOW}[1/6] Fetching latest release from GitHub...${NC}"
LATEST_URL=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" | grep "browser_download_url.*batocera-ogst-xu4.*\.tar\.gz" | cut -d '"' -f 4)

if [ -z "$LATEST_URL" ]; then
    echo -e "${YELLOW}[!] No GitHub Release asset found yet. Downloading direct repository scripts...${NC}"
    curl -sSL "https://raw.githubusercontent.com/$REPO/main/scripts/ogst_display.py" -o /userdata/system/ogst_display.py
else
    echo -e "${GREEN}[+] Downloading release archive: $LATEST_URL${NC}"
    curl -sSL "$LATEST_URL" -o "$TMP_DIR/release.tar.gz"
    tar -xzf "$TMP_DIR/release.tar.gz" -C "$TMP_DIR"

    # Install Kernel Modules
    if [ -f "$TMP_DIR/fbtft.ko" ] && [ -f "$TMP_DIR/fb_ili9340.ko" ]; then
        echo -e "${YELLOW}[2/6] Installing kernel modules...${NC}"
        cp "$TMP_DIR/fbtft.ko" "$MODULES_DIR/"
        cp "$TMP_DIR/fb_ili9340.ko" "$MODULES_DIR/"
        chmod 644 "$MODULES_DIR"/*.ko
    fi

    # Install Device Tree
    if [ -f "$TMP_DIR/exynos5422-odroidxu4.dtb" ]; then
        echo -e "${YELLOW}[3/6] Updating Device Tree in /boot...${NC}"
        mount -o remount,rw /boot 2>/dev/null || true
        if [ ! -f /boot/boot/exynos5422-odroidxu4.dtb.stock ]; then
            cp /boot/boot/exynos5422-odroidxu4.dtb /boot/boot/exynos5422-odroidxu4.dtb.stock
            echo -e "${GREEN}[+] Stock DTB backed up to /boot/boot/exynos5422-odroidxu4.dtb.stock${NC}"
        fi
        cp "$TMP_DIR/exynos5422-odroidxu4.dtb" /boot/boot/exynos5422-odroidxu4.dtb
        mount -o remount,ro /boot 2>/dev/null || true
    fi

    if [ -f "$TMP_DIR/ogst_display.py" ]; then
        cp "$TMP_DIR/ogst_display.py" /userdata/system/ogst_display.py
    fi
fi

echo -e "${YELLOW}[4/6] Configuring /userdata/system/ogst_display.py...${NC}"
chmod +x /userdata/system/ogst_display.py

echo -e "${YELLOW}[5/6] Setting up boot script /userdata/system/custom.sh...${NC}"
cat << 'EOF' > /userdata/system/custom.sh
#!/bin/bash

# Load OGST LCD Kernel Modules (if present)
if [ -f /userdata/system/modules/fbtft.ko ]; then
    insmod /userdata/system/modules/fbtft.ko 2>/dev/null || true
fi
if [ -f /userdata/system/modules/fb_ili9340.ko ]; then
    insmod /userdata/system/modules/fb_ili9340.ko 2>/dev/null || true
fi

# Wait up to 5 seconds for framebuffer device
for i in {1..5}; do
    if [ -e /dev/fb1 ]; then
        mv /dev/fb1 /dev/fb_
        break
    fi
    sleep 1
done

# Start display telemetry & artwork daemon
python3 /userdata/system/ogst_display.py daemon &
EOF
chmod 755 /userdata/system/custom.sh

echo -e "${YELLOW}[6/6] Installing EmulationStation event hook scripts...${NC}"
cat << 'EOF' > "$ES_SCRIPTS/system-selected/ogst.sh"
#!/bin/bash
python3 /userdata/system/ogst_display.py art "$1" &
EOF

cat << 'EOF' > "$ES_SCRIPTS/game-selected/ogst.sh"
#!/bin/bash
python3 /userdata/system/ogst_display.py art "$1" "$2" &
EOF

cat << 'EOF' > "$ES_SCRIPTS/screensaver-start/ogst.sh"
#!/bin/bash
rm -f /tmp/ogst/last_activity
python3 /userdata/system/ogst_display.py idle &
EOF

cat << 'EOF' > /userdata/system/scripts/ogst_game.sh
#!/bin/bash
mkdir -p /tmp/ogst
case "$1" in
    gameStart)
        touch /tmp/ogst/in_game
        python3 /userdata/system/ogst_display.py art "$2" "$5" &
        ;;
    gameStop)
        rm -f /tmp/ogst/in_game
        date +%s > /tmp/ogst/last_activity
        ;;
esac
EOF

chmod 755 "$ES_SCRIPTS/system-selected/ogst.sh" \
          "$ES_SCRIPTS/game-selected/ogst.sh" \
          "$ES_SCRIPTS/screensaver-start/ogst.sh" \
          /userdata/system/scripts/ogst_game.sh

rm -rf "$TMP_DIR"

echo -e "\n${GREEN}=====================================================${NC}"
echo -e "${GREEN}   Installation Complete!                           ${NC}"
echo -e "${GREEN}   Please run 'reboot' to activate the display.     ${NC}"
echo -e "${GREEN}=====================================================${NC}"
