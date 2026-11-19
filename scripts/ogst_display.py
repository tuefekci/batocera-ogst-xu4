#!/usr/bin/env python3
"""
OGST Front LCD Display Daemon & Multi-Screen Rotating Engine
Designed for Batocera Linux on Odroid XU4 (OGST N64 Console Case)
Screen resolution: 320x240 RGB565 via /dev/fb_ (/dev/fb1)
"""

import io
import json
import os
import signal
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Framebuffer & Path configurations
FB_DEV = "/dev/fb_" if os.path.exists("/dev/fb_") else "/dev/fb1"
STATE_DIR = "/tmp/ogst"
STATE_FILE = f"{STATE_DIR}/state.json"
LAST_GAME_FILE = f"{STATE_DIR}/last_game.json"

FONT_DIR = "/usr/share/fonts/dejavu"
FONT_BOLD = f"{FONT_DIR}/DejaVuSans-Bold.ttf" if os.path.exists(f"{FONT_DIR}/DejaVuSans-Bold.ttf") else None
FONT_REG = f"{FONT_DIR}/DejaVuSans.ttf" if os.path.exists(f"{FONT_DIR}/DejaVuSans.ttf") else None

SYSTEM_NAMES = {
    "dreamcast": "SEGA DREAMCAST",
    "n64": "NINTENDO 64",
    "psx": "SONY PLAYSTATION",
    "ps2": "SONY PLAYSTATION 2",
    "psp": "SONY PSP",
    "snes": "SUPER NINTENDO",
    "nes": "NINTENDO NES",
    "megadrive": "SEGA MEGA DRIVE",
    "genesis": "SEGA GENESIS",
    "saturn": "SEGA SATURN",
    "mastersystem": "SEGA MASTER SYSTEM",
    "gamecube": "NINTENDO GAMECUBE",
    "gba": "GAME BOY ADVANCE",
    "gbc": "GAME BOY COLOR",
    "gb": "NINTENDO GAME BOY",
    "mame": "ARCADE (MAME)",
    "fbneo": "ARCADE (FBNEO)",
    "arcade": "ARCADE",
    "neogeo": "SNK NEO GEO",
    "nds": "NINTENDO DS",
}

# In-memory image cache for fast decoding without disk/ffmpeg re-reads
_IMAGE_CACHE = {}

def get_font(bold=False, size=14):
    fpath = FONT_BOLD if bold else FONT_REG
    if fpath:
        try:
            return ImageFont.truetype(fpath, size)
        except Exception:
            pass
    return ImageFont.load_default()

def load_image(path):
    if not path or not os.path.exists(path):
        return None
    if path in _IMAGE_CACHE:
        return _IMAGE_CACHE[path].copy()
    
    img = None
    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        # Fallback to ffmpeg for webp or formats unsupported by PIL build
        try:
            cmd = ["ffmpeg", "-loglevel", "quiet", "-y", "-i", path, "-f", "image2pipe", "-vcodec", "png", "-"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            img = Image.open(io.BytesIO(res.stdout)).convert("RGBA")
        except Exception:
            img = None

    if img is not None:
        if len(_IMAGE_CACHE) > 20:
            _IMAGE_CACHE.clear()
        _IMAGE_CACHE[path] = img.copy()
    return img

def img_to_rgb565(img):
    if img.size != (320, 240):
        canvas = Image.new("RGB", (320, 240), (10, 12, 18))
        img_copy = img.copy()
        img_copy.thumbnail((320, 240), Image.Resampling.LANCZOS)
        offset = ((320 - img_copy.size[0]) // 2, (240 - img_copy.size[1]) // 2)
        canvas.paste(img_copy, offset)
        img = canvas
    else:
        img = img.convert("RGB")

    arr = np.array(img, dtype=np.uint16)
    r = (arr[:, :, 0] >> 3) << 11
    g = (arr[:, :, 1] >> 2) << 5
    b = (arr[:, :, 2] >> 3)
    rgb565 = (r | g | b).astype("<u2")
    return rgb565.tobytes()

def write_framebuffer(img):
    target = "/dev/fb_" if os.path.exists("/dev/fb_") else "/dev/fb1"
    if not os.path.exists(target):
        return
    buf = img_to_rgb565(img)
    try:
        with open(target, "wb") as f:
            f.write(buf)
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

def get_thermals():
    temps = []
    for p in sorted(os.listdir("/sys/class/thermal")):
        if p.startswith("thermal_zone"):
            tpath = f"/sys/class/thermal/{p}/temp"
            try:
                with open(tpath) as f:
                    temps.append(int(f.read().strip()) // 1000)
            except Exception:
                pass
    max_t = f"{max(temps)}°C" if temps else "N/A"
    gpu_t = f"{temps[-1]}°C" if len(temps) > 1 else max_t
    return max_t, gpu_t

def get_cpu_freq():
    try:
        with open("/sys/devices/system/cpu/cpu4/cpufreq/scaling_cur_freq") as f:
            return f"{int(f.read().strip()) // 1000} MHz"
    except Exception:
        return "2000 MHz"

def get_ram_info():
    try:
        mem_total, mem_free, mem_avail = 0, 0, 0
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if parts[0] == "MemTotal:":
                    mem_total = int(parts[1]) // 1024
                elif parts[0] == "MemAvailable:":
                    mem_avail = int(parts[1]) // 1024
        used = mem_total - mem_avail
        return f"{used}M / {mem_total}M"
    except Exception:
        return "OK"

def get_storage_free():
    try:
        st = os.statvfs("/userdata")
        free_gb = (st.f_bavail * st.f_frsize) // (1024**3)
        total_gb = (st.f_blocks * st.f_frsize) // (1024**3)
        return f"{free_gb} GB / {total_gb} GB"
    except Exception:
        return "OK"

def find_console_image(system_name):
    # Check theme images
    for base in ("/userdata/themes", "/usr/share/emulationstation/themes"):
        if not os.path.exists(base):
            continue
        for root, dirs, files in os.walk(base):
            for ext in ("webp", "png", "svg", "jpg"):
                fname = f"{system_name}.{ext}"
                if fname in files:
                    return os.path.join(root, fname)
    return None

def extract_game_metadata(system_name, rom_path):
    if not rom_path:
        return {
            "title": system_name.upper(),
            "system": system_name,
            "system_label": SYSTEM_NAMES.get(system_name.lower(), system_name.upper()),
            "image": None,
            "marquee": None,
            "developer": "",
            "publisher": "",
            "year": "",
            "genre": "",
            "console_image": find_console_image(system_name),
        }

    rom_dir = os.path.dirname(rom_path)
    rom_base = os.path.basename(rom_path)
    stem = os.path.splitext(rom_base)[0]

    info = {
        "title": stem,
        "system": system_name,
        "system_label": SYSTEM_NAMES.get(system_name.lower(), system_name.upper()),
        "image": None,
        "marquee": None,
        "developer": "",
        "publisher": "",
        "year": "",
        "genre": "",
        "console_image": find_console_image(system_name),
    }

    # 1. Parse gamelist.xml if present
    gamelist_path = os.path.join(rom_dir, "gamelist.xml")
    if os.path.exists(gamelist_path):
        try:
            tree = ET.parse(gamelist_path)
            for game in tree.getroot().findall("game"):
                path_el = game.find("path")
                if path_el is not None and path_el.text:
                    p = path_el.text.strip()
                    if p in (f"./{rom_base}", rom_base, rom_path):
                        for tag in ("name", "image", "marquee", "thumbnail", "developer", "publisher", "releasedate", "genre"):
                            el = game.find(tag)
                            if el is not None and el.text:
                                val = el.text.strip()
                                if tag == "name":
                                    info["title"] = val
                                elif tag in ("image", "thumbnail") and not info["image"]:
                                    full_p = os.path.normpath(os.path.join(rom_dir, val))
                                    if os.path.exists(full_p):
                                        info["image"] = full_p
                                elif tag == "marquee":
                                    full_m = os.path.normpath(os.path.join(rom_dir, val))
                                    if os.path.exists(full_m):
                                        info["marquee"] = full_m
                                elif tag == "developer":
                                    info["developer"] = val
                                elif tag == "publisher":
                                    info["publisher"] = val
                                elif tag == "releasedate" and len(val) >= 4:
                                    info["year"] = val[:4]
                                elif tag == "genre":
                                    info["genre"] = val
                        break
        except Exception:
            pass

    # 2. Filesystem fallbacks for cover art
    if not info["image"]:
        for sub in ("images", "covers", "media/images", "media/covers", ""):
            for ext in ("png", "jpg", "jpeg", "webp"):
                candidate = os.path.join(rom_dir, sub, f"{stem}.{ext}") if sub else os.path.join(rom_dir, f"{stem}.{ext}")
                if os.path.exists(candidate):
                    info["image"] = candidate
                    break
            if info["image"]:
                break

    # 3. Filesystem fallbacks for marquee/wheel art
    if not info["marquee"]:
        for sub in ("marquee", "wheel", "media/marquee", "media/wheel"):
            for ext in ("png", "jpg", "jpeg", "webp"):
                candidate = os.path.join(rom_dir, sub, f"{stem}.{ext}")
                if os.path.exists(candidate):
                    info["marquee"] = candidate
                    break
            if info["marquee"]:
                break

    return info

# ==============================================================================
# SCREEN RENDERERS (320x240 RGB)
# ==============================================================================

def render_cover_screen(info):
    """Screen 1: Full Game Cover / Boxart centered with stylish backdrop"""
    canvas = Image.new("RGB", (320, 240), (10, 12, 18))
    cover_img = load_image(info.get("image"))
    if cover_img:
        cover_img.thumbnail((320, 240), Image.Resampling.LANCZOS)
        offset = ((320 - cover_img.size[0]) // 2, (240 - cover_img.size[1]) // 2)
        canvas.paste(cover_img, offset, cover_img if cover_img.mode == "RGBA" else None)
    else:
        # Fallback if no cover art exists
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([(10, 10), (310, 230)], outline=(30, 40, 60), width=2)
        draw.text((160, 60), "NOW PLAYING", font=get_font(bold=True, size=16), fill=(0, 210, 255), anchor="mm")
        draw.text((160, 110), info.get("system_label", "GAME"), font=get_font(bold=True, size=20), fill=(255, 255, 255), anchor="mm")
        draw.text((160, 170), info.get("title", "")[:25], font=get_font(bold=False, size=14), fill=(255, 215, 90), anchor="mm")
    return canvas

def render_title_screen(info):
    """Screen 2: Marquee / Title Logo & Game Metadata"""
    canvas = Image.new("RGB", (320, 240), (12, 16, 26))
    draw = ImageDraw.Draw(canvas)
    marquee_img = load_image(info.get("marquee"))

    y_offset = 15
    if marquee_img:
        marquee_img.thumbnail((280, 85), Image.Resampling.LANCZOS)
        m_x = (320 - marquee_img.size[0]) // 2
        canvas.paste(marquee_img, (m_x, y_offset), marquee_img if marquee_img.mode == "RGBA" else None)
        y_offset += marquee_img.size[1] + 12
    else:
        draw.text((160, 45), info.get("title", "")[:22], font=get_font(bold=True, size=20), fill=(0, 220, 255), anchor="mm")
        y_offset = 80

    # Separator
    draw.line([(20, y_offset), (300, y_offset)], fill=(40, 50, 75), width=2)
    y_offset += 14

    # System Badge
    draw.text((25, y_offset), "SYSTEM:", font=get_font(bold=True, size=13), fill=(100, 255, 140))
    draw.text((100, y_offset), info.get("system_label", "GAME")[:22], font=get_font(bold=False, size=13), fill=(255, 255, 255))
    y_offset += 24

    # Developer / Publisher
    dev = info.get("developer") or info.get("publisher") or "Sega"
    year = info.get("year", "")
    dev_str = f"{dev} ({year})" if year else dev
    draw.text((25, y_offset), "STUDIO:", font=get_font(bold=True, size=13), fill=(255, 210, 90))
    draw.text((100, y_offset), dev_str[:22], font=get_font(bold=False, size=13), fill=(220, 230, 245))
    y_offset += 24

    # Genre
    genre = info.get("genre", "Arcade")
    draw.text((25, y_offset), "GENRE:", font=get_font(bold=True, size=13), fill=(0, 210, 255))
    draw.text((100, y_offset), genre[:24], font=get_font(bold=False, size=13), fill=(200, 210, 230))
    y_offset += 26

    # Bottom status pill
    draw.rectangle([(20, y_offset), (300, y_offset + 24)], fill=(20, 26, 40), outline=(50, 65, 95))
    draw.text((160, y_offset + 12), f"BATOCERA // {info.get('system_label', '')}", font=get_font(bold=True, size=11), fill=(160, 175, 200), anchor="mm")

    return canvas

def render_console_screen(info):
    """Screen 3: 3D Console Render & Hardware Branding"""
    canvas = Image.new("RGB", (320, 240), (12, 16, 26))
    draw = ImageDraw.Draw(canvas)

    # Header
    draw.text((160, 20), "CONSOLES & PLATFORMS", font=get_font(bold=True, size=12), fill=(0, 210, 255), anchor="mm")
    draw.text((160, 42), info.get("system_label", "RETRO CONSOLE"), font=get_font(bold=True, size=17), fill=(255, 255, 255), anchor="mm")
    draw.line([(25, 56), (295, 56)], fill=(40, 50, 75), width=2)

    # Console 3D Render
    c_img = load_image(info.get("console_image"))
    if c_img:
        c_img.thumbnail((260, 130), Image.Resampling.LANCZOS)
        cx = (320 - c_img.size[0]) // 2
        cy = 65 + (135 - c_img.size[1]) // 2
        canvas.paste(c_img, (cx, cy), c_img if c_img.mode == "RGBA" else None)
    else:
        draw.rectangle([(40, 75), (280, 185)], fill=(18, 24, 38), outline=(40, 55, 80))
        draw.text((160, 130), info.get("system_label", "PLATFORM"), font=get_font(bold=True, size=16), fill=(200, 210, 230), anchor="mm")

    # Footer
    draw.text((160, 220), info.get("title", "")[:28], font=get_font(bold=False, size=12), fill=(255, 215, 90), anchor="mm")
    return canvas

def render_in_game_telemetry(info, start_time):
    """Screen 4: Live In-Game Hardware & Session Telemetry"""
    canvas = Image.new("RGB", (320, 240), (8, 12, 18))
    draw = ImageDraw.Draw(canvas)

    elapsed_s = int(time.time() - start_time) if start_time else 0
    m, s = divmod(elapsed_s, 60)
    h, m = divmod(m, 60)
    session_str = f"{h:02d}:{m:02d}:{s:02d}"

    cpu_t, gpu_t = get_thermals()
    freq = get_cpu_freq()
    ram = get_ram_info()

    # Header Card
    draw.rectangle([(10, 8), (310, 42)], fill=(16, 22, 34), outline=(40, 55, 85))
    draw.text((22, 25), "LIVE TELEMETRY", font=get_font(bold=True, size=13), fill=(100, 255, 140), anchor="lm")
    draw.text((298, 25), f"PLAY: {session_str}", font=get_font(bold=True, size=13), fill=(255, 215, 90), anchor="rm")

    # Metrics Grid
    y = 54
    metrics = [
        ("GAME", info.get("title", "")[:20], (255, 255, 255)),
        ("PLATFORM", info.get("system_label", "")[:20], (0, 210, 255)),
        ("CPU CLOCK", f"{freq} [BIG CLUSTER]", (100, 255, 140)),
        ("THERMALS", f"CPU: {cpu_t}  |  GPU: {gpu_t}", (255, 140, 100)),
        ("MEMORY", f"{ram} ACTIVE", (200, 215, 240)),
        ("CLOCK", time.strftime("%H:%M:%S // %d %b"), (160, 175, 200)),
    ]

    for label, val, color in metrics:
        draw.text((16, y), label, font=get_font(bold=True, size=11), fill=(130, 145, 170))
        draw.text((105, y), val, font=get_font(bold=False, size=12), fill=color)
        draw.line([(14, y + 19), (306, y + 19)], fill=(20, 28, 42), width=1)
        y += 26

    # Bottom Pill
    draw.rectangle([(10, 214), (310, 234)], fill=(12, 16, 24))
    draw.text((160, 224), "ODROID-XU4 // MALI-T628 PANFROST", font=get_font(bold=True, size=10), fill=(100, 115, 140), anchor="mm")

    return canvas

def render_idle_dashboard():
    """Idle Screen 1: Batocera Front Hub & System Telemetry"""
    canvas = Image.new("RGB", (320, 240), (8, 12, 18))
    draw = ImageDraw.Draw(canvas)

    cpu_t, gpu_t = get_thermals()
    freq = get_cpu_freq()
    ip_addr = get_ip()
    storage = get_storage_free()
    ram = get_ram_info()

    # Title Card
    draw.rectangle([(10, 8), (310, 44)], fill=(14, 20, 32), outline=(0, 210, 255))
    draw.text((160, 26), "ODROID-XU4 // BATOCERA", font=get_font(bold=True, size=16), fill=(0, 210, 255), anchor="mm")

    y = 56
    items = [
        ("IP ADDR", ip_addr, (255, 255, 255)),
        ("CPU FREQ", f"{freq} [8 CORES]", (100, 255, 140)),
        ("THERMALS", f"CPU: {cpu_t}  |  GPU: {gpu_t}", (255, 140, 100)),
        ("RAM USAGE", ram, (200, 215, 240)),
        ("STORAGE", storage, (255, 215, 90)),
        ("LOCAL TIME", time.strftime("%H:%M:%S // %a %d %b"), (160, 175, 200)),
    ]

    for label, val, color in items:
        draw.text((16, y), label, font=get_font(bold=True, size=11), fill=(130, 145, 170))
        draw.text((105, y), val, font=get_font(bold=False, size=12), fill=color)
        draw.line([(14, y + 20), (306, y + 20)], fill=(20, 28, 42), width=1)
        y += 27

    draw.rectangle([(10, 216), (310, 234)], fill=(14, 20, 30))
    draw.text((160, 225), "OGST N64 EDITION // FRONT DISPLAY ONLINE", font=get_font(bold=True, size=10), fill=(100, 255, 140), anchor="mm")
    return canvas

def render_idle_showcase(last_info):
    """Idle Screen 2: Last Played Game Showcase or Retro Platform Hub"""
    if last_info and last_info.get("image"):
        return render_cover_screen(last_info)
    elif last_info and last_info.get("console_image"):
        return render_console_screen(last_info)
    else:
        return render_idle_dashboard()

# ==============================================================================
# DAEMON CYCLE ENGINE
# ==============================================================================

def daemon_loop():
    os.makedirs(STATE_DIR, exist_ok=True)
    screen_idx = 0
    last_switch = 0
    SWITCH_INTERVAL = 10  # 10 seconds per screen

    # Track game state
    current_game = None
    last_game = None

    if os.path.exists(LAST_GAME_FILE):
        try:
            with open(LAST_GAME_FILE) as f:
                last_game = json.load(f)
        except Exception:
            pass

    print("[+] OGST Display Daemon started. Cycling screens every 10 seconds.")

    while True:
        now = time.time()

        # Check for state changes from ogst_game.sh
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    new_state = json.load(f)
                if new_state.get("status") == "playing":
                    if not current_game or current_game.get("rom") != new_state.get("rom"):
                        current_game = new_state
                        screen_idx = 0
                        last_switch = 0  # Force immediate refresh
                else:
                    if current_game:
                        last_game = current_game
                        with open(LAST_GAME_FILE, "w") as f:
                            json.dump(last_game, f)
                    current_game = None
            except Exception:
                pass

        if now - last_switch >= SWITCH_INTERVAL:
            last_switch = now

            if current_game and current_game.get("status") == "playing":
                info = current_game.get("info", {})
                start_time = current_game.get("start_time", now)

                # Available in-game screens:
                # 0: Cover Art
                # 1: Title & Marquee Details
                # 2: Console Platform 3D Showcase
                # 3: Live In-Game Hardware & Session Telemetry
                screens = [0, 1, 2, 3]
                active_screen = screens[screen_idx % len(screens)]
                screen_idx += 1

                if active_screen == 0:
                    frame = render_cover_screen(info)
                elif active_screen == 1:
                    frame = render_title_screen(info)
                elif active_screen == 2:
                    frame = render_console_screen(info)
                else:
                    frame = render_in_game_telemetry(info, start_time)

                write_framebuffer(frame)
            else:
                # Idle Mode: Alternate between Full Dashboard and Last Played / Console Showcase
                if screen_idx % 2 == 0:
                    frame = render_idle_dashboard()
                else:
                    frame = render_idle_showcase(last_game.get("info") if last_game else None)
                screen_idx += 1
                write_framebuffer(frame)

        time.sleep(1)

# ==============================================================================
# CLI HANDLERS
# ==============================================================================

def on_game_start(system_name, emulator, rom_path):
    os.makedirs(STATE_DIR, exist_ok=True)
    info = extract_game_metadata(system_name, rom_path)
    state = {
        "status": "playing",
        "system": system_name,
        "emulator": emulator,
        "rom": rom_path,
        "start_time": time.time(),
        "info": info
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

    # Immediately show Cover Art
    frame = render_cover_screen(info)
    write_framebuffer(frame)

def on_game_stop():
    os.makedirs(STATE_DIR, exist_ok=True)
    state = {"status": "idle", "stop_time": time.time()}
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

    # Immediately show Idle Dashboard
    frame = render_idle_dashboard()
    write_framebuffer(frame)

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    if action == "daemon":
        daemon_loop()
    elif action == "game_start":
        sys_name = sys.argv[2] if len(sys.argv) > 2 else "dreamcast"
        emu_name = sys.argv[3] if len(sys.argv) > 3 else "flycast"
        r_path = sys.argv[4] if len(sys.argv) > 4 else ""
        on_game_start(sys_name, emu_name, r_path)
    elif action == "game_stop":
        on_game_stop()
    elif action == "art":
        sys_name = sys.argv[2] if len(sys.argv) > 2 else "SYSTEM"
        r_path = sys.argv[3] if len(sys.argv) > 3 else ""
        if r_path:
            on_game_start(sys_name, "auto", r_path)
        else:
            info = extract_game_metadata(sys_name, "")
            write_framebuffer(render_console_screen(info))
    elif action == "idle":
        on_game_stop()
    elif action == "test":
        # Render sample screen
        info = extract_game_metadata("dreamcast", "/userdata/roms/dreamcast/Crazy Taxi (Europe).chd")
        write_framebuffer(render_cover_screen(info))
        time.sleep(3)
        write_framebuffer(render_title_screen(info))
        time.sleep(3)
        write_framebuffer(render_console_screen(info))
        time.sleep(3)
        write_framebuffer(render_in_game_telemetry(info, time.time() - 450))
        print("[+] Test cycle complete.")
