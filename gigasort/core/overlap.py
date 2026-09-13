"""Overlap audit — baseline conflict check + cross-tree same-path detection.

Two read-only capabilities (nothing is ever moved here):

1. **baseline check** — given one or more game-relative trees (e.g. drop-in
   pack folders) plus a read-only reference tree (e.g. an unpicked WTNC /
   "base + WTNC" install), report any file whose game-relative path already
   exists in the reference. Those are hard-overwrites: installing the pack
   would clobber a file the reference already provides.

2. **cross-tree same-path** — when the same game-relative path appears in
   more than one audited tree, report it and mark IDENTICAL (byte-identical,
   harmless duplicate) vs DIFFERENT (real content conflict, last-drop wins).

The reference tree is READ-ONLY — its relative path may or may not line up
with a `Cyberpunk 2077/` wrapper dir; a leading `Cyberpunk 2077/` component
is stripped so Vortex-style trees compare correctly.
"""

import os
import hashlib

SKIP_NAMES = {
    "meta.ini",
    "MOD_LIST.txt",
    "COMPATIBILITY_NOTES.txt",
    "placeholder.vortex",
}


def _sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def rel_paths(root):
    """{game-relative path -> sha256} for every file under root.

    A leading `Cyberpunk 2077/` wrapper dir is stripped; separator
    normalized to '/'; SKIP_NAMES are excluded (pack metadata)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name in SKIP_NAMES:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel.startswith("Cyberpunk 2077/"):
                rel = rel[len("Cyberpunk 2077/"):]
            out[rel] = _sha256(full)
    return out


def baseline_hits(tree_paths, baseline_path):
    """Return {tree_label: [rel paths present in the baseline as well]}.

    tree_paths is a dict {label: {rel: sha}}. Those rel paths are exactly the
    files the pack would hard-overwrite if dropped onto the baseline."""
    ref = rel_paths(baseline_path) if os.path.isdir(baseline_path) else {}
    hits = {}
    for label, paths in tree_paths.items():
        shared = sorted(set(paths) & set(ref))
        if shared:
            hits[label] = shared
    return hits


def cross_tree(paths_by_label):
    """Return {rel: {"labels": [...], "identical": bool}} for paths that
    appear in more than one audited tree."""
    by_rel = {}
    for label, paths in paths_by_label.items():
        for rel, digest in paths.items():
            by_rel.setdefault(rel, {})[label] = digest
    cross = {}
    for rel, got in sorted(by_rel.items()):
        if len(got) < 2:
            continue
        digests = set(got.values())
        cross[rel] = {
            "labels": sorted(got),
            "identical": len(digests) == 1,
        }
    return cross


def audit(tree_labels, labels_and_paths, baseline=None):
    """Run the full overlap audit.

    tree_labels: ordered list of display names.
    labels_and_paths: {label: rel-path map} (from rel_paths()).
    baseline: optional path to a read-only reference tree.
    Returns a dict {trees: [...], baseline_hits: {...}, cross: {...},
    hard_overwrites: int, differing: [rel...]}."""
    result = {
        "trees": tree_labels,
        "counts": {label: len(paths)
                   for label, paths in labels_and_paths.items()},
        "baseline": os.path.abspath(baseline) if baseline else None,
        "baseline_hits": {},
        "cross": {},
        "hard_overwrites": 0,
        "differing": [],
    }
    if baseline:
        result["baseline_hits"] = baseline_hits(labels_and_paths, baseline)
        result["hard_overwrites"] = sum(
            len(v) for v in result["baseline_hits"].values())
    result["cross"] = cross_tree(labels_and_paths)
    result["differing"] = [rel for rel, info in result["cross"].items()
                           if not info["identical"]]
    return result


def format_audit(result):
    """Human-readable report for an audit() result dict."""
    lines = []
    lines.append("OVERLAP AUDIT — %d tree(s) vs baseline %s" % (
        len(result["trees"]),
        result["baseline"] or "(none, cross-tree only)"))
    for label in result["trees"]:
        lines.append("  %-40s %d file(s)" % (
            label, result["counts"].get(label, 0)))

    if result["baseline"]:
        lines.append("")
        if not result["baseline_hits"]:
            lines.append("baseline overlap : none (nothing hard-overwrites "
                         "the reference tree)")
        else:
            lines.append("baseline overlap : %d file(s) WOULD overwrite "
                         "the reference tree" % result["hard_overwrites"])
            for label, shared in result["baseline_hits"].items():
                lines.append("  %s:" % label)
                for rel in shared:
                    lines.append("      %s" % rel)

    lines.append("")
    cross = result["cross"]
    if not cross:
        lines.append("cross-tree       : none (no path appears in >1 tree)")
    else:
        lines.append("cross-tree same-path : %d path(s) in >1 tree" % len(cross))
        for rel, info in cross.items():
            tag = "IDENTICAL" if info["identical"] else "DIFFERENT !!"
            lines.append("  [%s] %s -> %s" % (
                tag, rel, ", ".join(info["labels"])))
    lines.append("")
    lines.append("hard overwrites vs baseline : %d   real conflicts : %d" % (
        result.get("hard_overwrites", 0), len(result.get("differing", []))))
    return "\n".join(lines)