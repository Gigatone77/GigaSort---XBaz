"""Welcome to Night City (WTNC) collection compatibility sweep.

z9er's open-source project (github.com/z9er/CyberpunkTHING) is the canonical
source behind the Nexus "Welcome to Night City" / "Cyberpunk THING" collection
(slug `iszwwe`): Wabbajack/Modlist.md lists every curated mod with its Nexus
mod id. This module:

  * reads the bundled manifest (gigasort/data/wtnc_modlist.md - shipped with
    the tool, so the sweep is fully OFFLINE),
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
from datetime import datetime, timezone
from pathlib import Path

from gigasort.constants import (
    ARCHIVE_EXTS,
    NOT_WTNC_BIN,
    WTNC_EXTRA_COMPAT_FILENAME,
    WTNC_EXTRA_COMPAT_SEED,
    WTNC_REPORT_FILENAME,
    WTNC_BUNDLED_MANIFEST,
)
from gigasort.core import categorize, storage
from gigasort.utils import fs


# '[...](https://www.nexusmods.com/cyberpunk2077/mods/<id>)' - every curated
# mod in the Modlist is an anchor to its Nexus page, so the link IS the id.
_MOD_ID_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(https://www\.nexusmods\.com/cyberpunk2077/mods/(\d+)\)")

_SECTION_RE = re.compile(r"^#+\s+(.+)$")

# Per-mod variant configuration blocks in the Modlist. The collection ships
# two variants built on the same curated mod list - "Welcome to Night City"
# (WTNC) and "Cyberpunk THING" (CyberTHING). A mod that carries one (or both)
# of these blocks is configured differently per variant; the block marks which
# variant(s) the described settings apply to. Mods with no block are configured
# identically in both variants.
_VARIANT_BLOCK_RE = re.compile(r"^\*\*(WTNC|THING)\*\*\s*$")

# Any workspace sub-folder starting with '_' is a GigaSort bin / state dir
# (category folders are 'NN Name', author folders plain names) - never part
# of the mod library proper. Dot-dirs are hidden/home scratch.
_SKIP_DIR_PREFIXES = ("_", ".")


def parse_modlist(text):
    """Parse Modlist.md into {mod_id: {"title", "section", "variants"}}.

    Section `## <name>` headers give each mod a category so the report can
    group matches thematically. Multi-link rows (e.g. the "Apartment Cats"
    pack) yield one entry per linked mod id with that fragment's title.

    `variants` records which variant(s) a mod's settings block belongs to:
    the collection covers BOTH "Welcome to Night City" and "Cyberpunk THING"
    on the same curated mod list, and a `**WTNC**` / `**THING**` block under a
    mod marks variant-specific configuration. Mods with no block carry no
    `variants` key (identical config in both variants).
    """
    manifest = {}
    section = "Overview"
    pending_variants = set()
    # The markers apply to the PREVIOUS mod link: parse one pass, attributing
    # each `**WTNC**`/`**THING**` block to the last mod seen.
    current_id = None
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            section = m.group(1).strip()
            continue
        links = _MOD_ID_LINK_RE.findall(line)
        if links:
            # flush pending variant blocks onto the mod they described
            if current_id and pending_variants:
                manifest[current_id]["variants"] = sorted(pending_variants)
            pending_variants = set()
            for title, mod_id in links:
                manifest.setdefault(mod_id, {
                    "title": title.strip(),
                    "section": section,
                })
                current_id = mod_id
            continue
        vm = _VARIANT_BLOCK_RE.match(line.strip())
        if vm and current_id:
            pending_variants.add(vm.group(1).lower())
    if current_id and pending_variants:
        manifest[current_id]["variants"] = sorted(pending_variants)
    return manifest


def _bundled_manifest_path():
    """Absolute path of the bundled Wabbajack/Modlist.md (shipped with the
    tool, so the sweep is fully offline)."""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "data", WTNC_BUNDLED_MANIFEST)


def fetch_manifest(folder, force=False, max_age_days=7):
    """Return the WTNC manifest record; never raises.

    Fully OFFLINE: the curated Modlist.md ships inside the package
    (gigasort/data/wtnc_modlist.md), so a compatibility sweep never needs a
    network round-trip. The record carries "bundled" as its source_event.
    `force`/`max_age_days` are accepted for API compatibility and ignored.
    """
    path = _bundled_manifest_path()
    try:
        if not os.path.exists(path):
            return {"source": "bundled", "error": "bundled Modlist.md not "
                    "found (%s)" % path, "manifest": {}, "mod_count": 0,
                    "source_event": "none"}
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        mtime = datetime.fromtimestamp(os.path.getmtime(path),
                                       tz=timezone.utc)
        rec = {
            "source": "bundled:%s" % path,
            "fetched_at": mtime.isoformat(),
            "bundled": True,
            "source_event": "bundled",
            "manifest": parse_modlist(text),
        }
        rec["mod_count"] = len(rec["manifest"])
        return rec
    except Exception as e:
        return {"source": "bundled", "error": str(e),
                "manifest": {}, "mod_count": 0, "source_event": "none"}


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
                             **({"variants": info["variants"]}
                                if info.get("variants") else {}),
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


def _print_rel_list(paths, records, folder, limit=50):
    """Print at most `limit` paths (full data stays in the report JSON)."""
    total = len(paths)
    for path in sorted(paths, key=lambda p: p.lower())[:limit]:
        r = records[path]
        print("  %-8s %s  | %s" % (r["mod_id"] or "-", r.get("title") or "",
                                   os.path.relpath(path, folder)))
    if total > limit:
        print("  ... and %d more (full list in %s)"
              % (total - limit, WTNC_REPORT_FILENAME))


def run_wtnc_sweep(folder, dry_run=True, input_fn=None, confirm=True):
    """Full compatibility sweep against the WTNC collection.

    Returns a summary dict. When `dry_run` is False and `confirm` is True the
    move is gated on an interactive yes/no (unless `input_fn` supplies it).
    A report JSON is always written to _GigaSort_wtnc_report.json.
    """
    input_fn = input_fn or input
    manifest = fetch_manifest(folder)
    print("=" * 72)
    print("WELCOME TO NIGHT CITY + CYBERPUNK THING (CyberTHING variant)")
    print("  two variants share one curated modlist; WTNC is the baseline and")
    print("  CyberTHING the alternate tuning.")
    print("=" * 72)
    if manifest.get("error"):
        print("! Bundled Modlist.md missing: %s" % manifest["error"])
        print("  (reinstall the package - this is a fully offline build.)")
        return {"error": manifest["error"]}
    bundled = manifest.get("source_event") == "bundled"
    src = "bundled Modlist.md (offline)" if bundled else "no manifest"
    print("Modlist: %d curated mod(s) (%s, shipped %s)"
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

    print("== SUMMARY ==")
    print("  %-14s %d" % ("in WTNC list", len(by_v["in-wtnc"])))
    print("  %-14s %d" % ("not in list", len(by_v["not-in-wtnc"])))
    print("  %-14s %d" % ("skipped id? ", len(by_v["skip-candidate"])))
    print("  %-14s %d" % ("no id", len(by_v["no-id"])))
    print()

    if by_v["in-wtnc"]:
        print("== CLASSIFIES AS PART OF THE WTNC COLLECTION ==")
        _print_rel_list(by_v["in-wtnc"], records, folder)
        var_counts = {}
        for path in by_v["in-wtnc"]:
            for v in records[path].get("variants") or ():
                var_counts[v] = var_counts.get(v, 0) + 1
        if var_counts:
            print("  variant-specific config: %s"
                  % ", ".join("%s=%d" % (v, n)
                              for v, n in sorted(var_counts.items())))
        print()

    print("== NOT COMPATIBLE WITH WTNC -> '%s' ==" % NOT_WTNC_BIN)
    if by_v["not-in-wtnc"]:
        _print_rel_list(by_v["not-in-wtnc"], records, folder)
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
        _print_rel_list(by_v["skip-candidate"] + by_v["no-id"],
                        records, folder)
        print()

    summary = {"workspace": os.path.normpath(os.path.abspath(folder)),
               "swept_at": datetime.now(timezone.utc).isoformat(),
               "manifest_mod_count": manifest["mod_count"],
               "extra_compat_ids": sorted(extra),
               "bundled": bundled,
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