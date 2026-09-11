"""Agent bridge — minimal JSON-RPC over the workspace for external agents."""

import os

from gigasort.core import storage, tags as tags_mod
from gigasort.core.verify import build_verified_gate

OPS = ("info", "batch-sort", "move", "tags")


def _bridge(folder):
    d = os.path.join(storage.state_dir(folder), "bridge")
    os.makedirs(d, exist_ok=True)
    return d


def handle(folder, op, payload=None, origin=""):
    """Handle one agent op. Returns a JSON-serializable result dict.

    origins: "opencode" | "local" | "" (agent.py) — retained in the log."""
    payload = payload or {}
    if op not in OPS:
        return {"error": "unknown op %r" % op}

    if op == "info":
        settings = storage.load_settings(folder)
        return {
            "workspace": os.path.abspath(folder),
            "game_dir": settings.get("game_dir") or "",
            "state_dir": storage.state_dir(folder),
            "state_files": sorted(
                n for n in os.listdir(storage.state_dir(folder))
                if n.startswith("_GigaSort")
            ),
            "origin": origin,
        }

    if op == "batch-sort":
        from gigasort.core.engine import run_batch_sort
        dry_run = bool(payload.get("dry_run", True))
        results, _ = run_batch_sort(folder, dry_run=dry_run,
                                    move=not dry_run)
        summary = [{"workspace": r.folder,
                    "kept": len(r.kept), "rejects": len(r.rejects),
                    "duplicates": len(r.duplicates)}
                   for r in results]
        return {"dry_run": dry_run, "results": summary, "origin": origin}

    if op == "move":
        target = payload.get("path")
        dest = payload.get("dest")
        if not target or not dest:
            return {"error": "move requires path and dest"}
        src = os.path.abspath(os.path.join(folder, target))
        dst = os.path.abspath(os.path.join(folder, dest))
        if not os.path.realpath(src).startswith(os.path.realpath(folder)) or \
                not os.path.realpath(dst).startswith(os.path.realpath(folder)):
            return {"error": "move outside workspace"}
        if os.path.basename(src) not in build_verified_gate(folder, [target]):
            return {"error": "unverified file — refused"}
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.replace(src, dst)
        except OSError as exc:
            return {"error": str(exc)}
        return {"moved": True, "to": dest, "origin": origin}

    if op == "tags":
        name = payload.get("file")
        action = payload.get("action", "add")
        value = payload.get("tags") or []
        if not name:
            return {"error": "tags requires file"}
        if action == "add":
            tags_mod.tag_file(folder, name, *value)
        elif action == "remove":
            tags_mod.untag_file(folder, name, *value)
        else:
            return {"error": "unknown action %r" % action}
        return {"file": name, "tags": tags_mod.file_tags(folder, name),
                "origin": origin}

    return {"error": "unreachable"}