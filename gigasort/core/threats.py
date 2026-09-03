"""Nexus-identity reputation gate (--gate)."""

import os

from gigasort.constants import (
    TRUSTED, ON_HOLD, WATCHED, NOMODID, SUSPICIOUS_KEYWORDS, HOLD_BIN,
)
from gigasort.core import storage
from gigasort.core.categorize import extract_mod_id


def load_threats(folder):
    return storage.load_threats(folder)


def _identity_ok(fn, mod_id, cache):
    """Best-effort Nexus identity check (offline-first): is this file a known
    good mod page? We trust the local approved cache as the identity source;
    live lookups are done by --verify."""
    entry = (cache or {}).get(fn)
    if entry and entry.get("status") == "approved":
        return True, "approved in local cache"
    if not mod_id:
        return False, "no Nexus mod id in filename"
    return True, "mod id present (live identity via --verify)"


def assess_threat(fn, mod_id, identity_ok, threats):
    """Return (verdict, reason) for one file."""
    low = fn.lower()
    # watched by user watchlist id?
    ids = (threats or {}).get("ids", []) or []
    if mod_id and mod_id in ids:
        return WATCHED, "mod id %s is on your threat watchlist" % mod_id
    reasons = (threats or {}).get("reasons", {}) or {}
    if mod_id and reasons.get(mod_id):
        return WATCHED, reasons[mod_id]
    # suspicious keywords
    for kw in SUSPICIOUS_KEYWORDS:
        if kw in low:
            return WATCHED, "filename contains '%s'" % kw
    if not identity_ok[0]:
        return ON_HOLD, identity_ok[1]
    return TRUSTED, "identity satisfied"


def run_threat_gate(folder, keep, cache):
    """Return dict filename -> (verdict, reason) for the keep files."""
    threats = load_threats(folder)
    out = {}
    for fn, _size in keep:
        mod_id = extract_mod_id(fn)
        identity = _identity_ok(fn, mod_id, cache)
        out[fn] = assess_threat(fn, mod_id, identity, threats)
    return out


def withheld_paths(folder):
    """Return the _ON_HOLD folder (created lazily by callers)."""
    return os.path.join(folder, HOLD_BIN)
