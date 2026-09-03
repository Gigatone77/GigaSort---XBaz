"""Agent bridge (--agent): a read-only-by-design communication channel with a
LOCAL opencode agent. Remote/cloud agents and third-party MCP servers are
refused.

The bridge (workspace/_GigaSort_bridge/) is the ONLY exchange surface. The
agent writes request.json; GigaSort validates every op against the safety
guards and writes result.json. Supported ops: info, batch-sort, move, tags.
"""

import json
import os
import sys

from gigasort.constants import BRIDGE_DIR
from gigasort.core import storage, sort, tags as tags_mod
from gigasort.core.categorize import categorize, clean_name
from gigasort.utils import fs


def bridge_root(folder):
    return os.path.join(folder, BRIDGE_DIR)


def _allowed_origins():
    return ("opencode", "local", "")


def execute_agent_request(folder, req_file):
    """Read request.json, validate origin, execute the op, write result.json.
    Returns a process exit code."""
    root = bridge_root(folder)
    os.makedirs(root, exist_ok=True)
    try:
        with open(req_file, "r", encoding="utf-8") as fh:
            req = json.load(fh)
        if not isinstance(req, dict):
            raise ValueError("request must be a JSON object")
    except (OSError, ValueError) as e:
        _write_result(root, {"ok": False, "op": "?", "error": "bad request: %s" % e})
        return 1

    origin = (req.get("origin") or "").strip().lower()
    if origin not in _allowed_origins():
        msg = "Refused: only local agents / opencode may pair with GigaSort"
        _write_result(root, {"ok": False, "op": req.get("op"), "error": msg})
        return 1

    op = req.get("op")
    dry = bool(req.get("dry_run", False))

    if op == "info":
        result = sort.scan_workspace(folder)
        _write_result(root, {
            "ok": True, "op": op, "totals": {
                "archives": len(result.kept) + len(result.duplicates),
                "kept": len(result.kept),
                "duplicates": len(result.duplicates),
                "rejects": len(result.rejects),
            },
            "rejects": [fn for fn, _ in result.rejects],
        })
        return 0

    if op == "batch-sort":
        try:
            summary = sort.run_batch_sort(folder, dry_run=dry)
            _write_result(root, {"ok": True, "op": op, "dry_run": dry, **summary})
            return 0
        except Exception as e:
            _write_result(root, {"ok": False, "op": op, "error": str(e)})
            return 1

    if op == "move":
        name = req.get("name")
        category = req.get("category")
        if not name or not category:
            _write_result(root, {"ok": False, "op": op,
                                 "error": "move needs 'name' and 'category'"})
            return 1
        # SAFETY: never move anything not web-verified as a CP2077 mod.
        from gigasort.core.sort import build_verified_gate
        verified, _flagged = build_verified_gate(folder, [(name, 0)])
        if name not in verified:
            _write_result(root, {"ok": False, "op": op,
                                 "error": "refusing to move unverified file "
                                          "(not confirmed as a Cyberpunk 2077 mod)"})
            return 1
        src = os.path.join(folder, clean_name(name))
        dst = os.path.join(folder, category, clean_name(name))
        try:
            fs.guarded_move(folder, src, dst, dry_run=dry)
            storage.record_move(folder, src, dst, dry)
            _write_result(root, {"ok": True, "op": op, "dry_run": dry,
                                 "src": src, "dst": dst})
            return 0
        except Exception as e:
            _write_result(root, {"ok": False, "op": op, "error": str(e)})
            return 1

    if op == "tags":
        count = tags_mod.write_tags(folder)
        _write_result(root, {"ok": True, "op": op, "count": count})
        return 0

    _write_result(root, {"ok": False, "op": op, "error": "unknown op"})
    return 1


def _write_result(root, data):
    path = os.path.join(root, "result.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
