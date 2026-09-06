"""Processed-mods tags (machine-readable handle for the paired agent)."""

import os

from gigasort.core import storage
from gigasort.core.categorize import extract_mod_id, extract_mod_author
from gigasort.utils.io import json_load as _json_load


def _collect_processed(folder):
    """Collect only mods GigaSort has actually processed (never raw archives).
    Sources: verified cache (verified), move manifest (moved), _MOD_INFO.json
    (extracted).

    Each record carries the expected verification tags:
      - Verified (always, when processed)
      - Online / Offline (how it was confirmed: live Nexus vs local cache)
      - Missing dependency (keep list needs a dep not present/kept)
      - Unstructured (is a CP2077 mod but its archive is NOT a game-path
        layout -> manual handling / re-download needed)
    """
    tags = []

    cache = storage.load_cache(folder)
    manifest = storage.load_manifest(folder)
    handled = set()

    for fn, entry in (cache or {}).items():
        if entry.get("status") in ("approved", "mismatch"):
            flags = _verification_flags(folder, fn, entry, manifest)
            tags.append({
                "file": fn,
                "mod_id": extract_mod_id(fn),
                "author": extract_mod_author(fn),
                "type": entry.get("category"),
                "verdict": entry.get("status"),
                "handle": "verified",
                **flags,
            })
            handled.add(fn)

    for m in manifest:
        src = m.get("src", "")
        base = os.path.basename(src)
        if base in handled:
            continue
        entry = (cache or {}).get(base) or {}
        flags = _verification_flags(folder, base, entry, manifest)
        tags.append({
            "file": base,
            "mod_id": extract_mod_id(src),
            "author": extract_mod_author(src),
            "handle": "moved",
            **flags,
        })
        handled.add(base)

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


def _verification_flags(folder, fn, entry, manifest):
    """The five requested per-file tags → flat dict (keys only when known)."""
    entry = entry or {}
    flags = {"verified": True}
    if entry.get("source") == "offline-structure":
        flags["offline"] = True
    elif os.path.exists(os.path.join(folder, fn)) or entry.get("struct_ok"):
        flags["offline"] = True
    else:
        flags["online"] = True
    deps = entry.get("deps") or []
    if deps:
        present_ids = set()
        for m in manifest:
            mid = m.get("mod_id")
            if mid:
                present_ids.add(str(mid))
        missing = [d for d in deps if str(d) not in present_ids]
        if missing:
            flags["missing_dependency"] = True
    struct = entry.get("struct_ok")
    if struct is False:
        flags["unstructured"] = True
    return flags


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
