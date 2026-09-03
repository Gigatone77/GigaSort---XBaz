"""Trash-bin management (--trash) and reject-pile cleanup (--delete-rejects).

SAFETY (HARD NO-DELETE RULE): this module NEVER permanently deletes anything.
Items selected for "deletion" are instead MOVED into a hidden, restorable
sub-folder inside the relevant bin, so they can always be recovered by hand.
Only files that pass the web-verification gate (real Cyberpunk 2077 mods) are
ever moved; anything unverified is reported and left in place.
"""

import os

from gigasort.constants import TRASH_BIN, REJECT_BIN
from gigasort.core import storage, verify
from gigasort.utils import fs

# Hidden, restorable sub-folder inside each bin where "deleted" items land.
# They are MOVED here, never removed, so the no-delete rule holds.
DELETED_DIR = "~deleted"


def _bin_deleted_dir(folder, bin_name):
    return os.path.join(folder, bin_name, DELETED_DIR)


def _send_to_deleted(folder, bin_name, filename, dry_run=False):
    """Move one verified item into the bin's restorable '~deleted' sub-folder.

    Replaces permanent deletion: the file is moved (never removed), and the
    move is appended to the undo manifest so it is always reversible.
    """
    src = os.path.join(folder, bin_name, filename)
    dst = os.path.join(_bin_deleted_dir(folder, bin_name), filename)
    fs.guarded_move(
        folder,
        src,
        dst,
        dry_run=dry_run,
        record_fn=(lambda s, d: storage.record_move(folder, s, d, dry_run)),
    )


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
            print("  (non-interactive) nothing verified to move to '%s/'; "
                  "unverified items left untouched." % DELETED_DIR)
            for fn in items:
                if fn not in approved:
                    print("  unverified (kept): %s" % fn)
            return 0
        if dry_run:
            print("  would move to '%s/' (verified):" % DELETED_DIR)
            for fn in deletable:
                print("    %s" % fn)
            return 0
        for fn in deletable:
            _send_to_deleted(folder, TRASH_BIN, fn, dry_run=dry_run)
        print("  Moved %d verified item(s) to '%s/' (restorable, nothing deleted)."
              % (len(deletable), DELETED_DIR))
        for fn in items:
            if fn not in approved:
                print("  unverified (kept): %s" % fn)
        return 0

    sel = input("  move which numbers to '%s/' (verified only)? "
                "[n/N to abort]: " % DELETED_DIR).strip()
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
                print("  would move to '%s/': %s" % (DELETED_DIR, fn))
            else:
                _send_to_deleted(folder, TRASH_BIN, fn)
                print("  moved to '%s/' (restorable): %s" % (DELETED_DIR, fn))
    return 0


def delete_rejects(folder, dry_run=False, yes=False, strict=False):
    """Move VERIFIED-only, double-confirmed items in _REJECTS to the hidden,
    restorable '~deleted' sub-folder. Never permanently deletes; never touches
    unverified files."""
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
        print("  would move to '%s/' (verified):" % DELETED_DIR)
        for fn in deletable:
            print("    %s" % fn)
        print("  unverified (kept, HARD rule):")
        for fn in kept:
            print("    %s" % fn)
        return 0

    if not deletable:
        print("  No verified rejects to move; unverified kept in place.")
        return 0

    if not yes:
        if strict:
            print("  abort (--strict): would move %d verified reject(s) to "
                  "'%s/' without confirmation" % (len(deletable), DELETED_DIR))
            return 0
        ans = input("  move %d verified reject(s) to the restorable '%s/' "
                    "folder (nothing is deleted)? [y/N]: "
                    % (len(deletable), DELETED_DIR)).strip().lower()
        if ans not in ("y", "yes"):
            print("  Cancelled.")
            return 0

    for fn in deletable:
        _send_to_deleted(folder, REJECT_BIN, fn)
        print("  moved to '%s/' (restorable): %s" % (DELETED_DIR, fn))
    for fn in kept:
        print("  unverified (kept, HARD rule): %s" % fn)
    return 0
