"""Persistence for GigaSort state files (kept format-compatible with the
original single-file tool so existing workspaces keep working)."""

import os

from gigasort.constants import (
    CACHE_FILENAME, LOG_FILENAME, MANIFEST_FILENAME, TAGS_FILENAME,
    THREAT_FILENAME, SETTINGS_FILENAME, REFERENCE_FILENAME,
    WEB_OVERRIDES_FILENAME, REJECT_BIN, TRASH_BIN,
)
from gigasort.utils.io import json_load, json_dump, _atomic_write_text
from gigasort.utils import fs

# Hidden, restorable sub-folder inside each bin. One-bin rule copies are
# MOVED here (never removed) so GigaSort never permanently deletes anything.
_DELETED_SUBDIR = "~deleted"


def _join(folder, name):
    return os.path.join(folder, name)


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def cache_path(folder):
    return _join(folder, CACHE_FILENAME)


def reference_path(folder):
    """Path of the Nexus mod-ID reference cache.

    Keyed by Nexus mod ID (not filename), so EVERY file on a mod page — the
    MAIN zip, an Optional file, an "Old Version", a newly re-downloaded newer
    build — hits one shared reference record instead of requiring its own live
    Nexus lookup on a future sort.
    """
    return _join(folder, REFERENCE_FILENAME)


def web_overrides_path(folder):
    """Path of the human-confirmed web-category override map.

    Maps exact archive filenames to the category folder a VERIFIED ONLINE source
    (Nexus page category / Google-confirmed identity) assigned them. These
    overrides WIN over offline filename-keyword routing so that live, verified
    web info is never silently reverted by a keyword guess on the next sort.
    """
    return _join(folder, WEB_OVERRIDES_FILENAME)


def load_web_overrides(folder):
    """Load {filename: category-folder} overrides; {} when absent/invalid."""
    return json_load(web_overrides_path(folder), {})


def save_web_overrides(folder, overrides):
    """Persist the human-confirmed web-category override map."""
    json_dump(web_overrides_path(folder), overrides)


def log_path(folder):
    return _join(folder, LOG_FILENAME)


def manifest_path(folder):
    return _join(folder, MANIFEST_FILENAME)


def tags_path(folder):
    return _join(folder, TAGS_FILENAME)


def threat_path(folder):
    return _join(folder, THREAT_FILENAME)


def settings_path(folder):
    return _join(folder, SETTINGS_FILENAME)


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------
def load_settings(folder):
    return json_load(settings_path(folder), {})


def save_settings(folder, settings):
    json_dump(settings_path(folder), settings)


# ---------------------------------------------------------------------------
# verified cache
# ---------------------------------------------------------------------------
def load_cache(folder):
    return json_load(cache_path(folder), {})


def save_cache(folder, cache):
    json_dump(cache_path(folder), cache)


# ---------------------------------------------------------------------------
# Nexus mod-ID reference cache
# ---------------------------------------------------------------------------
# Each record: {"verified": True, "title": "...", "category": "NN Name" or None}
def load_references(folder):
    return json_load(reference_path(folder), {})


def save_references(folder, refs):
    json_dump(reference_path(folder), refs)


def write_info_log(folder, cache):
    """Write the human-readable verification log; return entry count."""
    lines = ["GigaSort verification log", "=" * 50, ""]
    count = 0
    for fn, entry in (cache or {}).items():
        if entry.get("status") == "approved":
            lines.append("APPROVED  %s" % fn)
            lines.append("    category : %s" % entry.get("category"))
            lines.append("    nexus    : %s (%s)"
                         % (entry.get("nexus_title"), entry.get("nexus_cat")))
            count += 1
    _atomic_write_text(log_path(folder), "\n".join(lines) + "\n")
    return count


# ---------------------------------------------------------------------------
# manifest (whole-run undo)
# ---------------------------------------------------------------------------
def load_manifest(folder):
    data = json_load(manifest_path(folder), {}) or {}
    return data.get("moves", [])


def save_manifest(folder, moves):
    json_dump(manifest_path(folder), {"moves": moves})


def record_move(folder, src, dst, dry_run=False):
    """Append a move to the undo manifest (skipped on dry_run)."""
    if dry_run:
        return
    moves = load_manifest(folder)
    moves.append({"src": src, "dst": dst})
    save_manifest(folder, moves)


# ---------------------------------------------------------------------------
# tags (processed-mods handle for the agent)
# ---------------------------------------------------------------------------
def load_tags(folder):
    return json_load(tags_path(folder), {})


def save_tags(folder, data):
    json_dump(tags_path(folder), data)


# ---------------------------------------------------------------------------
# threats
# ---------------------------------------------------------------------------
def load_threats(folder):
    data = json_load(threat_path(folder), {}) or {}
    if isinstance(data, dict):
        return data
    return {}


# ---------------------------------------------------------------------------
# bins / one-bin rule
# ---------------------------------------------------------------------------
def bin_path(folder, bin_name):
    return _join(folder, bin_name)


def prepare_one_bin(folder, filename, bin_name, dry_run=False, remove_fn=None):
    """Enforce the one-bin rule: if the file is sitting in the opposite bin,
    relocate it there first (unless dry_run). `remove_fn` overrides the
    default, which MOVES the older copy into that bin's restorable '~deleted'
    sub-folder instead of permanently deleting it (no-delete rule)."""
    other = TRASH_BIN if bin_name == REJECT_BIN else REJECT_BIN
    other_path = os.path.join(bin_path(folder, other), filename)
    if not os.path.exists(other_path):
        return
    if dry_run:
        return
    if remove_fn:
        remove_fn(other_path)
    else:
        # No-delete default: move the other-bin copy to its '~deleted' folder.
        try:
            deleted_dir = os.path.join(os.path.dirname(other_path), _DELETED_SUBDIR)
            dst = os.path.join(deleted_dir, filename)
            if os.path.abspath(other_path) != os.path.abspath(dst):
                fs.guarded_move(folder, other_path, dst)
        except OSError:
            pass
