"""Superseded detection + same-page grouping + placement review (offline).

All READ-ONLY — never moves files. Scores pairs of downloaded mods that may
represent newer/older releases of one mod, groups files that belong to the
same Nexus page, and checks that everything sits where the sort expects."""
import os
import re

from gigasort.core.categorize import (
    clean_name, extract_mod_id, extract_mod_author, name_tokens,
)

POSSIBLE_THRESHOLD = 0.35
STRONG_THRESHOLD = 0.6

_VERSION_KEYWORDS = ("v2", "redux", "remaster", "revamped", "optimum",
                     "complete", "final")

_RENAME_SUFFIXES = re.compile(r"(?:-\d{3,6})?[-_]?\d+(?:\.\d+)*$")


def _strip_ver(name):
    n = name_tokens(name)
    return " ".join(sorted(n))


def extract_mods(folder):
    """Map (category, author) -> {file: (mod_id, clean_name)} for archives
    under the workspace (category folders + root)."""
    out = []
    for root, _dirs, files in os.walk(folder):
        if any(seg.startswith("_") for seg in
               os.path.relpath(root, folder).split(os.sep)):
            continue
        for f in files:
            if not f.lower().endswith((".zip", ".rar", ".7z")):
                continue
            cat = os.path.basename(os.path.dirname(root))
            author = extract_mod_author(f)
            out.append({
                "file": f, "path": os.path.join(root, f),
                "cat": cat, "author": author,
                "mod_id": extract_mod_id(f),
                "clean": clean_name(f),
                "tokens": _strip_ver(f),
            })
    return out


def _score_pair(a, b):
    """Weighted similarity of two archive records. Returns float >= 0."""
    if a["cat"] != b["cat"]:
        return 0.0
    ta, tb = a["tokens"], b["tokens"]
    if not ta or not tb:
        return 0.0
    overlap = len(set(ta.split()) & set(tb.split())) / max(
        len(set(ta.split())), len(set(tb.split())))
    score = 0.6 * overlap
    for key in (a["clean"].lower(), b["clean"].lower()):
        if key in a["clean"].lower() or key in b["clean"].lower():
            score += 0.2
    return round(score, 3)


def find_superseded(folder, threshold=POSSIBLE_THRESHOLD):
    """Return a list of {older, newer, author, score, reason} dicts."""
    mods = extract_mods(folder)
    pairs = []
    for i, a in enumerate(mods):
        for b in mods[i + 1:]:
            if a["mod_id"] == b["mod_id"]:
                continue
            if not a["author"] or a["author"] != b["author"]:
                continue
            score = _score_pair(a, b)
            if score < threshold:
                continue
            # Nexus id = chronological proxy: higher id is newer
            older, newer = (a, b) if int(a["mod_id"] or 0) < int(b["mod_id"] or 0) \
                else (b, a)
            reason = "similar author+name"
            if any(v in (older["clean"] or "").lower()
                   for v in _VERSION_KEYWORDS):
                reason = "older version-keyword"
            if score >= STRONG_THRESHOLD:
                reason += " (strong)"
            pairs.append({
                "older": older["file"], "newer": newer["file"],
                "author": a["author"], "score": score, "reason": reason,
            })
    pairs.sort(key=lambda p: p["score"], reverse=True)
    return pairs


def group_by_modpage(folder):
    """Group downloaded files sharing one Nexus mod id per
    Category/Author context. Returns {mod_id: {...}} dict."""
    mods = extract_mods(folder)
    groups = {}
    for m in mods:
        if not m["mod_id"]:
            continue
        key = "%s|%s" % (m["mod_id"], m["cat"])
        groups.setdefault(key, {
            "mod_id": m["mod_id"], "cat": m["cat"],
            "author": m["author"], "files": [],
        })
        groups[key]["files"].append(m["file"])
    for g in groups.values():
        g["files"].sort()
        g["main"] = g["files"][0]
    return groups


def check_placement(folder):
    """Verify the whole batch is where the sort expects it. Returns a list
    of {file, expected, current, kind} dicts (misplaced | root | split-page)."""
    from gigasort.core.scan import find_misplaced
    issues = []
    for f, want, cur in find_misplaced(folder):
        issues.append({"file": f, "expected": want, "current": cur,
                       "kind": "misplaced"})

    mods = extract_mods(folder)
    by_id = {}
    for m in mods:
        if m["mod_id"]:
            by_id.setdefault(m["mod_id"], set()).add(m["cat"])
    for mid, cats in by_id.items():
        if len(cats) > 1:
            for m in mods:
                if m["mod_id"] == mid:
                    issues.append({"file": m["file"], "expected": "one page",
                                   "current": m["cat"], "kind": "split-page"})
    return issues