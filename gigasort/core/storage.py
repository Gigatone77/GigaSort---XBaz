"""Persistence — settings, caches, manifest, overrides, state files.

All _GigaSort_* state lives in a CENTRAL state directory per workspace
(~/.local/share/GigaSort/state/<workspace-key>/), never inside the folder
being sorted. This keeps GigaSort from injecting state into the mod library
or the organized target folders. A legacy state file found inside a
workspace is migrated losslessly into the central dir on first access.
Override the base with the env var GS_STATE_DIR.
"""

import hashlib
import json
import os
import re
import shutil
import time
import uuid

from gigasort.constants import (
    SETTINGS_FILENAME, CACHE_FILENAME, REFERENCE_FILENAME,
    WEB_OVERRIDES_FILENAME, MANIFEST_FILENAME, TAGS_FILENAME,
    THREAT_FILENAME, WTNC_REPORT_FILENAME, WTNC_EXTRA_COMPAT_FILENAME,
    WTNC_EXTRA_COMPAT_SEED, GS_COLLECTION_CACHE, REJECT_BIN,
)
from gigasort.utils import json_load

_STATE_BASE = os.path.join(os.path.expanduser("~"), ".local", "share",
                           "GigaSort", "state")


def state_base():
    """Root of all GigaSort state (env GS_STATE_DIR overrides)."""
    base = os.environ.get("GS_STATE_DIR") or _STATE_BASE
    return os.path.abspath(os.path.expanduser(base))


def state_dir(folder):
    """Central per-workspace state directory (created on demand).

    Keyed by the realpath so two paths to the same folder share one state
    home, and moving the folder keeps its state reachable."""
    real = os.path.realpath(folder or ".")
    slug = os.path.basename(real.rstrip(os.sep)) or "root"
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", slug)
    key = hashlib.sha1(real.encode("utf-8", "surrogateescape")).hexdigest()[:10]
    d = os.path.join(state_base(), "%s-%s" % (slug, key))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def scratch_dir(folder):
    """Per-workspace scratch area for tool-own temp work (extraction stage
    etc.) — outside the workspace so a sort never pollutes its target."""
    d = os.path.join(state_dir(folder), "scratch")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def state_path(folder, name):
    """Central path for a state file, with one-time lossless migration: a
    legacy in-folder copy moves into the central state dir on first access
    and is never written back into the workspace."""
    p = os.path.join(state_dir(folder), name)
    if not os.path.exists(p):
        legacy = os.path.join(folder, name)
        if os.path.isfile(legacy):
            try:
                shutil.move(legacy, p)
            except OSError:
                pass
    return p


def _path(folder, name):
    return state_path(folder, name)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "game_dir": "",
    "bin_style": "keep",          # keep | one-bin
    "top_level_authors": [],
    "framework_grouping": True,
}


def load_settings(folder):
    s = dict(DEFAULT_SETTINGS)
    s.update(json_load(_path(folder, SETTINGS_FILENAME)) or {})
    return s


def save_settings(folder, settings):
    try:
        with open(_path(folder, SETTINGS_FILENAME), "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except OSError:
        pass


def save_web_overrides(folder, overrides):
    """Persist {filename: category-folder} human-driven web overrides."""
    try:
        with open(_path(folder, WEB_OVERRIDES_FILENAME), "w",
                  encoding="utf-8") as fh:
            json.dump(overrides, fh, indent=2)
    except OSError:
        pass


def load_web_overrides(folder):
    return json_load(_path(folder, WEB_OVERRIDES_FILENAME)) or {}


# ---------------------------------------------------------------------------
# Verified cache  (approved -> {filename: record})
# ---------------------------------------------------------------------------
def load_verified(folder):
    return json_load(_path(folder, CACHE_FILENAME)) or {}


def save_cache(folder, cache):
    """Compatibility alias of save_verified (GUI rejects page)."""
    save_verified(folder, cache)


def save_verified(folder, cache):
    try:
        with open(_path(folder, CACHE_FILENAME), "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2)
    except OSError:
        pass


def add_verified(folder, filename, mod_id=None, title=None, category=None,
                 struct_ok=None):
    """Add one approved record (web-verified or user-approved) to the cache."""
    cache = load_verified(folder)
    record = cache.get(filename) or {}
    record.update({
        "approved": True,
        "mod_id": mod_id or record.get("mod_id"),
        "title": title or record.get("title") or filename,
        "category": category or record.get("category"),
    })
    if struct_ok is not None:
        record["struct_ok"] = struct_ok
    record["when"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cache[filename] = record
    save_verified(folder, cache)
    return record


# ---------------------------------------------------------------------------
# Reference cache  (mod id -> {title, category, deps, verified})
# ---------------------------------------------------------------------------
def load_references(folder):
    return json_load(_path(folder, REFERENCE_FILENAME)) or {}


def load_cache(folder):
    """The filename-keyed verified/approved cache (legacy GUI name)."""
    return load_verified(folder)


def save_references(folder, refs):
    try:
        with open(_path(folder, REFERENCE_FILENAME), "w", encoding="utf-8") as fh:
            json.dump(refs, fh, indent=2)
    except OSError:
        pass


def upsert_reference(folder, mod_id, title="", category=None, deps=None,
                     verified=True, source="approved"):
    refs = load_references(folder)
    rec = refs.get(mod_id) or {}
    rec["verified"] = verified
    if title:
        rec["title"] = title
    if category:
        rec["category"] = category
    if deps is not None:
        rec["deps"] = list(deps)
    rec["source"] = source
    refs[mod_id] = rec
    save_references(folder, refs)


# ---------------------------------------------------------------------------
# Manifest (undo bookkeeping)
# ---------------------------------------------------------------------------
def load_manifest(folder):
    return json_load(_path(folder, MANIFEST_FILENAME)) or {}


def save_manifest(folder, manifest):
    try:
        with open(_path(folder, MANIFEST_FILENAME), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
    except OSError:
        pass


def begin_manifest_entry(folder):
    """Start a new manifest entry (unique id). Returns the entry id."""
    entry_id = uuid.uuid4().hex[:12]
    manifest = load_manifest(folder)
    manifest.setdefault("moves", {})
    manifest["moves"][entry_id] = {
        "time": time.time(), "changes": [], "applied": False,
    }
    save_manifest(folder, manifest)
    return entry_id


def record_move(folder, entry_id, src, dst, verified=True):
    manifest = load_manifest(folder)
    entry = manifest.get("moves", {}).get(entry_id)
    if entry is None:
        return
    entry["changes"].append({
        "from": src, "to": dst, "verified": verified,
    })
    save_manifest(folder, manifest)


def finalize_manifest(folder, entry_id, applied=True):
    manifest = load_manifest(folder)
    entry = manifest.get("moves", {}).get(entry_id)
    if entry is not None:
        entry["applied"] = applied
        save_manifest(folder, manifest)


# ---------------------------------------------------------------------------
# Tags / threats / wtnc extras
# ---------------------------------------------------------------------------
def load_tags(folder):
    return json_load(_path(folder, TAGS_FILENAME)) or {}


def save_tags(folder, tags):
    try:
        with open(_path(folder, TAGS_FILENAME), "w", encoding="utf-8") as fh:
            json.dump(tags, fh, indent=2)
    except OSError:
        pass


def load_threats(folder):
    return json_load(_path(folder, THREAT_FILENAME)) or {}


def save_threats(folder, threats):
    try:
        with open(_path(folder, THREAT_FILENAME), "w", encoding="utf-8") as fh:
            json.dump(threats, fh, indent=2)
    except OSError:
        pass


def load_wtnc_compat(folder):
    c = json_load(_path(folder, WTNC_EXTRA_COMPAT_FILENAME))
    if not c:
        c = dict(WTNC_EXTRA_COMPAT_SEED)
        try:
            with open(_path(folder, WTNC_EXTRA_COMPAT_FILENAME), "w",
                      encoding="utf-8") as fh:
                json.dump(c, fh, indent=2)
        except OSError:
            pass
    return c


def save_wtnc_compat(folder, compat_map):
    try:
        with open(_path(folder, WTNC_EXTRA_COMPAT_FILENAME), "w",
                  encoding="utf-8") as fh:
            json.dump(compat_map, fh, indent=2)
    except OSError:
        pass


def load_wtnc_report(folder):
    return json_load(_path(folder, WTNC_REPORT_FILENAME)) or {}


def save_wtnc_report(folder, report):
    try:
        with open(_path(folder, WTNC_REPORT_FILENAME), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    except OSError:
        pass


def load_collection_cache(folder):
    return json_load(_path(folder, GS_COLLECTION_CACHE)) or {}


def save_collection_cache(folder, cache):
    try:
        with open(_path(folder, GS_COLLECTION_CACHE), "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Misc filesystem helpers
# ---------------------------------------------------------------------------
def one_bin(folder):
    """One-bin layout: fake _REJECTS -> _TRASH single bucket. Returns the
    actual bin path used for rejects."""
    return os.path.join(folder, REJECT_BIN)


def prepare_one_bin(folder, bin_name="~deleted"):
    """Hidden restorable sub-bin inside the reject bin (never hard delete)."""
    path = os.path.join(folder, REJECT_BIN, bin_name)
    os.makedirs(path, exist_ok=True)
    return path