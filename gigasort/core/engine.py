"""Verified move execution engine.

Safety: NO file is ever moved, trashed, or deleted unless it has passed the
verification gate (build_verified_gate). Every move goes through
_move_skip_collision so a destination collision downgrades the source to the
recoverable _DUPLICATES bin instead of overwriting or deleting anything.
Empty directories may be pruned with os.rmdir (contents never touched).
"""

import os

from gigasort.constants import (
    REJECT_BIN, TRASH_BIN, HOLD_BIN, DUPLICATES_BIN,
)
from gigasort.core import storage
from gigasort.utils import guarded_move, guarded_makedirs


class DryRun(Exception):
    pass


def _move_skip_collision(src_abs, dst_abs, folder, plan_name,
                         duplicates_bin=DUPLICATES_BIN):
    """Move src under folder; if the destination already holds the same file,
    the redundant source moves to _DUPLICATES (never overwritten, never
    deleted). Never aborts the run."""
    if os.path.exists(dst_abs):
        dup_dir = os.path.join(folder, duplicates_bin)
        guarded_makedirs(folder, dup_dir)
        dup_dst = os.path.join(dup_dir, os.path.basename(src_abs))
        i = 1
        base, ext = os.path.splitext(dup_dst)
        while os.path.exists(dup_dst):
            dup_dst = "%s(%d)%s" % (base, i, ext)
            i += 1
        guarded_move(folder, src_abs, dup_dst)
        return "duplicate"
    guarded_makedirs(folder, os.path.dirname(dst_abs))
    guarded_move(folder, src_abs, dst_abs)
    return "moved"


def route_hold_conflicts(folder, plan, game_dir=None, dry_run=False):
    """Flag files whose archive contents overwrite installed game files.
    Returns a dict {basename: [conflicting relpaths]}.

    game_dir defaults to the workspace's game_dir setting + GAME-DIR check.
    This only marks; nothing is moved here."""
    settings = storage.load_settings(folder)
    game_dir = game_dir or settings.get("game_dir") or ""
    if not game_dir or not os.path.isdir(game_dir):
        return {}

    conflicts = {}
    for base, dest in plan.items():
        src = os.path.join(folder, base)
        if not os.path.exists(src):
            continue
        hits = []
        for entry in _list_game_conflicts(src):
            rel = _game_rel(entry)
            if rel and os.path.exists(os.path.join(game_dir, rel)):
                hits.append(rel)
        if hits:
            conflicts[base] = hits
    return conflicts


def _list_game_conflicts(src):
    """Best-effort list of install-relative paths inside an archive."""
    try:
        from gigasort.core.compat import list_entries
        return [e for e in list_entries(src)
                if e and (e.startswith("archive/") or e.startswith("r6/")
                          or e.startswith("red4ext/")
                          or e.startswith("bin/x64/plugins"))]
    except Exception:  # noqa: BLE001
        return []


def _game_rel(entry):
    """Dropped 'Cyberpunk 2077/' wrapper, else as-is."""
    if entry.startswith("Cyberpunk 2077/"):
        return entry[len("Cyberpunk 2077/"):]
    return entry


def _backup_dest(folder, base, into):
    """Pre-hold backup inside the workspace (never outside it)."""
    d = os.path.join(folder, into)
    guarded_makedirs(folder, d)
    return os.path.join(d, base)


def execute_sort(folder, result=None, dry_run=False, trashed=None,
                 game_dir=None, one_bin=False, only_categories=None, log=None,
                 input_fn=None):
    """Execute a ScanResult plan. Moves only gate-verified files.

    Returns a dict: {"moved", "duplicates", "rejects_moved", "holds",
    "pruned", "flagged_unverified"}."""
    moved = duplicates = rejects_moved = holds = 0
    if hasattr(folder, "plan"):
        # support the GUI's execute_sort(result, input_fn=...) call shape
        result = folder
        folder = result.folder
    flagged = sorted(n for n in (result.plan or {})
                     if n not in result.gate)

    if dry_run:
        c = _plan_counts(result, dry_run=True)
        return {"moved": c[0], "duplicates": c[1],
                "rejects_moved": c[2], "holds": c[3],
                "pruned": [], "flagged_unverified": flagged}

    settings = storage.load_settings(folder)
    one_bin = one_bin or settings.get("bin_style") == "one-bin"

    for base, dest in (result.plan or {}).items():
        src = os.path.join(folder, base)
        if not os.path.exists(src):
            continue

        # hard safety: only verified files leave their place
        if base not in result.gate:
            continue

        if only_categories and not dest.startswith(tuple(only_categories)):
            continue

        if dest.startswith(REJECT_BIN + "/"):
            if one_bin:
                dest = os.path.join(TRASH_BIN, base)
            dst_abs = os.path.join(folder, dest)
            dst_abs = _backup_dest(folder, base, TRASH_BIN) if one_bin \
                else dst_abs
            rc = _move_skip_collision(src, dst_abs, folder, base)
            if rc == "moved":
                rejects_moved += 1
            else:
                duplicates += 1
            continue

        if dest.startswith(HOLD_BIN + "/"):
            dst_abs = os.path.join(folder, dest)
            rc = _move_skip_collision(src, dst_abs, folder, base)
            holds += 1 if rc == "moved" else 0
            continue

        if dest.startswith(DUPLICATES_BIN + "/"):
            dst_abs = os.path.join(folder, dest)
            rc = _move_skip_collision(src, dst_abs, folder, base)
            duplicates += 1 if rc == "moved" or rc == "duplicate" else 0
            continue

        dst_abs = os.path.join(folder, dest)
        rc = _move_skip_collision(src, dst_abs, folder, base)
        if rc == "moved":
            moved += 1
        elif rc == "duplicate":
            duplicates += 1

    # prune empty dir shells left over from dry runs (never contents)
    pruned = []
    for root, _dirs, _files in os.walk(folder, topdown=False):
        if root == folder:
            continue
        try:
            if not os.listdir(root) and \
                    os.path.basename(root) not in (REJECT_BIN, TRASH_BIN):
                os.rmdir(root)
                pruned.append(root)
        except OSError:
            pass

    return {"moved": moved, "duplicates": duplicates,
            "rejects_moved": rejects_moved, "holds": holds,
            "pruned": pruned, "flagged_unverified": flagged}


def _plan_counts(result, dry_run=True):
    """What a dry run would do (never creates anything)."""
    moved = sum(1 for d in result.plan.values()
                if not (d.startswith(REJECT_BIN + "/")
                        or d.startswith(TRASH_BIN + "/")
                        or d.startswith(HOLD_BIN + "/")
                        or d.startswith(DUPLICATES_BIN + "/")))
    rejects = sum(1 for d in result.plan.values()
                  if d.startswith((REJECT_BIN + "/", TRASH_BIN + "/")))
    duplicates = sum(1 for d in result.plan.values()
                     if d.startswith(DUPLICATES_BIN + "/"))
    holds = sum(1 for d in result.plan.values()
                if d.startswith(HOLD_BIN + "/"))
    return moved, duplicates, rejects, holds


def run_batch_sort(workspace, contexts=None, dry_run=False, yes=False,
                   move=True, only_categories=None, pursue=None, report=None,
                   one_bin=False, log=None):
    """Full batch: scan (all context folders) -> execute (gate only)."""
    from gigasort.core.scan import scan_workspace

    results = []
    combined_plan = {}
    combined_gate = set()

    items = [workspace] + list(contexts or [])
    for idx, folder in enumerate(items):
        res = scan_workspace(folder)
        results.append(res)
        for base, dest in res.plan.items():
            combined_plan[("%s::%s" % (folder, base))] = (folder, base, dest)
        combined_gate |= res.gate

    if not move and not dry_run:
        return results, combined_plan

    total_moved = total_dup = total_rej = total_hold = 0
    for res in results:
        rc = execute_sort(res.folder, res, dry_run=dry_run,
                          one_bin=one_bin,
                          only_categories=only_categories, log=log)
        if len(rc) == 4:
            total_moved += rc[0]
            total_dup += rc[1]
            total_rej += rc[2]
            total_hold += rc[3]
        else:
            total_moved += rc[0]

    # prune empty dirs created by dry-run shells (never contents)
    if results:
        for res in results:
            _prune_empty_dirs(res.folder)

    return results, combined_plan


def _prune_empty_dirs(folder, files_ok=True):
    """Remove only empty DIRECTORY shells (os.rmdir never touches files).
    Folders that become needed again are re-created on the next sort."""
    from gigasort.constants import REJECT_BIN, TRASH_BIN
    bins = {REJECT_BIN, TRASH_BIN}
    for root, _dirs, _files in os.walk(folder, topdown=False):
        entries = [os.path.join(root, n) for n in os.listdir(root)]
        if not entries and os.path.basename(root) not in bins and \
                root != folder:
            try:
                os.rmdir(root)
            except OSError:
                pass


def prune_empty_dirs(folder):
    """Public API for --prune (folders only, contents never removed)."""
    _prune_empty_dirs(folder)