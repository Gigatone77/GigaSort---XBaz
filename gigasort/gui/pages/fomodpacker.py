"""FOMODPacker companion tab — activate + customize FOMOD installers.

The scan routes every FOMOD-installer archive into the workspace _FOMODS
bin (structural detection — never a filename keyword). This page lists
those archives so the user can activate each one individually: pick a
vehicle, dump its full step/group/plugin option tree (with preview image
paths), then build the customized game tree with a JSON picks file.

The page drives the native gigasort CLI (python -m gigasort
--fomodpacker …) in a background thread and streams output like the other
companion tabs.
"""

import os
import shlex
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, GLib

from gigasort.constants import FOMOD_BIN
from gigasort.gui.pages.companion import CompanionPage


class FomodPackerPage(CompanionPage):
    __gtype_name__ = "GigaSortFomodPackerPage"

    TOOL_NAME = "FOMODPacker"

    def _build_sidebar(self):
        self._run_button.set_visible(False)
        self._subtitle.set_text(
            "Activate FOMOD installers one vehicle at a time. Scan parks "
            "them in _FOMODS (detected by archive structure, never by "
            "filename keywords). Choose a vehicle, inspect its options, "
            "then build from a picks file.")

        self._folder_entry = self._add_entry("Workspace", "")
        self._folder_entry.set_text(self.workspace or "")
        self._folder_entry.connect("changed", lambda *a: self._refresh())

        self._combo = self._add_combo("Vehicle (FOMOD)", ["(none)"])
        self._combo.connect("notify::selected", lambda *a: self._update_desc())

        self._desc = Gtk.Label(label="", css_classes=["dim-label"])
        self._desc.set_xalign(0)
        self._desc.set_wrap(True)
        self._options.append(self._desc)

        self._picks_entry = self._add_entry(
            "Picks JSON file", "/path/to/picks.json")
        self._picks_entry.set_text("")

        self._dry = self._add_toggle("Dry run", "preview, change nothing")

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._inspect_btn = Gtk.Button(label="Inspect options")
        self._inspect_btn.connect("clicked", lambda *a: self._inspect())
        btn_row.append(self._inspect_btn)
        self._build_btn = Gtk.Button(label="Build custom")
        self._build_btn.add_css_class("suggested-action")
        self._build_btn.connect("clicked", lambda *a: self._build())
        btn_row.append(self._build_btn)
        self._options.append(btn_row)

        self._refresh()

    # ------------------------------------------------------------------
    def _workspace(self):
        return os.path.abspath(self._folder_entry.get_text().strip() or ".")

    def _fomod_dir(self):
        return os.path.join(self._workspace(), FOMOD_BIN)

    def _selected_archive(self):
        i = self._combo.get_selected()
        models = self._combo.get_model()
        if i < 0 or i >= models.get_n_items():
            return None
        text = models.get_string(i)
        if text in ("", "(none)"):
            return None
        return text

    def _refresh(self):
        """Rebuild the vehicle dropdown from the _FOMODS bin."""
        names = []
        d = self._fomod_dir()
        if os.path.isdir(d):
            names = sorted(n for n in os.listdir(d)
                           if n.lower().endswith(".zip"))
        strings = Gtk.StringList.new(["(none)"] + names)
        self._combo.set_model(strings)
        self._combo.set_selected(0)
        self._update_desc()

    def _update_desc(self):
        name = self._selected_archive() or ""
        self._desc.set_text("Selected: %s" % name if name
                            else "No FOMOD parked yet — rescan the workspace.")

    # ------------------------------------------------------------------
    def _base_cmd(self):
        cmd = ["--fomodpacker", "--folder", self._workspace()]
        name = self._selected_archive()
        if name:
            cmd += ["--fomod-archive", name]
        if self._dry.get_active():
            cmd.append("--dry-run")
        return cmd

    def _inspect(self):
        if not self._selected_archive():
            self._append("FOMODPacker: no vehicle selected.\n")
            return
        self.run_subprocess(self._base_cmd())

    def _build(self):
        picks = self._picks_entry.get_text().strip()
        if not self._selected_archive():
            self._append("FOMODPacker: no vehicle selected.\n")
            return
        if not picks or not os.path.isfile(picks):
            self._append("FOMODPacker: picks JSON file not found: %s\n"
                         % (picks or "(empty)"))
            return
        cmd = self._base_cmd() + ["--fomod-picks", picks]
        self.run_subprocess(cmd)

    def run_subprocess(self, argv):
        """Invoke the native GigaSort CLI (FOMODPacker is a core mode)."""
        folder = self._workspace()
        full = [sys.executable, "-m", "gigasort"] + list(argv)
        self._status_label.set_text("Running...")
        self._run_button.set_sensitive(False)
        self._append("\n$ %s\n" % " ".join(shlex.quote(a) for a in full))
        import subprocess
        import threading

        def worker():
            try:
                proc = subprocess.Popen(
                    full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, bufsize=1,
                    cwd=folder if os.path.isdir(folder) else None)
                self._proc = proc
                for line in proc.stdout:
                    GLib.idle_add(self._append, line)
                proc.wait()
                rc = proc.returncode
                GLib.idle_add(self._on_done, rc)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._on_error, str(e))

        threading.Thread(target=worker, daemon=True).start()