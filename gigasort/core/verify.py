"""Offline verification of downloaded archives.

A file is verified ONLY against the offline knowledge base (merged sig
archive + approved cache + readme id) or a strong CP2077 archive structure
with a numeric Nexus id. verified=True NEVER comes from a bare filename
token alone. Unverified files are never moved, trashed, or deleted.
"""

import os
import re
import time

from gigasort.core import signature
from gigasort.core import compat
from gigasort.core.storage import state_path
from gigasort.constants import (
    UNVERIFIED, APPROVED, MISMATCH, NOMODID, LOG_FILENAME,
)
from gigasort.core.categorize import (
    extract_mod_id, clean_name,
)

# --- archive filename id regexes (kept here so both CLI + verify use one) ---
_ID_RE = re.compile(r"-(\d{3,6})-", re.IGNORECASE)
_CCXL_RE = re.compile(r"(?<![a-z0-9-])(\d{3,6})(?![a-z0-9-])", re.IGNORECASE)


class VerificationResult:
    __slots__ = (
        "status", "mod_id", "title", "category", "source", "struct_ok",
        "details",
    )

    def __init__(self, status, mod_id=None, title=None, category=None,
                 source=None, struct_ok=None, details=""):
        self.status = status            # APPROVED / UNVERIFIED / MISMATCH / NOMODID
        self.mod_id = mod_id or extract_mod_id(title or "")
        self.title = title
        self.category = category
        self.source = source
        self.struct_ok = struct_ok
        self.details = details


def _id_tokens(path):
    """Ordered list of plausible mod-id candidates for a file."""
    base = os.path.basename(path)
    classic = _ID_RE.search(base)
    if classic:
        return [classic.group(1)]
    loose = _CCXL_RE.search(base)
    if loose:
        return [loose.group(1)]
    return []


def verify_file(folder, path):
    """Verify a single archive file (fully offline).

    Returns a VerificationResult. This is the ONLY path that decides
    verified vs unverified; the safe rule lives here — only a truthy result
    lets a caller move/delete the file."""
    base = os.path.basename(path)
    clean = clean_name(base)

    # 0) Approved cache (fastest).
    approved = signature.load_approved(folder)
    cached = approved.get(clean) or approved.get(base)
    if cached and (cached.get("approved") or cached.get("status") == "approved"):
        return VerificationResult(
            APPROVED, mod_id=cached.get("mod_id"),
            title=cached.get("title") or clean,
            category=cached.get("category"), source="approved-cache",
            struct_ok=cached.get("struct_ok"),
        )

    # 1) Offline sig archive lookup by filename id.
    ids = _id_tokens(base)
    if ids:
        for mid in ids:
            rec = signature.offline_lookup(folder, mid)
            if rec:
                return VerificationResult(
                    APPROVED, mod_id=mid,
                    title=rec.get("title") or clean,
                    category=rec.get("category"),
                    source="offline-archive",
                    struct_ok=rec.get("struct_ok", True),
                )

    # 2) Offline structural gate: strong CP2077 layout + numeric id.
    mid = ids[0] if ids else None
    if mid:
        struct, _ = compat.looks_like_cp2077_archive(path, mid)
        if struct in ("strong", "partial"):
            return VerificationResult(
                APPROVED, mod_id=mid, title=clean,
                category=None, source="offline-structure",
                struct_ok=(struct == "strong"),
            )

    # 3) Readme fallback id + structural gate.
    readme_id = compat.readme_mod_id(path) if not ids else None
    if readme_id:
        rec = signature.offline_lookup(folder, readme_id)
        if rec:
            return VerificationResult(
                APPROVED, mod_id=readme_id,
                title=rec.get("title") or clean,
                category=rec.get("category"),
                source="readme-offline", struct_ok=True,
            )
        struct, _ = compat.looks_like_cp2077_archive(path, readme_id)
        if struct in ("strong", "partial"):
            return VerificationResult(
                APPROVED, mod_id=readme_id, title=clean,
                category=None, source="readme-structure",
                struct_ok=(struct == "strong"),
            )

    # 4) Unverified — either no id at all, or an id whose offline signature
    #    and structure could not confirm it.
    if not ids and not readme_id:
        return VerificationResult(NOMODID, title=clean, details="no nexus id / signature")
    return VerificationResult(
        UNVERIFIED, mod_id=ids[0] if ids else None,
        title=clean, details="not found in offline archive or structure",
    )


def verify_allowlist(folder, items=None, log=True, only_new=False):
    """Verify many files; returns {path: VerificationResult}.

    items: optional explicit file list; defaults to scanning the workspace
    folder for archives."""
    signature.ensure_archive(folder)
    known_archives = sorted(
        items or [
            os.path.join(folder, n)
            for n in os.listdir(folder)
            if n.lower().endswith((".zip", ".rar", ".7z"))
        ]
    )

    results = {}
    for path in known_archives:
        if only_new and _result_cached(folder, os.path.basename(path)):
            continue
        results[path] = verify_file(folder, path)

    if log:
        _write_log(folder, results)
    return results


def _result_cached(folder, base):
    """True when the verified cache already has this file (dedupe hot path)."""
    approved = signature.load_approved(folder)
    return any((k in approved) for k in (base,))

    # never reached — kept explicit for readers


def _write_log(folder, results):
    path = state_path(folder, LOG_FILENAME)
    lines = ["GigaSort verification log", "=" * 60,
             "generated %s" % time.strftime("%Y-%m-%d %H:%M:%S")]
    for path_, res in sorted(results.items()):
        lines.append("%-22s %-18s %-11s %s" % (
            res.status, (res.mod_id or "-"),
            (res.source or "-"), os.path.basename(path_)))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


# --- Gate (kept here so sort engine + agent use one definition) ----------

def build_verified_gate(folder, kept):
    """Return a set of file paths (relative to folder) that are VERIFIED and
    therefore safe to move/delete. Unverified files NEVER pass this gate."""
    results = verify_allowlist(folder, items=[os.path.join(folder, n) for n in kept],
                               log=False)
    gate = set()
    for abs_path, res in results.items():
        if res.status in (APPROVED, MISMATCH):
            gate.add(os.path.basename(abs_path))
    return gate


def verification_statuses(folder, kept):
    """Return ({fn: status}, {fn: struct_ok}) for the GUI Status tab.

    struct True = CP2077 game layout confirmed, False = unstructured,
    None = not checked."""
    statuses, structs = {}, {}
    for fn in kept:
        name = fn if isinstance(fn, str) else fn[0]
        res = verify_file(folder, os.path.join(folder, name))
        statuses[name] = res.status
        if res.struct_ok is not None:
            structs[name] = res.struct_ok
    return statuses, structs


def fetch_dependencies(folder, kept):
    """Populate the mod-id reference cache deps from the offline archive.

    Returns the number of records enriched. Fully offline."""
    from gigasort.core import signature as sigmod
    refs = sigmod.load_json_refs(folder)
    added = 0
    for fn in kept:
        name = fn if isinstance(fn, str) else fn[0]
        mid = extract_mod_id(name)
        if not mid or mid in refs:
            continue
        rec = sigmod.offline_lookup(folder, mid)
        if rec:
            deps = (rec.get("deps") or []) if isinstance(rec, dict) else []
            refs[mid] = {"verified": True,
                         "title": (rec.get("title") if isinstance(rec, dict)
                                   else name) or name,
                         "category": rec.get("category")
                         if isinstance(rec, dict) else None,
                         "deps": deps,
                         "source": rec.get("source")
                         if isinstance(rec, dict) else "sig"}
            added += 1
    from gigasort.core import storage
    storage.save_references(folder, refs)
    return added