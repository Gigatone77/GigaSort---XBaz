"""Game Structure companion tab — compile archives into a game-ready tree."""

import os
import shlex
import subprocess
import sys

from gi.repository import GLib

from gigasort.gui.pages.companion import CompanionPage


class GameStructurePage(CompanionPage):
    __gtype_name__ = "GigaSortGameStructurePage"

    TOOL_NAME = "Game Structure"

    def _build_sidebar(self):
        self._folder = self._add_entry(
            "Source folder",
            os.path.expanduser("~/Downloads"))
        self._folder.set_text(self.workspace or os.path.expanduser("~/Downloads"))
        self._game_dir = self._add_entry(
            "Target game dir", "optional (default: <folder>/_game-structure)")
        self._dry = self._add_toggle("Dry run", "preview, change nothing")
        self._yes = self._add_toggle("Skip confirmation", "--yes")

        self._add_button("Build structure", "suggested-action").connect(
            "clicked", lambda *a: self._run_cmd())
        self._subtitle.set_text(
            "Resolves each archive's layout (local -> nexus -> manual), "
            "stages and compiles a ready-to-use CP2077 folder tree. Never "
            "deletes or touches unverified files.")

    def _run_cmd(self):
        argv = ["--gamestructure"]
        folder = self._folder.get_text().strip()
        if folder:
            argv += ["--folder", folder]
        game_dir = self._game_dir.get_text().strip()
        if game_dir:
            argv += ["--game-dir", game_dir]
        if self._dry.get_active():
            argv.append("--dry-run")
        if self._yes.get_active():
            argv.append("--yes")
        self.run_subprocess(argv)

    def run_subprocess(self, argv):
        """Run the native gigasort CLI (python -m gigasort) and stream output.

        Game Structure is a core GigaSort mode, not a standalone script, so we
        invoke the installed module rather than a separate .py companion.
        """
        folder = self._folder.get_text().strip() or os.path.expanduser("~/Downloads")
        full = [sys.executable, "-m", "gigasort"] + list(argv)
        self._status_label.set_text("Running...")
        self._run_button.set_sensitive(False)
        self._append("\n$ %s\n" % " ".join(shlex.quote(a) for a in full))

        def worker():
            try:
                proc = subprocess.Popen(
                    full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    cwd=folder if os.path.isdir(folder) else None)
                self._proc = proc
                for line in proc.stdout:
                    GLib.idle_add(self._append, line)
                proc.wait()
                rc = proc.returncode
                GLib.idle_add(self._on_done, rc)
            except Exception as e:
                GLib.idle_add(self._on_error, str(e))

        import threading
        threading.Thread(target=worker, daemon=True).start()
