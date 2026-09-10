"""Offline information archive for GigaSort.

Builds a per-workspace ``_GigaSort_sig_archive.json`` that merges every
offline identity source (ZERO network access):

    bundled data/sig_seeds.json    web-confirmed pages, framework ids, WTNC
                                   curated list ids (verified: True)
    bundled data/wtnc_modlist.md   parsed the same way the WTNC sweep parses it
    per-mod meta.ini files         title/author/version/category from prior
                                   VERIFIED extractions (verified: True)
    _GigaSort_verified.json        approved offline-structure entries
    archive filenames              Nexus id + keyword category; identity only,
                                   never proof by itself

``verified: True`` is only awarded when real evidence proves the Nexus page
exists (bundled seed, meta.ini from a verified extraction, or an approved
verified-cache entry).  A bare filename token is identity, not proof.

The archive also seeds the slim ID cache (``_GigaSort_references.json``) so
every existing code path (rescue_category, verification_statuses, superseded
enrichment, GUI) benefits from the archive without code changes.

Public API:
    ensure_archive(folder, force=False)  build if missing, then seed ID cache
    build_offline_archive(folder)        full rebuild, returns the archive
    load_offline_archive(folder)         read-only accessor
    offline_lookup(folder, mod_id)       single mod record or None
    seed_id_cache(folder)                write refs from the archive
"""

import json
import os
import re
from datetime import datetime, timezone

from gigasort.constants import (
    APPROVED,
    ARCHIVE_EXTS,
    KNOWN_FOLDERS,
    SIG_ARCHIVE_FILENAME,
    SIG_SEEDS_BUNDLED,
    WTNC_BUNDLED_MANIFEST,
)

_SKIP_DIR_PREFIXES = ("_", ".")

_META_FIELDS = ("modid", "nexusname", "author", "uploadedby", "version",
                "nexusurl", "categoryname", "installationfile",
                "nexusfilename")

_META_KV_RE = re.compile(r"^\s*(\w+)\s*=\s*(.*)$")


def _data_path(name):
    """Absolute path of a bundled data file inside the package."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "data", name)


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Bundled knowledge base
# ---------------------------------------------------------------------------

def load_bundled_seeds():
    """{mod_id: record} from the shipped data/sig_seeds.json."""
    rec = _load_json(_data_path(SIG_SEEDS_BUNDLED))
    mods = (rec or {}).get("mods") or {}
    out = {}
    for mid, m in mods.items():
        out[str(mid)] = {
            "title": m.get("title"),
            "category": m.get("category"),
            "verified": bool(m.get("verified")),
            "source": m.get("source") or "bundled-seed",
            "note": m.get("note"),
        }
    return out


def load_bundled_modlist():
    """{mod_id: {"title", "section"}} parsed from the bundled Modlist.md."""
    path = _data_path(WTNC_BUNDLED_MANIFEST)
    if not os.path.exists(path):
        return {}
    try:
        from gigasort.core.wtnc import parse_modlist
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        return parse_modlist(text)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Library evidence
# ---------------------------------------------------------------------------

def _archive_files(folder):
    """Every archive path in the workspace (GigaSort bins/state skipped)."""
    if not folder or not os.path.isdir(folder):
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(_SKIP_DIR_PREFIXES)]
        for fn in filenames:
            if fn.lower().endswith(ARCHIVE_EXTS):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def parse_meta_ini(path):
    """Parse one extracted per-mod meta.ini into a dict (None if junk)."""
    kvs = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _META_KV_RE.match(line)
                if m:
                    kvs[m.group(1).lower()] = m.group(2).strip()
    except Exception:
        return None
    modid = kvs.get("modid") or kvs.get("mod_id")
    nexusurl = kvs.get("nexusurl") or ""
    if not modid or not re.search(r"/mods/%s(?:[?/]|$)" % re.escape(modid),
                                  nexusurl, re.I):
        return None
    return kvs


def _meta_evidence(folder):
    """{mod_id: [(title, author, version, category)]} from verified meta.ini."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(_SKIP_DIR_PREFIXES)]
        if "meta.ini" not in filenames:
            continue
        kvs = parse_meta_ini(os.path.join(dirpath, "meta.ini"))
        if not kvs:
            continue
        modid = kvs["modid"]
        title = kvs.get("nexusname") or kvs.get("name") or ""
        author = kvs.get("author") or kvs.get("uploadedby") or ""
        category = kvs.get("categoryname") or ""
        if category not in KNOWN_FOLDERS:
            category = None
        out.setdefault(modid, []).append(
            (title, author, kvs.get("version") or "", category))
    return out


# ---------------------------------------------------------------------------
# Archive build
# ---------------------------------------------------------------------------

def _merge_mod(mods, mod_id, **fields):
    """Merge fields into mods[mod_id]; evidence-bearing fields never lose."""
    rec = mods.setdefault(mod_id, {
        "id": mod_id,
        "title": None,
        "author": None,
        "version": None,
        "category": None,
        "verified": False,
        "sources": [],
        "page": "https://www.nexusmods.com/cyberpunk2077/mods/%s" % mod_id,
    })
    for key in ("title", "author", "version", "category"):
        val = fields.get(key)
        if val and not rec.get(key):
            rec[key] = val
    if fields.get("verified"):
        rec["verified"] = True
    src = fields.get("source")
    if src and src not in rec["sources"]:
        rec["sources"].append(src)
    return rec


def build_offline_archive(folder):
    """Rebuild _GigaSort_sig_archive.json from every offline source.

    Returns the archive dict: {"schema", "built", "mods"}.
    """
    from gigasort.core.categorize import candidate_mod_id, extract_mod_id
    from gigasort.core import storage

    mods = {}

    for mid, m in load_bundled_seeds().items():
        _merge_mod(mods, mid, title=m.get("title") or None,
                   category=m.get("category") or None,
                   verified=m.get("verified"),
                   source=m.get("source"))
        if m.get("note"):
            mods[mid]["note"] = m["note"]

    for mid, info in load_bundled_modlist().items():
        rec = mods.setdefault(mid, {
            "id": mid, "title": None, "author": None, "version": None,
            "category": None, "verified": False, "sources": [], "page":
            "https://www.nexusmods.com/cyberpunk2077/mods/%s" % mid})
        if not rec.get("title"):
            rec["title"] = info["title"]
        if "source" not in rec["sources"]:
            rec["sources"].append("wtnc-curated")
        rec["verified"] = True

    for modid, ev in _meta_evidence(folder).items():
        title = next((t for t, _a, _v, _c in ev if t), None)
        author = next((a for _t, a, _v, _c in ev if a), None)
        version = next((v for _t, _a, v, _c in ev if v), None)
        category = next((c for _t, _a, _v, c in ev if c), None)
        _merge_mod(mods, modid, title=title, author=author, version=version,
                   category=category, verified=True, source="meta.ini")

    cache = storage.load_cache(folder) or {}
    for fn, entry in cache.items():
        if not (entry and entry.get("status") == APPROVED):
            continue
        mod_id = extract_mod_id(fn)
        if not mod_id:
            mod_id = candidate_mod_id(fn)
        if not mod_id:
            continue
        _merge_mod(mods, mod_id,
                   title=(entry.get("nexus_title") or mods.get(mod_id, {})
                          .get("title")),
                   category=(entry.get("nexus_cat")
                             if entry.get("nexus_cat") in KNOWN_FOLDERS
                             else mods.get(mod_id, {}).get("category")),
                   verified=True, source="offline-structure")

    # Record filename-token-only mod ids so they exist in the archive as
    # identity (verified stays False - a bare token is never proof by itself).
    for path in _archive_files(folder):
        fn = os.path.basename(path)
        mod_id = extract_mod_id(fn)
        if not mod_id:
            mod_id = candidate_mod_id(fn)
        entry = cache.get(fn) or {}
        approved = bool(entry.get("status") == "approved")
        if mod_id and not approved and not mods.get(mod_id):
            _merge_mod(mods, mod_id, verified=False, source="filename-token")

    archive = {
        "schema": 1,
        "built": datetime.now(timezone.utc).isoformat(),
        "workspace": os.path.normpath(os.path.abspath(folder)),
        "mods": mods,
    }
    _save_json(os.path.join(folder, SIG_ARCHIVE_FILENAME), archive)
    return archive


# ---------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------

def load_offline_archive(folder):
    rec = _load_json(os.path.join(folder, SIG_ARCHIVE_FILENAME))
    if not rec or rec.get("schema") != 1:
        return None
    return rec


def offline_lookup(folder, mod_id):
    """Single confirmed record for a mod id (None if unknown)."""
    rec = load_offline_archive(folder)
    if not rec:
        return None
    return rec.get("mods", {}).get(str(mod_id))


def seed_id_cache(folder, archive=None):
    """Extend _GigaSort_references.json from the offline archive.

    Verified records fill the slim ID cache so all existing consumers
    (rescue_category, verification_statuses, superseded, GUI) work offline.
    Existing refs entries are never demoted or overwritten (title/category
    only filled when missing).
    """
    archive = archive or load_offline_archive(folder)
    if not archive:
        return
    from gigasort.core import storage
    refs = storage.load_references(folder) or {}
    dirty = False
    for mid, m in archive.get("mods", {}).items():
        if not m.get("verified"):
            continue
        cur = refs.get(mid) or {}
        merged = False
        if not cur:
            refs[mid] = {}
            merged = True
        if not refs[mid].get("verified"):
            refs[mid]["verified"] = True
            merged = True
        if m.get("title") and not refs[mid].get("title"):
            refs[mid]["title"] = m["title"]
            merged = True
        if m.get("category") and not refs[mid].get("category"):
            refs[mid]["category"] = m["category"]
            merged = True
        if m.get("page") and not refs[mid].get("page"):
            refs[mid]["page"] = m["page"]
            merged = True
        if merged:
            dirty = True
    if dirty:
        storage.save_references(folder, refs)


def ensure_archive(folder, force=False):
    """Build the offline archive if missing (or force) and seed the ID cache.

    Cheap when the archive already exists - only the ID-cache seeding runs,
    so per-run cost is a small JSON read + possible write.
    """
    if not folder or not os.path.isdir(folder):
        return
    archive = None
    if force or not os.path.exists(os.path.join(folder, SIG_ARCHIVE_FILENAME)):
        archive = build_offline_archive(folder)
    seed_id_cache(folder, archive)