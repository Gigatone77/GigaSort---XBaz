"""Nexus-based verification and dependency checking.

verify_allowlist() is the safety gate that enforces the "never touch what is
not web-verified as a Cyberpunk 2077 mod" rule: only files whose Nexus mod ID
resolves to a real CP2077 page (or that are already held APPROVED in the
verified cache) may be moved. Everything else is flagged so the caller leaves
it alone.
"""

import re

from gigasort.constants import (
    APPROVED, MISMATCH, UNVERIFIED, NOMODID, AUTO, NEXUS_CAT_MAP,
)
from gigasort.utils import net
from gigasort.core.categorize import categorize, extract_mod_id


def build_allowlist(keep, cache=None, progress=None):
    """Return two sets of filenames over the `keep` candidates:
      (verified, flagged)

    A filename is `verified` (safe to move) ONLY if:
      - it already carries APPROVED in the local verified cache, OR
      - its Nexus mod ID resolves to a real Cyberpunk 2077 page online.

    A filename is `flagged` if it is not verified — it must NOT be moved,
    deleted, or otherwise touched by the sort.
    """
    verified, flagged = set(), set()
    cache = cache or {}
    for fn, _size in keep:
        entry = cache.get(fn)
        if entry and entry.get("status") == APPROVED:
            verified.add(fn)
            continue
        mod_id = extract_mod_id(fn)
        if mod_id and net.verified_nexus_title(mod_id):
            verified.add(fn)
            cache[fn] = {
                "status": APPROVED,
                "category": categorize(fn),
                "nexus_title": net.verified_nexus_title(mod_id),
                "nexus_cat": None,
            }
        else:
            flagged.add(fn)
        if progress:
            progress(fn)
    return verified, flagged


def verification_statuses(folder, kept, progress=None):
    """Per-file verification origin, using the same gate as the sort.

    Returns {filename: status} where status is one of:
      'offline'    - already APPROVED in the local verified cache (no Net).
      'online'     - resolved live against Nexus just now.
      'unverified' - neither; never touched by the sort.

    Mirrors build_allowlist() but records *why* each file passed, so the UI can
    show an offline vs online indicator. Newly online-verified hits are cached
    for future offline confirmation, exactly as the sort's gate does.
    """
    from gigasort.core import storage

    cache = storage.load_cache(folder)
    already = {
        fn for fn, e in cache.items()
        if e and e.get("status") == APPROVED
    }
    statuses = {}
    for fn, _size in kept:
        entry = cache.get(fn)
        if entry and entry.get("status") == APPROVED:
            statuses[fn] = "offline" if fn in already else "online"
            continue
        mod_id = extract_mod_id(fn)
        title = net.verified_nexus_title(mod_id) if mod_id else None
        if title:
            statuses[fn] = "online"
            cache[fn] = {
                "status": APPROVED,
                "category": categorize(fn),
                "nexus_title": title,
                "nexus_cat": None,
            }
        else:
            statuses[fn] = "unverified"
        if progress:
            progress(fn)
    if cache:
        storage.save_cache(folder, cache)
    return statuses


def verify_categories(keep, cache, rejects=()):
    """Cross-reference each archive against its Nexus page.

    keep: list of (filename, size) to verify. Returns
      dict filename -> (our_cat, nexus_title, nexus_cat, status)
    Cache-first: already approved + matching files are not re-fetched.
    """
    from gigasort.core.categorize import categorize as _cat

    verify = {}
    for fn, _size in keep:
        our = _cat(fn)
        mod_id = extract_mod_id(fn)
        entry = (cache or {}).get(fn)
        if entry and entry.get("status") == APPROVED and entry.get("category") == our:
            verify[fn] = (our, entry.get("nexus_title"),
                          entry.get("nexus_cat"), APPROVED)
            continue
        if not mod_id:
            verify[fn] = (our or "?", None, None, NOMODID)
            continue
        title, ncat = net.lookup_nexus_category(mod_id)
        if title is None:
            verify[fn] = (our or "?", None, None, UNVERIFIED)
            continue
        mapped = NEXUS_CAT_MAP.get(ncat)
        if our and mapped and mapped == our:
            status = APPROVED
        elif our is None and mapped:
            status = AUTO
            our = mapped
        elif our and mapped and mapped != our:
            status = MISMATCH
        else:
            status = APPROVED if our else UNVERIFIED
        verify[fn] = (our, title, ncat, status)

    # Rejects get looked up too; if Nexus gives a category, mark AUTO.
    for fn, _size in rejects:
        mod_id = extract_mod_id(fn)
        if not mod_id:
            continue
        title, ncat = net.lookup_nexus_category(mod_id)
        if not ncat:
            continue
        mapped = NEXUS_CAT_MAP.get(ncat)
        if mapped:
            verify[fn] = (mapped, title, ncat, AUTO)
    return verify


def check_dependencies(folder, keep, dry_run):
    """Check each keep-archive's Nexus page for required mods and flag any
    dependency you don't appear to have. Read-only; nothing is downloaded."""
    from gigasort.utils import net
    from gigasort.utils.net import parse_required_deps

    have = set()
    for fn, _ in keep:
        mid = extract_mod_id(fn)
        if mid:
            have.add(mid)
    missing_any = False
    for fn, _ in keep:
        mid = extract_mod_id(fn)
        if not mid:
            continue
        html = net.fetch(net.nexus_page(mid))
        if not html:
            continue
        deps, _found = parse_required_deps(html)
        need = [did for _game, did in deps if did not in have]
        if need:
            print("  %s  needs: %s" % (fn, ", ".join(need)))
            missing_any = True
    return missing_any
