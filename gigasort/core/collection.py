"""Recognized-collection cache.

When the game directory's installed mod archives follow a load-order naming
convention (e.g. 'zw_<order>_<mod_id>_<Name>' - the ordering scheme used by
curated modlists such as CyberVision), GigaSort recognizes that collection
structure and caches it as _GigaSort_collection.json. Later runs can then
compare a freshly downloaded archive against the SAME installed set (mod id
present in the ordered cache = already part of the loadout) without
re-walking the game tree every time.

Recognition is data-driven: it looks for the naming convention and a
matching subset of known collection marker files. It never fabricates a name
when only the convention is present.
"""

import json
import os
import re
from datetime import datetime, timezone

from gigasort.constants import GS_COLLECTION_CACHE

# 'zw_<order>_<mod_id>_<Name>' - the curated-modlist load-order prefix.
ZW_RE = re.compile(r"^zw_(\d+)_(\d+)_(.+)$", re.I)

# Data-driven fingerprint: Nexus mod ids that together mark a curated
# modlist's installed set (taken from this machine's own loadout + the
# modlists' published manifests). At least MIN_MARKER_HITS must be present.
_KNOWN_LISTS = {
    "CyberVision": {
        "23109",  # Blackwall Side Effects
        "29125",  # Combat Evolved
        "25788",  # More Pizza Options
        "9191",   # Rita Romanced
        "22987",  # Killing Moon Life Path Dialog
        "31371",  # Desperate Measures Pacifist Fix
        "31304",  # Air Traffic Dupe Fix
    },
}
MIN_MARKER_HITS = 3


def installed_zw_entries(game_dir):
    """Return sorted [(order, mod_id, name)] from the installed loadout.

    Only <game>/archive/pc/mod/*.archive|*.xl files named zw_<order>_<id>_*
    count; the definitive CP2077 mod-data location.
    """
    root = os.path.join(game_dir, "archive", "pc", "mod")
    if not os.path.isdir(root):
        return []
    entries = []
    for fn in os.listdir(root):
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in (".archive", ".xl"):
            continue
        m = ZW_RE.match(stem)
        if m:
            entries.append((int(m.group(1)), m.group(2), m.group(3)))
    return sorted(entries)


def recognize_collection(game_dir):
    """Return a record describing the recognized collection structure, or
    None when the installed set shows no such convention."""
    entries = installed_zw_entries(game_dir)
    if len(entries) < MIN_MARKER_HITS:
        return None
    ids = {e[1] for e in entries}
    name = None
    for list_name, markers in _KNOWN_LISTS.items():
        if len(ids & markers) >= MIN_MARKER_HITS:
            name = list_name
            break
    return {
        "name": name,
        "convention": "zw_<order>_<mod_id>_<name>",
        "mods": [{"order": o, "mod_id": i, "name": n}
                 for o, i, n in entries],
        "mod_count": len(entries),
    }


def build_collection_cache(folder, game_dir):
    """Recognize the collection in `game_dir` and write the cache file.

    Returns the record (dict) written, or None when no structure is
    recognized. Never raises on bad paths - it is a cache, not a gate.
    """
    try:
        rec = recognize_collection(game_dir)
    except Exception:
        return None
    if not rec:
        return None
    rec["game_dir"] = os.path.normpath(os.path.abspath(game_dir))
    rec["built_at"] = datetime.now(timezone.utc).isoformat()
    try:
        path = os.path.join(folder, GS_COLLECTION_CACHE)
        with open(path, "w") as fh:
            json.dump(rec, fh, indent=2)
    except Exception:
        return rec
    return rec