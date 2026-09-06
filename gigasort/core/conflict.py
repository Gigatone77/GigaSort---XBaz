"""Game-directory conflict detection for GigaSort.

Compares what each workspace archive would install into the actual Cyberpunk
2077 game directory against the files that are ALREADY installed there. A mod
that would OVERWRITE an existing installed file is a conflict and is routed to
the _ON_HOLD review bin instead of its normal category folder, so the user can
decide before it is placed.

This check is STRICT by design: it only flags a mod when it literally writes
the SAME named file that already exists in the game dir (e.g. it drops a
`r6/scripts/foo.reds` that is already sitting on disk). Folder-level overlap
or "touches the same mods folder" collisions are deliberately NOT reported, to
keep false positives low.

The check is a no-op whenever no game directory has been configured: if the
user has not pointed GigaSort at a game install, nothing is flagged and the
sort behaves exactly as before.
"""

import os

from gigasort.core import compat

# Paths under the game root that hold user-installed MOD content (as opposed
# to vanilla game files). Only these are scanned for conflicts, so a mod that
# happens to write a 'config' file matching some vanilla game file is not
# falsely held. These are the real locations CP2077 mods install into.
MOD_INSTALL_ROOTS = (
    "archive/pc/mod",        # .archive mod files
    "r6/config",             # XML config overrides
    "r6/scripts",            # redscript files (.reds)
    "r6/cache",              # compiled redscript/mod caches
    "red4ext/plugins",       # RED4ext plugin DLLs + configs
    "red4ext/sdks",          # RED4ext SDK headers
    "engine/config",         # engine tweaks
    "mods",                  # loose mod root
    "bin/x64/plugins/cyber_engine_tweaks",  # CET Lua mods
)


def _norm(rel):
    """Normalize an archive-relative or game-relative path for comparison."""
    rel = rel.replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def _under(root_abs, subdir):
    """If `subdir` (game-relative, e.g. 'archive/pc/mod') exists under the
    game root, return its absolute normalized path prefix; else None."""
    base = os.path.join(root_abs, *subdir.split("/"))
    return _norm(os.path.normpath(base).replace("\\", "/"))


def load_installed_files(game_dir):
    """Walk the game directory and return the set of installed MOD file paths
    (normalized, case-folded) that a downloaded archive could collide with.

    Only files under MOD_INSTALL_ROOTS are collected — vanilla game files are
    not considered, so normal gameplay files never cause a false hold.
    Returns a set of normalized absolute paths (lowercased for comparison).
    Returns an empty set when game_dir is not a valid directory.
    """
    installed = set()
    if not game_dir or not os.path.isdir(game_dir):
        return installed
    game_norm = _norm(os.path.normpath(game_dir).replace("\\", "/"))
    for sub in MOD_INSTALL_ROOTS:
        root_abs = os.path.join(game_dir, *sub.split("/"))
        if not os.path.isdir(root_abs):
            continue
        for dirpath, _dirs, files in os.walk(root_abs):
            for f in files:
                full = os.path.normpath(os.path.join(dirpath, f)).replace("\\", "/")
                rel = os.path.relpath(full, game_dir).replace("\\", "/")
                if rel.startswith(".."):
                    continue
                installed.add(os.path.join(game_norm, rel).lower())
    return installed


def archive_install_paths(archive_path, game_dir):
    """Resolve the game-absolute paths one archive would write, by mapping its
    entries under the game root (like --gamestructure does).

    Returns a set of normalized lowercase absolute paths the archive WOULD
    install under `game_dir`. Handles both game-shaped (archive/pc/mod/...)
    and single-wrapper (Cyberpunk 2077/archive/pc/mod/...) layouts, plus loose
    CET plugin roots. Never extracts — reads only the archive index.
    """
    if not game_dir or not os.path.isdir(game_dir):
        return set()
    game_norm = _norm(os.path.normpath(game_dir).replace("\\", "/"))
    paths = set()
    try:
        entries = compat.list_entries(archive_path)
    except Exception:
        return paths

    _WRAP = ("cyberpunk 2077", "cyberpunk2077", "cp2077")
    for e in entries:
        norm = _norm(e)
        if not norm or norm.endswith("/"):
            continue
        parts = norm.split("/")
        first = parts[0].lower()
        if first in _WRAP:
            parts = parts[1:]
            norm = "/".join(parts)
            if not norm:
                continue
            first = parts[0].lower() if parts else ""
        if first not in MOD_INSTALL_ROOTS[0:1] and not any(
                norm.startswith(r) for r in MOD_INSTALL_ROOTS):
            # Join the archive entry under the matching install root if it
            # begins with one of the real game roots (r6, red4ext, engine,
            # archive, mods, bin/.../cyber_engine_tweaks).
            match = None
            for r in MOD_INSTALL_ROOTS:
                if norm == r or norm.startswith(r + "/"):
                    match = r
                    break
            if not match:
                continue
        paths.add(os.path.join(game_norm, norm).lower())
    return paths


def find_conflicts(folder, fns, game_dir):
    """Return {filename: [list of conflicting installed absolute paths]}.

    A conflict is recorded ONLY when the archive would write exactly the same
    named file that is already present in the game directory (exact
    overwrite). The value lists every such installed file path (human-readable)
    so the caller can explain to the user WHY each mod was held.

    Returns {} when game_dir is unset/invalid (check disabled).
    """
    if not game_dir or not os.path.isdir(game_dir):
        return {}
    installed = load_installed_files(game_dir)
    if not installed:
        return {}
    conflicts = {}
    for fn in fns:
        path = os.path.join(folder, fn)
        if not os.path.isfile(path):
            continue
        would = archive_install_paths(path, game_dir)
        hits = sorted(would & installed)
        if hits:
            conflicts[fn] = hits
    return conflicts
