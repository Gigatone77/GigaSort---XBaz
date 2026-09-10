"""Same-author redundancy + shared-mod-page analysis for GigaSort.

Three read-only analyses (never moves or deletes files):

1. find_superseded()   — same author produced an older mod whose features the
                        newer release likely covers (title/name overlap,
                        dependency superset, version keywords).
2. group_by_modpage()  — several downloads belonging to ONE Nexus mod page
                        (same mod id), labeled MAIN / VARIANT / OPTIONAL / OLD.
                        Analyzed inside each Category / Author folder.
3. check_placement()   — whole-batch verification that every mod sits where
                        the sort expects it (right category, right author,
                        one mod page not split across categories).
"""

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from gigasort.constants import ARCHIVE_EXTS, TOPLEVEL_AUTHORS
from gigasort.core.categorize import (
    categorize, extract_mod_author, extract_mod_id, candidate_mod_id,
    name_tokens,
)
from gigasort.core.sort import resolve_category
from gigasort.core import storage


# Scores at or above this threshold are reported as superseded.
STRONG_THRESHOLD = 0.6
POSSIBLE_THRESHOLD = 0.35


@dataclass
class SupersededMod:
    author: str
    old_fn: str
    new_fn: str
    score: float
    reasons: list
    category: str = ""


@dataclass
class SamePageGroup:
    category: str = ""
    author: str = ""
    mod_id: str = ""
    mod_name: str = ""
    files: list = field(default_factory=list)   # [(filename, role)]


@dataclass
class PlacementIssue:
    kind: str = ""          # "misplaced" | "root" | "split-page"
    fn: str = ""
    where: str = ""         # current location
    expected: str = ""      # where it should be
    detail: str = ""


def _mod_id_int(fn):
    """Nexus mod id as int (for chronological ordering), or 0."""
    mid = extract_mod_id(fn)
    return int(mid) if mid else 0


def _title_tokens(title):
    """Extract lowercase word tokens from a Nexus title string."""
    if not title:
        return set()
    # Strip common Nexus title decorations.
    t = re.sub(r"\s*[|\-–—]\s*Nexus\s*Mods.*$", "", title, flags=re.I)
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    t = re.sub(r"[-_.]", " ", t)
    return {w for w in t.lower().split() if len(w) > 1}


def _similarity(a_tokens, b_tokens):
    """Jaccard similarity between two token sets."""
    if not a_tokens or not b_tokens:
        return 0.0
    inter = a_tokens & b_tokens
    union = a_tokens | b_tokens
    return len(inter) / len(union) if union else 0.0


# Version/remake keywords in the NEWER title that signal an update. Only
# multi-letter/keyword forms are listed — bare digits/roman numerals match too
# many unrelated titles (e.g. any title containing "2").
_VERSION_KEYWORDS = (
    "v2", "v3", "v4", "2.0", "3.0", "4.0",
    "remaster", "remastered", "redux", "revamp", "overhaul",
    "updated", "rework", "reworked", "rewrite", "reborn",
    "plus", "expanded", "extended", "enhanced", "improved",
    "complete", "definitive", "ultimate", "collection",
)

# Strip Nexus id + version suffix for offline filename comparison.
# Matches: -12345-1-0, -12345-2, v2, v3.1, etc.
_OFFLINE_VER_RE = re.compile(r"-?\d{4,6}-.*$|[-_]v?\d+(\.\d+)*$", re.I)


def _strip_ver(name):
    """Remove Nexus id AND any vN/version segment (a single re.sub pass only
    removes one segment — 'sportscar-v1-44444-1-0' needs two). Loop until
    stable, then trim stray separators."""
    prev = None
    while prev != name:
        prev = name
        name = _OFFLINE_VER_RE.sub("", name).strip("- _.")
    return name

# Role markers in a filename, used to label files of one shared mod page.
_OLD_MARKERS = (
    "old version", "old-version", "old_version", "previous version",
    "previous-version", "legacy", " deprecated", "-old", " old ",
)
_OPTIONAL_MARKERS = (
    "optional", " addon", "-addon", " extra", "-extra", " alternate",
    "alternative", " alt files", "-alt", " alt ",
)
_VARIANT_MARKERS = (
    "variant", "variation", "-4k", "-2k", "-8k", "-light", "-dark",
    "-gold", "-silver", "-red", "-clear",
)


def classify_mod_file(fn):
    """Best-effort role of one file within its Nexus mod page."""
    low = fn.lower()
    if any(m in low for m in _OLD_MARKERS):
        return "OLD"
    if any(m in low for m in _OPTIONAL_MARKERS):
        return "OPTIONAL"
    if any(m in low for m in _VARIANT_MARKERS):
        return "VARIANT"
    return "MAIN"


_ROLE_ORDER = {"MAIN": 0, "VARIANT": 1, "OPTIONAL": 2, "OLD": 3}


def _fn_of(item):
    """Filename from a (fn, size) or (category, author, fn, size) entry."""
    return item[0] if len(item) == 2 else item[2]


def _author_is_listed(author, toplevel_authors):
    if not author:
        return False
    low = author.lower()
    return any(low == a.strip().lower() for a in toplevel_authors)


def _derive_mod_name(fn, author):
    """Clean offline mod name from a filename (author/id/version stripped).

    Casing is preserved from the filename (no verbatim title-casing).
    """
    base = os.path.splitext(os.path.basename(fn))[0]
    low = base
    if author:
        low = re.sub(r"^%s[\s_-]+" % re.escape(author.lower()), "", low,
                     flags=re.I)
    low = _strip_ver(low)
    for m in _OLD_MARKERS + _OPTIONAL_MARKERS + _VARIANT_MARKERS:
        low = re.sub(re.escape(m), " ", low, flags=re.I)
    low = re.sub(r"[-_\[\]()]+", " ", low)
    low = re.sub(r"\s+", " ", low).strip()
    return low if low else base


def _author_stripped_tokens(fn, author):
    """Filename tokens with the author segment removed.

    Within an author's own mods the author name is constant and would dilute
    the similarity between different mods. Remove it before comparing.
    """
    base = os.path.basename(fn)
    low = base.lower()
    if author:
        low = re.sub(r"^%s[\s_-]+" % re.escape(author.lower()), "", low)
    toks = name_tokens(low)
    return toks


def _score_pair(old_fn, new_fn, old_title, new_title, old_deps, new_deps,
                old_cat, new_cat, author=None):
    """Score how likely `new_fn` supersedes `old_fn`. Returns (score, reasons).

    Score is 0.0–1.0. Higher = more likely superseded.
    """
    score = 0.0
    reasons = []

    # Must be in the same category to be considered redundant.
    if old_cat and new_cat and old_cat != new_cat:
        return 0.0, ["different category"]

    old_toks = _title_tokens(old_title) or _author_stripped_tokens(old_fn, author)
    new_toks = _title_tokens(new_title) or _author_stripped_tokens(new_fn, author)

    sim = _similarity(old_toks, new_toks)

    # --- Title overlap (strongest signal) ---
    if sim >= 0.7:
        score += 0.5
        reasons.append("title overlap %.0f%%" % (sim * 100))
    elif sim >= 0.4:
        score += 0.3
        reasons.append("title overlap %.0f%%" % (sim * 100))
    elif sim >= 0.25:
        score += 0.15
        reasons.append("title overlap %.0f%%" % (sim * 100))

    # --- Containment (one title includes the other) ---
    if old_title and new_title:
        ot = old_title.lower()
        nt = new_title.lower()
        if ot in nt and sim < 0.7:
            score += 0.2
            reasons.append("newer title contains older")
        elif nt in ot and sim < 0.7:
            score += 0.15
            reasons.append("older title contains newer")

    # --- Filename containment (offline fallback when no titles are known) ---
    if not (old_title and new_title):
        old_stem = os.path.splitext(os.path.basename(old_fn))[0].lower()
        new_stem = os.path.splitext(os.path.basename(new_fn))[0].lower()
        if author:
            old_stem = re.sub(r"^%s[\s_-]+" % re.escape(author.lower()),
                              "", old_stem)
            new_stem = re.sub(r"^%s[\s_-]+" % re.escape(author.lower()),
                              "", new_stem)
        old_clean = _strip_ver(old_stem)
        new_clean = _strip_ver(new_stem)
        if old_clean and new_clean and old_clean == new_clean:
            score += 0.35
            reasons.append("same offline mod name (newer version)")
        elif old_clean and old_clean in new_clean and sim < 0.7:
            score += 0.25
            reasons.append("newer filename contains older mod name")

    # --- Dependency superset check ---
    if old_deps and new_deps:
        old_set = set(old_deps)
        new_set = set(new_deps)
        if old_set <= new_set and old_set != new_set:
            score += 0.15
            reasons.append("newer has all older deps + more")
        elif old_set & new_set:
            shared = old_set & new_set
            score += 0.05 * min(len(shared), 3)
            reasons.append("shared deps [%s]" % ", ".join(sorted(shared)[:3]))

    # --- "New version" keywords in the newer title ---
    if new_title:
        nw = new_title.lower()
        hits = [kw for kw in _VERSION_KEYWORDS if kw in nw]
        if hits:
            score += 0.15
            reasons.append("newer has keywords: %s" % ", ".join(hits[:3]))

    return min(score, 1.0), reasons


def _enrich_titles(mods, cache, folder):
    """Load Nexus titles for mods not already cached. Returns updated cache.

    Fully offline: titles come from the persistent mod-ID REFERENCE cache
    (verified on a previous run or seeded by the bundled offline info
    archive). One lookup per mod id — every file of the same mod page shares
    it.
    """
    cache = cache or {}
    by_id = defaultdict(list)
    for item in mods:
        fn = _fn_of(item)
        entry = cache.get(fn) or {}
        if entry.get("nexus_title"):
            continue
        mid = extract_mod_id(fn)
        if mid:
            by_id[mid].append(fn)

    changed = False
    refs = storage.load_references(folder) or {}
    for mid, fns in by_id.items():
        ref = refs.get(mid) or {}
        title = ref["title"] if ref.get("verified") and ref.get("title") else None
        if not title:
            continue
        for fn in fns:
            cache.setdefault(fn, {})["nexus_title"] = title
        changed = True
    if changed:
        storage.save_cache(folder, cache)
    return cache


def collect_context_entries(folder):
    """Every archive in the workspace with its expected sort context.

    Yields (category, author, filename, size): root files get their category
    from the offline rules, already-organized files from the category folder
    they actually sit under. Author always comes from the filename.
    """
    from gigasort.core.sort import collect_nested_archives

    entries = []
    for fn in sorted(os.listdir(folder)):
        full = os.path.join(folder, fn)
        if os.path.isfile(full) and fn.lower().endswith(ARCHIVE_EXTS):
            entries.append((categorize(fn), extract_mod_author(fn), fn,
                            os.path.getsize(full)))
    for fn, size, src in collect_nested_archives(folder):
        rel_dir = os.path.dirname(os.path.relpath(src, folder))
        top = rel_dir.split(os.sep)[0]
        cat = top if re.match(r"^\d{2} ", top) else categorize(fn)
        entries.append((cat, extract_mod_author(fn), fn, size))
    return entries


def find_superseded(folder, mods, cache=None, progress=None):
    """Detect mods from the same author where an older one is likely redundant.

    `mods` may be (filename, size) pairs or (category, author, filename, size)
    context entries. Analysis runs INSIDE each (category, author) folder so a
    hair mod and a cyberware mod by the same author are never compared.

    Returns a list of SupersededMod instances, sorted by score descending.
    Uses Nexus mod id as a chronological proxy (higher id = newer on Nexus).
    Read-only — never moves or deletes files.
    """
    mods = list(mods)
    cache = storage.load_cache(folder) if cache is None else cache
    cache = _enrich_titles(mods, cache, folder)

    # Group by (category, author) context.
    by_ctx = defaultdict(list)
    for item in mods:
        if len(item) == 4:
            cat, author, fn, size = item
        else:
            fn, size = item
            cat = categorize(fn)
            author = extract_mod_author(fn)
        if author:
            by_ctx[(cat or "", author)].append((fn, size))

    results = []
    for (cat, author), files in by_ctx.items():
        if len(files) < 2:
            continue
        # Sort by mod id (chronological — lower id = older on Nexus).
        files.sort(key=lambda ms: _mod_id_int(ms[0]))

        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                old_fn, _ = files[i]
                new_fn, _ = files[j]
                old_entry = cache.get(old_fn) or {}
                new_entry = cache.get(new_fn) or {}
                old_title = old_entry.get("nexus_title") or ""
                new_title = new_entry.get("nexus_title") or ""
                old_deps = old_entry.get("deps") or []
                new_deps = new_entry.get("deps") or []

                sc, reasons = _score_pair(
                    old_fn, new_fn, old_title, new_title,
                    old_deps, new_deps, cat, cat, author=author)

                if sc >= POSSIBLE_THRESHOLD:
                    results.append(SupersededMod(
                        author=author,
                        old_fn=old_fn,
                        new_fn=new_fn,
                        score=sc,
                        reasons=reasons,
                        category=cat,
                    ))
                if progress:
                    progress(old_fn)

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def group_by_modpage(entries, cache=None, folder=None):
    """Group downloads that share ONE Nexus mod page, inside each
    (category, author) folder.

    Returns a list of SamePageGroup (groups with 2+ files). Each file's role
    is classified MAIN / VARIANT / OPTIONAL / OLD from its filename. The mod
    name prefers the cached Nexus title, else an offline cleaned filename.
    """
    cache = cache or {}
    by_ctx = defaultdict(list)
    for cat, author, fn, size in entries:
        if not (cat or author) or not extract_mod_id(fn):
            continue
        by_ctx[(cat or "", author or "")].append((fn, size))

    groups = []
    for (cat, author), files in sorted(by_ctx.items()):
        by_page = defaultdict(list)
        for fn, _size in files:
            mid = extract_mod_id(fn)
            if mid:
                by_page[mid].append((fn, _size))
        for mid, same_page in sorted(by_page.items()):
            if len(same_page) < 2:
                continue
            title = next(
                (cache.get(fn, {}).get("nexus_title")
                 for fn, _ in same_page if cache.get(fn, {}).get("nexus_title")),
                "")
            labeled = [(fn, classify_mod_file(fn)) for fn, _ in same_page]
            labeled.sort(key=lambda f: _ROLE_ORDER[f[1]])
            name_src = next((fn for fn, r in labeled if r == "MAIN"),
                            labeled[0][0])
            mod_name = title or _derive_mod_name(name_src, author)
            groups.append(SamePageGroup(
                category=cat, author=author, mod_id=mid,
                mod_name=mod_name, files=labeled))
    return groups


def check_placement(folder, cache=None, entries=None, toplevel_authors=None,
                    author_plus_batch=None, group_frameworks=None):
    """Whole-batch verification that every mod is where the sort expects it.

    Reports three issue kinds:
      "misplaced"   — an already-organized mod sits in the wrong category /
                      author folder (uses the sort's own routing logic).
      "root"        — a verifiable mod still sits at the workspace root though
                      the current sort mode would place it in a folder.
      "split-page"  — files of ONE Nexus mod page are spread over several
                      category folders.
    Read-only — never moves or deletes.
    """
    from gigasort.core.sort import find_misplaced, scan_workspace

    settings = storage.load_settings(folder)
    if toplevel_authors is None:
        toplevel_authors = (settings.get("toplevel_authors")
                            or list(TOPLEVEL_AUTHORS))
    if author_plus_batch is None:
        author_plus_batch = bool(settings.get("author_plus_batch"))
    if group_frameworks is None:
        group_frameworks = bool(settings.get("group_frameworks"))
    cache = storage.load_cache(folder) if cache is None else cache

    issues = []

    # 1) Misplaced nested files (routing computed by the sort engine itself).
    try:
        for fn, src, dst, _size in find_misplaced(
                folder, toplevel_authors=toplevel_authors,
                author_plus_batch=author_plus_batch,
                group_frameworks=group_frameworks, cache=cache):
            where = os.path.relpath(os.path.dirname(src), folder)
            expected = os.path.relpath(os.path.dirname(dst), folder)
            issues.append(PlacementIssue("misplaced", fn, where, expected))
    except Exception:
        pass

    # 2) Root files that the current sort mode would place somewhere.
    result = scan_workspace(folder, toplevel_authors=toplevel_authors,
                            author_plus_batch=author_plus_batch,
                            group_frameworks=group_frameworks)
    for fn, _size in result.kept:
        if not candidate_mod_id(fn) or not extract_mod_author(fn):
            continue
        cat = resolve_category(fn, cache, storage.load_web_overrides(folder))
        author = extract_mod_author(fn)
        if author_plus_batch and cat:
            issues.append(PlacementIssue("root", fn, "workspace root", cat))
        elif _author_is_listed(author, toplevel_authors):
            issues.append(PlacementIssue("root", fn, "workspace root", author))

    # 3) One Nexus page split across category folders.
    if entries is None:
        entries = collect_context_entries(folder)
    by_page = defaultdict(set)
    by_page_fns = defaultdict(list)
    for cat, _author, fn, _size in entries:
        mid = extract_mod_id(fn)
        if not mid:
            continue
        by_page[mid].add(cat or "")
        by_page_fns[mid].append(fn)
    for mid, cats in by_page.items():
        real = {c for c in cats if c}
        if len(real) > 1:
            issues.append(PlacementIssue(
                "split-page", "mod page %s" % mid,
                ", ".join(sorted(real)), ", ".join(sorted(real)),
                "files of one Nexus page sit in different category folders: "
                + "; ".join(by_page_fns[mid][:5])))
    return issues


def print_superseded(results):
    """Pretty-print superseded-mod results to stdout (grouped by folder)."""
    if not results:
        print("  (no superseded mods detected)")
        return

    by_ctx = defaultdict(list)
    for r in results:
        by_ctx[(r.category, r.author)].append(r)

    for (cat, author), items in sorted(by_ctx.items()):
        heading = ("%s / %s" % (cat, author)) if cat else author
        print("\n  %s (%d potential)" % (heading, len(items)))
        for r in items:
            tag = "strong" if r.score >= STRONG_THRESHOLD else "possible"
            print("    [%s]  %s" % (tag, r.old_fn))
            print("      -> %s" % r.new_fn)
            print("      Reason: %s" % "; ".join(r.reasons))

    strong = sum(1 for r in results if r.score >= STRONG_THRESHOLD)
    possible = len(results) - strong
    print("\n  Summary: %d strong + %d possible superseded mod(s)"
          % (strong, possible))


def print_modpage_groups(groups):
    """Pretty-print same-mod-page groups (per Category / Author folder)."""
    if not groups:
        print("  (no mod has multiple downloads on one Nexus page)")
        return

    by_ctx = defaultdict(list)
    for g in groups:
        by_ctx[(g.category, g.author)].append(g)

    for (cat, author), items in sorted(by_ctx.items()):
        heading = ("%s / %s" % (cat, author)) if cat else (author or "root")
        print("\n  %s" % heading)
        for g in items:
            print("    [mod %s] %s  (%d file%s)" % (
                g.mod_id, g.mod_name, len(g.files),
                "s" if len(g.files) != 1 else ""))
            for fn, role in g.files:
                print("      %-8s  %s" % (role, fn))

    pages = len(groups)
    extra = sum(len(g.files) for g in groups) - pages
    print("\n  Summary: %d mod page(s) with multiple downloads "
          "(%d repeat/old/optional file(s))." % (pages, extra))


def print_placement(issues):
    """Pretty-print whole-batch placement issues."""
    if not issues:
        print("  All mods are where the sort expects them.")
        return
    labels = {
        "misplaced": "MISPLACED (sits in the wrong category/author folder)",
        "root": "NOT ORGANIZED (still at workspace root)",
        "split-page": "SPLIT ACROSS MORE THAN ONE CATEGORY (same Nexus page)",
    }
    by_kind = defaultdict(list)
    for i in issues:
        by_kind[i.kind].append(i)
    for kind, items in by_kind.items():
        print("\n  %s (%d):" % (labels.get(kind, kind), len(items)))
        for i in items:
            if kind == "split-page":
                print("    • %s" % i.fn)
                print("        in: %s" % i.where)
                if i.detail:
                    print("        %s" % i.detail)
            elif kind == "root":
                print("    • %-55s -> %s" % (i.fn, i.expected))
            else:
                print("    • %-55s %s -> %s" % (i.fn, i.where, i.expected))
    print("\n  Summary: %d placement issue(s)." % len(issues))


def analyze(folder, cache=None):
    """Run all three analyses. Returns (superseded, modpage_groups, issues)."""
    cache = storage.load_cache(folder) if cache is None else cache
    entries = collect_context_entries(folder)
    superseded = find_superseded(folder, entries, cache=cache)
    groups = group_by_modpage(entries, cache=cache, folder=folder)
    issues = check_placement(folder, cache=cache, entries=entries)
    return superseded, groups, issues


def run_superseded_report(folder):
    """Print the full author/mod analysis (superseded + same-page + placement)."""
    superseded, groups, issues = analyze(folder)
    print("=" * 70)
    print("SUPERSEDED MODS (same author, older may be redundant)")
    print("=" * 70)
    print_superseded(superseded)
    print()
    print("=" * 70)
    print("SAME MOD PAGE GROUPS (files of one Nexus mod, per Category/Author)")
    print("=" * 70)
    print_modpage_groups(groups)
    print()
    print("=" * 70)
    print("PLACEMENT CHECK (whole batch — mods not where they should be)")
    print("=" * 70)
    print_placement(issues)


def apply_warnings(folder):
    """Post-sort warning block used by --apply / --dry-run (read-only)."""
    try:
        superseded, _groups, issues = analyze(folder)
        if superseded:
            print("\n== SUPERSEDED MODS (same author, older may be redundant) ==")
            print_superseded(superseded)
        if issues:
            print("\n== PLACEMENT CHECK (mods not where they should be) ==")
            print_placement(issues)
    except Exception:
        pass