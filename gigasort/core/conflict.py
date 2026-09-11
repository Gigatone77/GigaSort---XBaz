"""Game-dir conflict detection — archives whose interior files would
overwrite already-installed game files."""

import os

from gigasort.core.compat import list_entries
from gigasort.core import storage

MOD_INSTALL_ROOTS = (
    "archive/pc/mod",
    "r6/config",
    "r6/scripts",
    "r6/cache",
    "red4ext/plugins",
    "red4ext/sdks",
    "engine/config",
    "mods",
    "bin/x64/plugins/cyber_engine_tweaks",
)


def find_conflicts(workspace, game_dir=None):
    """Return {archive_basename: [conflicting rel game paths]}.

    Only archives whose contents duplicate an EXISTING installed file are
    flagged (same-name collision = dangerous). game_dir comes from the
    workspace settings when not supplied."""
    settings = storage.load_settings(workspace)
    game_dir = game_dir or settings.get("game_dir") or ""
    if not game_dir or not os.path.isdir(game_dir):
        return {}

    conflicts = {}
    archives = sorted(n for n in os.listdir(workspace)
                      if n.lower().endswith((".zip", ".rar", ".7z")))
    for name in archives:
        path = os.path.join(workspace, name)
        hits = []
        for entry in list_entries(path):
            e = entry.replace("\\", "/").lstrip("./")
            if e.startswith("Cyberpunk 2077/"):
                e = e[len("Cyberpunk 2077/"):]
            if not any(e.startswith(r) for r in MOD_INSTALL_ROOTS):
                continue
            if os.path.exists(os.path.join(game_dir, e)):
                hits.append(e)
        if hits:
            conflicts[name] = hits
    return conflicts