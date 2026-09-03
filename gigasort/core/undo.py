"""Whole-run undo (--undo): reverse the last run's moves from the manifest."""

import os

from gigasort.core import storage
from gigasort.utils import fs
from gigasort.utils.format import human_size


def run_undo(folder, dry_run=False, input_fn=input):
    """Reverse every move from the manifest in reverse order, then clear it."""
    moves = storage.load_manifest(folder)
    if not moves:
        print("Nothing to undo - manifest is empty.")
        return
    print("Undoing %d move(s) in reverse order..." % len(moves))
    undone = 0
    for m in reversed(moves):
        src, dst = m.get("src"), m.get("dst")
        if not src or not dst:
            continue
        if not os.path.exists(dst):
            print("  skip (dst missing): %s" % dst)
            continue
        fs.guarded_makedirs(folder, os.path.dirname(src), input_fn=input_fn)
        fs.guarded_move(folder, dst, src, dry_run=dry_run, input_fn=input_fn)
        undone += 1
    print("Reversed %d move(s)." % undone)
    if not dry_run:
        storage.save_manifest(folder, [])
        print("Undo manifest cleared.")
