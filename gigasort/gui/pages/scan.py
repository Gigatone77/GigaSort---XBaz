"""Scan & Sort page — scan workspace, preview plan, apply moves."""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from gigasort.core import sort, verify
from gigasort.utils.format import human_size
from gigasort.constants import REJECT_BIN, TRASH_BIN, DUPLICATES_BIN
from gigasort.gui.util import esc, show_error


class ScanPage(Adw.NavigationPage):
    __gtype_name__ = "GigaSortScanPage"

    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Scan and Sort")
        self.workspace = workspace
        self._result = None
        self._task = None
        self.status_callback = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.append(controls)

        self._scan_button = Gtk.Button(label="Scan")
        self._scan_button.add_css_class("suggested-action")
        self._scan_button.connect("clicked", self._on_scan)
        controls.append(self._scan_button)

        self._apply_button = Gtk.Button(label="Apply")
        self._apply_button.add_css_class("destructive-action")
        self._apply_button.set_visible(False)
        self._apply_button.connect("clicked", self._on_apply)
        controls.append(self._apply_button)

        self._status_label = Gtk.Label(label="", css_classes=["dim-label"])
        self._status_label.set_use_markup(False)
        self._status_label.set_hexpand(True)
        self._status_label.set_xalign(0)
        self._status_label.set_ellipsize(3)
        controls.append(self._status_label)

        folder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._folder_button = Gtk.Button(label="Select Folder...")
        self._folder_button.connect("clicked", self._on_select_folder)
        folder_box.append(self._folder_button)

        self._path_label = Gtk.Label(label=str(self.workspace))
        self._path_label.set_use_markup(False)
        self._path_label.set_hexpand(True)
        self._path_label.set_xalign(0)
        self._path_label.set_ellipsize(3)
        folder_box.append(self._path_label)
        outer.append(folder_box)

        self._notebook = Gtk.Notebook()
        self._notebook.set_vexpand(True)
        outer.append(self._notebook)

        self._rejects_list = Gtk.ListBox()
        self._rejects_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._rejects_list), Gtk.Label(label="Rejects"))

        self._dupes_list = Gtk.ListBox()
        self._dupes_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._dupes_list), Gtk.Label(label="Duplicates"))

        self._plan_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._notebook.append_page(
            self._scroll(self._plan_box), Gtk.Label(label="Planned Moves"))

    def _scroll(self, child):
        sc = Gtk.ScrolledWindow()
        sc.set_child(child)
        sc.set_vexpand(True)
        return sc

    def _clear_list(self, ls):
        child = ls.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            ls.remove(child)
            child = nxt

    def _on_select_folder(self, *args):
        dialog = Gtk.FileDialog()
        dialog.set_title("Select mod workspace folder")
        has_folder = self.workspace and __import__("os").path.isdir(self.workspace)
        if self.workspace:
            import os
            from gi.repository import Gio
            folder = Gio.File.new_for_path(self.workspace)
        else:
            folder = None
        dialog.select_folder(self.get_root(), None, self._on_folder_selected, folder)

    def _on_folder_selected(self, dialog, result):
        import os
        from gi.repository import Gio
        try:
            file = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if file:
            self.workspace = file.get_path()
            self._path_label.set_text(self.workspace)
            self._status_label.set_text("Folder set. Click Scan.")

    def _on_scan(self, *args):
        self._status_label.set_text("Scanning...")
        self._scan_button.set_sensitive(False)
        self._result = None

        def worker():
            try:
                result = sort.scan_workspace(self.workspace)
                GLib.idle_add(self._on_scan_done, result)
            except Exception as e:
                GLib.idle_add(self._on_scan_error, e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _status_chip(self, status):
        """Small colored badge: OFFLINE (cached) / ONLINE (live) / UNVERIFIED."""
        badges = {
            "offline": ("OFFLINE", "success"),
            "online": ("ONLINE", "warning"),
            "unverified": ("UNVERIFIED", "error"),
        }
        text, cls = badges.get(status, ("UNVERIFIED", "error"))
        lbl = Gtk.Label(label=text)
        lbl.set_css_classes([cls, "giga-veri-chip"])
        return lbl

    def _row(self, fn, size, status=None):
        row = Adw.ActionRow(title=esc(fn), subtitle=human_size(size))
        if status and status != "unverified":
            row.add_suffix(self._status_chip(status))
        return row

    def _populate(self, result, statuses=None):
        statuses = statuses or {}

        self._clear_list(self._rejects_list)
        if result.rejects:
            for fn, size in result.rejects:
                self._rejects_list.append(
                    self._row(fn, size, statuses.get(fn)))
        else:
            self._rejects_list.append(
                Adw.ActionRow(title="No rejects - every file categorized"))

        self._clear_list(self._dupes_list)
        if result.duplicates:
            for fn, size in result.duplicates:
                self._dupes_list.append(
                    self._row(fn, size, statuses.get(fn)))
        else:
            self._dupes_list.append(
                Adw.ActionRow(title="No duplicates"))

        self._clear_list(self._plan_box)
        if result.plan:
            for cat in sorted(result.plan):
                files = result.plan[cat]
                grp = Adw.PreferencesGroup(title="%s  (%d)" % (esc(cat), len(files)))
                for fn, size in files:
                    grp.add(self._row(fn, size, statuses.get(fn)))
                self._plan_box.append(grp)
        else:
            self._plan_box.append(
                Adw.ActionRow(title="Nothing to move"))

    def _on_scan_done(self, result):
        self._result = result
        self._scan_button.set_sensitive(True)

        totals = (
            "kept %d  |  duplicates %d  |  rejects %d  |  %s"
            % (len(result.kept), len(result.duplicates), len(result.rejects),
               human_size(result.total_bytes))
        )
        self._status_label.set_text(totals)
        self._populate(result)

        def worker():
            try:
                statuses = verify.verification_statuses(
                    result.folder, result.kept)
                GLib.idle_add(self._populate, result, statuses)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

        self._apply_button.set_visible(
            bool(result.plan or result.rejects or result.duplicates))

    def _on_scan_error(self, error):
        self._scan_button.set_sensitive(True)
        self._status_label.set_text(
            "Scan failed - see the error dialog for details.")
        show_error(self, "Scan failed", error)

    def _on_apply(self, *args):
        self._apply_button.set_sensitive(False)
        self._status_label.set_text("Applying...")

        def worker():
            try:
                result = sort.execute_sort(self._result,
                                           input_fn=lambda *a: "confirm")
                GLib.idle_add(self._on_apply_done, result)
            except Exception as e:
                GLib.idle_add(self._on_apply_error, e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_apply_done(self, result):
        self._apply_button.set_sensitive(True)
        self._apply_button.set_visible(False)
        moved = result.get("moved", 0)
        flagged = result.get("flagged_unverified", [])
        if flagged:
            msg = (
                "%d file(s) moved.\n\n%d UNVERIFIED file(s) were left "
                "untouched (never moved/trashed):\n\n%s"
                % (moved, len(flagged), "\n".join("  \u2022 %s" % f
                                                  for f in flagged))
            )
            self._status_label.set_text(
                "%d moved; %d unverified left in place."
                % (moved, len(flagged)))
            show_error(self, "Apply finished with skipped files", msg)
        else:
            self._status_label.set_text("Applied %d move(s)." % moved)
        try:
            from gigasort.core import tags
            tags.write_tags(self.workspace)
        except Exception:
            pass
        if self.status_callback:
            self.status_callback()

    def _on_apply_error(self, error):
        self._apply_button.set_sensitive(True)
        self._status_label.set_text(
            "Apply failed - see the error dialog for details.")
        show_error(self, "Apply failed", error)
