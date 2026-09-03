"""CyberFlashSync companion tab — options sidebar + live output."""

import os

from gigasort.gui.pages.companion import CompanionPage


class CyberFlashSyncPage(CompanionPage):
    __gtype_name__ = "GigaSortCyberFlashSyncPage"

    TOOL_NAME = "CyberFlashSync"
    SCRIPT = "CyberFlashSync.py"
    SCRIPT_CANDIDATES = [
        os.path.expanduser("~/Games/CyberFlashSync.py"),
        "/run/media/Gigatone/ToolBox/ToolBox/Cyberpunk-Tools/GigaSort-core-tools/CyberFlashSync.py",
    ]

    def _build_sidebar(self):
        self._drive = self._add_entry("Flash drive mount", "auto-detect")
        self._only = self._add_entry("Only mapping ids", "all")
        self._with_game = self._add_toggle(
            "Include live game dir", "~90 GB, OFF by default")
        self._dry = self._add_toggle("Dry run", "preview, change nothing")
        self._json = self._add_toggle("JSON summary", "machine-readable")

        self._add_button("Backup", "suggested-action").connect(
            "clicked", lambda *a: self._run_cmd())
        self._add_button("Status").connect(
            "clicked", lambda *a: self._run_cmd("status"))

    def _run_cmd(self, cmd=None):
        argv = []
        if cmd:
            argv.append(cmd)
        drive = self._drive.get_text().strip()
        if drive and drive != "auto-detect":
            argv += ["--drive", drive]
        only = self._only.get_text().strip()
        if only and only != "all":
            argv += ["--only", only]
        if self._with_game.get_active():
            argv.append("--with-game")
        if self._dry.get_active():
            argv.append("--dry-run")
        if self._json.get_active():
            argv.append("--json")
        self.run_subprocess(argv)
