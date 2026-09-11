"""Collection-aware caching: recognize zw_<order>_<mod_id>_<name> downloads
(CyberVision-style ordered collections) and cache their source mod page."""

import os
import re

from gigasort.core import storage

ZW_RE = re.compile(r"^zw_(\d+)_(\d+)_(.+)$", re.IGNORECASE)

# Known ordered mod lists (collection id -> list of mod ids in order).
_KNOWN_LISTS = {
    "cybervision": [
        "23109", "29125", "25788", "9191", "22987", "31371", "31304",
    ],
}
_MIN_MARKER_HITS = 3


def _marker_meta(name):
    """Return (collection_label, order, mod_id, clean_name) or None."""
    m = ZW_RE.match(os.path.basename(name))
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3), m.group(1)


def recognize_zw(name):
    """Recognize a CyberVision-ordered filename. Returns metadata dict."""
    meta = _marker_meta(name)
    if not meta:
        return None
    _, order, mod_id, label = meta
    return {"collection": label, "order": order, "mod_id": mod_id,
            "name": name}


def cache_collection_state(workspace):
    """Scan for zw_-prefixed archives and write _GigaSort_collection.json.

    Only recognizes a marker when >=3 distinctive zw_<order>_<id> files of
    the same collection are present (avoid accidental single-mark hits)."""
    state = {"collections": {}, "files": {}}
    counters = {}
    for n in os.listdir(workspace):
        rec = recognize_zw(n)
        if not rec:
            continue
        label = rec["collection"]
        counters[label] = counters.get(label, 0) + 1
        state["files"][n] = rec
    for label, count in counters.items():
        if count < _MIN_MARKER_HITS:
            state["files"] = {k: v for k, v in state["files"].items()
                              if v["collection"] != label}
            continue
        state["collections"][label] = {
            "file_count": count,
            "ordered": bool(count == len(_KNOWN_LISTS.get(label, []))),
        }
    storage.save_collection_cache(workspace, state)
    return state