"""Offline verification and dependency checking.

verify_allowlist() is the safety gate that enforces the "never touch what is
not verified as a Cyberpunk 2077 mod" rule: only files whose Nexus mod ID is
confirmed by the offline info archive / reference cache (or that are already
held APPROVED in the verified cache) may be moved. Everything else is flagged
so the caller leaves it alone.
"""

import os

from gigasort.constants import (
    APPROVED, MISMATCH, UNVERIFIED, NOMODID, AUTO, NEXUS_CAT_MAP,
    KNOWN_FOLDERS,
)
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
    cache and log remain transparent about why a file was approved without an
    online hit (this build has none).
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
      - its Nexus mod ID is in the mod-ID REFERENCE cache / offline info
        archive (a page confirmed on a previous run or by a bundled seed),
        OR
      - (offline) its Nexus mod ID is present AND the archive's internal
        structure is a strong Cyberpunk 2077 signature.

    A filename is `flagged` if it is not verified — it must NOT be moved,
    deleted, or otherwise touched by the sort.
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
            # The archive interior cannot prove it offline, but the bare
            # number is still a candidate id: the offline info archive may
            # still confirm it (bundled seed / WTNC list / cached ref).
            mod_id = candidate_mod_id(fn)
        if not mod_id:
            flagged.add(fn)
            if progress:
                progress(fn)
            continue

        # Aggressive all-methods check before anything is decided: the mod-ID
        # reference cache first (fastest - verified on a previous run), then
        # the offline info archive / CP2077-archive signature. A file is ONLY
        # flagged as unverified when every method has been exhausted.
        title, ncat = None, None
        from_ref = refs.get(mod_id) or {}
        if from_ref.get("verified"):
            title = from_ref.get("title")
            ncat = from_ref.get("category")
        if title:
            verified.add(fn)
            cache[fn] = {
                "status": APPROVED,
                "category": categorize(fn),
                "nexus_title": title,
                "nexus_cat": ncat,
            }
            # Record whether the archive interior is a CP2077 game layout, so
            # the verification tags can flag 'Unstructured' (verified mod whose
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

    return verified, flagged


def verification_statuses(folder, kept, progress=None):
    """Per-file verification origin, using the same gate as the sort.

    Returns (statuses, structs) where:
      statuses {filename: status} with:
        'offline'           - already in the verified cache / reference cache.
        'offline-structure' - confirmed offline from the archive's CP2077 layout.
        'offline-archive'   - confirmed by the merged offline info archive.
        'unverified'        - neither; never touched by the sort.
      structs  {filename: True|False|None} — whether the archive's interior is
        a CP2077 game layout (False -> 'Unstructured', needs manual handling).

    Mirrors build_allowlist() but records *why* each file passed, so the UI
    can show the offline origin. Newly confirmed hits are cached for future
    offline confirmation, exactly as the sort's gate does.
    """
    from gigasort.core import compat, storage

    cache = storage.load_cache(folder)
    refs = storage.load_references(folder) or {}

    statuses = {}
    structs = {}
    for fn, _size in kept:
        entry = cache.get(fn)
        if entry and entry.get("status") == APPROVED:
            statuses[fn] = "offline"
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
            title = from_ref.get("title")
            ncat = from_ref.get("category")
        if title:
            statuses[fn] = "offline-archive"
            cache[fn] = {
                "status": APPROVED,
                "category": categorize(fn),
                "nexus_title": title,
                "nexus_cat": ncat,
            }
            # Same as build_allowlist(): even a reference-confirmed file's
            # archive interior is checked, so 'Unstructured' (non-CP2077
            # layout) can still be flagged for manual handling.
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
    return statuses, structs


def verify_categories(keep, cache, rejects=(), folder=None):
    """Cross-reference each archive against the offline info sources.

    keep: list of (filename, size) to verify. Returns
      dict filename -> (our_cat, nexus_title, nexus_cat, status)
    Cache-first: already approved + matching files are not re-fetched; the
    mod-ID reference cache (when `folder` is given) short-circuits repeat
    lookups of an already-known page.
    """
    from gigasort.core.categorize import categorize as _cat

    refs = {}
    if folder:
        from gigasort.core import storage as _st
        try:
            refs = _st.load_references(folder) or {}
        except Exception:
            refs = {}

    def _page(mod_id):
        """Return (title, ncat) for `mod_id`, from the offline refs only."""
        ref = refs.get(mod_id)
        if ref and ref.get("verified"):
            return ref.get("title"), ref.get("category")
        return None, None

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

    return verify


def check_dependencies(folder, keep):
    """Check each keep-archive's recorded dependencies and flag any dependency
    you don't appear to have. Read-only; nothing is downloaded.

    The dependency list comes from the offline reference cache (previous
    lookups / bundled seeds). A dependency is counted as satisfied when its
    mod id is already in the download library OR it is one of the
    always-installed CP2077 frameworks (CET/RED4ext/TweakXL/ArchiveXL and
    friends, which live in the game dir rather than the archive shelf).

    Language/translation packs (RU/FR/DE/PT-BR/JP/... add-ons) are excluded:
    they only add translated text and do not block the base mod. Same for
    modding-tool-only entries (WolvenKit) and self-referencing deps. This
    keeps the report focused on genuine runtime gap downloads."""
    from gigasort.constants import MAJOR_FRAMEWORKS
    from gigasort.core import storage

    # always-installed framework ids (game-dir resident, not archive shelf)
    INSTALLED_ALWAYS = MAJOR_FRAMEWORKS | {
        "7780",  # Codeware
        "1511",  # redscript
        "4575",  # Input Loader
        "4885",  # Mod Settings
        "3518",  # Native Settings UI
        "6945",  # Equipment-EX
        "13077",  # Trigger Mode Control
        "7831",  # Deceptious Quest Core
        "790",  # Appearance Menu Mod (AMM)
    }
    _TOOLING = {"2201"}  # WolvenKit is a dev tool, not a runtime mod
    # translation-pack title markers -> those pages only add localized text
    _I18N = ("translation", "translate", "portugu", " russian", "polish",
             "german", "french", "okr ", "ukrain", "spanish", " pt-br",
             "chinese", "simp chinese", "korean", "japanese", " - jp", " - kr",
             "deutsch", "franc", " italian", "turkish", "ru ", " - ru", "_ru",
             " - fr", "fr translation", " - de", " - pt", "brasilian",
             "tradu")

    refs = storage.load_references(folder) or {}
    have = set()
    for fn, _ in keep:
        mid = extract_mod_id(fn)
        if mid:
            have.add(mid)
    present = have | INSTALLED_ALWAYS

    def _is_noise(mid, ref):
        """True when a dependency record should not count as a runtime gap."""
        if mid in present or mid in _TOOLING:
            return True
        title = "".join(
            str(ref.get(k)) or "" for k in ("title", "verified_title", "verified"))
        title_l = title.lower()
        if any(marker in title_l for marker in _I18N):
            return True
        return False

    missing_any = False
    seen = set()
    for fn, _ in keep:
        mid = extract_mod_id(fn)
        if not mid:
            continue
        if mid in seen:
            continue
        seen.add(mid)
        ref = refs.get(mid) or {}
        # cached deps only (fully offline build - live pages are never fetched)
        deps = _normalize_deps(ref.get("deps")) if ref.get("deps") else []
        need = []
        for did in deps:
            if str(did) == str(mid):  # self-referencing requirement
                continue
            dep_ref = refs.get(str(did)) or {}
            if not _is_noise(did, dep_ref):
                need.append(did)
        if need:
            print("  %s  needs: %s" % (fn, ", ".join(sorted(need))))
            missing_any = True
    return missing_any


def _normalize_deps(deps):
    """Normalize cached deps to bare mod-id strings.

    Older runs stored [game_slug, mod_id] pairs (JSON -> [slug, id] lists);
    consumers (framework grouping, dependency gate, superseded analysis) need
    hashable plain mod-id strings. Coerces either shape to sorted unique
    string ids. Returns [] when empty/unknown.
    """
    out = []
    for d in deps or []:
        if isinstance(d, (list, tuple)) and len(d) >= 2:
            out.append(str(d[1]))
        else:
            out.append(str(d))
    seen = set()
    uniq = []
    for x in sorted(out):
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def fetch_dependencies(folder, fn_list, progress=None):
    """Fetch and cache each mod's Nexus Requirements ids (best-effort).

    Reads the existing verified cache first; only mods without a cached
    'deps' list are fetched. Deps are stored per filename AND shared via the
    mod-ID reference cache, so other files of the same mod page (new versions,
    optional builds) need no repeated lookups. Returns the updated cache.
    Never writes user data - cache only.
    """
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
        # deps are normalized to plain mod-id strings; heal any legacy
        # [game_slug, mod_id] pairs that an older run stored.
        cur_deps = _normalize_deps(ref.get("deps"))
        if cur_deps:
            if cur_deps != ref.get("deps"):
                refs[mid]["deps"] = cur_deps
                refs_dirty = True
            cache.setdefault(fn, {})["deps"] = cur_deps
            changed = True
            if progress:
                progress(fn)
            continue
        entry = cache.get(fn) or {}
        entry_deps = _normalize_deps(entry.get("deps"))
        if entry_deps:
            refs[mid]["deps"] = entry_deps
            refs_dirty = True
            if entry_deps != entry.get("deps"):
                cache[fn]["deps"] = entry_deps
                changed = True
            continue
        # Deps are cache-only: the fully-offline build never fetches a live Nexus
        # page, so a mod with no recorded requirements simply stays that way
        # and framework grouping falls back to name matching for it.
    if changed:
        storage.save_cache(folder, cache)
    if refs_dirty:
        try:
            storage.save_references(folder, refs)
        except Exception:
            pass
    return cache
