"""Scan & Sort page — scan workspace, preview plan, apply moves."""

import os
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from gigasort.core import storage, verify
from gigasort.core.scan import scan_workspace
from gigasort.core.engine import execute_sort
from gigasort.core.categorize import extract_mod_author
from gigasort.utils import human_size
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

        self._conn_label = Gtk.Label(
            label="Offline", css_classes=["giga-veri-chip", "error"])
        self._conn_label.set_ellipsize(3)
        controls.append(self._conn_label)

        folder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        folder_label = Gtk.Label(label="Folder:")
        folder_label.set_xalign(0)
        folder_box.append(folder_label)
        self._folder_entry = Gtk.Entry(
            placeholder_text="Path to mod folder to scan")
        self._folder_entry.set_text(self.workspace or "")
        self._folder_entry.set_hexpand(True)
        folder_box.append(self._folder_entry)
        outer.append(folder_box)

        authors_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._author_plus_batch = Gtk.CheckButton(
            label="Author + organize rest")
        self._author_plus_batch.set_active(True)
        authors_box.append(self._author_plus_batch)
        authors_label = Gtk.Label(label="Author(s) folder:")
        authors_label.set_xalign(0)
        authors_label.add_css_class("dim-label")
        authors_box.append(authors_label)
        self._authors_entry = Gtk.Entry(
            placeholder_text="Comma-separated: ScorpionTank, AuthorName")
        self._authors_entry.set_hexpand(True)
        authors_box.append(self._authors_entry)
        outer.append(authors_box)

        gb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._group_frameworks = Gtk.CheckButton(
            label="Group by shared framework")
        gb_box.append(self._group_frameworks)
        gb_hint = Gtk.Label(label="(requires 'Author + organize rest')")
        gb_hint.set_xalign(0)
        gb_hint.add_css_class("dim-label")
        gb_box.append(gb_hint)
        outer.append(gb_box)

        game_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._game_dir_entry = Gtk.Entry(
            placeholder_text="Path to the installed Cyberpunk 2077 folder "
                             "(enables conflict check); leave empty to disable")
        self._game_dir_entry.set_hexpand(True)
        game_box.append(self._game_dir_entry)
        game_btn = Gtk.Button(label="Browse...")
        game_btn.connect("clicked", self._on_select_game_dir)
        game_box.append(game_btn)
        outer.append(game_box)

        if self.workspace:
            try:
                settings = storage.load_settings(self.workspace)
                saved = settings.get("toplevel_authors", "")
                if saved:
                    self._authors_entry.set_text(", ".join(saved))
                self._author_plus_batch.set_active(
                    bool(settings.get("author_plus_batch", True)))
                self._group_frameworks.set_active(
                    bool(settings.get("group_frameworks")))
                if settings.get("game_dir"):
                    self._game_dir_entry.set_text(settings["game_dir"])
            except Exception:
                pass

        self._notebook = Gtk.Notebook()
        self._notebook.set_vexpand(True)
        outer.append(self._notebook)

        self._rejects_list = Gtk.ListBox()
        self._rejects_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._rejects_list), Gtk.Label(label="Rejects"))

        self._hold_list = Gtk.ListBox()
        self._hold_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._hold_list), Gtk.Label(label="On Hold"))

        self._dupes_list = Gtk.ListBox()
        self._dupes_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._dupes_list), Gtk.Label(label="Duplicates"))

        self._relocate_list = Gtk.ListBox()
        self._relocate_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._relocate_list),
            Gtk.Label(label="Relocations"))

        self._placement_list = Gtk.ListBox()
        self._placement_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._placement_list),
            Gtk.Label(label="Final Sweep"))

        self._struct_list = Gtk.ListBox()
        self._struct_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._notebook.append_page(
            self._scroll(self._struct_list),
            Gtk.Label(label="Structure"))

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

    def _populate_hold(self, conflicts=None):
        conflicts = conflicts or {}
        self._clear_list(self._hold_list)
        if not conflicts:
            self._hold_list.append(Adw.ActionRow(
                title="No game-directory conflicts detected."))
            return
        for fn in sorted(conflicts):
            paths = conflicts[fn]
            row = Adw.ActionRow(
                title=esc(fn),
                subtitle="Would overwrite %d installed file(s) - sent to "
                         "_ON_HOLD for review" % len(paths))
            detail = "\n".join("  \u2022 %s" % p for p in paths[:8])
            if len(paths) > 8:
                detail += "\n  \u2022 ... and %d more" % (len(paths) - 8)
            hl = Gtk.Label(label=detail, wrap=True, css_classes=["dim-label"])
            hl.set_xalign(0)
            row.add_suffix(hl)
            self._hold_list.append(row)

    def _populate_struct(self, structs=None):
        structs = structs or {}
        self._clear_list(self._struct_list)
        if not structs:
            self._struct_list.append(Adw.ActionRow(
                title="No verified archives to report structure for yet."))
            return
        reports = []
        for fn, s in structs.items():
            if s is False:
                reports.append(Adw.ActionRow(
                    title=esc(fn),
                    subtitle="Unstructured - archive interior is NOT a "
                             "CP2077 game layout (manual handling needed)"))
            elif s is True:
                reports.append(Adw.ActionRow(
                    title=esc(fn),
                    subtitle="CP2077 game-path structure confirmed"))
            else:
                reports.append(Adw.ActionRow(
                    title=esc(fn),
                    subtitle="Structure unknown - archive not readable"))
        for row in sorted(reports, key=lambda r: r.get_title()):
            self._struct_list.append(row)

    def _populate_placement(self, issues=None):
        self._clear_list(self._placement_list)
        issues = issues or []
        labels = {
            "misplaced": "wrong category/author folder",
            "root": "still at workspace root",
            "split-page": "split across categories",
        }
        if not issues:
            self._placement_list.append(Adw.ActionRow(
                title="All mods are where the sort expects them."))
            return
        for i in issues:
            detail = i.get("expected") or ""
            if i.get("current") and detail and i["current"] != detail:
                detail = "%s  ->  %s" % (i["current"], detail)
            row = Adw.ActionRow(
                title=esc(i.get("file")),
                subtitle="%s: %s" % (esc(labels.get(i.get("kind"), i.get("kind"))),
                                     esc(detail)))
            self._placement_list.append(row)

    def _on_select_game_dir(self, *args):
        from gi.repository import Gio
        dialog = Gtk.FileDialog()
        dialog.set_title("Select the installed Cyberpunk 2077 folder")
        cur = self._game_dir_entry.get_text().strip()
        start = Gio.File.new_for_path(cur) if cur and os.path.isdir(cur) else None
        dialog.select_folder(self.get_root(), None,
                             self._on_game_dir_selected, start)

    def _on_game_dir_selected(self, dialog, result):
        try:
            file = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if file:
            self._game_dir_entry.set_text(file.get_path())

    def _get_toplevel_authors(self):
        text = self._authors_entry.get_text().strip()
        if not text:
            return []
        return [a.strip() for a in text.split(",") if a.strip()]

    def _on_scan(self, *args):
        self._status_label.set_text("Scanning...")
        self._scan_button.set_sensitive(False)
        self._result = None
        self.workspace = os.path.expanduser(
            self._folder_entry.get_text().strip())
        if not self.workspace:
            self.workspace = None

        if not self.workspace or not os.path.isdir(self.workspace):
            self._scan_button.set_sensitive(True)
            self._status_label.set_text("Folder not found.")
            return

        authors = self._get_toplevel_authors()
        plus_batch = self._author_plus_batch.get_active()
        if not authors:
            plus_batch = True
        group_fw = self._group_frameworks.get_active()
        game_dir = self._game_dir_entry.get_text().strip()
        try:
            settings = storage.load_settings(self.workspace)
            settings["toplevel_authors"] = authors
            settings["author_plus_batch"] = plus_batch
            settings["group_frameworks"] = group_fw
            settings["game_dir"] = game_dir
            storage.save_settings(self.workspace, settings)
        except Exception:
            pass

        def worker():
            try:
                result = scan_workspace(
                    self.workspace, toplevel_authors=authors,
                    author_plus_batch=plus_batch, group_frameworks=group_fw,
                    game_dir=game_dir)
                GLib.idle_add(self._on_scan_done, result)
            except Exception as e:
                GLib.idle_add(self._on_scan_error, e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _row(self, fn, size):
        return Adw.ActionRow(title=esc(fn), subtitle=human_size(size))

    def _populate(self, result):
        self._populate_hold(result.hold_conflicts)

        self._clear_list(self._rejects_list)
        if result.rejects:
            for fn, size in result.rejects:
                self._rejects_list.append(self._row(fn, size))
        else:
            self._rejects_list.append(
                Adw.ActionRow(title="No rejects - every file categorized"))

        self._clear_list(self._dupes_list)
        if result.duplicates:
            for fn, size in result.duplicates:
                self._dupes_list.append(self._row(fn, size))
        else:
            self._dupes_list.append(
                Adw.ActionRow(title="No duplicates"))

        self._clear_list(self._relocate_list)
        if result.relocate:
            for fn, src, dst, size in result.relocate:
                src_show = esc(os.path.relpath(src, result.folder))
                dst_show = esc(os.path.relpath(dst, result.folder))
                row = Adw.ActionRow(title=esc(fn), subtitle=human_size(size))
                row.add_suffix(Gtk.Label(
                    label="%s  ->  %s" % (src_show, dst_show),
                    css_classes=["dim-label"]))
                self._relocate_list.append(row)
        else:
            self._relocate_list.append(
                Adw.ActionRow(
                    title="No mis-placed already-organized mods found"))

        self._clear_list(self._plan_box)
        if result.plan_groups:
            if not result.author_plus_batch:
                self._plan_box.append(Adw.ActionRow(
                    title="Author-only mode: only the listed author(s) "
                          "are sorted; everything else stays in place"))
            for cat in sorted(result.plan_groups):
                files = result.plan_groups[cat]
                grp = Adw.PreferencesGroup(
                    title="%s  (%d)" % (esc(cat), len(files)))
                for fn, size in files:
                    row = self._row(fn, size)
                    author = extract_mod_author(fn)
                    if author and any(
                            author.lower() == a.strip().lower()
                            for a in result.toplevel_authors):
                        row.set_subtitle("%s  ->  %s/" % (
                            human_size(size), author))
                    elif fn in result.framework_of:
                        arrow = "%s  ->  %s/" % (
                            human_size(size), result.framework_of[fn])
                        if author:
                            arrow += "%s/" % author
                        row.set_subtitle(arrow)
                    grp.add(row)
                self._plan_box.append(grp)
        else:
            self._plan_box.append(
                Adw.ActionRow(title="Nothing to move"))

    def _on_scan_done(self, result):
        self._result = result
        self._scan_button.set_sensitive(True)

        totals = (
            "kept %d  |  duplicates %d  |  rejects %d  |  holds %d  |  "
            "relocations %d  |  %s"
            % (len(result.kept), len(result.duplicates), len(result.rejects),
               len(result.hold_conflicts), len(result.relocate),
               human_size(result.total_bytes))
        )
        self._status_label.set_text(totals)
        self._populate(result)

        def worker():
            try:
                statuses, structs = verify.verification_statuses(
                    result.folder, [f for f, _ in result.kept])
                verify.fetch_dependencies(result.folder, result.kept)
                issues = []
                try:
                    from gigasort.core.superseded import check_placement
                    issues = check_placement(result.folder)
                except Exception:
                    pass
                GLib.idle_add(self._populate_struct, structs)
                GLib.idle_add(self._populate_placement, issues)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

        self._apply_button.set_visible(
            bool(result.plan or result.rejects or result.duplicates
                 or result.relocate or result.hold_conflicts))

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
                result = execute_sort(self._result, input_fn=lambda *a: "s")
                GLib.idle_add(self._on_apply_done, result)
            except Exception as e:
                GLib.idle_add(self._on_apply_error, e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_apply_done(self, result):
        self._apply_button.set_sensitive(True)
        self._apply_button.set_visible(False)
        moved = result.get("moved", 0)
        pruned = result.get("pruned", [])
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
        if pruned:
            self._status_label.set_text(
                "%s %d empty folder(s) removed." % (
                    self._status_label.get_text(), len(pruned)))
        if self.status_callback:
            self.status_callback()

    def _on_apply_error(self, error):
        self._apply_button.set_sensitive(True)
        self._status_label.set_text(
            "Apply failed - see the error dialog for details.")
        show_error(self, "Apply failed", error)