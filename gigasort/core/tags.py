"""Processed-mods tags (machine-readable handle for the paired agent)."""

import os

from gigasort.core import storage
from gigasort.core.categorize import extract_mod_id, extract_mod_author
from gigasort.utils.io import json_load as _json_load


def _collect_processed(folder):
    """Collect only mods GigaSort has actually processed (never raw archives).
    Sources: verified cache (verified), move manifest (moved), _MOD_INFO.json
    (extracted)."""
    tags = []

    cache = storage.load_cache(folder)
    for fn, entry in (cache or {}).items():
        if entry.get("status") in ("approved", "mismatch"):
            tags.append({
                "file": fn,
                "mod_id": extract_mod_id(fn),
                "author": extract_mod_author(fn),
                "type": entry.get("category"),
                "verdict": entry.get("status"),
                "handle": "verified",
            })

    manifest = storage.load_manifest(folder)
    for m in manifest:
        src = m.get("src", "")
        tags.append({
            "file": os.path.basename(src),
            "mod_id": extract_mod_id(src),
            "author": extract_mod_author(src),
            "handle": "moved",
        })

    mod_index = os.path.join(folder, "_MOD_INFO.json")
    data = _json_load(mod_index, []) or []
    for rec in data or []:
        if isinstance(rec, dict):
            tags.append({
                "file": rec.get("file", rec.get("name", "")),
                "mod_id": rec.get("mod_id"),
                "author": rec.get("author"),
                "type": rec.get("type"),
                "verdict": rec.get("verdict"),
                "handle": "extracted",
            })
    return tags


def write_tags(folder):
    """Write _GigaSort_tags.json listing processed mods; return count."""
    tags = _collect_processed(folder)
    storage.save_tags(folder, {
        "tool": "GigaSort",
        "purpose": "handle of mods GigaSort has processed",
        "count": len(tags),
        "tags": tags,
    })
    return len(tags)
