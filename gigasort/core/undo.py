"""Undo — replay the manifest back to its pre-sort state."""

import os

from gigasort.core.storage import load_manifest, save_manifest


def _reverse_path(folder, relpath):
    """Return an absolute path inside folder, guarding against escapes."""
    joined = os.path.normpath(os.path.join(folder, relpath))
    if not os.path.realpath(joined).startswith(os.path.realpath(folder)):
        raise ValueError("path escapes workspace: %r" % relpath)
    return joined


def undo_move(folder, entry_id=None, dry_only=False):
    """Undo the last manifest entry (or a specific one).

    Returns (undone, skipped) counts. dry_only=True prints what would move
    without moving."""
    manifest = load_manifest(folder)
    moves = manifest.get("moves", {})
    if entry_id is None:
        ids = [k for k, v in moves.items() if v.get("applied")]
        if not ids:
            return 0, 0
        entry_id = sorted(ids, key=lambda k: moves[k].get("time", 0))[-1]

    entry = moves.get(entry_id)
    if not entry:
        return 0, 0

    undone = skipped = 0
    for change in reversed(entry.get("changes", [])):
        if not change.get("applied") is not False and change.get("verified"):
            pass
        to = change.get("to")
        back_to = change.get("from")
        if not to or not back_to:
            continue
        src = _reverse_path(folder, to)
        dst = _reverse_path(folder, back_to)
        if not os.path.exists(src):
            skipped += 1
            continue
        if dry_only:
            undone += 1
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.replace(src, dst)
            undone += 1
        except OSError:
            skipped += 1

    if not dry_only:
        entry["applied"] = False
        save_manifest(folder, manifest)
    return undone, skipped


def list_undone(folder):
    """Return manifest entries with their file lists (for --undo preview)."""
    manifest = load_manifest(folder)
    out = []
    for eid, entry in sorted(
            manifest.get("moves", {}).items(),
            key=lambda kv: kv[1].get("time", 0)):
        out.append({
            "id": eid,
            "time": entry.get("time"),
            "applied": entry.get("applied"),
            "files": [c.get("to") for c in entry.get("changes", [])],
        })
    return out