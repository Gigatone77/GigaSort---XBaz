"""WTNC Collection page - Welcome to Night City (z9er / Cyberpunk THING) sweep.

Reads the bundled WTNC/THING modlist (gigasort/data/wtnc_modlist.md, shipped
with the tool - fully offline), scans the whole mod library, and shows which
archives are part of the curated list vs NOT compatible with WTNC (mods with
a Nexus id absent from the manifest). The move button pushes the non-compatible
mods into the _NOT_WTNC bin - collision-safe, never deletes.

Defaults to preview (dry-run): nothing moves unless the button is pressed.
"""

import os
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from gigasort.constants import NOT_WTNC_BIN
from gigasort.core import wtnc

_VERDICT_LABEL = {
    "not-in-wtnc": "NOT compatible with WTNC",
    "skip-candidate": "id uncertain - left in place",
    "no-id": "no Nexus id - left in place",
    "in-wtnc": "on the WTNC list",
}


class WtncPage(Adw.NavigationPage):
    """WTNC Collection tab - manifest status, sweep preview, safe move."""

    __gtype_name__ = "GigaSortWtncPage"

    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("WTNC Collection")
        self.workspace = workspace
        self._busy = False

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Welcome to Night City (z9er)",
                          css_classes=["title-2"])
        title.set_xalign(0)
        header.append(title)
        header.append(Gtk.Label(hexpand=True))

        self._manifest_chip = Gtk.Label(
            label="no manifest", css_classes=["giga-veri-chip", "dim-label"])
        self._manifest_chip.set_ellipsize(3)
        header.append(self._manifest_chip)

        self._fetch_btn = Gtk.Button(label="Reload bundled")
        self._fetch_btn.connect("clicked", self._on_fetch)
        header.append(self._fetch_btn)
        outer.append(header)

        hint = Gtk.Label(
            label="Every mod on z9er's curated WTNC / Cyberpunk THING modlist "
                  "is 'compatible'. Archives with a Nexus id that are NOT on "
                  "the list are pushed to the '%s' section - never deleted, "
                  "collision-safe. Files without an id, or a bare non-approved "
                  "candidate id, stay put." % NOT_WTNC_BIN,
            css_classes=["dim-label"], wrap=True)
        hint.set_xalign(0)
        outer.append(hint)

        self._summary = Gtk.Label(label="", css_classes=["dim-label"],
                                  wrap=True)
        self._summary.set_xalign(0)
        outer.append(self._summary)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        sc = Gtk.ScrolledWindow()
        sc.set_child(self._list)
        sc.set_vexpand(True)
        outer.append(sc)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._status = Gtk.Label(label="", css_classes=["dim-label"])
        self._status.set_xalign(0)
        self._status.set_hexpand(True)
        bottom.append(self._status)

        self._preview_btn = Gtk.Button(label="Run sweep (preview)")
        self._preview_btn.connect("clicked", self._on_refresh)
        bottom.append(self._preview_btn)

        self._move_btn = Gtk.Button(label="Move incompatible to _NOT_WTNC")
        self._move_btn.add_css_class("suggested-action")
        self._move_btn.connect("clicked", self._on_move)
        bottom.append(self._move_btn)
        outer.append(bottom)

        self._on_refresh()

    # -- helpers ------------------------------------------------------------
    def _set_busy(self, busy):
        self._busy = busy
        for btn in (self._fetch_btn, self._preview_btn, self._move_btn):
            btn.set_sensitive(not busy)

    def _worker(self, fn, done):
        def run():
            try:
                result = fn()
            except Exception as e:
                result = {"error": str(e)}
            GLib.idle_add(done, result)
        threading.Thread(target=run, daemon=True).start()

    # -- actions ------------------------------------------------------------
    def _on_refresh(self, *args):
        if not self.workspace:
            self._status.set_text("Workspace not set.")
            return
        self._set_busy(True)
        self._status.set_text("Sweeping library…")
        self._worker(lambda: wtnc.run_wtnc_sweep(self.workspace, dry_run=True),
                     self._render)

    def _on_fetch(self, *args):
        if not self.workspace:
            return
        self._set_busy(True)
        self._status.set_text("Reloading the bundled WTNC modlist…")

        def run():
            try:
                wtnc.fetch_manifest(self.workspace, force=True)
            except Exception as e:
                return {"error": str(e)}
            return wtnc.run_wtnc_sweep(self.workspace, dry_run=True)

        self._worker(run, self._render)

    def _on_move(self, *args):
        if not self.workspace:
            return
        self._set_busy(True)
        self._status.set_text("Sweeping (preview)…")
        self._worker(
            lambda: wtnc.run_wtnc_sweep(self.workspace, dry_run=True),
            self._confirm_move)

    def _confirm_move(self, summary):
        self._set_busy(False)
        self._render(summary)
        n = summary.get("counts", {}).get("not-in-wtnc", 0)
        if not n:
            return
        dlg = Adw.AlertDialog.new(
            "Move %d archive(s)?" % n,
            "These %d mod(s) are not on the WTNC curated list and will be "
            "pushed into '%s'. Collision-safe, never deleted, easily reversed "
            "by dragging them back." % (n, NOT_WTNC_BIN))
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("move", "Move")
        dlg.set_default_response("move")
        dlg.connect("response", self._on_move_confirmed, summary)
        dlg.present(self)

    def _on_move_confirmed(self, dlg, response, summary):
        if response != "move":
            self._status.set_text("Move cancelled - nothing changed.")
            return
        n = summary.get("counts", {}).get("not-in-wtnc", 0)
        self._set_busy(True)
        self._status.set_text("Moving %d incompatible archive(s)…" % n)
        self._worker(
            lambda: wtnc.run_wtnc_sweep(self.workspace, dry_run=False,
                                        confirm=False),
            self._render)

    # -- rendering ----------------------------------------------------------
    def _render(self, summary):
        self._set_busy(False)
        if not isinstance(summary, dict) or summary.get("error"):
            err = summary.get("error") if isinstance(summary, dict) else summary
            self._manifest_chip.set_text("unreachable")
            self._manifest_chip.set_css_classes(
                ["giga-veri-chip", "error"])
            self._summary.set_text(
                "Bundled Modlist.md missing: %s" % err)
            self._status.set_text("Reinstall the package - this is a fully "
                                  "offline build, there is no network fetch.")
            return

        self._manifest_chip.set_text(
            "modlist: %d mods%s" % (summary.get("manifest_mod_count", 0),
                                    " (bundled)"))
        self._manifest_chip.set_css_classes(
            ["giga-veri-chip", "success" if summary.get("bundled") else "dim-label"])

        c = summary.get("counts", {})
        extra = summary.get("extra_compat_ids") or []
        extra_txt = ("   |   extra-compat ids: %s" % ", ".join(extra)
                     if extra else "")
        self._summary.set_text(
            "in WTNC list: %d   |   NOT compatible: %d   |   left in place "
            "(uncertain/no id): %d%s"
            % (c.get("in-wtnc", 0), c.get("not-in-wtnc", 0),
               c.get("skip-candidate", 0) + c.get("no-id", 0), extra_txt))

        self._clear()
        shown = 0
        for rel, rec in sorted(summary.get("records", {}).items(),
                               key=lambda kv: kv[0].lower()):
            if rec.get("verdict") == "in-wtnc":
                continue
            label = _VERDICT_LABEL.get(rec.get("verdict"), rec.get("verdict"))
            row = Adw.ActionRow(
                title=rec.get("filename", os.path.basename(rel)),
                subtitle="%s  |  %s  |  %s"
                         % (rec.get("mod_id") or "-", label, rel))
            self._list.append(row)
            shown += 1
        if shown == 0:
            self._list.append(Adw.ActionRow(
                title="Every identified mod is on the WTNC list.",
                subtitle="Nothing to move. Fetch/run again after adding mods."))

        moved = summary.get("moved")
        if moved is not None:
            self._status.set_text(
                "Moved %d incompatible archive(s) to %s." % (moved, NOT_WTNC_BIN))
        else:
            self._status.set_text(
                "Preview - use 'Move incompatible' to push them to %s." % NOT_WTNC_BIN)

    def _clear(self):
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt

    def refresh(self):
        self._on_refresh()