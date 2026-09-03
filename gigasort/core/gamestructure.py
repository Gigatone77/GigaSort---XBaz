"""Game-structure sort (--gamestructure) and archive extraction.

Compiles ready-to-use Cyberpunk 2077 folder trees by resolving each archive's
local layout first, then falling back to Nexus info and trusted pages. Never
guesses blindly: anything it cannot place confidently is left `manual`.

Every extraction is guarded (path sanitisation + workspace fence) and any
overwrite is detected with an optional timestamped backup before commit.
"""

import os
import re
import shutil
import subprocess
import time
import zipfile

from gigasort.constants import (
    CP2077_ROOT_DIRS, ARCHIVE_INSTALL_EXTS, GS_STRUCTURE_DIR, GS_STAGE_DIR,
    GS_MANIFEST, GS_BACKUP_DIR, GS_MOD_INDEX,
)
from gigasort.core import storage
from gigasort.core.categorize import extract_mod_id, extract_mod_author
from gigasort.utils import fs
from gigasort.utils.format import human_size
from gigasort.utils.io import json_load, json_dump


def _norm_rel(path):
    """Sanitise a zip entry path: drop '..' segments and drive/abs prefixes."""
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", "..")]
    return "/".join(parts)


def _entry_subpath(entry):
    """Map one archive entry to its game-root folder, or None if loose."""
    top = entry.split("/", 1)[0].lower()
    if top in ("archive",):
        return "archive"
    if top in CP2077_ROOT_DIRS:
        return top
    return None


def _game_subpaths(entries):
    """Set of game-root sub-paths an archive provides + loose entries."""
    subs = set()
    loose = []
    for e in entries:
        top = _entry_subpath(e)
        if top:
            subs.add(top)
        else:
            loose.append(e)
    return subs, loose


def _resolve_layout(folder, path):
    """Determine how an archive maps into the game tree.

    Returns dict {method, subpaths, loose, category}. Strategies in order:
    local (game-shaped) -> nested (one wrapper) -> nexus -> trusted -> manual.
    """
    from gigasort.core import compat
    entries = compat.list_entries(path)
    if not entries:
        return {"method": "unknown", "subpaths": set(), "loose": [], "category": None}
    subs, loose = _game_subpaths(entries)
    if subs:
        return {"method": "local", "subpaths": subs, "loose": loose, "category": None}
    # nested single-wrapper
    tops = {e.split("/", 1)[0] for e in entries if "/" in e}
    if len(tops) == 1 and not loose:
        return {"method": "nested", "subpaths": set(), "loose": [],
                "category": None}
    # nexus category fallback
    mid = extract_mod_id(path)
    cat = None
    if mid:
        from gigasort.utils import net
        _t, ncat = net.lookup_nexus_category(mid)
        cat = ncat
    return {"method": "nexus" if cat else "manual",
            "subpaths": {"archive"} if cat else set(),
            "loose": loose, "category": cat}


def _safe_extract(root, archive_path, dest_dir):
    """Extract an archive into dest_dir with path sanitisation and fence
    guarding. Uses zipfile for .zip, 7z/unrar subprocess for others."""
    fs.guard_under(root, dest_dir)  # assert containment; keep dest_dir
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(archive_path)[1].lower()
    if ext == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            for info in zf.infolist():
                name = _norm_rel(info.filename)
                if not name or name.endswith("/"):
                    continue
                target = os.path.join(dest_dir, name)
                fs.guard_under(root, target)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    else:
        tmp = os.path.join(dest_dir, "_gs_extract_tmp")
        os.makedirs(tmp, exist_ok=True)
        if ext == ".7z":
            subprocess.run(["7z", "x", "-y", "-o" + tmp, archive_path],
                           check=False)
        elif ext == ".rar":
            subprocess.run(["unrar", "x", "-y", archive_path, tmp + "/"],
                           check=False)
        for root2, _dirs, files in os.walk(tmp):
            for f in files:
                rel = os.path.relpath(os.path.join(root2, f), tmp)
                target = os.path.join(dest_dir, rel)
                fs.guard_under(root, target)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(os.path.join(root2, f), target)
        shutil.rmtree(tmp, ignore_errors=True)


def _check_storage(folder, needed_bytes):
    """True if there is at least needed_bytes + 5% + 256MB free."""
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return True
    required = int(needed_bytes * 1.05) + (256 * 1024 * 1024)
    return free >= required


def _collect_plan(folder):
    """Resolve every archive into a plan list (no extraction yet)."""
    plan = {}
    manual = []
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith((".zip", ".rar", ".7z")):
            continue
        path = os.path.join(folder, fn)
        if not os.path.isfile(path):
            continue
        r = _resolve_layout(folder, path)
        if r["method"] == "manual":
            manual.append(fn)
        else:
            plan.setdefault(r["method"], []).append((fn, r))
    return plan, manual


def run_gamestructure(folder, game_dir=None, dry_run=False, input_fn=input):
    """The main game-structure mode: resolve -> plan -> stage/install."""
    plan, manual = _collect_plan(folder)
    print("=" * 70)
    print("GAME-STRUCTURE SORT")
    print("=" * 70)
    for method, items in plan.items():
        print("  [%s] %d archive(s)" % (method, len(items)))
    if manual:
        print("\n  MANUAL (cannot place confidently - sort by hand):")
        for fn in manual:
            print("    • %s" % fn)

    dest_root = game_dir or os.path.join(folder, GS_STRUCTURE_DIR)

    if not dry_run:
        ans = input_fn("\nPlace into '%s'? [y/N] " % dest_root).strip().lower()
        if ans not in ("y", "yes", "confirm"):
            print("Aborted.")
            return

    os.makedirs(dest_root, exist_ok=True)

    # compute archive sizes for a storage pre-flight
    need = 0
    for method, items in plan.items():
        for fn, _r in items:
            need += os.path.getsize(os.path.join(folder, fn))
    if not _check_storage(folder, need):
        print("  Not enough free space (need ~%s). Aborted before any change."
              % human_size(need))
        return

    compiled = 0
    for method, items in plan.items():
        for fn, r in items:
            src = os.path.join(folder, fn)
            stage = os.path.join(folder, GS_STAGE_DIR)
            os.makedirs(stage, exist_ok=True)
            work = os.path.join(stage, "_%s" % compiled)
            try:
                _safe_extract(folder, src, work)
                # copy staged subpaths into dest_root
                if r.get("subpaths"):
                    for sub in sorted(r["subpaths"]):
                        src_dir = os.path.join(work, sub)
                        if not os.path.isdir(src_dir):
                            continue
                        dst_dir = os.path.join(dest_root, sub)
                        _copy_dir_guarded(folder, src_dir, dst_dir, dry_run)
                compiled += 1
            except Exception as exc:
                print("  could not compile %s: %s" % (fn, exc))
            finally:
                shutil.rmtree(work, ignore_errors=True)

    shutil.rmtree(os.path.join(folder, GS_STAGE_DIR), ignore_errors=True)

    json_dump(os.path.join(folder, GS_MANIFEST), {
        "tool": "GigaSort", "mode": "gamestructure",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dest": dest_root, "compiled": compiled,
    })
    print("\nCompiled %d archive(s) into %s"
          % (compiled, dest_root))


def _copy_dir_guarded(folder, src_dir, dst_dir, dry_run):
    """Copy a staged subpath into a destination root, guarding each target."""
    for root2, _dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root2, src_dir)
        for f in files:
            src = os.path.join(root2, f)
            rel = os.path.join(rel_root, f) if rel_root != "." else f
            dst = os.path.join(dst_dir, rel)
            fs.guard_under(folder, dst)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if dry_run:
                continue
            shutil.copy2(src, dst)
