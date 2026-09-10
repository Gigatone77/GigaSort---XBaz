"""Rejects & Overrides page — improve the sorter's recognition.

This tab (attached in the main window like the companion modules, but fully
in-app) lets you act on files GigaSort could not categorize or verify:

  - lists the current `_REJECTS` bin plus unrecognized root archives;
  - "Look up offline" consults the offline info archive + ID cache and shows
    the confirmed identity (verified title, category folder) if a record
    exists;
  - a category dropdown + Apply persists a manual override AND records the
    discovered identity (verified cache + mod-ID reference cache + web
    override), so the NEXT sort recognizes and routes the file itself.

Nothing is deleted here: applying an override MOVES the archive from its
reject/root location into the chosen category folder via the collision-safe
move (duplicate -> _DUPLICATES, never overwritten).
"""

import os
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from gigasort.constants import KNOWN_FOLDERS, REJECT_BIN
from gigasort.core import sort, storage
from gigasort.core.categorize import categorize, extract_mod_id
from gigasort.utils.format import human_size
from gigasort.gui.util import esc

ARCHIVE_EXT = (".zip", ".rar", ".7z", ".7zip")


def _is_archive(name):
    return name.lower().endswith(ARCHIVE_EXT)


class _OverrideRow(Adw.ActionRow):
    """One archive: filename, current status, search button, category
    dropdown and an Apply button that persists recognition + moves the file."""

    def __init__(self, page, fn, src, size, status, found=None):
        super().__init__()
        self.page = page
        self.fn = fn
        self.src = src
        self.size = size
        self.status = status
        self.found = found or {}
        self.set_title(esc(fn))
        self.set_subtitle(esc("%s  |  %s" % (human_size(size), status)))
        self.set_activatable(False)

        options = sorted(KNOWN_FOLDERS)
        self._combo = Gtk.DropDown.new_from_strings(options)
        cur = categorize(fn)
        if cur in options:
            self._combo.set_selected(options.index(cur))
        elif self.found.get("folder") in options:
            self._combo.set_selected(options.index(self.found["folder"]))
        self._combo.set_tooltip_text(
            "Category folder the file should be sorted into")

        self._search_btn = Gtk.Button(label="Search")
        self._search_btn.connect("clicked", self._on_search)
        self.add_suffix(self._search_btn)

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_apply)
        self.add_suffix(apply_btn)

        self.add_suffix(self._combo)

        self._info = Gtk.Label(label="", css_classes=["dim-label"])
        self._info.set_wrap(True)
        self._info.set_xalign(0)
        self.add_suffix(self._info)

    # --- actions -----------------------------------------------------------
    def _on_search(self, *args):
        mod_id = extract_mod_id(self.fn)
        if not mod_id:
            self._set_info("No Nexus id in filename - manual override only.")
            return
        self._set_info("Looking up offline…")
        self._search_btn.set_sensitive(False)

        def worker():
            res = self.page.offline_lookup(mod_id)
            GLib.idle_add(self._on_search_done, mod_id, res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_done(self, mod_id, res):
        self._search_btn.set_sensitive(True)
        if not res or not res.get("verified"):
            self.found = {}
            self._set_info("No offline record proves id %s (leave in "
                           "_REJECTS or apply a manual override)." % mod_id)
            return
        self.found = {
            "verified": True,
            "mod_id": mod_id,
            "title": res.get("title"),
            "folder": res.get("category"),
            "source": res.get("sources", ["offline-archive"])[0],
        }
        folder = res.get("category")
        title = res.get("title") or "Cyberpunk 2077 mod %s" % mod_id
        bits = ["verified: %s" % title]
        if folder:
            bits.append("category: %s" % folder)
            options = _combo_strings(self)
            if folder in options:
                self._combo.set_selected(options.index(folder))
        else:
            bits.append("no category detected - pick one below")
        self._set_info(" | ".join(bits))

    def _on_apply(self, *args):
        options = _combo_strings(self)
        folder = options[self._combo.get_selected()] \
            if self._combo.get_selected() >= 0 else None
        reason = self.page.apply_override(self.fn, self.src, folder,
                                          self.found)
        if reason:
            self._set_info(reason)
        else:
            self.set_sensitive(False)
            self._set_info("Applied - sorted into '%s'. Re-scan to refresh."
                           % folder)

    def _set_info(self, text):
        self._info.set_text(text)
        return False


def _combo_strings(combo_row):
    model = combo_row._combo.get_model()
    return [model.get_string(i) for i in range(model.get_n_items())]


class RejectsPage(Adw.NavigationPage):
    """Rejects & Overrides tab — run the search protocol and persist
    category overrides so GigaSort itself learns correct routing."""

    __gtype_name__ = "GigaSortRejectsPage"

    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Rejects & Overrides")
        self.workspace = workspace

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Rejects & Overrides", css_classes=["title-2"])
        title.set_xalign(0)
        header.append(title)
        header.append(Gtk.Label(hexpand=True))

        self._conn_label = Gtk.Label(
            label="Offline", css_classes=["giga-veri-chip", "error"])
        self._conn_label.set_ellipsize(3)
        header.append(self._conn_label)

        self._refresh_btn = Gtk.Button(label="Refresh")
        self._refresh_btn.connect("clicked", self._on_refresh)
        header.append(self._refresh_btn)

        self._search_all_btn = Gtk.Button(label="Look up all offline")
        self._search_all_btn.add_css_class("suggested-action")
        self._search_all_btn.set_tooltip_text(
            "Look up every listed file in the offline info archive / ID "
            "cache (verified title / category). Results stay visible in each "
            "row; Apply persists them.")
        self._search_all_btn.connect("clicked", self._on_search_all)
        header.append(self._search_all_btn)
        outer.append(header)

        hint = Gtk.Label(
            label="Files GigaSort could not route. 'Search' consults the "
                  "bundled offline archive for the mod's identity. 'Apply' "
                  "records the chosen category so the NEXT sort recognizes "
                  "it, and moves the archive there (duplicates go to "
                  "_DUPLICATES, never deleted).",
            css_classes=["dim-label"], wrap=True)
        hint.set_xalign(0)
        outer.append(hint)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        sc = Gtk.ScrolledWindow()
        sc.set_child(self._list)
        sc.set_vexpand(True)
        outer.append(sc)

        self._status_label = Gtk.Label(label="", css_classes=["dim-label"])
        self._status_label.set_xalign(0)
        outer.append(self._status_label)

        self._on_refresh()

    def offline_lookup(self, mod_id):
        """Single confirmed offline record for a mod id (None if unknown)."""
        try:
            from gigasort.core import signature
            return signature.offline_lookup(self.workspace, mod_id)
        except Exception:
            return None

    # -- listing -------------------------------------------------------------
    def _collect(self):
        """Return [(_OverrideRow payload)] of listed candidates."""
        candidates = []
        if self.workspace and os.path.isdir(self.workspace):
            cache = storage.load_cache(self.workspace)
            rejects_dir = os.path.join(self.workspace, REJECT_BIN)
            if os.path.isdir(rejects_dir):
                for fn in sorted(os.listdir(rejects_dir)):
                    path = os.path.join(rejects_dir, fn)
                    if not os.path.isfile(path) or not _is_archive(fn):
                        continue
                    size = os.path.getsize(path)
                    status = "in %s" % REJECT_BIN
                    candidates.append((fn, path, size, status))
            # Unrecognized archives still loose at the workspace root.
            for fn in sorted(os.listdir(self.workspace)):
                if fn.startswith("_GigaSort") or fn in (REJECT_BIN,):
                    continue
                path = os.path.join(self.workspace, fn)
                if not os.path.isfile(path) or not _is_archive(fn):
                    continue
                cache_entry = cache.get(fn) or {}
                if cache_entry.get("status") == "approved":
                    continue
                size = os.path.getsize(path)
                status = "unrecognized at root"
                candidates.append((fn, path, size, status))
        return candidates

    def _on_refresh(self, *args):
        self._clear()
        if not self.workspace or not os.path.isdir(self.workspace):
            self._status_label.set_text("Workspace not set/found.")
            return
        items = self._collect()
        if not items:
            self._list.append(Adw.ActionRow(
                title="No rejects or unrecognized archives.",
                subtitle="Run a Scan first if the workspace changed."))
            self._status_label.set_text("0 files need attention.")
            return
        for fn, src, size, status in items:
            self._list.append(_OverrideRow(self, fn, src, size, status))
        self._status_label.set_text("%d file(s) need attention." % len(items))

    def refresh(self):
        self._on_refresh()

    def _clear(self):
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt

    # -- search-all ----------------------------------------------------------
    def _on_search_all(self, *args):
        rows = _rows(self._list)
        if not rows:
            return
        self._search_all_btn.set_sensitive(False)
        self._status_label.set_text("Running search protocol…")

        def worker():
            for r in rows:
                r._on_search()
                # give the per-row worker a moment to fire its request
                time.sleep(0.3)
            GLib.idle_add(self._search_all_done)

        threading.Thread(target=worker, daemon=True).start()

    def _search_all_done(self):
        self._search_all_btn.set_sensitive(True)
        self._status_label.set_text(
            "Search protocol finished per file - Apply a category to persist.")
        return False

    # -- recognition persistence --------------------------------------------
    def apply_override(self, fn, src, folder, found=None):
        """Persist recognition for `fn` and move it into `folder`.

        Returns an error string on failure, or None on success. This is what
        teaches GigaSort to route the file in the future: the web-category
        override (exact-name win above every keyword), the mod-ID reference
        cache (verified page), and the verified cache entry are all written;
        then the archive is moved collision-safe into its category folder.
        """
        if not folder or folder == "":
            return "Choose a category folder first."
        cache = storage.load_cache(self.workspace)
        refs = storage.load_references(self.workspace)
        overrides = storage.load_web_overrides(self.workspace)

        overrides[fn] = folder
        mod_id = extract_mod_id(fn)
        found = found or {}
        title = found.get("title")
        if mod_id:
            refs[mod_id] = {"verified": True,
                            "title": title or refs.get(mod_id, {}).get("title"),
                            "category": folder}
        cache[fn] = {"status": "approved", "category": folder,
                     "nexus_title": title, "nexus_cat": folder,
                     "overridden": True}
        try:
            storage.save_web_overrides(self.workspace, overrides)
            storage.save_references(self.workspace, refs)
            storage.save_cache(self.workspace, cache)
        except OSError as e:
            return "Could not persist override: %s" % e

        # Move the archive into its category folder (collision-safe).
        dst = os.path.join(self.workspace, folder, fn)
        try:
            sort._move_skip_collision(self.workspace, src, dst)
        except Exception as e:
            return "Recognition saved, but move failed: %s" % e
        return None


def _rows(listbox):
    out = []
    child = listbox.get_first_child()
    while child is not None:
        if isinstance(child, _OverrideRow):
            out.append(child)
        child = child.get_next_sibling()
    return out