"""Game-structure sort — reorganize extracted/loose files into a CP2077
game-shaped tree (GAMESTRUCTURE) so they can be dropped on the game root.

Uses a verified reference structure (~/Games/Custom Mod Additions Archive -
GAME STRUCTURE) to map every loose file to its game subdirectory, falling
back to the offline category keyword resolution. Always read/stage only —
never writes into the real game install."""

import os
import shutil

from gigasort.constants import (
    GS_STRUCTURE_DIR, DEFAULT_REFERENCE_STRUCTURE,
)
from gigasort.core.storage import scratch_dir

# rel game-dir -> (accept stripped wrapper, sub-sort key)
_SORT_FN = {
    "r6/scripts": (True, "scripts"),
    "r6/tweaks": (True, "tweaks"),
    "r6/input": (True, "input"),
    "r6/audioware": (True, "audio"),
    "archive/pc/mod": (True, "archive"),
    "red4ext/plugins": (True, "red4ext"),
    "engine/config": (True, "engine"),
    "bin/x64/plugins/cyber_engine_tweaks": (True, "cet"),
    "mods": (True, "mods"),
}


def _ref_index(reference):
    """Precompute {game-subdir: set(file-exts)} from the reference tree."""
    if not reference:
        return {}
    idx = {}
    for root, _dirs, files in os.walk(reference):
        rel = os.path.relpath(root, reference)
        for name in files:
            ext = os.path.splitext(name)[1].lower() or "*"
            idx.setdefault(rel, set()).add(ext)
    return idx


class StructureError(Exception):
    pass


def stage_entries(workspace, only=None, dry_run=False, reference=None):
    """Build the GAMESTRUCTURE tree for every staged archive.

    reference: override path to the reference game structure. When unset and
    the default reference folder exists, it is used to map loose files.
    Returns (tree_root, staging_outcomes)."""
    reference = reference or os.environ.get("GS_REFERENCE_GAME_STRUCTURE") \
        or DEFAULT_REFERENCE_STRUCTURE
    reference_exists = reference and os.path.isdir(reference)
    idx = _ref_index(reference) if reference_exists else {}

    stage = scratch_dir(workspace)
    out_root = os.path.join(workspace, GS_STRUCTURE_DIR)
    if not dry_run:
        shutil.rmtree(out_root, ignore_errors=True)
        os.makedirs(out_root, exist_ok=True)

    outcomes = {}
    if not os.path.isdir(stage):
        return out_root, outcomes

    for folder in sorted(os.listdir(stage)):
        if only and folder not in only:
            continue
        src = os.path.join(stage, folder)
        if not os.path.isdir(src):
            continue
        if not dry_run:
            _place_folder(src, out_root, idx, outcomes)
        else:
            outcomes[folder] = "planned"
    return out_root, outcomes


def _place_folder(src, out_root, idx, outcomes):
    """Copy one staged mod folder into the game-shaped tree."""
    placed = files = 0
    for root, _dirs, files_ in os.walk(src):
        for name in files_:
            files += 1
            ext = os.path.splitext(name)[1].lower() or name.lower()
            game_rel = _map_ext_to_game_rel(ext, idx)
            dest_dir = os.path.join(out_root, game_rel)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(os.path.join(root, name), os.path.join(dest_dir, name))
            placed += 1
    outcomes[os.path.basename(src)] = "placed %d/%d" % (placed, files)


def _map_ext_to_game_rel(ext, idx):
    """Match a file ext to a game subdir using the reference index, else a
    default mapping."""
    for game_rel, exts in idx.items():
        if ext in exts or "*" in exts:
            return game_rel
    defaults = {
        ".reds": "r6/scripts",
        ".yaml": "r6/tweaks",
        ".xml": "engine/config/input",
        ".archive": "archive/pc/mod",
        ".xl": "archive/pc/mod",
        ".lua": "bin/x64/plugins/cyber_engine_tweaks",
        ".dll": "red4ext/plugins",
        ".ini": "engine/config",
    }
    return defaults.get(ext, "mods")


def plan_structure(workspace, reference=None):
    """Read-only preview: what _place_folder would do (no writes)."""
    reference = reference or os.environ.get("GS_REFERENCE_GAME_STRUCTURE") \
        or DEFAULT_REFERENCE_STRUCTURE
    idx = _ref_index(reference) if os.path.isdir(reference) else {}
    stage = scratch_dir(workspace)
    plan = []
    if not os.path.isdir(stage):
        return plan
    for folder in sorted(os.listdir(stage)):
        src = os.path.join(stage, folder)
        if not os.path.isdir(src):
            continue
        for root, _dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            for name in files:
                ext = os.path.splitext(name)[1].lower() or name.lower()
                plan.append((folder, rel, name,
                             _map_ext_to_game_rel(ext, idx)))
    return plan