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

# Detect running kernel version
LOCAL_KVER=$(uname -r | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' || uname -r | cut -d '-' -f 1)
echo -e "${GREEN}[+] Detected running Batocera Linux kernel: ${YELLOW}$LOCAL_KVER${NC} ($(uname -r))"

REPO="tuefekci/batocera-ogst-xu4"
TMP_DIR="/tmp/ogst_install"
MODULES_DIR="/userdata/system/modules"
ES_SCRIPTS="/userdata/system/configs/emulationstation/scripts"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR" "$MODULES_DIR" "$ES_SCRIPTS/system-selected" "$ES_SCRIPTS/game-selected" "$ES_SCRIPTS/screensaver-start" /userdata/system/scripts

echo -e "\n${YELLOW}[1/6] Searching for matching kernel drivers (v${LOCAL_KVER})...${NC}"

TARGET_URL="https://github.com/$REPO/releases/download/v${LOCAL_KVER}/batocera-ogst-xu4-v${LOCAL_KVER}.tar.gz"

DOWNLOAD_SUCCESS=0
if curl -sSL --fail "$TARGET_URL" -o "$TMP_DIR/release.tar.gz" 2>/dev/null; then
    echo -e "${GREEN}[+] Found exact driver match for kernel v${LOCAL_KVER}!${NC}"
    DOWNLOAD_SUCCESS=1
else
    # Try latest release if it matches the current kernel
    LATEST_JSON=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null || true)
    LATEST_TAG=$(echo "$LATEST_JSON" | grep '"tag_name":' | cut -d '"' -f 4 || true)
    
    if [ "$LATEST_TAG" = "v${LOCAL_KVER}" ]; then
        LATEST_URL="https://github.com/$REPO/releases/latest/download/batocera-ogst-xu4-latest.tar.gz"
        if curl -sSL --fail "$LATEST_URL" -o "$TMP_DIR/release.tar.gz" 2>/dev/null; then
            echo -e "${GREEN}[+] Found matching latest release ($LATEST_TAG)!${NC}"
            DOWNLOAD_SUCCESS=1
        fi
    fi
fi

if [ "$DOWNLOAD_SUCCESS" -ne 1 ]; then
    RELEASES_LIST=$(curl -s "https://api.github.com/repos/$REPO/releases" 2>/dev/null | grep '"tag_name":' | cut -d '"' -f 4 | tr '\n' ' ' || true)
    
    echo -e "\n${RED}=====================================================${NC}"
    echo -e "${RED}[ERROR] Incompatible Batocera Kernel Version!${NC}"
    echo -e "${RED}=====================================================${NC}"
    echo -e "Your Odroid XU4 is currently running: ${YELLOW}Linux $LOCAL_KVER${NC}"
    if [ -n "$RELEASES_LIST" ]; then
        echo -e "Available compiled driver versions:   ${GREEN}$RELEASES_LIST${NC}"
    fi
    echo -e "\nKernel display modules (.ko) must strictly match your running kernel."
    echo -e "No matching precompiled driver was found for version ${YELLOW}$LOCAL_KVER${NC}."
    echo -e "\n${BLUE}[ACTION REQUIRED]${NC}"
    echo -e "Please update Batocera to the latest version before installing the display drivers:"
    echo -e "  1. On your controller, open the Batocera Main Menu (START / Space)"
    echo -e "  2. Navigate to:  ${YELLOW}System Settings -> Updates & Downloads${NC}"
    echo -e "  3. Select ${YELLOW}START UPDATE${NC} and wait for the system to reboot"
    echo -e "  4. Once updated, run this installer command again."
    echo -e "\nAlternatively, you can trigger a build for kernel $LOCAL_KVER via GitHub Actions:"
    echo -e "  ${BLUE}https://github.com/$REPO/actions/workflows/build.yml${NC}"
    echo -e "${RED}=====================================================${NC}\n"
    rm -rf "$TMP_DIR"
    exit 1
fi

echo -e "${GREEN}[+] Unpacking release archive...${NC}"
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
