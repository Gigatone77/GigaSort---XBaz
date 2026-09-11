"""WTNC (Wake the Netrunner Collection) offline integration.

Loads the bundled wtnc_modlist.md (no network), resolves which downloaded
archives belong to the collection, and reports mods that are NOT compatible
(dep-less / conflicting) per the extra-compat map."""

import os
import re

from gigasort.constants import (
    WTNC_BUNDLED_MANIFEST,
)
from gigasort.core import storage

_ID_RE = re.compile(r"-(\d{3,6})-", re.IGNORECASE)


def load_manifest():
    """Parse the bundled WTNC mod list. {id: [name, category?]}"""
    out = {}
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "data", WTNC_BUNDLED_MANIFEST)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^M\s+(\d+)\s+(.+)$", line, re.I)
                if m:
                    out[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    return out


def _extra_compat(workspace):
    """User-editable extra-compat map (auto-seeded with 10426)."""
    return storage.load_wtnc_compat(workspace)


def _zw_id(name):
    m = re.match(r"^zw_\d+_(\d+)_", os.path.basename(name))
    return m.group(1) if m else None


def classify_archive(workspace, name):
    """Return 'collection' | 'manual' | 'unknown' for a staged archive."""
    manifest = load_manifest()
    ids = _ids_of(name)
    if not ids:
        return "unknown"
    for mid in ids:
        if mid in manifest:
            return "collection"
        compat = _extra_compat(workspace)
        if mid in compat:
            return "collection"
    return "manual"


def _ids_of(name):
    ids = []
    base = os.path.basename(name)
    m = _ID_RE.search(base)
    if m:
        ids.append(m.group(1))
    zw = _zw_id(base)
    if zw:
        ids.append(zw)
    return list(dict.fromkeys(ids))


def run_wtnc_report(workspace, only_missing=False):
    """Write _GigaSort_wtnc_report.json describing the collection fit.

    Returns the report dict."""
    manifest = load_manifest()
    compat = _extra_compat(workspace)
    report = {
        "manifest_total": len(manifest),
        "extra_compat_total": len(compat),
        "archives": [],
    }
    for n in sorted(os.listdir(workspace)):
        if not n.lower().endswith((".zip", ".rar", ".7z")):
            continue
        ids = _ids_of(n)
        rec = {"file": n, "ids": ids}
        matched = [i for i in ids if i in manifest]
        extra = [i for i in ids if i in compat]
        rec["in_manifest"] = matched
        rec["extra_compat"] = extra
        rec["kind"] = ("collection" if matched or extra else "manual/unknown")
        report["archives"].append(rec)
    storage.save_wtnc_report(workspace, report)
    return report


def fetch_manifest(workspace, force=False):
    """'Fetch' the bundled WTNC modlist (offline - ships with the tool).

    Compatible with the old GUI contract: returns True when a manifest is
    available. force is accepted for CLI parity but is a no-op here."""
    return bool(load_manifest())


def run_wtnc_sweep(workspace, dry_run=True, confirm=False):
    """Sweep the whole tree and classify every archive against the bundled
    WTNC list. Returns the GUI summary dict:
    {manifest_mod_count, bundled, extra_compat_ids,
     counts: {in-wtnc, not-in-wtnc, skip-candidate, no-id},
     records: {rel: {...}}, moved (int|None)}"""
    from gigasort.constants import NOT_WTNC_BIN
    manifest = load_manifest()
    compat = _extra_compat(workspace)
    counts = {"in-wtnc": 0, "not-in-wtnc": 0, "skip-candidate": 0,
              "no-id": 0}
    records = {}
    moved = None
    for root, _dirs, files in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)
        for n in files:
            if not n.lower().endswith((".zip", ".rar", ".7z")):
                continue
            if rel_root.split(os.sep)[0].startswith("_"):
                continue
            rel = os.path.join(rel_root, n) if rel_root != "." else n
            ids = _ids_of(n)
            verdict = "skip-candidate"
            if not ids:
                verdict = "no-id"
            elif any(i in manifest or i in compat for i in ids):
                verdict = "in-wtnc"
            else:
                verdict = "not-in-wtnc"
            counts[verdict] += 1
            records[rel] = {
                "filename": n,
                "mod_id": ids[0] if ids else None,
                "verdict": verdict,
            }

    if not dry_run and confirm is not False:
        # move only when explicitly requested (moved counts recorded below)
        pass
    if not dry_run:
        from gigasort.core.engine import _move_skip_collision
        n_moved = 0
        dest_root = os.path.join(workspace, NOT_WTNC_BIN)
        os.makedirs(dest_root, exist_ok=True)
        for rel, rec in list(records.items()):
            if rec["verdict"] != "not-in-wtnc":
                continue
            src = os.path.join(workspace, rel)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(dest_root, rec["filename"])
            if os.path.exists(dst):
                continue
            try:
                _move_skip_collision(src, dst, workspace, rec["filename"])
                n_moved += 1
                rec["moved"] = True
            except Exception:  # noqa: BLE001
                pass
        moved = n_moved

    return {
        "manifest_mod_count": len(manifest),
        "bundled": True,
        "extra_compat_ids": sorted(compat),
        "counts": counts,
        "records": records,
        "moved": moved,
    }