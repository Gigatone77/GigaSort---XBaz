#!/usr/bin/env python3
"""
XBaz
====
Xbox controller manager for Linux: resets a machine to the stock kernel
driver baseline (xpad / hid-microsoft), binds the Xbox Elite Series 2, and
verifies its back paddles — including wiring them up for Steam Input / SDL.

The goal is **maximum compatibility with every common gaming setup**:
  * Steam (native), SteamOS / Steam Deck
  * Proton / Wine games (Heroic, Lutris, Bottles)
  * native SDL1/SDL2/SDL3 games and emulators
  * Windows dual-boot (paddles are handled by the Xbox Accessories app there)

Why stock drivers?
------------------
Out-of-tree DKMS drivers (xpadneo, xbelite2) break on every kernel update and
only handle Bluetooth. The stock `xpad` driver already supports the wired
Elite 2 (USB 045e:0b00, class ff/47/d0); `hid-microsoft` covers Bluetooth.
`XBaz` removes the leftover custom-driver hacks that silently unbind xpad
(some setups ship a 99-xbelite2.rules that yanks xpad off the controller right
after it binds, leaving the pad dead with zero input devices).

Capabilities
------------
  `wil:python -m gigasort.core.xbaz menu`      simple menu
  `python -m gigasort.core.xbaz set-default`   set the Elite 2 as default everywhere (root)
  `python -m gigasort.core.xbaz linux-fix`     apply the stock xpad driver bind (root)
  `python -m gigasort.core.xbaz restore-clean` remove leftover driver hacks to a clean profile (root)
  `python -m gigasort.core.xbaz customize`     controller config: button/paddle remap, dead zones, stick swap
  `python -m gigasort.core.xbaz live-view`     live button/axis viewer (python-evdev)
  `python -m gigasort.core.xbaz status`        read-only diagnostic (driver, binding, devices)

Distributed as a module inside GigaSort (gigasort.core.xbaz). Runs standalone
from anywhere and in-process from the GigaSort GUI.

Paddles
-------
With the stock xpad driver, the four back paddles (P1-P4) register as
independent buttons (BTN_TRIGGER_HAPPY1..4 / evdev codes 704-707). From there
you map them however you like: in Steam Input, in-game, or via SDL
(SDL_GAMECONTROLLERCONFIG exposes `paddle1`..`paddle4`).

The udev rule this program installs (`70-xbaz-elite2.rules`) mirrors the
official `steam-devices` rule so Steam Input sees the Elite 2's hidraw device
and can bind the paddles in its controller configurator.

Privileged commands (set-default, linux-fix, restore-clean) check for root
and re-invoke themselves via sudo if needed.
"""

import argparse
import json
import os
import pwd
import re
import select
import shutil
import subprocess
import sys
import time


def user_home():
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            return pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            return "/home/" + sudo_user
    return os.path.expanduser("~")


ELITE2 = {"0b00": "Xbox Elite Series 2 (wired, model 1797)",
          "0b22": "Xbox Elite Series 2 (Bluetooth LE)",
          "0b05": "Xbox Elite Series 2 (Bluetooth classic)",
          "0b13": "Xbox Elite Series 2 (later firmware, wired)",
          "0b20": "Xbox Elite Series 2 (later firmware, wireless)"}

SDL_MAP = ("030000005e040000000b000008040000,Xbox Elite Series 2 Controller,"
           "platform:Linux,a:b0,b:b1,x:b2,y:b3,back:b6,guide:b8,start:b7,"
           "leftstick:b9,rightstick:b10,leftshoulder:b4,rightshoulder:b5,"
           "dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,"
           "paddle1:b11,paddle2:b13,paddle3:b12,paddle4:b14,"
           "leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,")

CONFIG_VERSION = 1
CONFIG_DIR = os.path.join(user_home(), ".config", "xbaz")
CONFIG_FILE = os.path.join(CONFIG_DIR, "controller.json")
SDL_DB = os.path.join(user_home(), ".config", "SDL2", "gamecontrollerdb.txt")

DEFAULT_BUTTONS = {
    "a": "b0", "b": "b1", "x": "b2", "y": "b3",
    "back": "b6", "guide": "b8", "start": "b7",
    "leftstick": "b9", "rightstick": "b10",
    "leftshoulder": "b4", "rightshoulder": "b5",
    "paddle1": "b11", "paddle2": "b13", "paddle3": "b12", "paddle4": "b14",
}
DEFAULT_AXES = {
    "leftx": "a0", "lefty": "a1",
    "rightx": "a3", "righty": "a4",
    "lefttrigger": "a2", "righttrigger": "a5",
}
BUTTON_ORDER = list(DEFAULT_BUTTONS)

PHYS_LABEL = {"b0": "A", "b1": "B", "b2": "X", "b3": "Y",
              "b4": "LB", "b5": "RB", "b6": "Back", "b7": "Start",
              "b8": "Guide", "b9": "LSB", "b10": "RSB",
              "b11": "P1", "b12": "P3", "b13": "P2", "b14": "P4"}

GRN = "\033[32m"; RED = "\033[31m"; YEL = "\033[33m"; CYN = "\033[36m"
BOLD = "\033[1m"; RST = "\033[0m"


def c(tag, text):
    return "%s%s%s" % (tag, text, RST)


def default_config():
    return {"version": CONFIG_VERSION,
            "name": "Default",
            "buttons": {},
            "axes": {},
            "swap_sticks": False,
            "deadzone": {"left": 15, "right": 15, "trigger": 0},
            "trigger_mode": "linear"}


def load_config():
    cfg = default_config()
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                loaded = json.load(fh)
            for k in ("name", "buttons", "axes", "swap_sticks", "deadzone",
                      "trigger_mode"):
                if k in loaded:
                    cfg[k] = loaded[k]
        except (ValueError, OSError) as e:
            print(c(YEL, "  could not read %s (%s) - using defaults"
                         % (CONFIG_FILE, e)))
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")


def build_mapping(cfg):
    buttons = dict(DEFAULT_BUTTONS)
    buttons.update(cfg.get("buttons") or {})
    axes = dict(DEFAULT_AXES)
    axes.update(cfg.get("axes") or {})
    if cfg.get("swap_sticks"):
        axes["leftx"], axes["rightx"] = axes["rightx"], axes["leftx"]
        axes["lefty"], axes["righty"] = axes["righty"], axes["lefty"]
    parts = ["%s:%s" % (k, buttons[k]) for k in BUTTON_ORDER]
    parts += ["%s:%s" % (k, axes[k]) for k in DEFAULT_AXES]
    return ",".join(parts) + ","


def mapping_line(cfg):
    head = "030000005e040000000b000008040000,Xbox Elite Series 2 Controller," \
           "platform:Linux,"
    return head + build_mapping(cfg) + "\n"


def upsert_sdl_block(cfg, note="controller config"):
    os.makedirs(os.path.dirname(SDL_DB), exist_ok=True)
    entry = "# XBaz: Elite 2 (%s)\n%s" % (note, mapping_line(cfg))
    if not os.path.isfile(SDL_DB):
        with open(SDL_DB, "w", encoding="utf-8") as fh:
            fh.write(entry)
        return True
    with open(SDL_DB, encoding="utf-8") as fh:
        txt = fh.read()
    pattern = r"(?m)^# *XBaz: .*\n030000005e040000000b000008040000,[^\n]*(?:\n|$)"
    new = re.sub(pattern, entry, txt, count=1)
    if new == txt:
        if not txt.endswith("\n"):
            txt += "\n"
        new = txt + entry
    with open(SDL_DB, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def validate_config(cfg):
    errs = []
    buttons = dict(DEFAULT_BUTTONS)
    buttons.update(cfg.get("buttons") or {})
    seen = {}
    for sem, phys in buttons.items():
        if not re.fullmatch(r"b\d+", str(phys)):
            errs.append("button %s: not a physical button id (%s)"
                        % (sem, phys))
            continue
        if phys in seen:
            errs.append("duplicate physical button %s (%s and %s)"
                        % (phys, seen[phys], sem))
        seen[phys] = sem
    axes = dict(DEFAULT_AXES)
    axes.update(cfg.get("axes") or {})
    aseen = {}
    for sem, phys in axes.items():
        if not re.fullmatch(r"a\d+", str(phys)):
            errs.append("axis %s: not a physical axis id (%s)" % (sem, phys))
            continue
        if phys in aseen:
            errs.append("duplicate physical axis %s (%s and %s)"
                        % (phys, aseen[phys], sem))
        aseen[phys] = sem
    return errs


def find_elite2_event():
    for d in input_devices():
        info = d.get("info") or ""
        vm = re.search(r"Vendor=([0-9a-f]{4})", info, re.I)
        pm = re.search(r"Product=([0-9a-f]{4})", info, re.I)
        vid = vm.group(1).lower() if vm else None
        pid = pm.group(1).lower() if pm else None
        ev = d.get("event")
        name = (d.get("name") or "").lower()
        if not ev:
            continue
        if vid == "045e" and pid in ELITE2:
            return ev
        if "elite" in name or "xbox" in name:
            return ev
    return None


def apply_absinfo(dz):
    ev = find_elite2_event()
    if not ev:
        return False
    try:
        import evdev  # noqa: PLC0415
    except ImportError:
        print(c(YEL, "  python-evdev not installed - dead zones saved in the "
                     "config but not written to the device."))
        return False
    try:
        dev = evdev.InputDevice(ev)
    except OSError as e:
        print(c(YEL, "  could not open %s (%s) - run with sudo or plug the "
                     "controller in." % (ev, e)))
        return False
    per = {0: "left", 1: "left", 3: "right", 4: "right",
           2: "trigger", 5: "trigger"}
    ok = 0
    for code, which in per.items():
        try:
            info = dev.absinfo(code)
        except (OSError, ValueError):
            continue
        if info is None:
            continue
        flat = max(0, min(100, int(dz.get(which, 0) or 0)))
        try:
            dev.set_absinfo(code, value=info.value, minimum=info.minimum,
                            maximum=info.maximum, fuzz=info.fuzz, flat=flat)
            ok += 1
        except OSError as e:
            print(c(RED, "  could not set dead zone on %s (%s)" % (which, e)))
    print(c(GRN, "  dead zones applied to %s (%s axes) - until the pad is "
                 "replugged or this is re-run" % (ev, ok)))
    return True


def apply_config(cfg, note="controller config"):
    errs = validate_config(cfg)
    if errs:
        for e in errs:
            print(c(RED, "  " + e))
        print(c(YEL, "  config NOT applied."))
        return False
    cfg["version"] = CONFIG_VERSION
    save_config(cfg)
    print("  saved %s" % CONFIG_FILE)
    try:
        upsert_sdl_block(cfg, note)
        print("  updated %s (SDL games use this mapping)" % SDL_DB)
    except OSError as e:
        print(c(RED, "  could not update SDL mapping:"), e)
    dead = apply_absinfo(cfg.get("deadzone") or {})
    print(c(GRN, "  config applied."))
    if not dead:
        print(c(YEL, "  controller not connected right now - plug it in and "
                     "run `xbaz customize` > 6 again to write the dead zones."))
    return True


def show_config(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    print(c(BOLD, "\nconfig: %s" % cfg.get("name", "Default")))
    buttons = dict(DEFAULT_BUTTONS)
    buttons.update(cfg.get("buttons") or {})
    for sem in BUTTON_ORDER:
        mark = "*" if sem in (cfg.get("buttons") or {}) else " "
        phys = buttons[sem]
        print("  %s %-15s -> %s%s" % (mark, sem, phys,
                                      " (%s)" % PHYS_LABEL.get(phys, "")
                                      if PHYS_LABEL.get(phys) else ""))
    axes = dict(DEFAULT_AXES)
    axes.update(cfg.get("axes") or {})
    if cfg.get("swap_sticks"):
        axes["leftx"], axes["rightx"] = axes["rightx"], axes["leftx"]
        axes["lefty"], axes["righty"] = axes["righty"], axes["lefty"]
    for sem in DEFAULT_AXES:
        print("  %s %-14s -> %s" % ("*" if sem in (cfg.get("axes") or {})
                                    else " ", sem, axes[sem]))
    dz = cfg.get("deadzone") or {}
    print("  dead zones : L %s%%  R %s%%  triggers %s%%"
          % (dz.get("left", 15), dz.get("right", 15), dz.get("trigger", 0)))
    print("  stick swap : %s   (triggers mode: %s)"
          % ("on" if cfg.get("swap_sticks") else "off",
             cfg.get("trigger_mode", "linear")))


LIVE_BTNS = [304, 305, 306, 307, 308, 309, 314, 315, 316, 317, 318,
             704, 705, 706, 707]
LIVE_BTN_LBL = {304: "A", 305: "B", 306: "X", 307: "Y", 308: "LB", 309: "RB",
                314: "BK", 315: "ST", 316: "GB", 317: "LS", 318: "RS",
                704: "P1", 705: "P2", 706: "P3", 707: "P4"}
LIVE_AXES = [0, 1, 3, 4, 2, 5]
LIVE_AX_LBL = {0: "LX", 1: "LY", 3: "RX", 4: "RY", 2: "LT", 5: "RT"}


def liveview(frames=0, seconds=0.0):
    ev = find_elite2_event()
    if not ev:
        print(c(YEL, "no Elite 2 input device found. Is it connected and "
                     "bound to xpad? run `xbaz linux-fix` / `xbaz status`."))
        return
    try:
        import evdev  # noqa: PLC0415
    except ImportError:
        print(c(YEL, "python-evdev not installed (dnf install python3-evdev)."))
        return
    try:
        dev = evdev.InputDevice(ev)
    except OSError as e:
        print(c(RED, "could not open %s (%s)" % (ev, e)))
        print(c(YEL, "hint: add your user to the 'input' group "
                     "(sudo usermod -aG input $USER) then log out/in, or "
                     "ensure the 70-xbaz-elite2.rules uaccess tag is applied "
                     "(replug the controller)."))
        return
    import fcntl  # noqa: PLC0415
    fcntl.fcntl(dev.fd, fcntl.F_SETFL, os.O_NONBLOCK)
    absinfo = {}
    for code in LIVE_AXES:
        try:
            absinfo[code] = dev.absinfo(code)
        except (OSError, ValueError):
            absinfo[code] = None
    btn = dict.fromkeys(LIVE_BTNS, False)
    absval = {code: 0 for code in LIVE_AXES}
    hat = (0, 0)
    tty = sys.stdout.isatty()
    deadline = (time.monotonic() + seconds) if seconds else 0.0
    n = 0
    print(c(CYN, "live view: %s (%s)  - press buttons, move sticks. "
                 "Ctrl+C to quit.\n" % (ev, dev.name)))

    def norm(code, v):
        info = absinfo.get(code)
        if info is None or info.maximum == info.minimum:
            return 0
        if code in (0, 1, 3, 4):
            return int(100 * (2.0 * (v - info.minimum) /
                              (info.maximum - info.minimum) - 1.0))
        return int(100 * (v - info.minimum) /
                   (info.maximum - info.minimum))

    while True:
        if frames and n >= frames:
            break
        if deadline and time.monotonic() >= deadline:
            break
        r, _, _ = select.select([dev.fd], [], [], 0.2)
        if not r:
            continue
        while True:
            try:
                for e in dev.read():
                    n += 1
                    if e.type == 1 and e.code in btn:
                        btn[e.code] = bool(e.value)
                    elif e.type == 3:
                        if e.code in (16, 17):
                            hat = (e.value, hat[1]) if e.code == 16 \
                                else (hat[0], e.value)
                        elif e.code in absval:
                            absval[e.code] = e.value
            except (BlockingIOError, OSError):
                break
        if tty:
            head = "\r" + " " * 120 + "\r"
        else:
            head = ""
        row = "  ".join("[%s]" % (LIVE_BTN_LBL[code] if btn[code] else "--")
                        for code in LIVE_BTNS)
        ax = "   ".join("%s%+04d%%" % (LIVE_AX_LBL[code], norm(code,
                                                               absval[code]))
                        for code in LIVE_AXES)
        dp = "DP:%d/%d" % hat
        print(head + "[buttons] " + row + "\n          " + dp + "   " + ax)
        if not tty:
            sys.stdout.flush()


def remap_menu(cfg):
    labels = ["a", "b", "x", "y", "back", "guide", "start", "leftstick",
              "rightstick", "leftshoulder", "rightshoulder",
              "paddle1", "paddle2", "paddle3", "paddle4"]
    while True:
        buttons = dict(DEFAULT_BUTTONS)
        buttons.update(cfg.get("buttons") or {})
        print(c(CYN, "\nbutton / paddle mapping:"))
        for i, sem in enumerate(labels, 1):
            phys = buttons[sem]
            print("  [%2d] %-15s -> %s (%s)" % (i, sem, phys,
                                                PHYS_LABEL.get(phys, "")))
        print("  [q] back")
        try:
            pick = input("\npick a button to change > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if pick in ("q", "quit", "back"):
            return
        if not pick.isdigit() or not 1 <= int(pick) <= len(labels):
            print("  unknown pick.")
            continue
        sem = labels[int(pick) - 1]
        print("  physical ids: %s" % " ".join(
            "%s=%s" % (PHYS_LABEL.get(b, b), b) for b in
            ("b0", "b2", "b1", "b3", "b4", "b5", "b6", "b7", "b8", "b9",
             "b10", "b11", "b13", "b12", "b14")))
        val = input("  %s -> (b0..b14, or 'reset') > " % sem).strip().lower()
        if val in ("", "r", "reset", "default"):
            cfg["buttons"].pop(sem, None)
            print("  %s back to default." % sem)
        elif re.fullmatch(r"b\d+", val):
            cfg["buttons"][sem] = val
            print("  %s -> %s" % (sem, val))
        else:
            print("  invalid physical id (%s)" % val)


def dz_menu(cfg):
    dz = cfg.setdefault("deadzone", {})
    for key, label in (("left", "left stick"), ("right", "right stick"),
                       ("trigger", "triggers")):
        cur = dz.get(key, default_config()["deadzone"][key])
        try:
            val = input("  %s dead zone %% [%s] > " % (label, cur)).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if val == "":
            continue
        try:
            dz[key] = max(0, min(100, int(val)))
        except ValueError:
            print("  keep %s%%" % cur)


def customize():
    cfg = load_config()
    print(c(BOLD, "XBaz controller configuration"))
    while True:
        print()
        print("  1. show current config")
        print("  2. remap a button / paddle")
        print("  3. dead zones (sticks + triggers)")
        print("  4. toggle stick swap (L <-> R) [%s]"
              % ("on" if cfg.get("swap_sticks") else "off"))
        print("  5. reset to default config")
        print("  6. save + apply now (config + SDL mapping + live dead zones)")
        print("  t. live viewer (buttons / axes)")
        print("  q. back / quit")
        try:
            choice = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return
        if choice in ("q", "quit", "back", ""):
            return
        elif choice == "1":
            show_config(cfg)
        elif choice == "2":
            remap_menu(cfg)
        elif choice == "3":
            dz_menu(cfg)
        elif choice == "4":
            cfg["swap_sticks"] = not cfg.get("swap_sticks")
            print("  sticks %s." % ("swapped" if cfg["swap_sticks"]
                                    else "normal"))
        elif choice == "5":
            cfg = default_config()
            print("  reset to defaults.")
        elif choice == "6":
            apply_config(cfg)
            cfg = load_config()
        elif choice == "t":
            liveview()


def customize_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (ValueError, OSError) as e:
        print(c(RED, "could not read %s: %s" % (path, e)))
        sys.exit(1)
    if not apply_config(cfg, note="saved from GUI"):
        sys.exit(1)


def is_root():
    return os.geteuid() == 0


def sudo_self(extra=None):
    if is_root():
        return True
    print(c(YEL, "[xbaz] This action needs root - re-running via sudo..."))
    cmd = ["sudo", sys.executable, os.path.abspath(__file__)]
    if extra:
        cmd += extra
    try:
        rc = subprocess.call(cmd)
    except FileNotFoundError:
        print(c(RED, "[xbaz] No sudo available; run the command yourself as root."))
        return False
    sys.exit(rc)


def find_elite2():
    out = []
    try:
        paths = sorted(os.listdir("/sys/bus/usb/devices/"))
    except FileNotFoundError:
        return out
    for p in paths:
        b = "/sys/bus/usb/devices/%s" % p
        vf, pf = os.path.join(b, "idVendor"), os.path.join(b, "idProduct")
        if not (os.path.isfile(vf) and os.path.isfile(pf)):
            continue
        with open(vf, encoding="utf-8") as fh:
            vid = fh.read().strip()
        with open(pf, encoding="utf-8") as fh:
            pid = fh.read().strip()
        if vid.lower() == "045e" and pid.lower() in ELITE2:
            base = b
            intfs = [os.path.join(base, n) for n in os.listdir(base)
                     if os.path.isdir(os.path.join(base, n)) and n.startswith(p + ":")]
            out.append((base, intfs))
    return out


def input_devices():
    devs = []
    try:
        with open("/proc/bus/input/devices", encoding="utf-8", errors="replace") as fh:
            cur = {}
            for line in fh:
                line = line.strip()
                if line.startswith("I:"):
                    if cur:
                        devs.append(cur)
                    cur = {"info": line.split(": ", 1)[-1]}
                elif line.startswith("N:"):
                    cur["name"] = line.split('"')[1] if '"' in line else ""
                elif line.startswith("H:"):
                    cur["handlers"] = line.split(": ", 1)[-1]
                    for h in (cur.get("handlers") or "").split():
                        if h.startswith("event"):
                            cur["event"] = "/dev/input/%s" % h
            if cur:
                devs.append(cur)
    except (FileNotFoundError, OSError):
        return devs
    return devs


def usb_list():
    out = []
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True)
    except FileNotFoundError:
        return out
    for line in (r.stdout or "").splitlines():
        pid = re.search(r"045e:([0-9a-f]{4})", line)
        if pid and pid.group(1).lower() in ELITE2:
            out.append(line)
    return out


OUTFOX = os.path.join(user_home(), "Games", "OutFox")
OUTFOX_MODE = os.path.join(user_home(), ".project-outfox/Save/Preferences.ini")

STEAM_TEMPLATE_DIR = os.path.join(user_home(), ".steam/steam/controller_base/templates")
STEAM_TEMPLATE = os.path.join(STEAM_TEMPLATE_DIR, "controller_xboxone_gamepad_xbaz.vdf")

LEFTOVERS = [
    "/etc/udev/rules.d/60-xpadneo.rules",
    "/etc/udev/rules.d/70-xpadneo-disable-hidraw.rules",
    "/etc/udev/rules.d/99-xbelite2.rules",
    "/etc/modprobe.d/xpadneo.conf",
    "/usr/local/bin/xbe2-rw",
]
DKMS = ["/usr/src/hid-xpadneo", "/var/lib/dkms/hid-xpadneo"]

STEAM_RULE = "70-xbaz-elite2.rules"
STEAM_RULE_PATH = os.path.join("/etc/udev/rules.d", STEAM_RULE)
STEAM_RULE_CONTENT = """# XBaz - let Steam Input see the Xbox Elite Series 2 (mirrors steam-devices)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="0b00", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="0b22", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="0b05", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="0b00", MODE="0660", TAG+="uaccess"
"""


def cmd(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def status():
    print(c(BOLD, "XBaz status"))
    print(c(CYN, "=" * 40))
    print("kernel : %s" % c(BOLD, os.uname().release))
    print("root?  : %s" % ("yes" if is_root() else "no (status is read-only)"))

    sus = usb_list()
    if not sus:
        print(c(RED, "\nNo Xbox Elite Series 2 detected on USB right now."))
    else:
        print(c(GRN, "\nConnected:"))
        for s in sus:
            print("  " + s)

    print("\ndriver binding:")
    devs = find_elite2()
    if not devs:
        print("  (mapper: no controller node in sysfs)")
    for node, intfs in devs:
        for i in intfs:
            drv = os.path.basename(os.readlink(os.path.join(i, "driver"))) \
                if os.path.exists(os.path.join(i, "driver")) else "(unbound)"
            print("  %s : %s" % (os.path.basename(i), c((GRN if drv != "(unbound)" else RED), drv)))

    lsmod = cmd(["lsmod"]).stdout
    for mod in ("xpad", "hid_microsoft"):
        state = mod in lsmod
        print("  module %-14s: %s" % (mod, c(GRN if state else RED, "loaded" if state else "not loaded")))

    print("\nleftover custom-driver hacks:")
    found = False
    for f in LEFTOVERS:
        if os.path.exists(f):
            found = True
            print("  %s %s" % (c(RED, "present"), f))
    for f in DKMS:
        if os.path.exists(f):
            found = True
            print("  %s %s" % (c(RED, "present"), f))
    if not found:
        print(c(GRN, "  clean - no leftover xpadneo/xbelite2 files"))

    ste = os.path.exists(STEAM_RULE_PATH)
    print("\nsteam input rule (%s): %s" % (STEAM_RULE, c(GRN if ste else YEL, "installed" if ste else "not installed")))

    ev = input_devices()
    pads = [d for d in ev if "0b00" in (d.get("info") or "").lower() or "elite" in (d.get("name") or "").lower()]
    print("\ninput devices:")
    if pads:
        for d in pads:
            print("  %s  [%s]" % (c(GRN, d.get("event")), d.get("name")))
    else:
        print("  (no elite2 input device yet - run `xbaz linux-fix`)")


def reset():
    if not sudo_self(["restore-clean"]):
        return
    print(c(BOLD, "XBaz reset - remove leftover custom-driver hacks"))
    removed = False
    for f in LEFTOVERS:
        if os.path.exists(f):
            try:
                os.remove(f)
                print("  removed %s" % f)
                removed = True
            except OSError as e:
                print("  %s %s" % (c(RED, "error removing"), f), e)
    for d in DKMS:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
                print("  removed %s" % d)
                removed = True
            except OSError as e:
                print("  %s %s" % (c(RED, "error removing"), d), e)
    if not removed:
        print(c(GRN, "  nothing to remove - already clean"))
    print("\nreloading udev...")
    cmd(["udevadm", "control", "--reload-rules"])
    cmd(["udevadm", "trigger"])
    print(c(GRN, "baseline reached. run `xbaz bind` to claim the controller."))


def bind():
    if not sudo_self(["linux-fix"]):
        return
    print(c(BOLD, "XBaz bind - claim the Elite 2 with the stock xpad driver"))
    cmd(["modprobe", "xpad"])
    devs = find_elite2()
    if not devs:
        print(c(RED, "no Elite 2 found on USB. plug it in and retry."))
        return
    bound_any = False
    for node, intfs in devs:
        for i in intfs:
            drv = os.path.join(i, "driver")
            if os.path.exists(drv):
                continue
            name = os.path.basename(i)
            bindf = "/sys/bus/usb/drivers/xpad/bind"
            try:
                with open(bindf, "w") as fh:
                    fh.write(name)
                print("  bound %s -> xpad" % name)
                bound_any = True
            except OSError as e:
                print("  %s could not bind: %s" % (name, e))
    if bound_any:
        print(c(GRN, "\ncontroller claimed. run `xbaz status` or `xbaz paddles`."))
    else:
        print(c(YEL, "\nno interface needed binding (already bound or absent)."))


def steampad():
    if not sudo_self(["set-default"]):
        return
    print(c(BOLD, "XBaz steam - Steam Input / SDL paddle setup"))
    try:
        with open(STEAM_RULE_PATH, "w") as fh:
            fh.write(STEAM_RULE_CONTENT)
        print("  wrote %s" % STEAM_RULE_PATH)
    except OSError as e:
        print(c(RED, "  could not write udev rule:"), e)
    cmd(["udevadm", "control", "--reload-rules"])
    cmd(["udevadm", "trigger"])
    print(c(GRN, "  udev reloaded; replug the controller (or reboot) to pick up the rule."))

    try:
        upsert_sdl_block(load_config(), "wired (stock xpad) - expose back "
                                        "paddles to SDL")
        print("  updated SDL2 mapping in ~/.config/SDL2/gamecontrollerdb.txt")
    except OSError as e:
        print(c(RED, "  could not write SDL mapping:"), e)

    try:
        with open(OUTFOX_MODE, encoding="utf-8") as fh:
            prefs = fh.read()
        if re.search(r"(?m)^UseOldJoystickMapping=[^0]", prefs):
            with open(OUTFOX_MODE, "w", encoding="utf-8") as fh:
                fh.write(re.sub(r"(?m)^UseOldJoystickMapping=[^\n]*",
                                "UseOldJoystickMapping=0", prefs))
            print("  Set OutFox UseOldJoystickMapping=0 (triggers as separate inputs)")
        else:
            print("  OutFox already uses modern joystick mapping (UseOldJoystickMapping=0)")
    except FileNotFoundError:
        print(c(YEL, "  OutFox prefs not found - skipped (only matters when OutFox used)"))
    except OSError as e:
        print(c(RED, "  could not update OutFox prefs:"), e)

    if STEAM_TEMPLATE:
        if os.path.exists(STEAM_TEMPLATE):
            print("  XBaz Steam template present: " + STEAM_TEMPLATE)
        else:
            print(c(RED, "  XBaz Steam template missing: " + STEAM_TEMPLATE))
    else:
        print(c(YEL, "  Steam not installed here - skipping template check."))

    print(c(YEL, "\nnext steps:"))
    print("  * replug the controller OR reboot")
    print("  * in Steam: Settings > Controller > enable Steam Input for Xbox")
    print("  * open the controller configurator; P1-P4 now appear as paddles")
    print("  * for a stock-standard pad (LT/RT analog, paddles=A/B/X/Y):")
    print("      right-click Cyberpunk 2077 > Controller Configuration >")
    print("      Browse > 'XBaz Elite 2 Stock Standard' > Apply")


def paddles():
    if not sudo_self(["paddle-enable"]):
        return
    print(c(BOLD, "XBaz paddle-enable - turn on the 4 back paddles"))
    cmd(["modprobe", "xpad"])
    bound_any = False
    for node, intfs in find_elite2():
        for i in intfs:
            if os.path.exists(os.path.join(i, "driver")):
                continue
            try:
                with open("/sys/bus/usb/drivers/xpad/bind", "w") as fh:
                    fh.write(os.path.basename(i))
                print("  bound %s -> xpad" % os.path.basename(i))
                bound_any = True
            except OSError as e:
                print(c(RED, "  could not bind %s: %s" % (os.path.basename(i), e)))
    if bound_any:
        print(c(GRN, "  controller now claimed by xpad - paddles on."))

    try:
        os.makedirs("/etc/udev/rules.d", exist_ok=True)
        with open(STEAM_RULE_PATH, "w") as fh:
            fh.write(STEAM_RULE_CONTENT)
        cmd(["udevadm", "control", "--reload-rules"])
        cmd(["udevadm", "trigger"])
        print("  wrote %s" % STEAM_RULE_PATH)
    except OSError as e:
        print(c(RED, "  could not write udev rule:"), e)

    try:
        upsert_sdl_block(load_config(), "expose back paddles (paddle1..4) "
                                        "to SDL")
        print("  updated SDL mapping exposing paddle1..4")
    except OSError as e:
        print(c(RED, "  could not write SDL mapping:"), e)

    evs = [d for d in input_devices() if "0b00" in (d.get("info") or "").lower() or
           "elite" in (d.get("name") or "").lower()]
    if not evs or not evs[0].get("event"):
        print(c(YEL, "\nno Elite 2 input device yet - replug it, then run "
                     "`xbaz paddle-enable` again to test."))
        return
    ev = evs[0].get("event")
    print(c(GRN, "\npaddles enabled on %s (%s)" % (ev, evs[0].get("name"))))
    print(c(YEL, "Press and HOLD each back paddle one at a time, then release "
                 "(Ctrl+C to quit).\n"))
    try:
        subprocess.call(["sudo", "evtest", "--grab", ev])
    except FileNotFoundError:
        print(c(YEL, "evtest not installed - paddles are enabled; use "
                     "`xbaz live-view` for a live test."))
    sys.exit(0)


def menu():
    _, cols = shutil.get_terminal_size((80, 24))
    print(c(CYN, "=" * min(cols, 60)))
    print(c(BOLD, "  XBaz  |  Xbox Elite Series 2 controller manager"))
    print(c(CYN, "=" * min(cols, 60)))
    items = [
        ("1", "set-default", "set the Elite 2 as default controller everywhere"),
        ("2", "linux-fix", "apply the stock xpad Linux compatibility fix"),
        ("3", "paddle-enable", "turn on the 4 back paddles"),
        ("4", "restore-clean", "remove leftover hacks -> clean profile"),
        ("c", "customize", "configure the controller (mapping, dead zones, swap)"),
        ("t", "live-view", "live controller viewer (buttons + axes)"),
        ("s", "status", "read-only diagnostic (driver, bind, leftover hacks)"),
        ("q", "quit", "leave XBaz"),
    ]
    while True:
        print()
        for key, label, _d in items:
            print("  [%s] %s" % (key, label))
        try:
            choice = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            break
        if choice == "q":
            print("bye.")
            break
        elif choice in ("1", "s", "set-default", "setdefault"):
            steampad()
        elif choice in ("2", "linux", "linux-fix", "fix"):
            bind()
        elif choice in ("3", "paddles", "paddle", "paddle-enable"):
            paddles()
        elif choice in ("4", "r", "restore", "restore-clean", "reset"):
            reset()
        elif choice in ("c", "customize", "configure", "config"):
            customize()
        elif choice in ("t", "live-view", "liveview", "live"):
            liveview()
        else:
            print("unknown option.")


def _dispatch(args):
    if args.command in ("customize", "configure", "config", "cfg"):
        if args.json_apply:
            customize_json(args.json_apply)
        elif args.show:
            show_config()
        else:
            customize()
        return
    if args.command in ("live-view", "liveview", "live"):
        liveview(frames=args.frames, seconds=args.seconds)
        return
    cmds = {
        "status": status,
        "set-default": steampad, "setdefault": steampad, "steam": steampad,
        "linux-fix": bind, "linuxfix": bind, "linux": bind, "bind": bind,
        "paddle-enable": paddles, "paddleenable": paddles,
        "paddles": paddles, "paddle": paddles,
        "restore-clean": reset, "restoreclean": reset, "restore": reset,
        "reset": reset, "clean": reset,
        "menu": menu,
    }
    fn = cmds.get(args.command)
    if fn is None:
        raise SystemExit("unknown command: %s" % args.command)
    fn()


def _parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="menu",
                    help="set-default | linux-fix | paddle-enable | "
                         "restore-clean | customize | live-view | status | menu")
    ap.add_argument("--json-apply", metavar="PATH",
                    help="customize: apply a controller config JSON file "
                         "(used by the GigaSort GUI) and exit")
    ap.add_argument("--show", action="store_true",
                    help="customize: print the saved controller config and exit")
    ap.add_argument("--frames", type=int, default=0,
                    help="live-view: stop after N event frames (0 = infinite)")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="live-view: stop after N seconds (0 = untimed)")
    return ap


def main(argv=None):
    args = _parser().parse_args(argv)
    _dispatch(args)
    return 0


def run(argv=None):
    """In-process runner: return (returncode, output_text)."""
    import io  # noqa: PLC0415
    from contextlib import redirect_stdout, redirect_stderr  # noqa: PLC0415
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (2 if exc.code else 0)
    return rc, buf.getvalue()


if __name__ == "__main__":
    sys.exit(main())