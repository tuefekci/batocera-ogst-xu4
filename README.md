# Batocera OGST Display Driver & Daemon (Odroid XU4)

[![Build Driver](https://github.com/tuefekci/batocera-ogst-xu4/actions/workflows/build.yml/badge.svg)](https://github.com/tuefekci/batocera-ogst-xu4/actions/workflows/build.yml)
[![Platform](https://img.shields.io/badge/Platform-Batocera.linux-blue.svg)](https://batocera.org)
[![Hardware](https://img.shields.io/badge/Hardware-Odroid--XU4%20%2F%20OGST-orange.svg)](https://www.hardkernel.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automated kernel driver builder, patched Device Tree, and display daemon for the **Odroid XU4** housed inside the **Hardkernel OGST (N64-style) Gaming Console Kit** running modern versions of **Batocera Linux** (Linux kernel 6.x mainline).

---

## The Problem

On older Batocera builds (v29–v31 running legacy Linux 4.14 BSP), the front 2.4" TFT screen could be enabled using staging module hacks (`modprobe fbtft_device name=hktft9340 ...`).

When Batocera upgraded the Odroid XU4 to modern upstream **Linux kernel 6.x**, `fbtft_device` was removed from the kernel tree, and the official Batocera build dropped the `fbtft` drivers and disabled the SPI bus. As a result, the front LCD remained completely dark on modern Batocera releases.

## The Solution

This repository provides an automated, self-sustaining pipeline that:
1. **Automatically compiles** the missing `fbtft.ko` and `fb_ili9340.ko` kernel drivers against the exact upstream Batocera kernel version via GitHub Actions.
2. **Patches the Device Tree** (`exynos5422-odroidxu4.dtb`) to enable the hardware SPI1 controller and bind the LCD's GPIO lines (`reset`, `dc`, `led`, `cs`).
3. **Installs a Python 3 display daemon** that delivers 20-second idle system telemetry and dynamically renders scraped game artwork and boxart directly to the front screen while browsing or playing games.

---

## ⚡ Quick Start (1-Command Install)

Connect to your Batocera Odroid XU4 over SSH as `root` and run:

```bash
curl -sSL https://raw.githubusercontent.com/tuefekci/batocera-ogst-xu4/main/install.sh | bash
```

Once the installation finishes, reboot your system:

```bash
reboot
```

---

## 🛡️ Smart Kernel Version Matching

Linux kernel modules (`.ko`) strictly require matching kernel headers (`vermagic`). Loading mismatched kernel drivers can cause instability or kernel panics.

The `install.sh` script automatically:
1. **Inspects your running kernel** via `uname -r` on the Odroid XU4.
2. **Searches published GitHub Releases** for drivers built specifically for your exact kernel version.
3. **Guards against mismatches**: If you are running an older Batocera release for which no driver build exists, the installer will **halt safely** and guide you to update Batocera first via `System Settings -> Updates & Downloads`.

---

## Features

* **Live Telemetry Mode (Idle)**:
  After 20 seconds of inactivity in EmulationStation, the front screen displays:
  * Network IP Address & local time
  * CPU & GPU thermal zone readings
  * CPU clock speed (MHz)
  * External / internal storage free space
* **Active Artwork Mode**:
  * Browsing games in EmulationStation renders high-resolution boxart, marquees, or screenshots directly onto the LCD.
  * Launching a game freezes the active game art on the screen during gameplay until you exit back to the menu.
* **Safe / Non-Destructive**:
  * Your original stock Device Tree is automatically backed up to `/boot/boot/exynos5422-odroidxu4.dtb.stock`.
  * Zero changes to your ROMs, BIOS files, save states, or emulator configs.
* **Self-Updating CI/CD**:
  * Whenever Batocera bumps the kernel version, the GitHub Actions workflow in this repository automatically detects the change, cross-compiles new binaries, and publishes a new release.

---

## ⚠️ Hardware Safety Note

> **CRITICAL POWER REQUIREMENT:** The Odroid XU4 requires **5V DC (4A–6A)** via a 5.5 × 2.1 mm center-positive barrel plug. **Never** connect a 12V adapter (such as bricks from an Odroid-HC2 or external 3.5" HDD enclosure), as it will permanently destroy the SBC.

---

## Uninstallation / Restoring Stock

To remove the display drivers and restore the stock Batocera Device Tree:

```bash
curl -sSL https://raw.githubusercontent.com/tuefekci/batocera-ogst-xu4/main/uninstall.sh | bash
reboot
```

---

## Repository Structure

```text
├── .github/workflows/
│   └── build.yml               # Automated cross-compilation CI/CD pipeline
├── dts/
│   └── ogst-overlay.dtsi       # Device Tree source fragment for the ILI9340 panel
├── scripts/
│   └── ogst_display.py         # Python 3 telemetry & artwork framebuffer daemon
├── install.sh                  # One-line client installation script
├── uninstall.sh                # Client rollback / uninstallation script
├── LICENSE                     # MIT License
└── README.md                   # Documentation
```

---

## License

This project is licensed under the [MIT License](LICENSE).
Kernel drivers and Device Tree bindings are derived from upstream Linux and Hardkernel under GPL-2.0.
