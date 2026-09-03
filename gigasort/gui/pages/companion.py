"""Reusable companion-tool launcher page.

A two-pane page: an options sidebar (left) + an output area (right). It runs
a companion CLI tool (GigaSlim / CyberFlashSync / XBaz) as a subprocess in a
background thread and streams its stdout/stderr into a read-only TextView.

Subclasses build the option widgets (sidebar) in `_build_sidebar()` and
assemble the argv in `_build_argv()`.
"""

import os
import shlex
import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Pango


class CompanionPage(Adw.NavigationPage):
    """Base companion tab. Subclass and set TOOL_NAME + SCRIPT + build sidebar."""

    TOOL_NAME = "Tool"
    SCRIPT = None            # script filename (e.g. GigaSlim.py)
    SCRIPT_CANDIDATES = []   # absolute candidate paths

    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title(self.TOOL_NAME)
        self.workspace = workspace
        self._proc = None

        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_wide_handle(True)
        self.set_child(split)

        # ---- options sidebar (left) ----
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.set_margin_top(12)
        side.set_margin_bottom(12)
        side.set_margin_start(12)
        side.set_margin_end(6)
        side.set_size_request(250, -1)

        title = Gtk.Label(label=self.TOOL_NAME,
                          css_classes=["title-1"])
        title.set_xalign(0)
        side.append(title)

        self._subtitle = Gtk.Label(
            label=self.SCRIPT or "", css_classes=["dim-label"])
        self._subtitle.set_xalign(0)
        self._subtitle.set_wrap(True)
        side.append(self._subtitle)

        self._options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        side.append(self._options)

        self._run_button = Gtk.Button(label="Run")
        self._run_button.add_css_class("suggested-action")
        self._run_button.connect("clicked", self._on_run)
        side.append(self._run_button)

        self._status_label = Gtk.Label(label="", css_classes=["dim-label"])
        self._status_label.set_xalign(0)
        self._status_label.set_wrap(True)
        side.append(self._status_label)

        side.append(Gtk.Label(hexpand=True))

        # ---- output area (right) ----
        self._text = Gtk.TextView()
        self._text.set_editable(False)
        self._text.set_cursor_visible(False)
        self._text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text.set_monospace(True)
        self._text.set_vexpand(True)
        self._text.set_hexpand(True)
        self._buf = self._text.get_buffer()

        sw = Gtk.ScrolledWindow()
        sw.set_child(self._text)
        sw.set_vexpand(True)
        sw.set_hexpand(True)
        split.set_start_child(side)
        split.set_end_child(sw)

        self._build_sidebar()

    # -- subclasses override these ------------------------------------------
    def _build_sidebar(self):
        self._options.append(Gtk.Label(label="(no options)", css_classes=["dim-label"]))

    def _build_argv(self):
        return [self.SCRIPT]

    # -- helpers for option widgets -----------------------------------------
    def _add_toggle(self, label, subtitle="", default=False):
        row = Adw.SwitchRow(title=label, subtitle=subtitle)
        row.set_active(default)
        self._options.append(row)
        return row

    def _add_entry(self, label, placeholder=""):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cap = Gtk.Label(label=label, css_classes=["dim-label"])
        cap.set_xalign(0)
        box.append(cap)
        entry = Gtk.Entry(placeholder_text=placeholder)
        box.append(entry)
        self._options.append(box)
        return entry

    def _add_combo(self, label, choices, default=0):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cap = Gtk.Label(label=label, css_classes=["dim-label"])
        cap.set_xalign(0)
        box.append(cap)
        combo = Gtk.DropDown.new_from_strings(list(choices))
        combo.set_selected(default)
        box.append(combo)
        self._options.append(box)
        return combo

    def _add_button(self, label, css_class=""):
        b = Gtk.Button(label=label)
        if css_class:
            b.add_css_class(css_class)
        self._options.append(b)
        return b

    # -- running ------------------------------------------------------------
    def _find_script(self):
        for c in self.SCRIPT_CANDIDATES:
            if os.path.isfile(c):
                return os.path.abspath(c)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local = os.path.join(os.path.expanduser("~/.local/share/gigasort"),
                             self.SCRIPT or "")
        if local and os.path.isfile(local):
            return local
        return None

    def _on_run(self, *args):
        self.run_subprocess(self._build_argv())

    def run_subprocess(self, argv):
        """Run `argv` (after the python script) and stream output. Safe to
        call from subclasses (e.g. from a per-command option button)."""
        import sys
        script = self._find_script()
        if not script:
            self._append("ERROR: %s not found.\n" % self.SCRIPT)
            return
        full = [sys.executable, script] + list(argv)
        self._status_label.set_text("Running...")
        self._run_button.set_sensitive(False)
        self._append("\n$ %s\n" % " ".join(shlex.quote(a) for a in full))

        def worker():
            try:
                proc = subprocess.Popen(
                    full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
                self._proc = proc
                for line in proc.stdout:
                    GLib.idle_add(self._append, line)
                proc.wait()
                rc = proc.returncode
                GLib.idle_add(self._on_done, rc)
            except Exception as e:
                GLib.idle_add(self._on_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _append(self, text):
        self._buf.insert_markup(
            self._buf.get_end_iter(), GLib.markup_escape_text(str(text)), -1)
        return False

    def _on_done(self, rc):
        self._run_button.set_sensitive(True)
        self._status_label.set_text(
            "Finished (exit %d)." % rc if rc else "Finished.")
        return False

    def _on_error(self, msg):
        self._run_button.set_sensitive(True)
        self._status_label.set_text("Error: %s" % msg)
        self._buf.insert(self._buf.get_end_iter(), "\nERROR: %s\n" % msg, -1)
        return False
