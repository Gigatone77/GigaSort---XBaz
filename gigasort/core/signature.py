"""Bundled offline knowledge base: signatures, seeds, references cache.

Fully offline — no network. The verification facts live in three sources,
all merged into the per-workspace archive at _GigaSort_sig_archive.json:

1.  Bundled gigasort/data/sig_seeds.json  (222 Nexus-confirmed framework /
    collection / WTNC records, shipped with the tool)
2.  Bundled gigasort/data/wtnc_modlist.md (parsed "M {id} {name}" manifest)
3.  Per-workspace _GigaSort_verified.json (approved cache, merged in)
"""

import hashlib
import json
import os
import re

from gigasort.constants import (
    SIG_ARCHIVE_FILENAME, SIG_SEEDS_BUNDLED, WTNC_BUNDLED_MANIFEST,
    CACHE_FILENAME, REFERENCE_FILENAME,
)
from gigasort.core.storage import state_path
from gigasort.utils import json_load

# ---------------------------------------------------------------------------
# Bundled data loading
# ---------------------------------------------------------------------------

_WTNC_MOD_RE = re.compile(r"^M\s+(\d+)\s+(.+)$", re.IGNORECASE)
# wtnc_modlist.md is shipped as markdown: "[Name](https://www.nexusmods.com/
# cyberpunk2077/mods/10355) by [Author](...)". Parse the link form.
_WTNC_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(\s*https?://(?:www\.)?nexusmods\.com/cyberpunk2077/mods/(\d+)\s*\)",
    re.IGNORECASE)


def load_bundled_seeds():
    """Load the shipped sig_seeds.json. Returns {} if it is missing."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "data", SIG_SEEDS_BUNDLED)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_bundled_wtnc():
    """Parse the shipped wtnc_modlist.md into {mod_id: mod_name}."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "data", WTNC_BUNDLED_MANIFEST)
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                m = _WTNC_MOD_RE.match(line)
                if m:
                    out[m.group(1)] = m.group(2).strip()
                    continue
                lm = _WTNC_LINK_RE.search(line)
                if lm:
                    out[lm.group(2)] = lm.group(1).strip()
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------
# Workspace trust list
# ---------------------------------------------------------------------------

def load_approved(folder):
    """Load the approved-cache records ({filename: {..}})."""
    return json_load(state_path(folder, CACHE_FILENAME)) or {}


# ---------------------------------------------------------------------------
# Offline archive build/lookup
# ---------------------------------------------------------------------------

def _seed_fingerprint():
    """Fingerprint of the bundled knowledge sources. When the shipped
    sig_seeds change (new expansion, corrected categories), every existing
    workspace archive must be rebuilt so routing uses the new KB."""
    seeds = load_bundled_seeds()
    mods = seeds.get("mods") if isinstance(seeds, dict) else {}
    seed_bytes = json.dumps(mods, sort_keys=True, default=str)
    return hashlib.sha256(seed_bytes.encode("utf-8")).hexdigest()[:16]


def _archive_fingerprint(data):
    return data.get("_seed_fp") if isinstance(data, dict) else None


def ensure_archive(folder, force=False):
    """Build the offline sig archive if it does not exist yet (or force, or
    when the bundled seed fingerprint changed).

    Returns True when an archive is present and loadable afterwards."""
    path = state_path(folder, SIG_ARCHIVE_FILENAME)
    if not force and os.path.exists(path):
        data = json_load(path)
        if data is not None and isinstance(data, dict):
            if _archive_fingerprint(data) == _seed_fingerprint():
                return True
        # stale (or legacy pre-fingerprint) archive: fall through to rebuild
    data = build_offline_archive(folder)
    if not data:
        return False
    data = dict(data)
    data["_seed_fp"] = _seed_fingerprint()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        return False
    return True


def build_offline_archive(folder):
    """Merge the bundled seeds + WTNC list + approved cache into one dict:
    {mod_id: {"title": str, "category": str|None, "source": str}}."""
    data = {}

    seeds = load_bundled_seeds()
    seed_mods = seeds.get("mods") if isinstance(seeds, dict) else {}
    if not isinstance(seed_mods, dict):
        seed_mods = {}
    for mod_id, rec in seed_mods.items():
        if isinstance(rec, dict):
            data[mod_id] = dict(rec, source="sig_seeds")

    for mod_id, title in load_bundled_wtnc().items():
        if mod_id not in data:
            data[mod_id] = {"title": title, "category": None,
                            "source": "wtnc"}

    approved = load_approved(folder) or {}
    for fname, rec in approved.items():
        if not isinstance(rec, dict):
            continue
        mid = str(rec.get("mod_id", "")).strip()
        if not mid:
            continue
        data.setdefault(mid, {
            "title": rec.get("title", "") or fname,
            "category": rec.get("category"),
        }).update({
            "title": rec.get("title", "") or fname,
            "category": rec.get("category") or data[mid].get("category"),
        })
        data[mid]["source"] = "approved"

    # Merge the per-workspace reference cache (mod-id records accumulated
    # from earlier web-verified lookups) so their titles/categories feed the
    # offline archive too. Refs entries never override a seed's category.
    # ID-ONLY RULE: a refs record only contributes a CATEGORY when it carries
    # web-verification evidence (a real title record is assumed verified; a
    # bare "verified" flag also qualifies). Legacy keyword-guess refs entries
    # (no title, no verified flag) feed deps/titles only, never a category --
    # otherwise an unverified guess can route a file, defeating the offline KB.
    refs = json_load(state_path(folder, REFERENCE_FILENAME)) or {}
    for mid, rec in refs.items():
        if not isinstance(rec, dict):
            continue
        entry = data.setdefault(mid, {"title": "", "category": None})
        entry["title"] = entry["title"] or rec.get("title", "")
        verified = bool(rec.get("verified") or rec.get("title"))
        if verified:
            entry["category"] = entry.get("category") or rec.get("category")
            entry.setdefault("source", "refs")

    return data


def seed_id_cache(folder):
    """Seed _GigaSort_references.json mod-id records from the built archive.
    Returns the number of records added/updated."""
    sig = json_load(state_path(folder, SIG_ARCHIVE_FILENAME))
    refs_path = state_path(folder, REFERENCE_FILENAME)
    refs = json_load(refs_path) or {}
    added = 0
    dirty = False
    for mid, rec in (sig or {}).items():
        if mid == "_seed_fp" or not str(mid).isdigit():
            continue
        if mid in refs:
            continue
        refs[mid] = {"verified": True,
                     "title": rec.get("title", ""),
                     "category": rec.get("category"),
                     "source": rec.get("source", "sig"),
                     "deps": []}
        dirty = True
        added += 1
    if dirty:
        with open(refs_path, "w", encoding="utf-8") as fh:
            json.dump(refs, fh, indent=2)
    return added


def offline_lookup(folder, mod_id):
    """Look up a mod id in the offline archive. Returns a dict, or None."""
    sig = json_load(state_path(folder, SIG_ARCHIVE_FILENAME))
    if not sig:
        return None
    return sig.get(str(mod_id))


def load_json_refs(folder):
    """Load the references cache ({mod_id: {title, category, deps, ...}})."""
    refs_path = state_path(folder, REFERENCE_FILENAME)
    return json_load(refs_path) or {}