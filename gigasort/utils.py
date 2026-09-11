"""GigaSort shared utilities.

Merged from the former utils/fs.py + utils/io.py + utils/format.py for a
cleaner module tree.  Three concerns live here:

    guarded_move / guard_under / classify_risk / enforce  (workspace safety)
    json_load / json_dump                                 (atomic persistence)
    human_size                                            (formatting)
"""

import json
import os
import shutil
import tempfile

from gigasort.constants import RISK_ALLOW, RISK_WARN, RISK_BLOCK

# ── Workspace safety guards ────────────────────────────────────────────────


class GuardError(RuntimeError):
    """Raised when a BLOCK-tier or refused action is attempted."""


def _is_inside(root_abs, path_abs):
    if root_abs == path_abs:
        return True
    return path_abs.startswith(root_abs + os.sep)


def _boundary_abs(root, path):
    return os.path.realpath(root), os.path.realpath(path)


def guard_under(root, path):
    root_abs, path_abs = _boundary_abs(root, path)
    c1 = _is_inside(root_abs, path_abs)
    c2 = _is_inside(os.path.normpath(root_abs), os.path.normpath(path_abs))
    if not (c1 and c2):
        raise GuardError(
            "Refusing: path escapes the assigned workspace.\n"
            "  root=%s\n  path=%s" % (root, path))
    return root_abs


def classify_risk(root, path, action="modify", strict=False):
    root_abs, path_abs = _boundary_abs(root, path)
    inside = (_is_inside(root_abs, path_abs)
              and _is_inside(os.path.normpath(root_abs),
                             os.path.normpath(path_abs)))
    if not inside:
        return RISK_BLOCK, "outside workspace"
    if action in ("delete", "overwrite", "remove"):
        if strict:
            return RISK_BLOCK, "refused in --strict (WARN-tier action)"
        return RISK_WARN, "destructive action: %s" % action
    return RISK_ALLOW, "ok"


def _double_verify(reason, path, input_fn=input):
    try:
        a = input_fn("%s\n  Continue? [y/N] " % reason).strip().lower()
        if a not in ("y", "yes"):
            return False
        b = input_fn("  Type the literal word 'confirm' to proceed: ").strip()
        return b == "confirm"
    except (EOFError, KeyboardInterrupt):
        return False


def enforce(root, action, *paths, strict=False, confirm=None, input_fn=input):
    for p in paths:
        tier, reason = classify_risk(root, p, action, strict=strict)
        if tier == RISK_BLOCK:
            raise GuardError("BLOCKED (%s): %s" % (reason, p))
        if tier == RISK_WARN:
            if confirm is None:
                if strict:
                    raise GuardError("BLOCKED (--strict): %s" % reason)
                if not _double_verify(reason, p, input_fn=input_fn):
                    raise GuardError("Refused: %s (%s)" % (reason, p))
            else:
                if not confirm(reason, p):
                    raise GuardError("Refused: %s (%s)" % (reason, p))


def guarded_move(root, src, dst, action="move", strict=False, dry_run=False,
                 input_fn=input, record_fn=None):
    guard_under(root, src)
    guard_under(root, dst)
    if os.path.exists(dst) and os.path.abspath(dst) != os.path.abspath(src):
        enforce(root, "overwrite", dst, strict=strict, input_fn=input_fn)
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    if dry_run:
        if record_fn:
            record_fn(src, dst)
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    if record_fn:
        record_fn(src, dst)


def guarded_makedirs(root, path, strict=False, input_fn=input):
    guard_under(root, path)
    os.makedirs(path, exist_ok=True)


# ── Atomic JSON persistence ────────────────────────────────────────────────


def _atomic_write_text(path, text):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def json_load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def json_dump(path, data):
    _atomic_write_text(path, json.dumps(data, indent=2))


# ── Formatting ─────────────────────────────────────────────────────────────


def human_size(n):
    """Human-readable file size (bytes -> B/K/M/G/T)."""
    n = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fT" % n
