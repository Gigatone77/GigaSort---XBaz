"""Conflict detection.

Module responsibilities:
- find_conflicts: game-dir archive collision (same file overwrites live game)
- find_semantic_conflicts: tag-based semantic coexistence check
  (two installed mods that fight for the same in-game resource even though
   they never share a file, detected by archive-filename → tag mapping)

The tag database schema is user-authored; the bundled copy ships as a
blank template (users supply their own data).  Tag grouping is a general
architectural pattern (commonsense) — no third-party code or curated data
is redistributed.
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from gigasort.core.compat import list_entries
from gigasort.core import storage

CONFLICT_TAGS_FILENAME = "conflict_tags.json"

# Nexus mod-id regex (strips leading #### hash tokens common in archive names)
_ID_RE = re.compile(r"(\d{3,6})")

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

# ─────────────────────────────────────────────────────────────────────
# Legacy: game-dir archive collision detector
# ─────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────
# Semantic tag conflict detector (pattern: tag→conflict-group)
# ─────────────────────────────────────────────────────────────────────


def _load_tag_db(workspace=None):
    """Locate and parse the user's conflict_tags.json.

    Resolution order:
      1. <workspace>/conflict_tags.json  (user-authored override)
      2. gigasort/data/conflict_tags.json (bundled blank template)
    Returns a dict or None if no usable file is found."""
    data_dir = Path(__file__).resolve().parents[2] / "data"
    candidates = []
    if workspace:
        candidates.append(Path(workspace) / CONFLICT_TAGS_FILENAME)
    candidates.append(data_dir / CONFLICT_TAGS_FILENAME)
    for p in candidates:
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, dict) and "mods" in d and d["mods"]:
                    return d
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _build_tag_index(db):
    """Pre-compute lookup tables from the raw DB.

    Returns (archive_map, tag_groups, explicit_conflicts, exceptions).

    archive_map:  {norm_archive_name: (display_name, [tag])}
    tag_groups:   {tag: set of display_names}
    explicit_conflicts: [[name, name], ...]  (already-resolved pairs)
    exceptions:   [[name, name], ...]  (pairs explicitly allowed to coexist)
    """
    archive_map = {}
    tag_groups = defaultdict(set)

    for display_name, entry in db["mods"].items():
        archives = entry.get("archives") or []
        tags = entry.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        for ar in archives:
            archive_map[ar.lower()] = (display_name, tags)
        for t in tags:
            tag_groups[t].add(display_name)

    explicit_conflicts = [pair for pair in (db.get("conflicts") or [])
                          if isinstance(pair, (list, tuple)) and len(pair) >= 2]
    exceptions = [pair for pair in (db.get("exceptions") or [])
                  if isinstance(pair, (list, tuple)) and len(pair) >= 2]
    return archive_map, dict(tag_groups), explicit_conflicts, exceptions


def _find_archive_stems(path):
    """Yield the lowercase basename (without extension) of every .archive
    found directly under a game-dir mod path (e.g. archive/pc/mod/)."""
    if not path or not os.path.isdir(path):
        return
    for entry in os.scandir(path):
        if entry.is_file() and entry.name.lower().endswith(".archive"):
            yield entry.name.lower()


def _find_workspace_archive_stems(folder):
    """Yield the lowercase basenames (without extension) of workspace archives
    (.zip, .rar, .7z).  These are NOT .archive files; they are mod
    distribution containers.  For tag matching we try to extract a Nexus
    mod-id from the basename and fall back to a loose keyword check."""
    if not folder or not os.path.isdir(folder):
        return
    for entry in os.scandir(folder):
        if entry.is_file() and entry.name.lower().endswith((".zip", ".rar",
                                                              ".7z")):
            stem = Path(entry.name).stem.lower()
            # strip leading "####-" style load-order prefix common in
            # published archives (e.g. "###-MyMod.archive" inside a zip)
            cleaned = re.sub(r"^[!#]{1,6}-?", "", stem)
            yield stem, cleaned


def _tag_for_stem(stem, archive_map):
    """Return (display_name, tags) if stem matches an archived mod."""
    # try exact match first, then stripped prefix form
    if stem in archive_map:
        return archive_map[stem]
    # strip a leading "ModId-" token to expose the actual archive name
    stripped = re.sub(r"^\d{3,6}-", "", stem)
    if stripped in archive_map:
        return archive_map[stripped]
    return None


def _pair_key(a, b):
    """Canonical key for an unordered pair."""
    return (a, b) if a <= b else (b, a)


def find_semantic_conflicts(workspace=None, game_dir=None):
    """Detect tags that appear with two or more installed mods.

    Returns ``{tag: [display_name, ...]}`` for each tag where >=2 distinct
    mods are present.  Explicit-pair conflicts are also reported (tag=None).
    Excepted pairs are silently removed.

    Detection uses:
      1. Installed .archive files under game_dir/archive/pc/mod/
      2. Workspace .zip/.rar/.7z basenames (proxy — not interior-inspected)

    Returns empty dict if no usable DB or no conflicts."""
    db = _load_tag_db(workspace)
    if not db:
        return {}
    archive_map, tag_groups, explicit_conflicts, exceptions = _build_tag_index(
        db)

    # build fast exception set
    excepted = {_pair_key(a, b) for a, b in exceptions}

    # collect present mods
    present = {}  # display_name -> set of tags
    game_dir_mods = os.path.join(game_dir, "archive", "pc", "mod") \
        if game_dir else None

    # 1. installed .archive files
    for stem in _find_archive_stems(game_dir_mods):
        hit = _tag_for_stem(stem, archive_map)
        if hit:
            name, tags = hit
            present.setdefault(name, set()).update(tags)

    # 2. workspace distribution containers (less precise — tags only if
    #    the container basename directly matches an archive_map key)
    for raw_stem, cleaned in _find_workspace_archive_stems(workspace):
        for try_stem in (raw_stem, cleaned):
            hit = _tag_for_stem(try_stem, archive_map)
            if hit:
                name, tags = hit
                present.setdefault(name, set()).update(tags)
                break

    if not present:
        return {}

    # group present mods by tag
    tag_hits = defaultdict(list)
    for name, tags in present.items():
        for t in tags:
            tag_hits[t].append(name)

    # filter: keep tags with >=2 distinct present mods; drop excepted pairs
    conflicts = {}
    for tag, names in tag_hits.items():
        if len(names) < 2:
            continue
        # remove excepted pairs
        active = []
        for n in names:
            conflicts_with_others = False
            for other in names:
                if other != n and _pair_key(n, other) not in excepted:
                    conflicts_with_others = True
                    break
            if conflicts_with_others:
                active.append(n)
        if len(active) >= 2:
            conflicts[tag] = sorted(active)

    # explicit non-tag conflicts
    present_names = set(present)
    for pair in explicit_conflicts:
        a, b = pair[0], pair[1]
        if a in present_names and b in present_names \
                and _pair_key(a, b) not in excepted:
            conflicts.setdefault(None, []).extend([a, b])

    # deduplicate any explicit-pair entries
    if None in conflicts:
        conflicts[None] = sorted(set(conflicts[None]))

    return conflicts


def format_semantic_conflicts(conflicts):
    """Human-readable lines for a tag conflict report."""
    if not conflicts:
        return []
    lines = ["  Semantic conflicts (tag-based):"]
    for tag, names in sorted(conflicts.items(), key=lambda kv: (kv[0] or "")):
        tag_label = tag or "explicit"
        lines.append("    [%s]  %s" % (tag_label, ", ".join(names)))
    return lines