"""Read-only reports: --json machine output, and --locate workspace map."""

import json
import os

from gigasort.constants import (
    GS_STRUCTURE_DIR, GS_STAGE_DIR, GS_BACKUP_DIR, BRIDGE_DIR,
    REJECT_BIN, TRASH_BIN, HOLD_BIN, DUPLICATES_BIN,
    SETTINGS_FILENAME, CACHE_FILENAME, MANIFEST_FILENAME, TAGS_FILENAME,
    LOG_FILENAME, THREAT_FILENAME,
)
from gigasort.core import storage, sort
from gigasort.core.categorize import extract_mod_id, categorize
from gigasort.utils import net
from gigasort.utils.format import human_size


def run_json_report(folder):
    """Scan the workspace (offline, cache-only) and emit a JSON report."""
    result = sort.scan_workspace(folder)
    cache = storage.load_cache(folder)

    cat_names = sorted(result.plan)
    files = []
    for fn, size in result.kept:
        entry = (cache or {}).get(fn) or {}
        files.append({
            "name": fn,
            "size_bytes": size,
            "size_human": human_size(size),
            "mod_id": extract_mod_id(fn),
            "category": categorize(fn),
            "verified": entry.get("status") in ("approved",) if entry else False,
            "verified_title": entry.get("nexus_title"),
        })

    report = {
        "tool": "GigaSort",
        "workspace": folder,
        "read_only": True,
        "online": net.check_connectivity(),
        "totals": {
            "archives": len(result.kept) + len(result.duplicates),
            "kept": len(result.kept),
            "duplicates": len(result.duplicates),
            "rejects": len(result.rejects),
            "categories": len(cat_names),
            "total_bytes": result.total_bytes,
            "total_human": human_size(result.total_bytes),
        },
        "duplicates": [{"name": fn, "size_human": human_size(s)}
                       for fn, s in result.duplicates],
        "rejects": [fn for fn, _ in result.rejects],
        "categories": {c: [fn for fn, _ in result.plan[c]] for c in cat_names},
        "files": files,
    }
    print(json.dumps(report, indent=2))


def run_locate(folder):
    """Print a map of everything GigaSort manages in the workspace."""
    rows = [
        ("workspace", folder, "the ONLY folder this tool touches"),
    ]
    dirs = [
        ("category folders", "(01 Eyes & Lashes ...)"),
        (REJECT_BIN, "review / uncategorized"),
        (TRASH_BIN, "marked for deletion"),
        (HOLD_BIN, "threat-gated, waiting"),
        (DUPLICATES_BIN, "collapsed repeat downloads"),
        (GS_STRUCTURE_DIR, "game-structure staging output"),
        (GS_STAGE_DIR, "temporary extraction scratch"),
        (GS_BACKUP_DIR, "timestamped conflict backups"),
        (BRIDGE_DIR, "agent communication channel"),
    ]
    print("GigaSort workspace: %s" % folder)
    for name, why in dirs:
        p = os.path.join(folder, name)
        print("  %-20s %s  (%s)" % (name, p, why))
    files = [
        (SETTINGS_FILENAME, "settings"),
        (CACHE_FILENAME, "verified cache"),
        (LOG_FILENAME, "verification log"),
        (MANIFEST_FILENAME, "undo manifest"),
        (TAGS_FILENAME, "processed-mods tags"),
        (THREAT_FILENAME, "threat watchlist"),
    ]
    print("  state files:")
    for fname, why in files:
        p = os.path.join(folder, fname)
        exists = "present" if os.path.exists(p) else "absent"
        print("    %-32s %s  [%s]" % (fname, p, exists))
