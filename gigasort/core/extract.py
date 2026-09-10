"""Per-mod folder extraction (--extract / extract_on_sort).

Takes the already-organized library one step further: every verified archive
sitting inside a managed category folder is given its own per-mod folder
(named after the mod), the archive is moved in and KEPT, its game content is
extracted (archive/, r6/, bin/, ...) into the same folder, and a Vortex-style
``meta.ini`` is written next to it.

Layout produced (mirrors the hand-built "Cyberpunk Vehicles Archive"):

    09 Vehicles & Transport/
      KRNLNIK Toyota MR2 SC/
        KRNLNIK Toyota MR2 SC-19749-...zip   <- archive kept
        archive/                              <- extracted content
        r6/
        meta.ini

Only VERIFIED files are touched (approved cache / verified references /
offline CP2077 structure). Existing content is never overwritten, and an
already-extracted folder (meta.ini present) is skipped on re-runs.
"""

import os
import re
import shutil
import time

from gigasort.constants import (
    APPROVED, MISMATCH, ARCHIVE_EXTS, GS_STAGE_DIR,
    NEXUS_ID_RE, KNOWN_FRAMEWORKS,
)
from gigasort.core import storage
from gigasort.core.categorize import extract_mod_id
from gigasort.utils import fs


def _mod_folder_name(fn):
    """A clean per-mod folder name for an archive filename.

    Prefers the mod display name embedded in the Nexus 'Name-<id>-...'
    filename; falls back to the author-extraction, then the bare stem.
    """
    base = os.path.splitext(fn)[0]
    base = re.sub(r"^\s*\[[^\]]*\]\s*", "", base)
    m = re.search(r"-\d{3,6}(?:-|\.|$)", base)
    if m and m.start() > 0:
        modname = base[: m.start()].replace("_", " ").strip()
    else:
        from gigasort.core.categorize import extract_mod_author
        modname = extract_mod_author(fn) or base
    modname = re.sub(r"\s+", " ", modname).strip(" ._-")
    return modname or base


def _peel_wrapper(stage):
    """If the staged tree is exactly one directory (a Nexus-style wrapper),
    return it; otherwise return the stage root. Offline-only. A single
    top-level dir that is itself a CP2077 game root (archive/, r6/, bin/, ...)
    is NOT a wrapper - those contents stay put."""
    from gigasort.constants import CP2077_ROOT_DIRS
    try:
        entries = [e for e in os.listdir(stage) if e not in (".", "..")]
    except OSError:
        return stage
    if len(entries) == 1:
        only = os.path.join(stage, entries[0])
        if os.path.isdir(only) and entries[0].lower() not in CP2077_ROOT_DIRS:
            return only
    return stage


def _parse_meta_from_filename(fn):
    """Best-effort {modid, version, fileid} pulled from a Nexus filename.

    'KRNLNIK Toyota MR2 SC-19749-1-0-5-Minor-1775611452.zip'
        -> modid 19749, version '1.0.5.Minor', fileid 1775611452
    """
    base = os.path.splitext(fn)[0]
    idm = NEXUS_ID_RE.search(base)
    if not idm:
        return {"modid": extract_mod_id(fn), "version": "", "fileid": ""}
    modid = idm.group(1)
    tail = base[idm.end():]
    parts = tail.split("-")
    if parts and parts[-1].isdigit():
        fileid = parts.pop()
    else:
        fileid = ""
    version = ".".join(parts)
    return {"modid": modid, "version": version, "fileid": fileid}


def _req_string(deps):
    """Format a dependency id list like '1047:CET;4198:ArchiveXL;'."""
    if not deps:
        return ""
    out = []
    for d in deps:
        d = str(d)
        name = KNOWN_FRAMEWORKS.get(d, d)
        out.append("%s:%s" % (d, name))
    return ";".join(out) + ";"


_META_ORDER = [
    "gamename", "modid", "fileid", "version", "author", "uploadedby",
    "nexusname", "nexusfilename", "installationfile", "filesize",
    "installed", "nexusurl", "description", "categoryid", "categoryname",
    "filecategory", "endorsed", "latestfileid", "latestversion",
    "hasupdate", "ignoreupdate", "ignoredversion", "missingrequirements",
    "nexusrequirements", "ignoredrequirements", "rootfolder", "fromcollection",
]


def _write_meta(target_dir, fn, size, refs, category_folder):
    """Write a best-effort Vortex-style meta.ini into target_dir."""
    info = _parse_meta_from_filename(fn)
    modid = info["modid"]
    ref = (refs or {}).get(modid) or {}
    title = ref.get("title") or ""
    title = re.sub(r"\s+at Cyberpunk 2077 Nexus.*$", "", title).strip()

    deps = ref.get("deps") or []
    req = _req_string(deps)

    fields = {
        "gamename": "cyberpunk2077",
        "modid": modid or "",
        "fileid": info["fileid"],
        "version": info["version"],
        "author": "",
        "uploadedby": "",
        "nexusname": title or _mod_folder_name(fn),
        "nexusfilename": "",
        "installationfile": fn,
        "filesize": str(size),
        "installed": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nexusurl": ("https://www.nexusmods.com/cyberpunk2077/mods/%s"
                     % modid) if modid else "",
        "description": "",
        "categoryid": "",
        "categoryname": category_folder or "",
        "filecategory": "",
        "endorsed": "false",
        "latestfileid": "0",
        "latestversion": "",
        "hasupdate": "false",
        "ignoreupdate": "false",
        "ignoredversion": "",
        "missingrequirements": req,
        "nexusrequirements": req,
        "ignoredrequirements": "",
        "rootfolder": "false",
        "fromcollection": "",
    }
    path = os.path.join(target_dir, "meta.ini")
    os.makedirs(target_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[General]\n")
        for k in _META_ORDER:
            f.write("%s = %s\n" % (k, fields.get(k, "")))


def _verified(folder, fn, cache, refs, src_abs=None):
    """True only if `folder/fn` is a confirmed CP2077 mod (offline-proofs only)."""
    entry = (cache or {}).get(fn) or {}
    if entry.get("status") in (APPROVED, MISMATCH):
        return True
    modid = extract_mod_id(fn)
    if modid and (refs or {}).get(modid, {}).get("verified"):
        return True
    try:
        from gigasort.core import compat
        # is_cp2077_mod_file already tolerates CCXL bare-number ids and weak
        # (non -NNN-) id forms, and needs BOTH id and strong layout/keyword.
        return compat.is_cp2077_mod_file(
            fn, src_abs or os.path.join(folder, fn), mod_id=modid)
    except Exception:
        return False


def _copy_game_root(folder, content_root, target_dir, skip_names):
    """Copy the extracted content root into target_dir, skipping any existing
    entry (never overwrites). `skip_names` prevents re-extracting the archive(s)
    themselves if they somehow landed in the staged tree."""
    if not os.path.isdir(content_root):
        return 0
    copied = 0
    for name in sorted(os.listdir(content_root)):
        if name.lower().endswith(ARCHIVE_EXTS) or name in skip_names:
            continue
        dst = os.path.join(target_dir, name)
        if os.path.exists(dst):
            continue
        fs.guard_under(folder, dst)
        src = os.path.join(content_root, name)
        os.makedirs(target_dir, exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        copied += 1
    return copied


def run_extract(folder, dry_run=False, input_fn=input, toplevel_authors=None):
    """Extract every verified organized archive into its own per-mod folder.

    Returns a summary dict. Never overwrites existing content; re-runs skip
    folders that already hold a meta.ini.
    """
    from gigasort.core.sort import collect_nested_archives
    if toplevel_authors is None:
        from gigasort.constants import TOPLEVEL_AUTHORS
        toplevel_authors = list(TOPLEVEL_AUTHORS)

    cache = storage.load_cache(folder)
    refs = storage.load_references(folder)

    nested = collect_nested_archives(folder, toplevel_authors)
    print("== PER-MOD FOLDER EXTRACTION  (%s) ==" % folder)
    print("  %d organized archive(s) under managed folders."
          % len(nested))

    extracted = 0
    skipped = 0
    moved_in = 0
    unverified = []

    stage = os.path.join(folder, GS_STAGE_DIR)

    for idx, (fn, size, src_abs) in enumerate(sorted(nested), start=1):
        if not fn.lower().endswith(ARCHIVE_EXTS):
            continue
        if not _verified(folder, fn, cache, refs, src_abs=src_abs):
            unverified.append(fn)
            continue

        modname = _mod_folder_name(fn)
        parent = os.path.dirname(src_abs)
        target_dir = (parent if os.path.basename(parent) == modname
                      else os.path.join(parent, modname))

        # Already-extracted marker: a meta.ini in the mod folder.
        if os.path.exists(os.path.join(target_dir, "meta.ini")):
            skipped += 1
            continue

        if os.path.abspath(src_abs) != os.path.abspath(
                os.path.join(target_dir, fn)):
            if dry_run:
                print("  [%d] would move %s -> %s" % (idx, fn, target_dir))
            else:
                os.makedirs(target_dir, exist_ok=True)
                dst = os.path.join(target_dir, fn)
                fs.guard_under(folder, dst)
                shutil.move(src_abs, dst)
                storage.record_move(folder, src_abs, dst)
                src_abs = dst
            moved_in += 1

        print("  [%d/%d] extracting '%s' -> %s"
              % (idx, len(nested), fn, os.path.relpath(target_dir, folder)))

        if dry_run:
            extracted += 1
            continue

        from gigasort.core.gamestructure import _safe_extract, ExtractionError

        work = os.path.join(stage, "_extract_%d" % idx)
        os.makedirs(stage, exist_ok=True)
        try:
            _safe_extract(folder, src_abs, os.path.join(work))
        except ExtractionError as exc:
            print("    extraction failed: %s" % exc)
            skipped += 1
            shutil.rmtree(work, ignore_errors=True)
            continue
        except Exception as exc:
            print("    could not extract: %s" % exc)
            skipped += 1
            shutil.rmtree(work, ignore_errors=True)
            continue

        content_root = _peel_wrapper(work)
        logs_abs = os.path.join(target_dir, "meta.ini")
        _copy_game_root(folder, content_root, target_dir,
                        skip_names={os.path.basename(fn)})
        shutil.rmtree(work, ignore_errors=True)
        if not os.path.exists(logs_abs):
            category = os.path.relpath(target_dir, folder).split(os.sep)[0]
            _write_meta(target_dir, os.path.basename(src_abs), size, refs,
                        category_folder=category)
        extracted += 1

    shutil.rmtree(stage, ignore_errors=True)

    print("=" * 70)
    print("Extracted/kept %d mod folder(s), skipped %d (already done/failed),"
          % (extracted, skipped))
    if moved_in:
        print("Moved %d archive(s) into their per-mod folder."
              % (0 if dry_run else moved_in))
    if unverified:
        print("UNVERIFIED (left untouched - never moved/extracted):")
        for fn in unverified:
            print("  \u2022 %s" % fn)
    if dry_run:
        print("(dry run - nothing written)")
    return {
        "extracted": extracted,
        "skipped": skipped,
        "moved_in": moved_in,
        "unverified": unverified,
    }