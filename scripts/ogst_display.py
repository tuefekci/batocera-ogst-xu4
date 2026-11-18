#!/usr/bin/env python3
"""
OGST Front LCD Display Daemon & Artwork Renderer
Designed for Batocera Linux on Odroid XU4 (OGST N64 Console Case)
"""

import glob
import os
import socket
import struct
import subprocess
import sys
import time

# Framebuffer device (/dev/fb_ after custom.sh rename, or /dev/fb1)
FB_DEV = "/dev/fb_" if os.path.exists("/dev/fb_") else "/dev/fb1"
STATE_DIR = "/tmp/ogst"
ACTIVITY_FILE = f"{STATE_DIR}/last_activity"
INGAME_FILE = f"{STATE_DIR}/in_game"
IDLE_TIMEOUT = 20

FONT = {
    ' ': [0,0,0,0,0], '!': [4,4,4,0,4], '-': [0,0,14,0,0], '.': [0,0,0,0,4],
    ':': [0,4,0,4,0], '/': [1,2,4,8,16], '%': [17,2,4,8,17], '(': [2,4,4,4,2],
    ')': [8,4,4,4,8], '_': [0,0,0,0,31],
    '0': [14,17,17,17,14], '1': [4,12,4,4,14], '2': [14,17,2,4,31],
    '3': [30,1,14,1,30], '4': [2,6,10,31,2], '5': [31,16,30,1,30],
    '6': [14,16,30,17,14], '7': [31,1,2,4,4], '8': [14,17,14,17,14],
    '9': [14,17,15,1,14],
    'A': [14,17,31,17,17], 'B': [30,17,30,17,30], 'C': [14,17,16,17,14],
    'D': [28,18,17,18,28], 'E': [31,16,30,16,31], 'F': [31,16,30,16,16],
    'G': [14,16,23,17,14], 'H': [17,17,31,17,17], 'I': [14,4,4,4,14],
    'J': [7,2,2,18,12], 'K': [17,18,28,18,17], 'L': [16,16,16,16,31],
    'M': [17,27,21,17,17], 'N': [17,25,21,19,17], 'O': [14,17,17,17,14],
    'P': [30,17,30,16,16], 'Q': [14,17,17,21,14], 'R': [30,17,30,18,17],
    'S': [15,16,14,1,30], 'T': [31,4,4,4,4], 'U': [17,17,17,17,14],
    'V': [17,17,17,10,4], 'W': [17,17,21,27,17], 'X': [17,10,4,10,17],
    'Y': [17,10,4,4,4], 'Z': [31,2,4,8,31]
}

def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def render_lines(lines, bg=(10, 12, 18)):
    target_fb = "/dev/fb_" if os.path.exists("/dev/fb_") else "/dev/fb1"
    if not os.path.exists(target_fb):
        return
    w, h = 320, 240
    bg_c = rgb565(*bg)
    buf = bytearray(struct.pack("<H", bg_c) * (w * h))

    def draw_text(x, y, text, scale, color):
        c_bytes = struct.pack("<H", rgb565(*color))
        for ch in text.upper():
            glyph = FONT.get(ch, FONT[' '])
            for row_idx, row_bits in enumerate(glyph):
                for col_idx in range(5):
                    if row_bits & (1 << (4 - col_idx)):
                        for sy in range(scale):
                            py = y + row_idx * scale + sy
                            if 0 <= py < h:
                                for sx in range(scale):
                                    px = x + col_idx * scale + sx
                                    if 0 <= px < w:
                                        off = (py * w + px) * 2
                                        buf[off:off+2] = c_bytes
            x += 6 * scale

    for x, y, text, scale, color in lines:
        draw_text(x, y, text, scale, color)

    try:
        with open(target_fb, "wb") as fb:
            fb.write(buf)
    except Exception:
        pass

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "OFFLINE"

def get_telemetry():
    temps = []
    for p in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        try:
            with open(p) as f:
                temps.append(int(f.read().strip()) // 1000)
        except Exception:
            pass
    max_t = f"{max(temps)}C" if temps else "N/A"
    gpu_t = f"{temps[-1]}C" if len(temps) > 1 else max_t

    try:
        with open("/sys/devices/system/cpu/cpu4/cpufreq/scaling_cur_freq") as f:
            freq = f"{int(f.read().strip()) // 1000} MHZ"
    except Exception:
        freq = "N/A"

    ext_mounts = [m for m in glob.glob("/media/*") if os.path.ismount(m)]
    if ext_mounts:
        try:
            st = os.statvfs(ext_mounts[0])
            free_gb = (st.f_bavail * st.f_frsize) // (1024**3)
            hdd = f"OK ({free_gb}GB FREE)"
        except Exception:
            hdd = "OK"
    else:
        hdd = "NO EXT DRIVE"

    return [
        (12, 12,  "ODROID-XU4 // BATOCERA", 2, (0, 210, 255)),
        (12, 34,  "------------------------", 2, (60, 70, 90)),
        (12, 58,  f"IP:   {get_ip()}", 2, (255, 255, 255)),
        (12, 88,  f"CPU:  {max_t} ({freq})", 2, (100, 255, 140)),
        (12, 118, f"GPU:  {gpu_t}", 2, (100, 255, 140)),
        (12, 148, f"HDD:  {hdd}", 2, (255, 210, 90)),
        (12, 198, f"TIME: {time.strftime('%H:%M:%S')}", 2, (150, 160, 180)),
    ]

def show_art(system_name, rom_path=""):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(ACTIVITY_FILE, "w") as f:
        f.write(str(time.time()))

    candidates = []
    if rom_path:
        rom_dir = os.path.dirname(rom_path)
        stem = os.path.splitext(os.path.basename(rom_path))[0]
        for suffix in ("-marquee", "-image", "-thumb"):
            for ext in ("png", "jpg", "jpeg"):
                candidates.append(f"{rom_dir}/images/{stem}{suffix}.{ext}")
                candidates.append(f"{rom_dir}/media/{suffix[1:]}/{stem}.{ext}")

    for base in ("/userdata/themes", "/usr/share/emulationstation/themes"):
        candidates.extend(glob.glob(f"{base}/*/{system_name}/_inc/*.png"))
        candidates.extend(glob.glob(f"{base}/*/{system_name}/art/*.png"))

    img = next((c for c in candidates if os.path.isfile(c)), None)
    target_fb = "/dev/fb_" if os.path.exists("/dev/fb_") else "/dev/fb1"

    if img and os.path.exists(target_fb):
        subprocess.run([
            "ffmpeg", "-loglevel", "quiet", "-y", "-i", img,
            "-vf", "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2",
            "-pix_fmt", "rgb565le", "-f", "fbdev", target_fb
        ])
    else:
        title = os.path.splitext(os.path.basename(rom_path))[0][:22] if rom_path else ""
        render_lines([
            (16, 40,  "NOW SELECTED", 2, (0, 210, 255)),
            (16, 85,  system_name[:12], 4, (255, 255, 255)),
            (16, 150, title, 2, (255, 210, 90)),
        ], bg=(15, 18, 28))

def daemon():
    os.makedirs(STATE_DIR, exist_ok=True)
    while True:
        if os.path.exists(INGAME_FILE):
            time.sleep(2)
            continue

        last_act = 0
        if os.path.exists(ACTIVITY_FILE):
            try:
                with open(ACTIVITY_FILE) as f:
                    last_act = float(f.read().strip())
            except Exception:
                pass

        if time.time() - last_act < IDLE_TIMEOUT:
            time.sleep(1)
        else:
            render_lines(get_telemetry())
            time.sleep(3)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "idle"
    if cmd == "daemon":
        daemon()
    elif cmd == "art":
        show_art(sys.argv[2] if len(sys.argv) > 2 else "SYSTEM",
                 sys.argv[3] if len(sys.argv) > 3 else "")
    elif cmd == "idle":
        render_lines(get_telemetry())
