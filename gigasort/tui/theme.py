"""Theme engine + interactive theme editor (ANSI truecolor)."""

import json
import os
import re

from gigasort.core import storage

THEME_DEFAULTS = {
    "bg": "#1b1b1b", "fg": "#d8d8d8", "accent": "#4fc1ff",
    "highlight": "#3a3a3a", "border": "single", "scale": 100,
}

_PALETTES = {
    "monokai": {"bg": "#272822", "fg": "#f8f8f2", "accent": "#a6e22e",
                "highlight": "#3e3d32"},
    "solarized": {"bg": "#002b36", "fg": "#839496", "accent": "#b58900",
                  "highlight": "#073642"},
    "gruvbox": {"bg": "#282828", "fg": "#ebdbb2", "accent": "#fabd2f",
                "highlight": "#3c3836"},
    "nord": {"bg": "#2e3440", "fg": "#d8dee9", "accent": "#88c0d0",
             "highlight": "#3b4252"},
    "one-dark": {"bg": "#282c34", "fg": "#abb2bf", "accent": "#61afef",
                 "highlight": "#3e4451"},
}

_BORDER_SETS = {
    "single": ("─", "│", "┌", "┐", "└", "┘"),
    "double": ("═", "║", "╔", "╗", "╚", "╝"),
    "rounded": ("─", "│", "╭", "╮", "╰", "╯"),
    "ascii": ("-", "|", "+", "+", "+", "+"),
}


def _hex_chans(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_ansi(kind, hexcolor):
    r, g, b = _hex_chans(hexcolor)
    if kind == "bg":
        return "\033[48;2;%d;%d;%dm" % (r, g, b)
    if kind == "fg" or kind == "accent":
        return "\033[38;2;%d;%d;%dm" % (r, g, b)
    return ""


def _tune_band(hexcolor, light):
    """Slide a color toward a luminance band (235 light / 40 dark) preserving
    hue by scaling to the target luminance."""
    r, g, b = _hex_chans(hexcolor)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    target = 235 if light else 40
    if abs(lum - target) < 45:
        return hexcolor
    scale = target / lum if lum else 1.0
    scale = max(0.35, min(2.2, scale))
    return "#%02x%02x%02x" % (
        max(0, min(255, int(r * scale))),
        max(0, min(255, int(g * scale))),
        max(0, min(255, int(b * scale))))


def auto_tune_colors(colors, mode):
    light = mode == "light"
    out = dict(colors)
    for k in ("bg", "fg", "accent", "highlight"):
        if out.get(k):
            out[k] = _tune_band(out[k], light)
    return out


def resolve_theme(settings, mode=None):
    """Resolve settings into an ANSI-ready theme."""
    colors = dict(THEME_DEFAULTS)
    saved = settings.get("theme_colors")
    if isinstance(saved, dict):
        colors.update(saved)
    if settings.get("theme_override") is False and mode:
        colors = auto_tune_colors(colors, mode)
    border = settings.get("theme_border", "single")
    scale = int(settings.get("theme_scale", 100))
    return {
        "fg": _rgb_ansi("fg", colors["fg"]),
        "bg": _rgb_ansi("bg", colors["bg"]),
        "accent": _rgb_ansi("accent", colors["accent"]),
        "reset": "\033[0m",
        "hl_bg": _rgb_ansi("bg", colors["highlight"]),
        "colors": colors,
        "border": _BORDER_SETS.get(border, _BORDER_SETS["single"]),
        "scale": scale,
    }


def read_theme_file(path):
    """Read a minimal palette config (JSON or key=value .theme)."""
    colors = dict(THEME_DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return colors
    text = text.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            for k in ("bg", "fg", "accent", "highlight"):
                if data.get(k):
                    colors[k] = data[k]
        except ValueError:
            pass
    else:
        for line in text.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k in colors:
                    colors[k] = v
    return colors


def theme_editor(folder):
    """Interactive full-screen theme editor (best-effort; falls back to a
    simple prompt loop when not a TTY)."""
    settings = storage.load_settings(folder)
    colors = dict(settings.get("theme_colors") or THEME_DEFAULTS)
    border = settings.get("theme_border", "single")
    scale = int(settings.get("theme_scale", 100))
    print("Theme editor - arrows adjust, q to save+quit, esc to quit")
    print("  palette: [m]onokai [s]olarized [g]ruvbox [n]ord [o]ne-dark")
    while True:
        try:
            ch = input("[b]g [f]g [a]ccent [h]l | palette | q/save, esc: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if ch in ("q", "esc"):
            break
        if ch in ("m", "s", "g", "n", "o"):
            name = {"m": "monokai", "s": "solarized", "g": "gruvbox",
                    "n": "nord", "o": "one-dark"}[ch]
            colors.update(_PALETTES[name])
            continue
        if ch in ("b", "f", "a", "h"):
            key = {"b": "bg", "f": "fg", "a": "accent", "h": "highlight"}[ch]
            hexv = input("  new #rrggbb for %s [current %s]: "
                         % (key, colors[key])).strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", hexv or ""):
                colors[key] = hexv
    settings["theme_colors"] = colors
    settings["theme_border"] = border
    settings["theme_scale"] = scale
    storage.save_settings(folder, settings)
    print("Theme saved.")
