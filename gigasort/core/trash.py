"""Recoverable trash — nothing here is ever hard-deleted by GigaSort.

_Trash and _Delete-Rejects move user files into a hidden, restorable
~deleted/ sub-folder inside the working bin. Remove happens only via the
GUI/user, never by this tool.
"""

import os

from gigasort.constants import TRASH_BIN, REJECT_BIN
from gigasort.core import verify
from gigasort.utils import guarded_move, guarded_makedirs


def send_to_trash(folder, items, gate=None, one_bin=False):
    """Move verified items to the recoverable trash bin.

    items: files relative to folder. Only items in `gate` (verified set) are
    moved; unverified are reported and left in place.
    Returns (moved, blocked) lists."""
    gate = gate if gate is not None else verify.build_verified_gate(
        folder, [os.path.basename(i) for i in items])
    moved, blocked = [], []
    for item in items:
        base = os.path.basename(item)
        if base not in gate:
            blocked.append(item)
            continue
        dest_bin = TRASH_BIN if one_bin else TRASH_BIN
        dst_dir = os.path.join(folder, dest_bin, "~deleted")
        guarded_makedirs(folder, dst_dir)
        dst = os.path.join(dst_dir, base)
        i = 1
        while os.path.exists(dst):
            stem, ext = os.path.splitext(dst)
            dst = "%s(%d)%s" % (stem, i, ext)
            i += 1
        try:
            guarded_move(folder, item, dst)
            moved.append(dst)
        except Exception:  # noqa: BLE001
            blocked.append(item)
    return moved, blocked


def delete_rejects(folder, items=None, gate=None):
    """Move unverified/reject files into the recoverable ~deleted sub-bin.

    This NEVER deletes — it relocates into the hidden restorable bin, the
    same no-delete rule as everywhere else in GigaSort."""
    reject_dir = os.path.join(folder, REJECT_BIN)
    if not os.path.isdir(reject_dir):
        return [], []
    deleted_root = os.path.join(reject_dir, "~deleted")
    if items is None:
        items = sorted(os.listdir(reject_dir))
    moved, blocked = [], []
    for item in items:
        if item == "~deleted":
            continue
        src = os.path.join(reject_dir, item)
        if not os.path.exists(src):
            continue
        if gate is not None and item not in gate:
            blocked.append(item)
            continue
        guarded_makedirs(folder, deleted_root)
        dst = os.path.join(deleted_root, item)
        i = 1
        while os.path.exists(dst):
            stem, ext = os.path.splitext(dst)
            dst = "%s(%d)%s" % (stem, i, ext)
            i += 1
        try:
            guarded_move(folder, src, dst)
            moved.append(dst)
        except Exception:  # noqa: BLE001
            blocked.append(item)
    return moved, blocked