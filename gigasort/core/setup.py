"""Setup — one-time workspace preparation + defaults."""

import os

from gigasort.constants import (
    DEFAULT_WORKSPACE, REJECT_BIN, TRASH_BIN, DUPLICATES_BIN, HOLD_BIN,
)
from gigasort.core import signature, storage
from gigasort.core.signature import seed_id_cache


def ensure_dirs(folder):
    """Create the workspace skeleton (bins + staging) if missing."""
    for name in (REJECT_BIN, TRASH_BIN, DUPLICATES_BIN, HOLD_BIN):
        os.makedirs(os.path.join(folder, name), exist_ok=True)


def setup_workspace(folder=None, game_dir=None, force=False):
    """Init a workspace: dirs, settings file, offline sig archive, seed refs.

    Returns the workspace path used."""
    folder = folder or DEFAULT_WORKSPACE
    folder = os.path.abspath(folder)
    ensure_dirs(folder)

    settings = storage.load_settings(folder)
    if game_dir or force:
        settings["game_dir"] = game_dir or settings.get("game_dir") or ""
        storage.save_settings(folder, settings)

    built = signature.ensure_archive(folder, force=force)
    seeded = 0
    if built:
        seeded = seed_id_cache(folder)
    return folder, built, seeded


def find_game_dir(hint=None):
    """Locate the CP2077 game install (Heroic prefix hints), else None."""
    if hint and os.path.isdir(hint):
        return hint
    candidates = [
        os.path.expanduser("~/Games/Heroic/Prefixes"),
        os.path.expanduser("~/Games/Cyberpunk 2077"),
    ]
    for base in candidates:
        if not os.path.isdir(base):
            continue
        for root, _dirs, _files in os.walk(base):
            if os.path.basename(root) == "Cyberpunk 2077" or \
                    (os.path.isdir(os.path.join(root, "bin"))
                     and os.path.isdir(os.path.join(root, "archive"))):
                return root
    return None