"""XBaz companion tab — Xbox controller manager (options sidebar + output)."""

import os

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gigasort.gui.pages.companion import CompanionPage


class XBazPage(CompanionPage):
    __gtype_name__ = "GigaSortXBazPage"

    TOOL_NAME = "XBaz"
    SCRIPT = "XBaz.py"
    SCRIPT_CANDIDATES = [
        os.path.expanduser("~/Games/XBaz.py"),
        "/run/media/Gigatone/ToolBox/ToolBox/Cyberpunk-Tools/GigaSort-core-tools/XBaz.py",
    ]

    def _build_sidebar(self):
        note = Gtk.Label(
            label="Xbox Elite Series 2 controller manager. "
                  "Status is read-only; bind/reset/steam need root "
                  "(re-invoke via sudo).",
            css_classes=["dim-label"])
        note.set_wrap(True)
        note.set_xalign(0)
        self._options.append(note)

        self._run_button.set_visible(False)

        self._add_button("Status (diagnostic)", "suggested-action").connect(
            "clicked", lambda *a: self._run_cmd("status"))
        self._add_button("Bind stock xpad").connect(
            "clicked", lambda *a: self._run_cmd("bind"))
        self._add_button("Reset driver hacks").connect(
            "clicked", lambda *a: self._run_cmd("reset"))
        self._add_button("Steam Input / SDL setup").connect(
            "clicked", lambda *a: self._run_cmd("steam"))
        self._add_button("Paddle test (interactive)").connect(
            "clicked", lambda *a: self._run_cmd("paddles"))
        self._add_button("Full-screen menu").connect(
            "clicked", lambda *a: self._run_cmd("menu"))

    def _run_cmd(self, cmd):
        self.run_subprocess([cmd])
