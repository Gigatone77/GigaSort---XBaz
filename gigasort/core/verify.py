"""Nexus-based verification and dependency checking.

verify_allowlist() is the safety gate that enforces the "never touch what is
not web-verified as a Cyberpunk 2077 mod" rule: only files whose Nexus mod ID
resolves to a real CP2077 page (or that are already held APPROVED in the
verified cache) may be moved. Everything else is flagged so the caller leaves
it alone.
"""

import os
import re

from gigasort.constants import (
    APPROVED, MISMATCH, UNVERIFIED, NOMODID, AUTO, NEXUS_CAT_MAP,
    KNOWN_FOLDERS,
)
from gigasort.utils import net
from gigasort.core.categorize import categorize, extract_mod_id, candidate_mod_id


def _folder_for(ncat):
    """Normalize a Nexus category value to one of GigaSort's real folders.

    Accepts both a slug ('weapons') and an already-mapped folder name
    ('06 Weapons & Misc Items'); returns None for anything unrecognized.
    """
    if not isinstance(ncat, str):
        return None
    if ncat in KNOWN_FOLDERS:
        return ncat
    return NEXUS_CAT_MAP.get(ncat)


def _struct_confirmed(folder, filename, mod_id=None):
    """True if the archive at `folder/filename` carries a Nexus mod id (from
    the filename, loose CCXL bare-number match, or the archive's readme) AND
    its internal layout is a strong Cyberpunk 2077 signature. Internet-free."""
    if not (candidate_mod_id(filename) or mod_id):
        return False
    from gigasort.core import compat
    return compat.is_cp2077_mod_file(
        filename, os.path.join(folder, filename), mod_id=mod_id)


def _approve(cache, fn, source):
    """Record an offline-confirmed file in the verified cache.

    `source` explains how it was confirmed (e.g. 'offline-structure') so the
    cache and log remain transparent about why a file was approved without a
    live Nexus hit.
    """
    cache[fn] = {
        "status": APPROVED,
        "category": categorize(fn),
        "nexus_title": None,
        "nexus_cat": None,
        "source": source,
    }


def _struct_ok(folder, fn):
    """Best-effort bool/None describing whether `folder/fn` is a CP2077 game
    layout (True), a non-CP2077 layout (False -> 'Unstructured'), or unknown /
    off-disk (None). Never raises."""
    if not folder:
        return None
    try:
        from gigasort.core import compat
        return compat.cp2077_structure_match(fn, os.path.join(folder, fn))
    except Exception:
        return None


def build_allowlist(keep, cache=None, progress=None, folder=None):
    """Return two sets of filenames over the `keep` candidates:
      (verified, flagged)

    A filename is `verified` (safe to move) ONLY if:
      - it already carries APPROVED in the local verified cache, OR
      - its Nexus mod ID is already in the mod-ID REFERENCE cache (a page
        verified on a previous run), OR
      - its Nexus mod ID resolves to a real Cyberpunk 2077 page online, OR
      - (offline) its Nexus mod ID is present AND the archive's internal
        structure is a strong Cyberpunk 2077 signature.

    A filename is `flagged` if it is not verified — it must NOT be moved,
    deleted, or otherwise touched by the sort.

    Successful live lookups are written back to the reference cache, keyed by
    mod ID, so every OTHER file on the same Nexus page (optional builds, old
    versions, re-downloads) resolves instantly on the next sort without
    another network call.
    """
    verified, flagged = set(), set()
    cache = cache or {}
    refs = {}
    if folder:
        from gigasort.core import storage
        try:
            refs = storage.load_references(folder) or {}
        except Exception:
            refs = {}
    refs_dirty = False

    # Connectivity probe: a single failed probe must NOT permanently disable
    # live lookups for the whole batch (one hiccup != offline). We only use it
    # to avoid a 15s urllib timeout PER FILE when the network is genuinely
    # down: if the probe fails we still try ONE live lookup; only when that
    # also yields nothing do we treat the run as offline.
    online_ok = True
    probe_done = False

    def _maybe_probe():
        nonlocal online_ok, probe_done
        if net.ALLOW_NET and not probe_done:
            online_ok = net.check_connectivity()
            probe_done = True

    from gigasort.core import compat
    for fn, _size in keep:
        entry = cache.get(fn)
        if entry and entry.get("status") == APPROVED:
            verified.add(fn)
            if progress:
                progress(fn)
            continue
        mod_id = extract_mod_id(fn)
        if not mod_id and folder:
            # Filename carries no usable Nexus id: try the archive's own
            # readme/description text (nexusmods URL or 'Mod ID:' line).
            try:
                mod_id = compat.readme_mod_id(
                    os.path.join(folder, fn), filename=fn)
            except Exception:
                mod_id = None
        if not mod_id and folder and candidate_mod_id(fn):
            # Even without a '-NNN-' token, a CCXL/bare-number id in the name
            # plus a strong CP2077 archive interior is proof enough of a real
            # Cyberpunk 2077 mod. Without this check a perfectly good CCXL
            # download (e.g. the Judy quest rar) would be flagged as
            # unverified purely because it lacks the classic '-id-' token.
            try:
                if compat.is_cp2077_mod_file(fn, os.path.join(folder, fn)):
                    verified.add(fn)
                    _approve(cache, fn, "offline-structure")
                    cache[fn]["struct_ok"] = True
                    if progress:
                        progress(fn)
                    continue
            except Exception:
                pass
        if not mod_id:
            flagged.add(fn)
            if progress:
                progress(fn)
            continue

        # Aggressive all-methods check before anything is decided: the mod-ID
        # reference cache first (fastest - verified on a previous run), then
        # the live Nexus page (title-based verify, then category-based), then
        # the offline CP2077-archive signature. A file is ONLY flagged as
        # unverified when every method has been exhausted.
        title, ncat = None, None
        from_ref = refs.get(mod_id) or {}
        if from_ref.get("verified"):
            title = from_ref.get("title")
            ncat = from_ref.get("category")
        elif net.ALLOW_NET:
            _maybe_probe()
            # If the probe failed we still try live lookups, but bound the
            # per-file timeout so a genuinely dead network doesn't stall the
            # whole batch at 15s per file. One hiccup must not skip lookups.
            to = 15 if online_ok else 6
            # Primary live path: one fetch that BOTH proves the page is a real
            # CP2077 mod (strict '<Name> at Cyberpunk 2077 Nexus' title) AND
            # captures the author-set Nexus category from the breadcrumb.
            title, ncat = net.lookup_nexus_category(mod_id, timeout=to)
            if not title:
                # Title-only fallback when lookup's strict gating refused the
                # page (e.g. category-less render); still authoritative.
                title = net.verified_nexus_title(mod_id, timeout=to)
            if title:
                # Cache the verified page by mod ID for future sorts.
                refs[mod_id] = {"verified": True, "title": title,
                                "category": ncat}
                refs_dirty = True
        if title:
            verified.add(fn)
            cache[fn] = {
                "status": APPROVED,
                "category": categorize(fn),
                "nexus_title": title,
                "nexus_cat": ncat,
            }
            # Record whether the archive interior is a CP2077 game layout, so
            # the verification tags can flag 'Unstructured' (online mod whose
            # zip is NOT a game-path structure -> manual handling needed).
            cache[fn]["struct_ok"] = _struct_ok(folder, fn)
        elif folder and (candidate_mod_id(fn) or mod_id) and compat.is_cp2077_mod_file(
                fn, os.path.join(folder, fn), mod_id=mod_id):
            # Offline structural confirmation: the filename (or its readme)
            # carries a Nexus mod id AND the archive index shows CP2077-only
            # paths/types.
            verified.add(fn)
            _approve(cache, fn, "offline-structure")
            cache[fn]["struct_ok"] = True
        else:
            flagged.add(fn)
        if progress:
            progress(fn)

    # Persist the mod-ID references only when the cache changed; keep the file
    # untouched on pure filename-cache hits so re-sorts don't rewrite state.
    if refs_dirty and folder:
        try:
            from gigasort.core import storage
            storage.save_references(folder, refs)
        except Exception:
            pass
    return verified, flagged


def verification_statuses(folder, kept, progress=None):
    """Per-file verification origin, using the same gate as the sort.

    Returns (statuses, structs) where:
      statuses {filename: status} with:
        'offline'         - already APPROVED in the local verified cache.
        'offline-structure' - confirmed offline from the archive's CP2077 layout.
        'online'          - resolved live against Nexus just now.
        'unverified'      - neither; never touched by the sort.
      structs  {filename: True|False|None} — whether the archive's interior is
        a CP2077 game layout (False -> 'Unstructured', needs manual handling).

    Mirrors build_allowlist() but records *why* each file passed, so the UI can
    show an offline vs online indicator. Newly confirmed hits are cached for
    future offline confirmation, exactly as the sort's gate does.
    """
    from gigasort.core import storage

    cache = storage.load_cache(folder)
    refs = storage.load_references(folder) or {}
    refs_dirty = False
    already = {
        fn for fn, e in cache.items()
        if e and e.get("status") == APPROVED
    }
    # Same bounded-probe policy as build_allowlist(): a failed probe never
    # disables live lookups, it only cuts the per-file timeout when the
    # network looks genuinely dead.
    online_ok = True
    probe_done = False

    def _maybe_probe():
        nonlocal online_ok, probe_done
        if net.ALLOW_NET and not probe_done:
            online_ok = net.check_connectivity()
            probe_done = True

    statuses = {}
    structs = {}
    for fn, _size in kept:
        entry = cache.get(fn)
        if entry and entry.get("status") == APPROVED:
            statuses[fn] = "offline" if fn in already else "online"
            if "struct_ok" in entry:
                structs[fn] = entry["struct_ok"]
            continue
        mod_id = extract_mod_id(fn)
        if not mod_id and folder:
            try:
                mod_id = compat.readme_mod_id(
                    os.path.join(folder, fn), filename=fn)
            except Exception:
                mod_id = None
        title = ncat = None
        from_ref = (refs.get(mod_id) or {}) if mod_id else {}
        if from_ref.get("verified"):
            # Mod page already confirmed on a previous run: no network needed.
            title = from_ref.get("title")
            ncat = from_ref.get("category")
        elif mod_id and net.ALLOW_NET:
            _maybe_probe()
            to = 15 if online_ok else 6
            # Primary live path captures the author-set Nexus category from the
            # breadcrumb in the SAME fetch that proves the page.
            title, ncat = net.lookup_nexus_category(mod_id, timeout=to)
            if not title:
                title = net.verified_nexus_title(mod_id, timeout=to)
            if title:
                refs[mod_id] = {"verified": True, "title": title,
                                "category": ncat}
                refs_dirty = True
        if title:
            statuses[fn] = "offline" if from_ref.get("verified") else "online"
            cache[fn] = {
                "status": APPROVED,
                "category": categorize(fn),
                "nexus_title": title,
                "nexus_cat": ncat,
            }
            # Same as build_allowlist(): even a live-verified file's archive
            # interior is checked, so 'Unstructured' (non-CP2077 layout) can
            # still be flagged for manual handling.
            cache[fn]["struct_ok"] = _struct_ok(folder, fn)
            structs[fn] = cache[fn]["struct_ok"]
        elif _struct_confirmed(folder, fn, mod_id=mod_id):
            # Offline structural confirmation (same gate as the sort).
            statuses[fn] = "offline-structure"
            cache[fn] = {
                "status": APPROVED,
                "category": categorize(fn),
                "nexus_title": None,
                "nexus_cat": None,
                "source": "offline-structure",
                "struct_ok": True,
            }
            structs[fn] = True
        else:
            statuses[fn] = "unverified"
        if progress:
            progress(fn)
    if cache:
        storage.save_cache(folder, cache)
    if refs_dirty:
        storage.save_references(folder, refs)
    return statuses, structs


def verify_categories(keep, cache, rejects=(), folder=None):
    """Cross-reference each archive against its Nexus page.

    keep: list of (filename, size) to verify. Returns
      dict filename -> (our_cat, nexus_title, nexus_cat, status)
    Cache-first: already approved + matching files are not re-fetched; the
    mod-ID reference cache (when `folder` is given) short-circuits repeat
    lookups of an already-known page.
    """
    from gigasort.core.categorize import categorize as _cat

    refs = {}
    refs_dirty = False
    if folder:
        from gigasort.core import storage as _st
        try:
            refs = _st.load_references(folder) or {}
        except Exception:
            refs = {}

    def _page(mod_id):
        """Return (title, ncat) for `mod_id`, from refs first then live."""
        nonlocal refs_dirty
        ref = refs.get(mod_id)
        if ref and ref.get("verified"):
            return ref.get("title"), ref.get("category")
        title, ncat = net.lookup_nexus_category(mod_id)
        if title and mod_id not in refs:
            refs[mod_id] = {"verified": True, "title": title,
                            "category": ncat}
            refs_dirty = True
        return title, ncat

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
        title, ncat = _page(mod_id)
        if title is None:
            verify[fn] = (our or "?", None, None, UNVERIFIED)
            continue
        mapped = _folder_for(ncat)
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
        title, ncat = _page(mod_id)
        if not ncat:
            continue
        mapped = _folder_for(ncat)
        if mapped:
            verify[fn] = (mapped, title, ncat, AUTO)

    if folder and refs_dirty:
        try:
            from gigasort.core import storage as _st
            _st.save_references(folder, refs)
        except Exception:
            pass
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


def fetch_dependencies(folder, fn_list, progress=None):
    """Fetch and cache each mod's Nexus Requirements ids (best-effort).

    Reads the existing verified cache first; only mods without a cached
    'deps' list are fetched. Deps are stored per filename AND shared via the
    mod-ID reference cache, so other files of the same mod page (new versions,
    optional builds) need no repeated lookups. Returns the updated cache.
    Never writes user data - cache only.
    """
    from gigasort.utils import net
    from gigasort.utils.net import parse_required_deps
    from gigasort.core import storage

    cache = storage.load_cache(folder)
    refs = storage.load_references(folder) or {}
    refs_dirty = False
    changed = False
    for fn, _size in fn_list:
        mid = extract_mod_id(fn)
        if not mid:
            continue
        ref = refs.setdefault(mid, {})
        ref_deps = ref.get("deps") or []
        if ref_deps:
            cache.setdefault(fn, {})["deps"] = ref_deps
            if progress:
                progress(fn)
            continue
        entry = cache.get(fn) or {}
        if entry.get("deps"):
            refs[mid]["deps"] = entry["deps"]
            refs_dirty = True
            continue
        html = net.fetch(net.nexus_page(mid))
        if not html:
            continue
        deps, _found = parse_required_deps(html)
        if deps:
            refs[mid]["deps"] = deps
            refs_dirty = True
        cache.setdefault(fn, {}).setdefault("deps", [])[:] = deps
        changed = True
        if progress:
            progress(fn)
    if changed:
        storage.save_cache(folder, cache)
    if refs_dirty:
        try:
            storage.save_references(folder, refs)
        except Exception:
            pass
    return cache
