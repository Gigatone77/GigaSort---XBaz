"""Undo page — reverse the last sort run from the manifest."""

import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from gigasort.core.undo import undo_move, list_undone
from gigasort.gui.util import esc


class UndoPage(Adw.NavigationPage):
    __gtype_name__ = "GigaSortUndoPage"

    def __init__(self, workspace=None, scan_page=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Undo")
        self.workspace = workspace
        self.scan_page = scan_page

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        self._undo_button = Gtk.Button(label="Undo Last Sort")
        self._undo_button.add_css_class("destructive-action")
        self._undo_button.connect("clicked", self._on_undo)
        outer.append(self._undo_button)

        self._status_label = Gtk.Label(label="", css_classes=["dim-label"])
        self._status_label.set_use_markup(False)
        self._status_label.set_xalign(0)
        self._status_label.set_hexpand(True)
        outer.append(self._status_label)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self._list)
        scroll.set_vexpand(True)
        outer.append(scroll)

        self.refresh()

    def refresh(self):
        try:
            moves = list_undone(self.workspace)
        except Exception:
            moves = []
        self._moves = moves

        def clear(ls):
            c = ls.get_first_child()
            while c is not None:
                n = c.get_next_sibling()
                ls.remove(c)
                c = n
        clear(self._list)

        if not moves:
            self._status_label.set_text("Nothing to undo - manifest is empty.")
            self._undo_button.set_sensitive(False)
            return
        applied = [m for m in moves if m.get("applied")]
        self._status_label.set_text(
            "%d sort run(s) recorded (%d applied)." % (len(moves),
                                                       len(applied)))
        self._undo_button.set_sensitive(bool(applied))
        for m in applied:
            for f in m.get("files", []):
                self._list.append(Adw.ActionRow(
                    title=esc(f),
                    subtitle="sort run %s  (%s)" % (
                        esc(m.get("id") or ""),
                        time.strftime("%H:%M", time.localtime(m.get("time", 0))))))

    def _on_undo(self, *args):
        self._undo_button.set_sensitive(False)
        self._status_label.set_text("Undoing...")

        def worker():
            try:
                undone, skipped = undo_move(self.workspace)
                GLib.idle_add(self._on_done, undone, skipped)
            except Exception as e:
                GLib.idle_add(self._on_error, e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_done(self, undone, skipped):
        self.refresh()
        self._undo_button.set_sensitive(True)
        self._status_label.set_text(
            "Undo complete: %d moved back, %d skipped." % (undone, skipped))

    def _on_error(self, error):
        self._undo_button.set_sensitive(True)
        self._status_label.set_text("Undo error: %s" % error)
