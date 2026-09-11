"""XBaz companion tab — Xbox controller manager (options sidebar + output).

Adds a "controller configuration" section that mirrors the standalone
`xbaz customize` editor: remap paddles/buttons, adjust stick + trigger dead
zones, swap sticks, plus a live button/axis viewer. The GUI writes a config
JSON and applies it through `xbaz customize --json-apply`, so the settings
land in ~/.config/xbaz/controller.json + the SDL gamecontrollerdb and get
written to the live device via EVIOCSABS when the pad is connected.
"""

import json
import os
import tempfile

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, GLib

from gigasort.gui.pages.companion import CompanionPage

# Mirrors the standalone script's defaults (XBaz.py) so the sidebar can
# render the current config without importing the external script.
PHYS_ORDER = ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8", "b9",
              "b10", "b11", "b12", "b13", "b14"]
PHYS_LABEL = {"b0": "A", "b1": "B", "b2": "X", "b3": "Y",
              "b4": "LB", "b5": "RB", "b6": "Back", "b7": "Start",
              "b8": "Guide", "b9": "LSB", "b10": "RSB",
              "b11": "P1", "b12": "P3", "b13": "P2", "b14": "P4"}
DEFAULT_BUTTONS = {
    "paddle1": "b11", "paddle2": "b13", "paddle3": "b12", "paddle4": "b14",
}
PADDLES = ["paddle1", "paddle2", "paddle3", "paddle4"]
CONFIG_FILE = os.path.expanduser("~/.config/xbaz/controller.json")


def _load_cfg():
    cfg = {"version": 1, "name": "Default", "buttons": {},
           "axes": {}, "swap_sticks": False,
           "deadzone": {"left": 15, "right": 15, "trigger": 0},
           "trigger_mode": "linear"}
    try:
        with open(CONFIG_FILE) as fh:
            loaded = json.load(fh)
        for k in ("name", "buttons", "axes", "swap_sticks", "deadzone",
                  "trigger_mode"):
            if k in loaded:
                cfg[k] = loaded[k]
    except (OSError, ValueError):
        pass
    return cfg


def _phys_str(phys):
    return "%s (%s)" % (phys, PHYS_LABEL.get(phys, phys.upper()))


class XBazPage(CompanionPage):
    __gtype_name__ = "GigaSortXBazPage"

    TOOL_NAME = "XBaz"
    MODULE = "gigasort.core.xbaz"

    def _build_sidebar(self):
        note = Gtk.Label(
            label="Xbox Elite Series 2 controller manager. "
                  "Set to default, Linux compatibility fix, and the paddle "
                  "enabler need root (re-invoke via sudo). The config editor "
                  "and live viewer run without root.",
            css_classes=["dim-label"])
        note.set_wrap(True)
        note.set_xalign(0)
        self._options.append(note)

        self._run_button.set_visible(False)

        self._add_button("Set to default", "suggested-action").connect(
            "clicked", lambda *a: self._run_cmd("set-default"))
        self._add_button("Linux compatibility fix").connect(
            "clicked", lambda *a: self._run_cmd("linux-fix"))
        self._add_button("Paddle enabler").connect(
            "clicked", lambda *a: self._run_cmd("paddle-enable"))
        self._add_button("Restore to clean profile").connect(
            "clicked", lambda *a: self._run_cmd("restore-clean"))
        self._add_button("Status (diagnostic)").connect(
            "clicked", lambda *a: self._run_cmd("status"))

        self._options.append(Gtk.Separator())
        head = Gtk.Label(label="Controller configuration",
                         css_classes=["title-4"])
        head.set_xalign(0)
        self._options.append(head)

        self._cfg = _load_cfg()

        self._paddle_combos = {}
        for paddle in PADDLES:
            combo = self._add_combo("Remap %s" % paddle.title(),
                                    self._paddle_options(paddle, self._cfg))
            combo.set_selected(self._paddle_index(paddle, self._cfg))
            self._paddle_combos[paddle] = combo

        self._dz_left = self._add_spin(
            "Left stick dead zone", self._cfg.get("deadzone", {}).get("left", 15))
        self._dz_right = self._add_spin(
            "Right stick dead zone", self._cfg.get("deadzone", {}).get("right", 15))
        self._dz_trig = self._add_spin(
            "Trigger dead zone", self._cfg.get("deadzone", {}).get("trigger", 0))

        self._swap = self._add_toggle(
            "Swap sticks (L &lt;-&gt; R)",
            "Swaps the left and right stick roles in the SDL mapping.")
        self._swap.set_active(bool(self._cfg.get("swap_sticks")))

        self._add_button("Save & apply config", "suggested-action").connect(
            "clicked", lambda *a: self._apply_cfg())
        self._add_button("Show current config").connect(
            "clicked", lambda *a: self._run_cmd("customize", "--show"))
        self._add_button("Live viewer (10s)").connect(
            "clicked", lambda *a: self._run_cmd("live-view", "--seconds", "10"))
        self._add_button("Stop running command").connect(
            "clicked", lambda *a: self._stop_proc())

    def _add_spin(self, label, value):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cap = Gtk.Label(label=label, css_classes=["dim-label"])
        cap.set_xalign(0)
        box.append(cap)
        spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        spin.set_value(float(value))
        box.append(spin)
        self._options.append(box)
        return spin

    def _paddle_options(self, paddle, cfg):
        """Paddle remap choices: the current/default target plus every
        physical button that is not already bound to another semantic (so an
        apply can never collide)."""
        used = set((cfg.get("buttons") or {}).values())
        for p in PADDLES:
            if p != paddle:
                used.add(DEFAULT_BUTTONS[p])
        cur = (cfg.get("buttons") or {}).get(paddle) or DEFAULT_BUTTONS[paddle]
        opts = [_phys_str(cur)]
        for phys in PHYS_ORDER:
            if phys not in used and _phys_str(phys) not in opts:
                opts.append(_phys_str(phys))
        return opts

    def _paddle_index(self, paddle, cfg):
        cur = (cfg.get("buttons") or {}).get(paddle) or DEFAULT_BUTTONS[paddle]
        opts = self._paddle_options(paddle, cfg)
        for i, o in enumerate(opts):
            if o.startswith(cur + " "):
                return i
        return 0

    def _current_paddle_choice(self, paddle):
        opts = self._paddle_options(paddle, self._cfg)
        i = self._paddle_combos[paddle].get_selected()
        if i < 0 or i >= len(opts):
            return DEFAULT_BUTTONS[paddle]
        return opts[i].split(" ")[0]

    def _build_cfg(self):
        cfg = {"version": 1, "name": "GUI custom",
               "buttons": {}, "axes": {},
               "swap_sticks": bool(self._swap.get_active()),
               "deadzone": {"left": int(self._dz_left.get_value()),
                            "right": int(self._dz_right.get_value()),
                            "trigger": int(self._dz_trig.get_value())},
               "trigger_mode": "linear"}
        for paddle in PADDLES:
            chosen = self._current_paddle_choice(paddle)
            if chosen != DEFAULT_BUTTONS[paddle]:
                cfg["buttons"][paddle] = chosen
        return cfg

    def _apply_cfg(self):
        self._cfg = self._build_cfg()
        cfg_dir = os.path.expanduser("~/.config/xbaz")
        os.makedirs(cfg_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="gui-cfg-", suffix=".json",
                                    dir=cfg_dir)
        with os.fdopen(fd, "w") as fh:
            json.dump(self._cfg, fh, indent=2)
        self._pending_cfg = path
        self._pending_refresh = True
        self.run_subprocess(["customize", "--json-apply", path])

    def _on_done(self, rc):
        result = CompanionPage._on_done(self, rc)
        path = getattr(self, "_pending_cfg", None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        self._pending_cfg = None
        if getattr(self, "_pending_refresh", False):
            self._pending_refresh = False
            GLib.idle_add(self._refresh_cfg)
        return result

    def _refresh_cfg(self):
        self._cfg = _load_cfg()
        for paddle in PADDLES:
            combo = self._paddle_combos[paddle]
            combo.set_model(Gtk.StringList.new(
                self._paddle_options(paddle, self._cfg)))
            combo.set_selected(self._paddle_index(paddle, self._cfg))
        dz = self._cfg.get("deadzone") or {}
        self._dz_left.set_value(dz.get("left", 15))
        self._dz_right.set_value(dz.get("right", 15))
        self._dz_trig.set_value(dz.get("trigger", 0))
        self._swap.set_active(bool(self._cfg.get("swap_sticks")))
        return False

    def _stop_proc(self):
        proc = getattr(self, "_proc", None)
        if proc and proc.poll() is None:
            proc.terminate()
            self._append("stopped.\n")

    def _run_cmd(self, cmd, *extra):
        self.run_subprocess([cmd] + list(extra))