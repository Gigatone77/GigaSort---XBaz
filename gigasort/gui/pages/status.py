"""Workspace status page — show bins, state files, and a read-only summary."""

import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from gigasort.constants import (
    REJECT_BIN, TRASH_BIN, HOLD_BIN, DUPLICATES_BIN,
    GS_STRUCTURE_DIR, SETTINGS_FILENAME, CACHE_FILENAME,
    MANIFEST_FILENAME, TAGS_FILENAME, LOG_FILENAME, THREAT_FILENAME,
)
from gigasort.gui.util import esc


class StatusPage(Adw.NavigationPage):
    __gtype_name__ = "GigaSortStatusPage"

    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Workspace")
        self.workspace = workspace

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        self._path_label = Adw.ActionRow(title="Workspace",
                                         subtitle=esc(str(workspace)))
        outer.append(self._path_label)

        self._dirs_group = Adw.PreferencesGroup(title="Folders")
        outer.append(self._dirs_group)
        self._dir_rows = []

        self._files_group = Adw.PreferencesGroup(title="State Files")
        outer.append(self._files_group)
        self._file_rows = []

        self.refresh()

    def refresh(self):
        for row in self._dir_rows:
            self._dirs_group.remove(row)
        self._dir_rows = []
        for row in self._file_rows:
            self._files_group.remove(row)
        self._file_rows = []

        dirs = [
            (REJECT_BIN, "review / uncategorized"),
            (TRASH_BIN, "marked for deletion"),
            (HOLD_BIN, "threat-gated, waiting"),
            (DUPLICATES_BIN, "collapsed repeat downloads"),
            (GS_STRUCTURE_DIR, "game-structure staging output"),
        ]

        for name, why in dirs:
            p = os.path.join(self.workspace, name)
            state = "[present]" if os.path.isdir(p) else "[absent]"
            row = Adw.ActionRow(title=esc(name),
                                subtitle="%s  %s" % (esc(why), state))
            self._dirs_group.add(row)
            self._dir_rows.append(row)

        files = [
            (SETTINGS_FILENAME, "settings"),
            (CACHE_FILENAME, "verified cache"),
            (LOG_FILENAME, "verification log"),
            (MANIFEST_FILENAME, "undo manifest"),
            (TAGS_FILENAME, "processed-mods tags"),
            (THREAT_FILENAME, "threat watchlist"),
        ]
        for fname, why in files:
            p = os.path.join(self.workspace, fname)
            state = "[present]" if os.path.isfile(p) else "[absent]"
            row = Adw.ActionRow(title=esc(fname),
                                subtitle="%s  %s" % (esc(why), state))
            self._files_group.add(row)
            self._file_rows.append(row)
