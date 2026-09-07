"""Welcome to Night City (WTNC) collection compatibility sweep.

z9er's open-source project (github.com/z9er/CyberpunkTHING) is the canonical
source behind the Nexus "Welcome to Night City" / "Cyberpunk THING" collection
(slug `iszwwe`): Wabbajack/Modlist.md lists every curated mod with its Nexus
mod id. This module:

  * fetches that manifest (cached as _GigaSort_wtnc.json, so offline runs use
    the last successful parse),
  * scans the WHOLE mod library (root + organized folders; bin folders are
    skipped), classifying every archive as in-list / not-in-list / no-id, and
  * moves not-in-list mods into the "Not compatible with WTNC" section
    (_NOT_WTNC) - the user-facing definition of "incompatible" here is simply
    "not on z9er's curated list".

SAFETY: this feature NEVER deletes or overwrites. A file is eligible to be
moved OUT of the library only when it carries a resolvable Nexus mod id from
the classic '-NNNN-' token (the Nexus download naming GigaSort trusts offline)
or is already approved in the verified cache. Id-less archives are always left
in place and reported.
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone

from gigasort.constants import (
    ARCHIVE_EXTS,
    NOT_WTNC_BIN,
    WTNC_EXTRA_COMPAT_FILENAME,
    WTNC_EXTRA_COMPAT_SEED,
    WTNC_MANIFEST_FILENAME,
    WTNC_MANIFEST_URL,
    WTNC_REPORT_FILENAME,
)
from gigasort.core import categorize, storage
from gigasort.utils import fs
from gigasort.utils import net


# '[...](https://www.nexusmods.com/cyberpunk2077/mods/<id>)' - every curated
# mod in the Modlist is an anchor to its Nexus page, so the link IS the id.
_MOD_ID_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(https://www\.nexusmods\.com/cyberpunk2077/mods/(\d+)\)")

_SECTION_RE = re.compile(r"^#+\s+(.+)$")

# Any workspace sub-folder starting with '_' is a GigaSort bin / state dir
# (category folders are 'NN Name', author folders plain names) - never part
# of the mod library proper. Dot-dirs are hidden/home scratch.
_SKIP_DIR_PREFIXES = ("_", ".")


def parse_modlist(text):
    """Parse Modlist.md into {mod_id: {"title", "section"}}.

    Section `## <name>` headers give each mod a category so the report can
    group matches thematically. Multi-link rows (e.g. the "Apartment Cats"
    pack) yield one entry per linked mod id with that fragment's title.
    """
    manifest = {}
    section = "Overview"
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            section = m.group(1).strip()
            continue
        for title, mod_id in _MOD_ID_LINK_RE.findall(line):
            manifest.setdefault(mod_id, {
                "title": title.strip(),
                "section": section,
            })
    return manifest


def _manifest_path(folder):
    return os.path.join(folder, WTNC_MANIFEST_FILENAME)


def _load_manifest_cache(folder):
    try:
        with open(_manifest_path(folder), "r") as fh:
            return json.load(fh)
    except Exception:
        return None


def _save_manifest_cache(folder, rec):
    try:
        with open(_manifest_path(folder), "w") as fh:
            json.dump(rec, fh, indent=2)
    except Exception:
        pass


def fetch_manifest(folder, force=False):
    """Return the WTNC manifest record; never raises.

    Cache-first, then a live GET of the GitHub Modlist.md. On any fetch
    failure the last cached parse is returned (so offline runs still work);
    with no cache and no network the record carries an "error" key.
    """
    cached = _load_manifest_cache(folder)
    if cached and cached.get("mod_count") and not force:
        return cached
    last_error = "unreachable"
    try:
        req = urllib.request.Request(WTNC_MANIFEST_URL,
                                     headers={"User-Agent": net.USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        rec = {
            "source": WTNC_MANIFEST_URL,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fetched": True,
            "manifest": parse_modlist(text),
        }
        rec["mod_count"] = len(rec["manifest"])
        _save_manifest_cache(folder, rec)
        return rec
    except Exception as e:
        last_error = str(e) or last_error
    if cached:
        return cached
    return {"source": WTNC_MANIFEST_URL, "error": last_error,
            "manifest": {}, "mod_count": 0}


def library_archives(folder):
    """Absolute paths of every archive in the mod library (bins/state skipped)."""
    if not folder or not os.path.isdir(folder):
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(_SKIP_DIR_PREFIXES)]
        for fn in filenames:
            if fn.lower().endswith(ARCHIVE_EXTS):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def _mod_identity(fn, cache):
    """(mod_id, movable) for a filename.

    movable=True when the identity comes from a classic '-NNNN-' Nexus token
    (the convention GigaSort trusts offline) OR the file is already approved
    in the verified cache. A bare CCXL-style number alone does not authorize a
    move.
    """
    mod_id = categorize.extract_mod_id(fn)
    if mod_id:
        return mod_id, True
    candidate = categorize.candidate_mod_id(fn)
    if candidate:
        entry = (cache or {}).get(fn) or {}
        if entry.get("status") == "approved":
            return candidate, True
        return candidate, False
    return None, False


def _extra_compat(folder):
    """{mod_id: note} treated as compatible even when absent from Modlist.md.

    A few collection-infra mods (the WTNC team's own WTNC Config) ship with the
    collection but are not listed in Wabbajack/Modlist.md. The file is seeded
    with those on first run and can be hand-edited/added to; an unreadable or
    invalid file is ignored (which just disables the overrides).
    """
    path = os.path.join(folder, WTNC_EXTRA_COMPAT_FILENAME)
    if not os.path.exists(path):
        try:
            with open(path, "w") as fh:
                json.dump(WTNC_EXTRA_COMPAT_SEED, fh, indent=2)
        except Exception:
            pass
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        return {}
    except Exception:
        return {}


def classify_archives(folder, manifest):
    """Classify every library archive against the WTNC manifest.

    Returns (records, extra_map). Verdicts:
      in-wtnc        - Nexus id is on z9er's curated modlist OR in the
                       user's extra-compat override file
      not-in-wtnc    - resolvable, movable id NOT on the modlist or overrides
      skip-candidate - id only a bare CCXL candidate + not approved (kept)
      no-id          - no Nexus id in the filename (kept)
    """
    ids = set((manifest or {}).get("manifest", {}).keys())
    extra = _extra_compat(folder)
    cache = storage.load_cache(folder)
    records = {}
    for path in library_archives(folder):
        fn = os.path.basename(path)
        mod_id, movable = _mod_identity(fn, cache)
        if not mod_id:
            records[path] = {"filename": fn, "mod_id": None,
                             "verdict": "no-id",
                             "reason": "no Nexus id in filename - left in place"}
        elif mod_id in ids:
            info = manifest["manifest"][mod_id]
            records[path] = {"filename": fn, "mod_id": mod_id,
                             "title": info["title"],
                             "section": info["section"],
                             "verdict": "in-wtnc",
                             "reason": "on the WTNC/THING curated modlist"}
        elif mod_id in extra:
            records[path] = {"filename": fn, "mod_id": mod_id,
                             "title": extra[mod_id],
                             "section": "User override",
                             "verdict": "in-wtnc",
                             "reason": "user-listed compatible (extra-compat "
                                       "override, not in parsed Modlist.md)"}
        elif movable:
            records[path] = {"filename": fn, "mod_id": mod_id,
                             "verdict": "not-in-wtnc",
                             "reason": "not on the WTNC/THING curated modlist"}
        else:
            records[path] = {"filename": fn, "mod_id": mod_id,
                             "verdict": "skip-candidate",
                             "reason": "id only a bare CCXL candidate and not "
                                       "approved in the verified cache - left "
                                       "in place"}
    return records, extra


def _move_to_bin(folder, src, dry_run=False, input_fn=None):
    """Move src into the 'Not compatible with WTNC' bin, collision-safe."""
    dst = os.path.join(folder, NOT_WTNC_BIN, os.path.basename(src))
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
        return "same"
    if os.path.exists(dst):
        return "exists"
    fs.guarded_makedirs(folder, os.path.dirname(dst),
                        input_fn=input_fn or input)
    fs.guarded_move(folder, src, dst, dry_run=dry_run,
                    input_fn=input_fn or input)
    storage.record_move(folder, src, dst, dry_run)
    return "moved"


def run_wtnc_sweep(folder, dry_run=True, input_fn=None, confirm=True):
    """Full compatibility sweep against the WTNC collection.

    Returns a summary dict. When `dry_run` is False and `confirm` is True the
    move is gated on an interactive yes/no (unless `input_fn` supplies it).
    A report JSON is always written to _GigaSort_wtnc_report.json.
    """
    input_fn = input_fn or input
    manifest = fetch_manifest(folder)
    print("=" * 72)
    print("WELCOME TO NIGHT CITY  (z9er / Cyberpunk THING)  -  compatibility sweep")
    print("=" * 72)
    if manifest.get("error"):
        print("! Manifest unreachable and no cached copy: %s" % manifest["error"])
        print("  (run again online, or that's it for now.)")
        return {"error": manifest["error"]}
    src = "GitHub (live)" if manifest.get("fetched") else "cached copy"
    print("Modlist: %d curated mod(s) (%s, fetched %s)"
          % (manifest["mod_count"], src, manifest.get("fetched_at", "never")))
    print("Workspace: %s" % folder)
    print()

    records, extra = classify_archives(folder, manifest)
    if extra:
        print("Extra-compatible ids (%s): %s"
              % (WTNC_EXTRA_COMPAT_FILENAME, ", ".join(sorted(extra))))
    order = ("not-in-wtnc", "skip-candidate", "no-id")
    by_v = {v: [] for v in order + ("in-wtnc",)}
    for path, rec in records.items():
        by_v[rec["verdict"]].append(path)

    o = os.path.relpath
    print("== SUMMARY ==")
    print("  %-14s %d" % ("in WTNC list", len(by_v["in-wtnc"])))
    print("  %-14s %d" % ("not in list", len(by_v["not-in-wtnc"])))
    print("  %-14s %d" % ("skipped id? ", len(by_v["skip-candidate"])))
    print("  %-14s %d" % ("no id", len(by_v["no-id"])))
    print()

    if by_v["in-wtnc"]:
        print("== CLASSIFIES AS PART OF THE WTNC COLLECTION ==")
        for path in sorted(by_v["in-wtnc"], key=lambda p: p.lower()):
            r = records[path]
            print("  %-8s %s  | %s" % (r["mod_id"], r["title"],
                                       o(path, folder)))
        print()

    print("== NOT COMPATIBLE WITH WTNC -> '%s' ==" % NOT_WTNC_BIN)
    if by_v["not-in-wtnc"]:
        for path in sorted(by_v["not-in-wtnc"], key=lambda p: p.lower()):
            r = records[path]
            print("  %-8s %s" % (r["mod_id"] or "-", o(path, folder)))
        if dry_run:
            print("  (dry run: would move %d to %s)"
                  % (len(by_v["not-in-wtnc"]), NOT_WTNC_BIN))
        else:
            print("  <- moved %d to %s"
                  % (len(by_v["not-in-wtnc"]), NOT_WTNC_BIN))
    else:
        print("  (nothing to move - every identified mod is on the list)")

    if by_v["skip-candidate"] or by_v["no-id"]:
        print()
        print("== LEFT IN PLACE (identity not strong enough to move) ==")
        for path in sorted(by_v["skip-candidate"] + by_v["no-id"],
                           key=lambda p: p.lower()):
            r = records[path]
            print("  %-8s %s  (%s)" % (r["mod_id"] or "-",
                                       o(path, folder), r["reason"]))
        print()

    summary = {"workspace": os.path.normpath(os.path.abspath(folder)),
               "swept_at": datetime.now(timezone.utc).isoformat(),
               "manifest_mod_count": manifest["mod_count"],
               "extra_compat_ids": sorted(extra),
               "fetched": bool(manifest.get("fetched")),
               "dry_run": bool(dry_run),
               "counts": {v: len(by_v[v]) for v in order + ("in-wtnc",)},
               "records": {os.path.relpath(p, folder): r
                           for p, r in records.items()}}
    try:
        with open(os.path.join(folder, WTNC_REPORT_FILENAME), "w") as fh:
            json.dump(summary, fh, indent=2)
    except Exception:
        pass

    to_move = by_v["not-in-wtnc"]
    if dry_run or not to_move:
        return summary

    if confirm:
        try:
            ans = input_fn("Move %d archive(s) to '%s'? [y/N] "
                           % (len(to_move), NOT_WTNC_BIN))
        except Exception:
            ans = ""
        if not (ans or "").strip().lower().startswith("y"):
            print("Nothing moved.")
            summary["moved"] = 0
            summary["collision_kept"] = 0
            return summary

    moved = collision = 0
    for path in to_move:
        outcome = _move_to_bin(folder, path, dry_run=False, input_fn=input_fn)
        if outcome == "moved":
            moved += 1
        elif outcome == "exists":
            collision += 1
    print("Moved %d archive(s) to '%s'; %d skipped (name already in bin)."
          % (moved, NOT_WTNC_BIN, collision))
    summary["moved"] = moved
    summary["collision_kept"] = collision
    return summary