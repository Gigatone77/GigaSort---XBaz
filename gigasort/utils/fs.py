"""Filesystem safety guards.

The security core of GigaSort. Every move/copy/delete/makedirs goes through
these guards so nothing can ever escape the workspace it was assigned, and
destructive actions are always confirmed.

State: rather than module globals, guards take an explicit `root` (the
workspace fence) and a `strict` flag so each caller passes its own context.
"""

import os
import shutil

from gigasort.constants import (
    RISK_ALLOW, RISK_WARN, RISK_BLOCK,
)


class GuardError(RuntimeError):
    """Raised when a BLOCK-tier or refused action is attempted."""


def _is_inside(root_abs, path_abs):
    """True if path_abs is equal to root_abs or below it."""
    if root_abs == path_abs:
        return True
    return path_abs.startswith(root_abs + os.sep)


def _boundary_abs(root, path):
    """Return (root_abs, path_abs) both fully resolved, for comparison."""
    root_abs = os.path.realpath(root)
    path_abs = os.path.realpath(path)
    return root_abs, path_abs


def guard_under(root, path):
    """Return the workspace path, refusing anything that escapes.

    Runs two independent _is_inside checks; if they disagree the action is
    refused conservatively (defeats symlink escapes via realpath).
    """
    root_abs, path_abs = _boundary_abs(root, path)
    check1 = _is_inside(root_abs, path_abs)
    check2 = _is_inside(os.path.normpath(root_abs), os.path.normpath(path_abs))
    if not (check1 and check2):
        raise GuardError(
            "Refusing: path escapes the assigned workspace.\n"
            "  root=%s\n  path=%s" % (root, path))
    return root_abs


def classify_risk(root, path, action="modify", strict=False):
    """Return (tier, reason) for one filesystem action on `path`.

    Tiers:
      RISK_ALLOW  safe in-workspace
      RISK_WARN   potentially irreversible (delete / overwrite) -> confirm
      RISK_BLOCK  outside workspace -> hard refusal always
    """
    root_abs, path_abs = _boundary_abs(root, path)
    inside = _is_inside(root_abs, path_abs) and _is_inside(
        os.path.normpath(root_abs), os.path.normpath(path_abs))
    if not inside:
        return RISK_BLOCK, "outside workspace"

    if action in ("delete", "overwrite", "remove"):
        if strict:
            return RISK_BLOCK, "refused in --strict (WARN-tier action)"
        return RISK_WARN, "destructive action: %s" % action

    return RISK_ALLOW, "ok"


def enforce(root, action, *paths, strict=False, confirm=None, input_fn=input):
    """Route all paths through classify_risk; raise on BLOCK, confirm WARN.

    `confirm(reason, path)` is a callable invoked for WARN-tier actions; if
    None, WARN-tier actions raise GuardError in strict mode or otherwise call
    the default two-step confirmation.
    """
    for p in paths:
        tier, reason = classify_risk(root, p, action, strict=strict)
        if tier == RISK_BLOCK:
            raise GuardError("BLOCKED (%s): %s" % (reason, p))
        if tier == RISK_WARN:
            if confirm is None:
                if strict:
                    raise GuardError("BLOCKED (--strict): %s" % reason)
                yes = _double_verify(reason, p, input_fn=input_fn)
                if not yes:
                    raise GuardError("Refused: %s (%s)" % (reason, p))
            else:
                ok = confirm(reason, p)
                if not ok:
                    raise GuardError("Refused: %s (%s)" % (reason, p))


def _double_verify(reason, path, input_fn=input):
    """Two-step confirmation: y/n, then the literal word 'confirm'."""
    try:
        a = input_fn("%s\n  Continue? [y/N] " % reason).strip().lower()
        if a not in ("y", "yes"):
            return False
        b = input_fn("  Type the literal word 'confirm' to proceed: ").strip()
        return b == "confirm"
    except (EOFError, KeyboardInterrupt):
        return False


def guarded_move(root, src, dst, action="move", strict=False, dry_run=False,
                 input_fn=input, record_fn=None):
    """Move src -> dst under the workspace fence.

    If record_fn is provided it is called with (src, dst) after a successful
    (non-dry-run) move so the caller can append to the undo manifest.
    """
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


def guarded_remove(root, path, action="delete", confirmed=False, strict=False,
                   input_fn=input):
    """Delete a file/path under the workspace fence.

    `confirmed=True` skips the WARN prompt (only for ops with their own prior
    confirmation). The BLOCK boundary check is never bypassed.
    """
    guard_under(root, path)
    if os.path.isdir(path):
        action = "remove"
    if not confirmed:
        enforce(root, action, path, strict=strict, input_fn=input_fn)
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def guarded_makedirs(root, path, strict=False, input_fn=input):
    """Create a directory tree under the workspace fence."""
    guard_under(root, path)
    os.makedirs(path, exist_ok=True)
