"""Trash-bin management (--trash) and reject-pile cleanup (--delete-rejects).

SAFETY: deletion only ever touches files that pass the web-verification gate
(real Cyberpunk 2077 mods). Anything unverified is reported and left in
place — never deleted, per the HARD GigaSort safety rule.
"""

import os

from gigasort.constants import TRASH_BIN, REJECT_BIN
from gigasort.core import storage, sort, verify


def _list_bin(folder, bin_name):
    bdir = os.path.join(folder, bin_name)
    items = []
    if os.path.isdir(bdir):
        items = sorted(f for f in os.listdir(bdir)
                       if os.path.isfile(os.path.join(bdir, f)))
    return bdir, items


def manage_trash(folder, dry_run=False, non_interactive=False):
    """List the _TRASH bin. With confirmation, delete VERIFIED-only items.
    Unverified items are never deleted and are reported."""
    import shutil

    bdir, items = _list_bin(folder, TRASH_BIN)
    print("TRASH BIN  (%s)" % TRASH_BIN)
    if not items:
        print("  Trash is empty - nothing to delete.")
        return 0
    for i, fn in enumerate(items, start=1):
        print("  %2d. %s" % (i, fn))

    # Determine which are verified (only those may ever be deleted).
    cache = storage.load_cache(folder)
    approved = set(verify.build_allowlist(
        [(fn, 0) for fn in items], cache)[0])

    if non_interactive:
        deletable = [fn for fn in items if fn in approved]
        if not deletable:
            print("  (non-interactive) nothing verified to delete; "
                  "unverified items left untouched.")
            for fn in items:
                if fn not in approved:
                    print("  unverified (kept): %s" % fn)
            return 0
        if dry_run:
            print("  would delete (verified):")
            for fn in deletable:
                print("    %s" % fn)
            return 0
        for fn in deletable:
            os.remove(os.path.join(bdir, fn))
            storage.record_move(folder, os.path.join(bdir, fn),
                                os.path.join(TRASH_BIN + "/~deleted", fn),
                                dry_run)
        print("  Deleted %d verified item(s)." % len(deletable))
        for fn in items:
            if fn not in approved:
                print("  unverified (kept): %s" % fn)
        return 0

    sel = input("  delete which numbers (verified only)? [n/N to abort]: ").strip()
    if not sel.lower() in ("", "n", "no"):
        for token in sel.split():
            try:
                i = int(token) - 1
                fn = items[i]
            except (ValueError, IndexError):
                continue
            if fn not in approved:
                print("  SKIP (unverified, HARD rule): %s" % fn)
                continue
            if dry_run:
                print("  would delete: %s" % fn)
            else:
                os.remove(os.path.join(bdir, fn))
                print("  deleted: %s" % fn)
    return 0


def delete_rejects(folder, dry_run=False, yes=False, strict=False):
    """Delete verified-only items in _REJECTS (double-confirmed). Never
    touches unverified files."""
    bdir, items = _list_bin(folder, REJECT_BIN)
    print("REJECT PILE  (%s)" % REJECT_BIN)
    if not items:
        print("  Nothing in _REJECTS to clean up.")
        return 0
    for i, fn in enumerate(items, start=1):
        print("  %2d. %s" % (i, fn))

    cache = storage.load_cache(folder)
    approved = set(verify.build_allowlist(
        [(fn, 0) for fn in items], cache)[0])
    deletable = [fn for fn in items if fn in approved]
    kept = [fn for fn in items if fn not in approved]

    if dry_run:
        print("  would delete (verified):")
        for fn in deletable:
            print("    %s" % fn)
        print("  unverified (kept, HARD rule):")
        for fn in kept:
            print("    %s" % fn)
        return 0

    if not deletable:
        print("  No verified rejects to delete; unverified kept in place.")
        return 0

    if not yes:
        if strict:
            print("  abort (--strict): would delete %d verified reject(s) "
                  "without confirmation" % len(deletable))
            return 0
        ans = input("  permanently delete %d verified reject(s)? "
                    "[y/N]: " % len(deletable)).strip().lower()
        if ans not in ("y", "yes"):
            print("  Cancelled.")
            return 0

    for fn in deletable:
        os.remove(os.path.join(bdir, fn))
        storage.record_move(folder, os.path.join(bdir, fn), os.path.join(
            REJECT_BIN + "/~deleted", fn))
        print("  deleted: %s" % fn)
    for fn in kept:
        print("  unverified (kept, HARD rule): %s" % fn)
    return 0
