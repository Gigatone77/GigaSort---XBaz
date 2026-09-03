"""GigaSlim companion tab — options sidebar + live output."""

import os

from gigasort.gui.pages.companion import CompanionPage


class GigaSlimPage(CompanionPage):
    __gtype_name__ = "GigaSortGigaSlimPage"

    TOOL_NAME = "GigaSlim"
    SCRIPT = "GigaSlim.py"
    SCRIPT_CANDIDATES = [
        os.path.expanduser("~/Games/GigaSlim.py"),
        "/run/media/Gigatone/ToolBox/ToolBox/Cyberpunk-Tools/GigaSort-core-tools/GigaSlim.py",
    ]

    def _build_sidebar(self):
        self._game = self._add_entry(
            "Game install root",
            os.path.expanduser("~/Games/Cyberpunk 2077"))
        self._keep = self._add_entry("Languages to keep", "en")
        self._backup = self._add_entry("Backup dir", "auto (flash drive)")
        self._videos = self._add_toggle(
            "Include 13 GB cutscene archive", "basegame_5_video.archive (OFF)")
        self._cache = self._add_toggle(
            "Include regenerable r6/cache", "final.redscripts.modded/.ts")
        self._dry = self._add_toggle("Dry run", "preview, don't move")
        self._yes = self._add_toggle("Skip confirmation", "--yes")

        self._add_button("Analyze", "suggested-action").connect(
            "clicked", lambda *a: self._run_cmd("analyze"))
        self._add_button("Apply").connect(
            "clicked", lambda *a: self._run_cmd("apply"))
        self._add_button("Restore").connect(
            "clicked", lambda *a: self._run_cmd("restore"))
        self._add_button("Status").connect(
            "clicked", lambda *a: self._run_cmd("status"))
        self._run_button.set_visible(False)

    def _run_cmd(self, cmd):
        argv = [cmd]
        if self._game.get_text().strip():
            argv += ["--game", self._game.get_text().strip()]
        if self._keep.get_text().strip():
            argv += ["--keep", self._keep.get_text().strip()]
        backup = self._backup.get_text().strip()
        if backup and backup != "auto (flash drive)":
            argv += ["--backup-dir", backup]
        if self._videos.get_active():
            argv.append("--videos")
        if self._cache.get_active():
            argv.append("--cache")
        if self._dry.get_active():
            argv.append("--dry-run")
        if self._yes.get_active():
            argv.append("--yes")
        self.run_subprocess(argv)
