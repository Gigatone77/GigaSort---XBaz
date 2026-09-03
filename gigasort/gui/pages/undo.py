"""Undo page — reverse the last sort run from the manifest."""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from gigasort.core import storage
from gigasort.core.undo import run_undo
from gigasort.gui.util import esc


def _auto_confirm(*args):
    return "confirm"


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
            moves = storage.load_manifest(self.workspace)
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
        self._status_label.set_text("%d move(s) recorded." % len(moves))
        self._undo_button.set_sensitive(True)
        for m in moves:
            self._list.append(Adw.ActionRow(
                title=esc(m.get("dst") or ""),
                subtitle="&lt;- %s" % esc(m.get("src") or ""),
            ))

    def _on_undo(self, *args):
        self._undo_button.set_sensitive(False)
        self._status_label.set_text("Undoing...")

        def worker():
            try:
                run_undo(self.workspace, input_fn=_auto_confirm)
                GLib.idle_add(self._on_done)
            except Exception as e:
                GLib.idle_add(self._on_error, e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_done(self):
        self.refresh()
        self._undo_button.set_sensitive(True)
        self._status_label.set_text("Undo complete.")

    def _on_error(self, error):
        self._undo_button.set_sensitive(True)
        self._status_label.set_text("Undo error: %s" % error)
