#!/bin/bash
# ==============================================================================
# Batocera OGST Display Driver Uninstaller / Restore Stock
# Target: Odroid-XU4 running Batocera Linux
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}=== Uninstalling Batocera OGST Display Drivers ===${NC}"

# Check for root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR] Please run this script as root.${NC}"
    exit 1
fi

# Restore stock Device Tree if backup exists
if [ -f /boot/boot/exynos5422-odroidxu4.dtb.stock ]; then
    echo -e "${YELLOW}[+] Restoring stock Device Tree...${NC}"
    mount -o remount,rw /boot 2>/dev/null || true
    mv /boot/boot/exynos5422-odroidxu4.dtb.stock /boot/boot/exynos5422-odroidxu4.dtb
    mount -o remount,ro /boot 2>/dev/null || true
    echo -e "${GREEN}[+] Stock Device Tree restored.${NC}"
fi

# Remove modules
echo -e "${YELLOW}[+] Removing compiled modules...${NC}"
rm -f /userdata/system/modules/fbtft.ko /userdata/system/modules/fb_ili9340.ko

# Clean hooks
echo -e "${YELLOW}[+] Cleaning hooks and scripts...${NC}"
rm -f /userdata/system/configs/emulationstation/scripts/system-selected/ogst.sh
rm -f /userdata/system/configs/emulationstation/scripts/game-selected/ogst.sh
rm -f /userdata/system/configs/emulationstation/scripts/screensaver-start/ogst.sh
rm -f /userdata/system/scripts/ogst_game.sh
rm -f /userdata/system/ogst_display.py

# Clean services
batocera-services disable custom_service 2>/dev/null || true
rm -f /userdata/system/services/custom_service

# Reset custom.sh
if [ -f /userdata/system/custom.sh ]; then
    sed -i '/ogst/d' /userdata/system/custom.sh
    sed -i '/fbtft/d' /userdata/system/custom.sh
    sed -i '/fb1/d' /userdata/system/custom.sh
fi

echo -e "${GREEN}=== Uninstallation Complete. Please reboot. ===${NC}"
