"""The core sort engine: scan, dedup, plan, preview, execute.

Design: scan_workspace() builds a ScanResult without side effects (read-only,
good for --dry-run/--json). execute_sort() performs the moves under the
safety guards and always reports the reject pile before touching anything.
"""

import os
import time
from dataclasses import dataclass, field

from gigasort.constants import (
    ARCHIVE_EXTS, REJECT_BIN, TRASH_BIN, DUPLICATES_BIN,
)
from gigasort.core.categorize import (
    clean_name, categorize, extract_mod_author,
)
from gigasort.core import storage
from gigasort.utils import fs
from gigasort.utils.format import human_size


@dataclass
class ScanResult:
    folder: str
    kept: list = field(default_factory=list)      # [(fn, size)]
    duplicates: list = field(default_factory=list)  # [(fn, size)]
    rejects: list = field(default_factory=list)     # [(fn, size)]
    plan: dict = field(default_factory=dict)        # cat -> [(fn, size)]
    scanned_at: float = field(default_factory=time.time)

    @property
    def total_bytes(self):
        return sum(s for _, s in self.kept)

    @property
    def moved_count(self):
        return sum(len(v) for v in self.plan.values())


def scan_workspace(folder):
    """Read the workspace, group by cleaned name, decide keep/dupe, and
    categorize the keepers. Pure/read-only."""
    archives = []
    for fn in sorted(os.listdir(folder)):
        full = os.path.join(folder, fn)
        if os.path.isfile(full) and fn.lower().endswith(ARCHIVE_EXTS):
            archives.append((fn, os.path.getsize(full)))

    by_clean = {}
    for fn, size in archives:
        by_clean.setdefault(clean_name(fn), []).append((fn, size))

    keep, dupes = [], []
    for clean, group in by_clean.items():
        non_suffixed = [g for g in group if os.path.basename(g[0]) == clean]
        if non_suffixed:
            keep.append(non_suffixed[0])
            dupes.extend(g for g in group if g not in non_suffixed)
        else:
            best = max(group, key=lambda g: g[1])
            keep.append(best)
            dupes.extend(g for g in group if g != best)

    plan, rejects = {}, []
    for fn, size in keep:
        cat = categorize(fn)
        if cat is None:
            rejects.append((fn, size))
        else:
            plan.setdefault(cat, []).append((fn, size))

    return ScanResult(folder=folder, kept=keep, duplicates=dupes,
                      rejects=rejects, plan=plan)


def build_verified_gate(folder, kept):
    """Web-verify the keep list per the 'never touch unverified' rule.

    Returns (verified_fns, flagged_fns): the allowlist used by the move paths.
    Only filenames in verified_fns may be moved. Uses the local verified cache
    first, then a read-only Nexus lookup.
    """
    from gigasort.core import storage, verify
    cache = storage.load_cache(folder)
    kept_list = [(fn, size) for fn, size in kept]
    verified, flagged = verify.build_allowlist(kept_list, cache)
    if verified:
        storage.save_cache(folder, cache)
    return verified, flagged



def print_plan(result, dry_run):
    """Report rejects, duplicates and planned moves — always before commit."""
    print("=" * 70)
    print("REJECT PILE  (files that matched no category)")
    print("=" * 70)
    if result.rejects:
        for fn, size in result.rejects:
            print("  %s   (%s)" % (fn, human_size(size)))
        print("  Rejects go into exactly one of: '%s' (review) or '%s' "
              "(trash, never auto-deleted)." % (REJECT_BIN, TRASH_BIN))
    else:
        print("  (none - every file categorized)")
    print()

    print("=" * 70)
    print("DUPLICATES  (suffixed copies kept separately, never deleted)")
    print("=" * 70)
    if result.duplicates:
        for fn, size in result.duplicates:
            print("  %s   (%s)" % (fn, human_size(size)))
    else:
        print("  (none)")
    print()

    print("=" * 70)
    print("PLANNED MOVES" + ("  (DRY RUN - nothing moved)" if dry_run else ""))
    print("=" * 70)
    for cat in sorted(result.plan):
        files = result.plan[cat]
        print("\n[%s]  (%d files)" % (cat, len(files)))
        for fn, size in files:
            print("    -> %s/%s   (%s)" % (cat, fn, human_size(size)))
    print()


def _to_bin(folder, filename, bin_name, dry_run, input_fn=input):
    """Move one file into a bin, enforcing the one-bin rule."""
    storage.prepare_one_bin(folder, filename, bin_name, dry_run)
    bin_dir = os.path.join(folder, bin_name)
    fs.guarded_makedirs(folder, bin_dir, input_fn=input_fn)
    src = os.path.join(folder, filename)
    dst = os.path.join(bin_dir, filename)
    if os.path.abspath(src) != os.path.abspath(dst):
        fs.guarded_move(folder, src, dst, dry_run=dry_run, input_fn=input_fn)


def execute_sort(result, dry_run=False, input_fn=input):
    """Execute the plan under the safety guards. Returns moved count.

    SAFETY: the 'never touch unverified' rule is absolute here. Only files
    web-verified as real Cyberpunk 2077 mods (or already APPROVED in cache)
    may be moved, trashed, or otherwise altered. Everything else is reported
    and LEFT IN PLACE regardless of the user's reject choice.
    """
    folder = result.folder
    moved = 0

    verified, flagged = build_verified_gate(folder, result.kept)

    # Rejects (report + prompt, mirroring the always-ask behaviour).
    if result.rejects:
        print("\n" + "=" * 70)
        print("REJECT PILE - action required")
        print("=" * 70)
        verified_rejects = [fn for fn, _ in result.rejects if fn in verified]
        unverified = [fn for fn, _ in result.rejects if fn not in verified]
        reject_sizes = dict(result.rejects)
        for fn, _size in result.rejects:
            print("  • %s  (matched no category rule)" % fn)
        if unverified:
            print("\n  UNVERIFIED (left in place, never touched):")
            for fn in unverified:
                print("    • %s" % fn)
        if not verified_rejects:
            print("\n  No verified rejects to act on - all reject files kept.")
        else:
            try:
                mode = input_fn("  [b] Batch to _REJECTS | [i] Individual | "
                                "[r] Batch to _TRASH | [s] Skip: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                mode = "s"
            if mode == "s":
                print("  Skipping rejects - left in place.")
            elif mode == "i":
                for fn in verified_rejects:
                    print("\n  • %s (%s)" % (fn, human_size(reject_sizes[fn])))
                    act = input_fn("      [1] _REJECTS | [2] _TRASH | [k] keep: "
                                   "").strip().lower()
                    if act == "1":
                        _to_bin(folder, fn, REJECT_BIN, dry_run, input_fn)
                    elif act == "2":
                        _to_bin(folder, fn, TRASH_BIN, dry_run, input_fn)
            elif mode == "r":
                for fn in verified_rejects:
                    _to_bin(folder, fn, TRASH_BIN, dry_run, input_fn)
                print("  Batch: moved verified rejects to %s." % TRASH_BIN)
            else:
                for fn in verified_rejects:
                    _to_bin(folder, fn, REJECT_BIN, dry_run, input_fn)
                print("  Batch: moved verified rejects to %s." % REJECT_BIN)

    # Categories -> <cat>/<author>/<file> (verified only).
    for cat, files in result.plan.items():
        cat_dir = os.path.join(folder, cat)
        fs.guarded_makedirs(folder, cat_dir, input_fn=input_fn)
        for fn, _ in files:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            author = extract_mod_author(fn)
            if author:
                author_dir = os.path.join(cat_dir, author)
                fs.guarded_makedirs(folder, author_dir, input_fn=input_fn)
                dst = os.path.join(author_dir, fn)
            else:
                dst = os.path.join(cat_dir, fn)
            fs.guarded_move(folder, src, dst, dry_run=dry_run, input_fn=input_fn)
            storage.record_move(folder, src, dst, dry_run)
            moved += 1

    # Duplicates -> _DUPLICATES (verified only).
    if result.duplicates:
        dup_dir = os.path.join(folder, DUPLICATES_BIN)
        fs.guarded_makedirs(folder, dup_dir, input_fn=input_fn)
        for fn, _ in result.duplicates:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            dst = os.path.join(dup_dir, fn)
            fs.guarded_move(folder, src, dst, dry_run=dry_run, input_fn=input_fn)
            storage.record_move(folder, src, dst, dry_run)
            moved += 1

    if flagged:
        print("\nNOT TOUCHED (%d unverified - never moved/trashed):" % len(flagged))
        for fn in sorted(flagged):
            print("  • %s" % fn)

    _write_tags_safe(folder)
    return moved


def run_batch_sort(folder, dry_run=False, to_rejects=True):
    """Headless, non-interactive sort (used by --apply and the agent bridge's
    batch-sort op). Returns a summary dict.

    SAFETY: only web-verified Cyberpunk 2077 mods are ever moved. Any file
    that is not confirmed (no Nexus mod id, or the page does not resolve to a
    real CP2077 mod) is routed to _REJECTS instead of being sorted or deleted.
    """
    from gigasort.core import tags as tags_mod, verify

    result = scan_workspace(folder)
    moved = 0

    verified, flagged = build_verified_gate(folder, result.kept)

    # Every planned category move is allowed only if the file is verified.
    for cat, files in list(result.plan.items()):
        cat_dir = os.path.join(folder, cat)
        fs.guarded_makedirs(folder, cat_dir)
        for fn, _ in files:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            author = extract_mod_author(fn)
            if author:
                author_dir = os.path.join(cat_dir, author)
                fs.guarded_makedirs(folder, author_dir)
                dst = os.path.join(author_dir, fn)
            else:
                dst = os.path.join(cat_dir, fn)
            fs.guarded_move(folder, src, dst, dry_run=dry_run)
            storage.record_move(folder, src, dst, dry_run)
            moved += 1

    # Verified rejects go to _REJECTS; unverified flagged files are NEVER
    # touched (left in place so nothing is auto-moved or lost).
    verified_rejects = [fn for fn, _ in result.rejects if fn in verified]
    if verified_rejects and to_rejects:
        bin_dir = os.path.join(folder, REJECT_BIN)
        fs.guarded_makedirs(folder, bin_dir)
        for fn in verified_rejects:
            storage.prepare_one_bin(folder, fn, REJECT_BIN, dry_run)
            src = os.path.join(folder, fn)
            dst = os.path.join(bin_dir, fn)
            if os.path.abspath(src) != os.path.abspath(dst):
                fs.guarded_move(folder, src, dst, dry_run=dry_run)
                storage.record_move(folder, src, dst, dry_run)

    # Duplicates: only verified duplicates may move.
    if result.duplicates:
        dup_dir = os.path.join(folder, DUPLICATES_BIN)
        fs.guarded_makedirs(folder, dup_dir)
        for fn, _ in result.duplicates:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            dst = os.path.join(dup_dir, fn)
            fs.guarded_move(folder, src, dst, dry_run=dry_run)
            storage.record_move(folder, src, dst, dry_run)
            moved += 1

    _write_tags_safe(folder)

    return {
        "moved": moved,
        "to_rejects": len(verified_rejects) if to_rejects else 0,
        "duplicates": len(result.duplicates),
        "archives": len(result.kept) + len(result.duplicates),
        "dry_run": bool(dry_run),
        "flagged_unverified": sorted(flagged),
    }


def _write_tags_safe(folder):
    try:
        from gigasort.core import tags as tags_mod
        tags_mod.write_tags(folder)
    except Exception:
        pass
