# Resurrecting the Odroid-XU4 OGST Front LCD on Modern Batocera Linux 6.x

*Published: November 19, 2026*  
*Author: [tuefekci](https://github.com/tuefekci)*  
*Repository: [batocera-ogst-xu4](https://github.com/tuefekci/batocera-ogst-xu4)*

---

## 1. Introduction & The Backstory

Back in the golden era of single-board retro gaming, Hardkernel released the **OGST Gaming Console Kit**—a nostalgic, Nintendo 64-styled shell designed specifically for the Samsung Exynos 5422-powered **Odroid XU4**. Beyond its sleek aesthetic, the crown jewel of the OGST case was its front-facing **2.4-inch color TFT LCD** (320×240 resolution, driven by an **Ilitek ILI9340** controller over a dedicated hardware SPI bus).

![OGST Case & Display Concept](https://raw.githubusercontent.com/tuefekci/batocera-ogst-xu4/main/README.md)

On older retro gaming distributions like Batocera v29 through v31—which ran on Hardkernel's legacy **Linux 4.14 BSP kernel**—enabling the display was straightforward. You could drop a staging module helper into your startup scripts:

```bash
# Legacy Linux 4.14 approach (No longer works)
modprobe fbtft_device name=hktft9340 busnum=1 rotate=270 force32b=1
```

However, as Batocera modernized its platform and upgraded the Odroid XU4 to upstream **Linux kernel 6.6.x (mainline)**, the display broke completely:

1. The kernel staging subsystem completely **deprecated and removed `fbtft_device`**.
2. Batocera’s official upstream kernel configuration **omitted the `fbtft` drivers** (`CONFIG_FB_TFT=n`).
3. The stock Device Tree Blob (`exynos5422-odroidxu4.dtb`) left the **SPI1 hardware bus disabled** (`status = "disabled"`).

For years, users who upgraded past Batocera v31 were greeted with a pitch-black front screen, leading many forum posts to declare: *"The OGST screen is dead on modern Batocera."*

We set out to prove that wrong. Here is the full engineering chronicle of how we diagnosed kernel panics, resolved low-level C struct ABI alignment mismatches, inverted hardware GPIO lines, and built a fully automated, self-updating CI/CD pipeline to bring the OGST display back to life on modern Batocera Linux (v44+).

---

## 2. High-Level Architecture of the Solution

To make the display functional and maintainable across future Batocera updates, we needed a 3-tier architecture:

```
+---------------------------------------------------------------+
|                      Userland Layer                           |
|  - ogst_display.py (Python 3 daemon)                          |
|  - 20s Idle Telemetry (IP, CPU/GPU Temp, Clocks, Storage)     |
|  - EmulationStation Scraped Artwork & In-Game Boxart Hooks    |
+---------------------------------------------------------------+
                               |
+---------------------------------------------------------------+
|                    System & Device Tree                       |
|  - Batocera v44 User Services (/userdata/system/services/)    |
|  - Patched exynos5422-odroidxu4.dtb                           |
|    * Activates &spi_1 at 32 MHz                               |
|    * Maps GPIOs (Reset: GPX1_5, DC: GPX1_6, LED: GPX1_2)      |
+---------------------------------------------------------------+
                               |
+---------------------------------------------------------------+
|                      Linux Kernel Layer                       |
|  - Cross-compiled ARMv7 out-of-tree kernel modules:           |
|    * fbtft.ko (FrameBuffer Thin Film Transistor core)         |
|    * fb_ili9340.ko (Panel controller driver)                  |
|  - ABI Alignment Patch (Decoupling CONFIG_FB_BACKLIGHT)       |
+---------------------------------------------------------------+
```

To eliminate manual maintenance, everything is built by a GitHub Actions workflow that automatically detects Batocera’s upstream kernel version, fetches the matching kernel sources, applies our patches, cross-compiles the binaries for `armv7l`, and publishes them as versioned GitHub releases.

---

## 3. The 4 Major Engineering Hurdles

Building kernel drivers and Device Tree patches for an embedded SBC looks simple on paper—until you run into the quirks of modern Linux kernel internals. Here are the four deep hurdles we solved.

---

### Hurdle 1: Compiling Out-of-Tree Modules Without `Module.symvers`

When cross-compiling the `drivers/staging/fbtft` subtree on GitHub Actions using `make M=drivers/staging/fbtft`, the build abruptly halted during `modpost`:

```text
WARNING: Module.symvers is missing.
MODPOST drivers/staging/fbtft/Module.symvers
ERROR: modpost: "unregister_framebuffer" [drivers/staging/fbtft/fbtft.ko] undefined!
ERROR: modpost: "vscnprintf" [drivers/staging/fbtft/fbtft.ko] undefined!
ERROR: modpost: "device_property_present" [drivers/staging/fbtft/fbtft.ko] undefined!
...
make[2]: *** [scripts/Makefile.modpost:145: drivers/staging/fbtft/Module.symvers] Error 1
```

#### The Analysis
In Linux 6.x, `modpost` defaults to fatal errors if any symbol referenced by an out-of-tree module cannot be matched against a top-level `Module.symvers` file (which only exists if you compile the entire `vmlinux` kernel image from scratch).

However, an inspection of Batocera’s official `linux-defconfig.config` revealed:
```text
# CONFIG_MODVERSIONS is not set
```
Because Batocera does not enforce symbol CRC versioning (`CONFIG_MODVERSIONS`), modules compiled against matching kernel headers can load cleanly as long as the vermagic string (`6.6.56 SMP preempt mod_unload ARMv7 p2v8`) matches.

#### The Fix
We passed `KBUILD_MODPOST_WARN=1` to the make command:
```bash
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- -j$(nproc) M=drivers/staging/fbtft KBUILD_MODPOST_WARN=1
```
This instructed `modpost` to emit warnings rather than fatal errors, generating intact `.ko` binaries.

---

### Hurdle 2: The Silent Killer — C Struct Layout & ABI Offset Mismatch

Once we transferred the newly compiled `fbtft.ko` and `fb_ili9340.ko` to the Odroid XU4 and loaded them via `insmod`, the kernel triggered an immediate Oops:

```text
[ 8724.105369] fb_ili9340 spi1.0: fbtft_property_value: buswidth = 8
[ 8724.105384] fb_ili9340 spi1.0: fbtft_property_value: rotate = 270
[ 8724.105394] fb_ili9340 spi1.0: fbtft_property_value: fps = 30
[ 8724.105505] ------------[ cut here ]------------
[ 8724.105511] kernel BUG at drivers/video/fbdev/core/fb_defio.c:268!
[ 8724.105520] Internal error: Oops - BUG: 0 [#1] PREEMPT SMP ARM
[ 8724.105675] PC is at fb_deferred_io_init+0x12c/0x164
[ 8724.106272]  fb_deferred_io_init from fbtft_framebuffer_alloc+0x2b4/0x544 [fbtft]
```

#### The Diagnostic Investigation
Line 268 of `drivers/video/fbdev/core/fb_defio.c` in Linux 6.6 is:
```c
int fb_deferred_io_init(struct fb_info *info)
{
    struct fb_deferred_io *fbdefio = info->fbdefio;
    ...
    BUG_ON(!fbdefio); // Line 268
```
The kernel was panicking because `info->fbdefio` was `NULL`! But inside `drivers/staging/fbtft/fbtft-core.c`, the driver explicitly assigned it immediately before calling `fb_deferred_io_init`:

```c
info->fbops = fbops;
info->fbdefio = fbdefio;  // Explicitly set!
...
fb_deferred_io_init(info); // Crashes with !fbdefio!
```

How could `info->fbdefio` be assigned on one line, yet be read as `NULL` inside the called function?

#### The Discovery: The Invisible 156-Byte Offset Shift
We inspected the definition of `struct fb_info` in `include/linux/fb.h`:

```c
struct fb_info {
    ...
    struct list_head modelist;
    struct fb_videomode *mode;

#if IS_ENABLED(CONFIG_FB_BACKLIGHT)
    /* assigned backlight device */
    struct backlight_device *bl_dev;
    struct mutex bl_curve_mutex;
    u8 bl_curve[FB_BACKLIGHT_LEVELS]; /* 128 bytes */
#endif

#ifdef CONFIG_FB_DEFERRED_IO
    struct delayed_work deferred_work;
    unsigned long npagerefs;
    struct fb_deferred_io_pageref *pagerefs;
    struct fb_deferred_io *fbdefio;
#endif
    ...
};
```

Notice the conditional compilation:
1. In `drivers/staging/fbtft/Kconfig`, upstream Linux has:
   ```kconfig
   menuconfig FB_TFT
       tristate "Support for small TFT LCD display modules"
       select FB_BACKLIGHT  # <--- FORCED CONFIG_FB_BACKLIGHT=y
   ```
2. But in Batocera’s official kernel image (`vmlinux`), **`CONFIG_FB_BACKLIGHT` was NOT set**.

Because `CONFIG_FB_BACKLIGHT` was enabled when building our module, `fbtft.ko` believed `struct fb_info` contained:
* `bl_dev` (4 bytes on ARM32)
* `bl_curve_mutex` (24 bytes)
* `bl_curve[128]` (128 bytes)
* **Total offset shift: 156 bytes!**

When `fbtft.ko` wrote `info->fbdefio = fbdefio`, it wrote to offset `X + 156`. When `fb_deferred_io_init(info)` (compiled into Batocera's core kernel without `CONFIG_FB_BACKLIGHT`) looked for `fbdefio`, it read from offset `X`—where it found `NULL`, triggering the assertion failure!

#### The Patch
We created [`patches/fbtft-abi-fix.patch`](https://github.com/tuefekci/batocera-ogst-xu4/blob/main/patches/fbtft-abi-fix.patch):
1. Stripped `select FB_BACKLIGHT` from `drivers/staging/fbtft/Kconfig`.
2. Moved `struct backlight_device *bl_dev;` into driver-private `struct fbtft_par`.
3. Updated `fbtft-core.c` to use `par->bl_dev` instead of `info->bl_dev`.
4. Enforced `# CONFIG_FB_BACKLIGHT is not set` in the kernel configuration.

With this patch, `struct fb_info` inside `fbtft.ko` matched Batocera’s `vmlinux` layout bit-for-bit. Upon reloading, `fb_deferred_io_init()` succeeded instantly:

```text
[  684.903681] graphics fb1: fb_ili9340 frame buffer, 320x240, 150 KiB video memory, 4 KiB buffer memory, fps=33, spi1.0 at 32 MHz
```

---

### Hurdle 3: Inverted GPIO Polarities (Hardware Reset & Backlight)

With `/dev/fb1` created and test patterns written to the framebuffer without errors, the physical LCD panel was still completely dark.

We inspected the GPIO controller state directly via Linux debugfs:

```bash
mount -t debugfs none /sys/kernel/debug
cat /sys/kernel/debug/gpio
```

```text
gpiochip2: GPIOs 16-23, parent: platform/13400000.pinctrl, gpx1:
 gpio-18  (          |led      ) out lo ACTIVE LOW
 gpio-21  (          |reset    ) out lo 
 gpio-22  (          |dc       ) out hi 
```

The output revealed two major hardware polarity bugs:

#### 1. Hardware Reset Pin (`GPX1_5` / `gpio-21`)
The ILI9340 reset line is **active-low** (`RESET#`). Our initial Device Tree fragment had:
```dts
reset-gpios = <&gpx1 5 0>; /* 0 = GPIO_ACTIVE_HIGH */
```
Because it was marked active-high, `fbtft` deasserted reset by driving the physical pin to `0V`. On active-low hardware, **`0V` held the ILI9340 in permanent hardware reset!**

**Fix**: Changed the flag to `GPIO_ACTIVE_LOW` (`1`):
```dts
reset-gpios = <&gpx1 5 1>; /* Active LOW: deassert drives 3.3V */
```

#### 2. Backlight LED Pin (`GPX1_2` / `gpio-18`)
The OGST case uses an N-channel MOSFET circuit to switch the backlight LEDs. A `HIGH` (`3.3V`) signal turns the backlight ON; a `LOW` (`0V`) signal turns it OFF. Our overlay originally had:
```dts
led-gpios = <&gpx1 2 1>; /* 1 = GPIO_ACTIVE_LOW */
```
The driver wanted the backlight active, so it drove the physical pin to `0V`—turning the backlight transistors completely OFF!

**Fix**: Changed the flag to `GPIO_ACTIVE_HIGH` (`0`):
```dts
led-gpios = <&gpx1 2 0>; /* Active HIGH: active drives 3.3V */
```

#### 3. SPI Timing
We also adjusted `samsung,spi-feedback-delay = <1>;` inside the SPI controller data to match Hardkernel’s hardware timing requirements on the Exynos5422.

---

### Hurdle 4: Batocera v44 Deprecation of `custom.sh`

In older Batocera builds, users put startup commands in `/userdata/system/custom.sh`. But on Batocera v44, running our installer did not load the modules on reboot.

Inspecting `/etc/init.d/S99userservices` revealed the explanation:
```bash
# custom.sh : deprecated in v43
# mv custom.sh to servicedir, only once. If service is already present then ignore whole action
if [[ -f /userdata/system/custom.sh && ! -f /userdata/system/services/custom_service ]]; then
    [[ -d /userdata/system/services ]] || mkdir /userdata/system/services
    mv /userdata/system/custom.sh /userdata/system/services/custom_service
    batocera-services enable custom_service
fi
```
Batocera v43+ migrated `custom.sh` to a managed user service in `/userdata/system/services/custom_service`. If that file already existed from an earlier boot, `/userdata/system/custom.sh` was silently ignored!

**Fix**: We updated `install.sh` to populate `/userdata/system/services/custom_service` and explicitly register it with Batocera's service manager:
```bash
mkdir -p /userdata/system/services
cp /userdata/system/custom.sh /userdata/system/services/custom_service
chmod 755 /userdata/system/services/custom_service
batocera-services enable custom_service
```

---

## 4. The Telemetry & Artwork Display Daemon

With `/dev/fb1` (aliased to `/dev/fb_`) operational, we wrote [`scripts/ogst_display.py`](https://github.com/tuefekci/batocera-ogst-xu4/blob/main/scripts/ogst_display.py), a lightweight, standalone Python 3 daemon tailored for Batocera.

### Features

1. **Idle Telemetry Mode (After 20s of Inactivity)**:
   * **Network Status**: Active local IP address.
   * **System Thermals**: Real-time CPU and GPU thermal zone readings (`/sys/devices/virtual/thermal/thermal_zone*/temp`).
   * **Clock Speed**: Active big.LITTLE CPU frequency in MHz.
   * **Storage**: Free space on both internal storage (`/userdata`) and external storage (`/media/New_Volume`).
   * **Clock**: Digital time display.

2. **Active Artwork Mode (EmulationStation Navigation)**:
   * Connected via event scripts in `/userdata/system/configs/emulationstation/scripts/`:
     * `system-selected/ogst.sh`: Displays console system logos (NES, SNES, N64, Genesis, PSX).
     * `game-selected/ogst.sh`: Renders scraped boxart, marquees, or titlescreen images.
   * Uses `ffmpeg` to scale and convert any image format into RGB565 raw format at hardware speed.

3. **In-Game Lock**:
   * When a game starts (`gameStart`), the display freezes the active game’s cover art on the front LCD during gameplay until you quit back to EmulationStation (`gameStop`).

---

## 5. Smart Version Checking in `install.sh`

Linux kernel modules are strictly bound to their target kernel version. If a user running an older Batocera release (e.g. Linux 5.10 or 6.1) attempts to load drivers compiled against 6.6.56, it will fail or cause instability.

To solve this, `install.sh` includes an automatic safety check:
1. Queries the local running kernel:
   ```bash
   LOCAL_KVER=$(uname -r | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+')
   ```
2. Checks GitHub Releases for a version built specifically for `v${LOCAL_KVER}`:
   `https://github.com/tuefekci/batocera-ogst-xu4/releases/download/v${LOCAL_KVER}/...`
3. If no matching build exists, the installer **halts safely** without touching `/boot` and directs the user to update their Batocera installation:
   ```text
   =====================================================
   [ERROR] Incompatible Batocera Kernel Version!
   =====================================================
   Your Odroid XU4 is currently running: Linux 6.1.x
   Available compiled driver versions:   v6.6.56

   Kernel display modules (.ko) must strictly match your running kernel.
   Please update Batocera in System Settings -> Updates & Downloads.
   =====================================================
   ```

---

## 6. How to Install on Your Console

Connect to your Batocera Odroid XU4 via SSH as `root` (password: `linux`) and run:

```bash
curl -sSL https://raw.githubusercontent.com/tuefekci/batocera-ogst-xu4/main/install.sh | bash
```

Once installation finishes, power-cycle your console (unplug the 5V barrel power plug for 3 seconds and plug it back in to bypass the Odroid XU4 warm-reboot PMIC quirk).

### Uninstallation / Rollback
To restore your stock Device Tree and remove all scripts:
```bash
curl -sSL https://raw.githubusercontent.com/tuefekci/batocera-ogst-xu4/main/uninstall.sh | bash
```

---

## 7. Key Takeaways & Lessons Learned

1. **Beware of Out-of-Tree Kconfig `select`s**: When building kernel modules against an existing kernel binary, a single `select` directive in Kconfig can enable conditional fields inside shared kernel structures (`struct fb_info`), shifting memory offsets by dozens of bytes and causing silent memory corruption.
2. **Always Verify GPIO Logic Levels Against Schematics**: Never assume a pin labeled "reset" or "led" is active-high. Active-low reset lines and N-channel transistor gates require exact Device Tree flags (`GPIO_ACTIVE_LOW` vs `GPIO_ACTIVE_HIGH`).
3. **Inspect OS Init Evolution**: When migrating across major distribution releases (e.g., Batocera v31 → v44), check how startup scripts are orchestrated. What used to be `/etc/init.d/` or `custom.sh` may have transitioned to managed service runners like `batocera-services`.

---

*All source code, patches, and build workflows are available on GitHub: [https://github.com/tuefekci/batocera-ogst-xu4](https://github.com/tuefekci/batocera-ogst-xu4)*
