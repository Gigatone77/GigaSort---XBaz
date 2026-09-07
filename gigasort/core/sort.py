"""The core sort engine: scan, dedup, plan, preview, execute.

Design: scan_workspace() builds a ScanResult without side effects (read-only,
good for --dry-run/--json). execute_sort() performs the moves under the
safety guards and always reports the reject pile before touching anything.
"""

import os
import re
import time
from dataclasses import dataclass, field

from gigasort.constants import (
    ARCHIVE_EXTS, REJECT_BIN, TRASH_BIN, DUPLICATES_BIN, TOPLEVEL_AUTHORS,
    KNOWN_FRAMEWORKS, MAJOR_FRAMEWORKS,
)
from gigasort.core.categorize import (
    clean_name, categorize, extract_mod_author, extract_mod_id,
    candidate_mod_id,
)
from gigasort.core import storage
from gigasort.utils import fs, net
from gigasort.utils.format import human_size

# Categories always look like "NN Name"; anything in the verified cache that
# matches this is an authoritative folder decision (from Nexus or a prior run).
_CAT_FOLDER_RE = re.compile(r"^\d{2} ")


@dataclass
class ScanResult:
    folder: str
    kept: list = field(default_factory=list)      # [(fn, size)]
    duplicates: list = field(default_factory=list)  # [(fn, size)]
    rejects: list = field(default_factory=list)     # [(fn, size)]
    plan: dict = field(default_factory=dict)        # cat -> [(fn, size)]
    toplevel_authors: list = field(default_factory=list)
    author_plus_batch: bool = False
    group_frameworks: bool = False
    framework_of: dict = field(default_factory=dict)  # fn -> group name
    relocate: list = field(default_factory=list)      # [(fn, src, dst, size)]
    # fn -> [installed game paths it would overwrite]; files here go to
    # _ON_HOLD instead of their category until the user resolves the conflict.
    hold_conflicts: dict = field(default_factory=dict)
    # Whether a game directory was configured (enables the conflict check).
    game_dir: str = ""
    scanned_at: float = field(default_factory=time.time)

    @property
    def total_bytes(self):
        return sum(s for _, s in self.kept)

    @property
    def moved_count(self):
        return sum(len(v) for v in self.plan.values())


def _author_matches(author, toplevel_authors):
    """Case-insensitive author membership check."""
    if not author:
        return False
    low = author.lower()
    return any(low == a.strip().lower() for a in toplevel_authors)


# Name-based fallback so short-id frameworks (CET=107, AMM=790 - outside the
# 4-6 digit NEXUS_ID_RE range) still join their own group without any regex
# widening. Only consulted when extract_mod_id() finds no 4-6 digit id.
# Grouping only ever uses NICHE frameworks - see MAJOR_FRAMEWORKS.
_FW_NAME_TRIGGERS = {
    "Native Settings UI": ("nativesettingsui",),
    "AMM": ("appearancemenumod",),
    "Equipment-EX": ("equipmentex", "equipment-ex"),
    "Virtual Atelier": ("virtualatelier",),
    "Input Loader": ("inputloader",),
    "Codeware": ("codeware",),
}


def _framework_self_name(fn):
    """Niche framework group name if `fn` IS a framework mod itself (matched
    by its own Nexus id or by its name), else None. Only NICHE frameworks -
    MAJOR_FRAMEWORKS (CET/RED4ext/etc.) never return here."""
    mid = extract_mod_id(fn)
    if mid and mid in KNOWN_FRAMEWORKS and mid not in MAJOR_FRAMEWORKS:
        return KNOWN_FRAMEWORKS[mid]
    low = fn.lower()
    for fname, triggers in _FW_NAME_TRIGGERS.items():
        if any(t in low for t in triggers):
            return fname
    return None


def _is_managed_subdir(name, authors):
    """True if `name` is a top-level folder GigaSort could have created, so the
    re-sort may look inside it: numbered categories ('NN Name'), niche
    framework folders or a listed top-level author folder. Anything else (bins,
    state dirs, unrelated user folders) is never entered."""
    if re.match(r"^\d{2} ", name):
        return True
    if name in _FW_NAME_TRIGGERS:
        return True
    return any(name.lower() == a.strip().lower() for a in authors)


def collect_nested_archives(folder, toplevel_authors=None):
    """List archives sitting inside the already-organized sub-folders.

    Returns [(fn, size, src_abs)] for archives under managed top-level
    folders (numbered categories / framework / listed-author). The workspace
    root is NOT included (those are the normal keep/plan candidates), and bin
    or tool-state folders are never entered.
    """
    if toplevel_authors is None:
        toplevel_authors = list(TOPLEVEL_AUTHORS)
    archives = []
    for sub in sorted(os.listdir(folder)):
        if sub.startswith(("_", ".")):
            continue
        sub_path = os.path.join(folder, sub)
        if not os.path.isdir(sub_path):
            continue
        if not _is_managed_subdir(sub, toplevel_authors):
            continue
        for root, _dirs, files in os.walk(sub_path):
            for fn in files:
                if fn.lower().endswith(ARCHIVE_EXTS):
                    p = os.path.join(root, fn)
                    archives.append((fn, os.path.getsize(p), p))
    return archives


def resolve_category(fn, cache=None, web_overrides=None):
    """Best-known category folder for an archive.

    Preference order (each source is exhausted before the next is trusted):
      0. human-confirmed web overrides (``_GigaSort_web_overrides.json``,
         keyed by exact filename) — this is LIVE online info a person already
         acted on, so it beats EVERY deterministic guess below, including a
         keyword match. Prevents an offline keyword from silently reverting a
         verified web move on the next sort;
      1. offline filename-keyword categorize() — deterministic and reliable,
         and it wins over a conflicting cached 'nexus_cat' because that field
         is itself only a loose page-keyword guess, never a verified Nexus
         category slug;
      2. verified cache 'nexus_cat' — used only when the filename keywords
         produce no category (garbage/stale values recorded by an old lookup
         must not override a clear filename signal).

    Returns the folder name (e.g. "02 Hair") or None when nothing matches.
    """
    override = (web_overrides or {}).get(fn)
    if isinstance(override, str) and _CAT_FOLDER_RE.match(override):
        return override
    kw = categorize(fn)
    if kw:
        return kw
    entry = (cache or {}).get(fn) or {}
    ncat = entry.get("nexus_cat")
    if isinstance(ncat, str) and _CAT_FOLDER_RE.match(ncat):
        return ncat
    return None


def find_misplaced(folder, toplevel_authors=None, author_plus_batch=False,
                   group_frameworks=False, cache=None):
    """Detect already-organized mods sitting in an inconsistent folder.

    For every archive under the managed sub-folders, work out where the
    CURRENT sort mode would place it (listed author > category/framework >
    category) and compare it with where it actually sits. A difference means
    the file is out of place and is scheduled for relocation.

    Returns [(fn, src_abs, dst_abs, size)]. Uses cached dep data only (no
    network) and never touches bins, state dirs or unrelated user folders.
    If two copies of the same cleaned name would collide at one destination,
    only the largest one is relocated (the leftover stays put).
    """
    if toplevel_authors is None:
        toplevel_authors = list(TOPLEVEL_AUTHORS)
    else:
        toplevel_authors = list(toplevel_authors)
    cache = cache or {}
    web_overrides = storage.load_web_overrides(folder)

    nested = collect_nested_archives(folder, toplevel_authors)

    groups = {}
    if author_plus_batch and group_frameworks:
        try:
            groups = resolve_framework_groups(
                folder, [(fn, size) for fn, size, _ in nested],
                cache, toplevel_authors=toplevel_authors)
        except Exception:
            groups = {}

    reloc = []
    for fn, size, src in nested:
        author = extract_mod_author(fn)
        cur_rel = os.path.relpath(os.path.dirname(src), folder)
        if _author_matches(author, toplevel_authors):
            target = author
        elif author_plus_batch:
            cat = resolve_category(fn, cache, web_overrides)
            if cat is None:
                if group_frameworks and _framework_self_name(fn):
                    cat = "08 Cores, Fixes & Utilities"
                else:
                    continue
            parts = [cat]
            if fn in groups:
                parts.append(groups[fn])
            if author:
                parts.append(author)
            target = os.path.join(*parts)
        else:
            continue  # author-only mode: non-listed-author files untouched
        if cur_rel != target:
            reloc.append((fn, src, os.path.join(folder, target, fn), size))

    best = {}
    for item in reloc:
        key = clean_name(item[0])
        if key not in best or item[3] > best[key][3]:
            best[key] = item
    return list(best.values())


def resolve_framework_groups(folder, keep, cache, toplevel_authors=None):
    """Return {filename: framework-group-name} for the keep list, using only
    cached dependency data (no network).

    Grouping rules, in order:
      - a mod whose cached 'deps' contains a NICHE KNOWN_FRAMEWORKS id joins
        that framework folder (first niche id wins);
      - a niche framework mod itself (its own id is in KNOWN_FRAMEWORKS, or
        its name matches a framework trigger) joins its own folder so core +
        dependents sit together;
      - a dependency not in KNOWN_FRAMEWORKS that is required by 2+ downloads
        creates a dynamic "Framework <id>" group.
    Universal/always-present frameworks (MAJOR_FRAMEWORKS: CET, RED4ext,
    TweakXL, ArchiveXL) never form group folders - nearly every mod carries
    one, so they'd just create huge meaningless folders. Files belonging to a
    listed toplevel_authors author are never grouped either (author folder
    wins and is handled by the caller).
    """
    from collections import Counter

    cache = cache or {}
    ids = {fn: extract_mod_id(fn) for fn, _ in keep}
    deps_of = {}
    for fn, _ in keep:
        entry = cache.get(fn) or {}
        deps_of[fn] = [d for d in (entry.get("deps") or [])]

    # Author folders win over framework grouping.
    authors = list(toplevel_authors) if toplevel_authors else []
    grouped_ok = [fn for fn, _ in keep
                  if not _author_matches(extract_mod_author(fn), authors)]

    groups = {}
    for fn, deps in deps_of.items():
        if fn not in grouped_ok:
            continue
        for d in deps:
            if d in KNOWN_FRAMEWORKS and d not in MAJOR_FRAMEWORKS:
                groups[fn] = KNOWN_FRAMEWORKS[d]
                break
    for fn, mid in ids.items():
        if fn not in grouped_ok:
            continue
        if (mid and mid in KNOWN_FRAMEWORKS
                and mid not in MAJOR_FRAMEWORKS and fn not in groups):
            groups[fn] = KNOWN_FRAMEWORKS[mid]
        elif not mid and fn not in groups:
            low = fn.lower()
            for fname, triggers in _FW_NAME_TRIGGERS.items():
                if any(t in low for t in triggers):
                    groups[fn] = fname
                    break

    counter = Counter()
    for fn, deps in deps_of.items():
        if fn not in grouped_ok:
            continue
        for d in deps:
            if d not in KNOWN_FRAMEWORKS:
                counter[d] += 1
    for fn, deps in deps_of.items():
        if fn in groups or fn not in grouped_ok:
            continue
        for d in deps:
            if d not in KNOWN_FRAMEWORKS and counter[d] >= 2:
                groups[fn] = "Framework %s" % d
                break
    return groups


def rescue_category(folder, fn, cache=None):
    """Category for an already-verified mod whose offline filename keywords
    missed every folder rule.

    The ONLY thing allowed to pull a file out of the reject pile is an
    authoritative Nexus category: checked first from the mod-ID REFERENCE
    cache (keyed by mod id, filled from a previous run's live lookup), then
    the per-filename verified cache (nexus_cat), then the live Nexus page
    when online. A filename guess never overrides the offline keyword result
    here.

    All sources yield REAL folder names ("NN Name" style) -- never slugs. A
    value only counts when it is one of GigaSort's known folders.

    Returns the target folder name, or None when no Nexus category resolves
    (the file genuinely stays rejected). Never raises.
    """
    from gigasort.constants import KNOWN_FOLDERS

    cache = cache if cache is not None else {}
    entry = cache.get(fn) or {}
    cached = entry.get("nexus_cat")
    if isinstance(cached, str) and cached in KNOWN_FOLDERS:
        return cached
    mid = extract_mod_id(fn) or candidate_mod_id(fn)
    if not mid:
        return None
    # Reference cache (verified on a previous run, keyed by mod id) resolves
    # offline without touching the network.
    if folder or True:
        try:
            from gigasort.core import storage
            refs = storage.load_references(folder) or {}
            ref_entry = refs.get(mid) or {}
            if ref_entry.get("verified") and isinstance(
                    ref_entry.get("category"), str) \
                    and ref_entry["category"] in KNOWN_FOLDERS:
                return ref_entry["category"]
        except Exception:
            pass
    if not net.ALLOW_NET:
        return None
    try:
        _title, ncat = net.lookup_nexus_category(mid)
        if isinstance(ncat, str) and ncat in KNOWN_FOLDERS:
            if cache:
                cache.setdefault(fn, {})["nexus_cat"] = ncat
                cache[fn]["category"] = ncat
                storage.save_cache(folder, cache)
            return ncat
    except Exception:
        pass
    return None


def rescue_verified_rejects(folder, rejects, verified, cache=None):
    """Triple-check for the reject pile: a verified CP2077 mod is NEVER
    rejected just because its filename missed the category keywords.

    Verdict flow for every reject file:
      1) offline category keywords        (already failed -> this is why it's here)
      2) cached Nexus category            (nexus_cat recorded at verification)
      3) live Nexus page category         (only when ALLOW_NET)
    Only a file that fails all three stays in _REJECTS.

    Safety: only files already in `verified` are considered; everything else
    is left alone. Returns {filename: (category, size)} for rescued files.
    """
    cache = storage.load_cache(folder) if cache is None else cache
    rescued = {}
    for fn, size in rejects:
        if fn not in verified:
            continue
        cat = rescue_category(folder, fn, cache)
        if cat:
            rescued[fn] = (cat, size)
    return rescued


def rescue_rejects(folder, dry_run=False, input_fn=input, toplevel_authors=None):
    """Re-verify + re-categorize files already sitting inside the _REJECTS bin.

    Files that ended up in _REJECTS on a previous run are web-verified but
    uncategorized (their filename missed the offline keywords AND no Nexus
    category resolved at the time - often because the tool thought it was
    offline). This pass looks each one up AGAIN (mod-ID reference cache ->
    verified cache -> live Nexus page, now including login-gated adult pages)
    and moves every verified file that has since gained a real folder out of
    the bin and into its category. Genuinely unclassifiable/unverified files
    stay in the bin, reported.

    Safety: only web-verified Cyberpunk 2077 mods are moved; everything else
    is reported and LEFT IN PLACE. Never deletes, never overwrites.
    Returns the number of files rescued from the bin.
    """
    from gigasort.core import storage, verify
    if toplevel_authors is None:
        toplevel_authors = list(TOPLEVEL_AUTHORS)

    bin_dir = os.path.join(folder, REJECT_BIN)
    if not os.path.isdir(bin_dir):
        print("No %s bin - nothing to rescue." % REJECT_BIN)
        return 0

    items = []
    for fn in sorted(os.listdir(bin_dir)):
        full = os.path.join(bin_dir, fn)
        if os.path.isfile(full) and fn.lower().endswith(ARCHIVE_EXTS):
            items.append((fn, os.path.getsize(full)))

    if not items:
        print("No archives in %s - nothing to rescue." % REJECT_BIN)
        return 0

    cache = storage.load_cache(folder)
    verified, _flagged = verify.build_allowlist(items, cache, folder=folder)

    # Fetch dep data (optional, read-only) so the reference cache is fresh.
    try:
        verify.fetch_dependencies(folder, items)
    except Exception:
        pass

    rescued = []
    still = []
    for fn, size in items:
        if fn not in verified:
            still.append((fn, "UNVERIFIED - left in place"))
            continue
        cat = rescue_category(folder, fn, cache)
        if not cat:
            still.append((fn, "verified but no Nexus category resolves"))
            continue
        # Move out of the bin into the same layout the plan uses.
        src = os.path.join(bin_dir, fn)
        author = extract_mod_author(fn)
        if author and _author_matches(author, toplevel_authors):
            dst_dir = os.path.join(folder, author)
        else:
            dst_dir = os.path.join(folder, cat, author) if author \
                else os.path.join(folder, cat)
        dst = os.path.join(dst_dir, fn)
        if _move_skip_collision(folder, src, dst, dry_run=dry_run,
                                input_fn=input_fn):
            rescued.append(fn)

    print("\n=== RESCUE %s ===" % REJECT_BIN)
    if rescued:
        for fn in rescued:
            print("  -> %s" % fn)
        print("Rescued %d verified mod(s) from %s."
              % (len(rescued), REJECT_BIN))
    else:
        print("  (nothing moved%s)" % (" - dry run" if dry_run else ""))
    if still:
        print("\nLeft in %s:" % REJECT_BIN)
        for fn, why in still:
            print("  • %s  (%s)" % (fn, why))
    return len(rescued)


def scan_workspace(folder, toplevel_authors=None, author_plus_batch=False,
                   group_frameworks=False, game_dir=None):
    """Read the workspace, group by cleaned name, decide keep/dupe, and
    categorize the keepers. Pure/read-only.

    Modes:
      author_plus_batch=False (default): only files whose author is in
          toplevel_authors are planned (moved to their own folder). Every
          other file is left untouched in place.
      author_plus_batch=True: the listed authors get their own folder AND the
          general category organization runs in parallel on all other files.
    When group_frameworks=True, framework groups are resolved from cached
    dependency data (never live network here) and stored in framework_of.

    `game_dir` (a real Cyberpunk 2077 install) enables the game-directory
    conflict check: any keep file that would OVERWRITE an already-installed
    mod file is routed to _ON_HOLD instead of its category (via
    hold_conflicts). When game_dir is None it is read from the workspace
    settings; if still unset the conflict check is disabled entirely.
    """
    if toplevel_authors is None:
        toplevel_authors = list(TOPLEVEL_AUTHORS)
    else:
        toplevel_authors = list(toplevel_authors)

    if game_dir is None:
        try:
            game_dir = (storage.load_settings(folder) or {}).get("game_dir") or ""
        except Exception:
            game_dir = ""
    game_dir = game_dir or ""

    archives = []
    for fn in sorted(os.listdir(folder)):
        full = os.path.join(folder, fn)
        if os.path.isfile(full) and fn.lower().endswith(ARCHIVE_EXTS):
            archives.append((fn, os.path.getsize(full)))

    by_clean = {}
    for fn, size in archives:
        by_clean.setdefault(clean_name(fn), []).append((fn, size))

    # Detect root-level copies of mods already organized inside the managed
    # sub-folders. A same-cleaned-name file deeper in the tree means the root
    # archive is a repeat download: keep the organized copy, classify the root
    # one as a duplicate so it goes to _DUPLICATES instead of trying to
    # overwrite the nested file and aborting the whole sort.
    nested_names = set()
    for fn, _size, _p in collect_nested_archives(folder, toplevel_authors):
        nested_names.add(clean_name(fn))

    keep, dupes = [], []
    for clean, group in by_clean.items():
        if clean in nested_names:
            # The mod already exists organized below the workspace root.
            dupes.extend(group)
            continue
        non_suffixed = [g for g in group if os.path.basename(g[0]) == clean]
        if non_suffixed:
            keep.append(non_suffixed[0])
            dupes.extend(g for g in group if g not in non_suffixed)
        else:
            best = max(group, key=lambda g: g[1])
            keep.append(best)
            dupes.extend(g for g in group if g != best)

    # Load the verified cache up front so EVERY category decision below sees
    # the strongest available source (live-verified Nexus category) before
    # falling back to offline filename keywords.
    cache = {}
    try:
        cache = storage.load_cache(folder)
    except Exception:
        pass
    try:
        web_overrides = storage.load_web_overrides(folder)
    except Exception:
        web_overrides = {}

    plan, rejects = {}, []
    for fn, size in keep:
        cat = resolve_category(fn, cache, web_overrides)
        author = extract_mod_author(fn)
        is_top = _author_matches(author, toplevel_authors)
        if is_top:
            plan.setdefault(cat or author, []).append((fn, size))
        elif author_plus_batch:
            if cat is None:
                if group_frameworks and _framework_self_name(fn):
                    # A niche framework's own zip is its category's framework
                    # folder's core member - give it the obvious home so it is
                    # always inside a category.
                    cat = "08 Cores, Fixes & Utilities"
                    plan.setdefault(cat, []).append((fn, size))
                else:
                    rejects.append((fn, size))
            else:
                plan.setdefault(cat, []).append((fn, size))
        # else: not a listed author and not in batch mode -> left in place

    framework_of = {}
    relocate = []
    try:
        if group_frameworks:
            framework_of = resolve_framework_groups(
                folder, keep, cache, toplevel_authors=toplevel_authors)
        relocate = find_misplaced(folder, toplevel_authors=toplevel_authors,
                                  author_plus_batch=author_plus_batch,
                                  group_frameworks=group_frameworks,
                                  cache=cache)
    except Exception:
        pass

    # Game-directory conflict check: a keep file that would OVERWRITE an
    # already-installed mod file is routed to _ON_HOLD instead of its category.
    # Runs only when game_dir is set (otherwise disabled / a no-op).
    hold_conflicts = {}
    if game_dir:
        try:
            from gigasort.core import conflict
            hold_conflicts = conflict.find_conflicts(
                folder, [fn for fn, _ in keep], game_dir)
        except Exception:
            pass

    return ScanResult(folder=folder, kept=keep, duplicates=dupes,
                      rejects=rejects, plan=plan,
                      toplevel_authors=toplevel_authors,
                      author_plus_batch=author_plus_batch,
                      group_frameworks=group_frameworks,
                      framework_of=framework_of,
                      relocate=relocate,
                      hold_conflicts=hold_conflicts,
                      game_dir=game_dir)


def build_verified_gate(folder, kept):
    """Web-verify the keep list per the 'never touch unverified' rule.

    Returns (verified_fns, flagged_fns): the allowlist used by the move paths.
    Only filenames in verified_fns may be moved. Uses the local verified cache
    first, then a read-only Nexus lookup.
    """
    from gigasort.core import storage, verify
    cache = storage.load_cache(folder)
    kept_list = [(fn, size) for fn, size in kept]
    verified, flagged = verify.build_allowlist(kept_list, cache, folder=folder)
    if verified:
        storage.save_cache(folder, cache)
    return verified, flagged



def print_plan(result, dry_run):
    """Report rejects, duplicates and planned moves — always before commit."""
    print("=" * 70)
    print("REJECT PILE  (files that matched no category)")
    print("=" * 70)
    if result.rejects:
        for fn, size in result.rejects:
            print("  %s   (%s)" % (fn, human_size(size)))
        print("  Rejects go into exactly one of: '%s' (review) or '%s' "
              "(trash, never auto-deleted)." % (REJECT_BIN, TRASH_BIN))
    else:
        print("  (none - every file categorized)")
    print()

    print("=" * 70)
    print("DUPLICATES  (suffixed copies kept separately, never deleted)")
    print("=" * 70)
    if result.duplicates:
        for fn, size in result.duplicates:
            print("  %s   (%s)" % (fn, human_size(size)))
    else:
        print("  (none)")
    print()

    print("=" * 70)
    print("PLANNED MOVES" + ("  (DRY RUN - nothing moved)" if dry_run else ""))
    print("=" * 70)
    if not result.author_plus_batch:
        print("  (author-only mode - only listed authors are sorted;")
        print("   every other file is left in place)")
    for cat in sorted(result.plan):
        files = result.plan[cat]
        print("\n[%s]  (%d files)" % (cat, len(files)))
        for fn, size in files:
            author = extract_mod_author(fn)
            dst_show = os.path.join(cat, fn)
            if author and _author_matches(author, result.toplevel_authors):
                dst_show = os.path.join(author, fn)
            elif fn in result.framework_of:
                fw = os.path.join(cat, result.framework_of[fn])
                dst_show = (os.path.join(fw, author, fn) if author
                            else os.path.join(fw, fn))
            print("    -> %s   (%s)" % (dst_show, human_size(size)))
    print()

    print("=" * 70)
    print("RELOCATE  (already-organized mods sitting in the wrong folder)")
    print("=" * 70)
    if result.relocate:
        for fn, src, dst, size in result.relocate:
            src_show = os.path.relpath(src, result.folder)
            dst_show = os.path.relpath(dst, result.folder)
            print("  %s   (%s)\n     %s\n  -> %s"
                  % (fn, human_size(size), src_show, dst_show))
    else:
        print("  (none - already-organized files are where they belong)")
    print()


def _to_bin(folder, filename, bin_name, dry_run, input_fn=input):
    """Move one file into a bin, enforcing the one-bin rule."""
    storage.prepare_one_bin(folder, filename, bin_name, dry_run)
    bin_dir = os.path.join(folder, bin_name)
    fs.guarded_makedirs(folder, bin_dir, input_fn=input_fn)
    src = os.path.join(folder, filename)
    dst = os.path.join(bin_dir, filename)
    if os.path.abspath(src) != os.path.abspath(dst):
        fs.guarded_move(folder, src, dst, dry_run=dry_run, input_fn=input_fn)


def route_hold_conflicts(result, verified, dry_run=False, input_fn=input):
    """Move game-directory-conflicting files to the _ON_HOLD review bin.

    For every file that would OVERWRITE an installed game file (per
    result.hold_conflicts), pull it out of the normal category plan and move
    it to _ON_HOLD so the user reviews it before placement. Only VERIFIED
    files are moved (a held conflict is still a real CP2077 mod — never touch
    the unverified). Returns the number moved.
    """
    if not result.hold_conflicts:
        return 0
    folder = result.folder
    moved = 0
    conflicts = dict(result.hold_conflicts)
    # Remove conflicted files from every category bucket so they are not
    # placed normally; they go to _ON_HOLD instead.
    for cat, files in list(result.plan.items()):
        kept_list = []
        for fn, size in files:
            if fn in conflicts:
                if fn in verified:
                    _to_bin(folder, fn, "_ON_HOLD", dry_run, input_fn)
                    moved += 1
                    print("  -> _ON_HOLD (conflict): %s" % fn)
                    for p in conflicts[fn]:
                        print("      overwrites installed: %s" % p)
            else:
                kept_list.append((fn, size))
        if kept_list:
            result.plan[cat] = kept_list
        else:
            del result.plan[cat]
    return moved


def execute_sort(result, dry_run=False, input_fn=input, toplevel_authors=None):
    """Execute the plan under the safety guards. Returns moved count.

    SAFETY: the 'never touch unverified' rule is absolute here. Only files
    web-verified as real Cyberpunk 2077 mods (or already APPROVED in cache)
    may be moved, trashed, or otherwise altered. Everything else is reported
    and LEFT IN PLACE regardless of the user's reject choice.
    """
    folder = result.folder
    moved = 0
    if toplevel_authors is None:
        toplevel_authors = result.toplevel_authors or list(TOPLEVEL_AUTHORS)
    else:
        toplevel_authors = list(toplevel_authors)
    plus_batch = result.author_plus_batch

    # In author-only mode only files from listed authors are ever touched;
    # everything else is left exactly where it is.
    relevant_dupes = [(fn, s) for fn, s in result.duplicates
                      if plus_batch or _author_matches(
                          extract_mod_author(fn), toplevel_authors)]

    plan_files = [fn for files in result.plan.values() for fn, _ in files]
    reject_files = [fn for fn, _ in result.rejects] if plus_batch else []
    to_verify = [(fn, 0) for fn in plan_files + reject_files]
    to_verify += relevant_dupes
    to_verify += [(fn, s) for fn, _src, _dst, s in result.relocate]
    # Also re-verify anything already sitting in the _REJECTS bin: a file may
    # have been binned by a TRANSIENT lookup failure (rate-limit/5xx) on an
    # earlier run even though it is a real Nexus mod. Including it in the
    # gate lets this run repair that - a verified mod is never stranded just
    # because one fetch hiccoughed.
    bin_dir = os.path.join(folder, REJECT_BIN)
    bin_files = []
    if os.path.isdir(bin_dir):
        bin_files = [(fn, 0) for fn in os.listdir(bin_dir)
                     if os.path.isfile(os.path.join(bin_dir, fn))]
        to_verify += bin_files
    verified, flagged = build_verified_gate(folder, to_verify)

    # Rescue verified mods from the reject pile. 'Matched no category keyword'
    # is NOT the same as 'not a mod': a web-verified Nexus mod whose filename
    # missed the offline keywords is re-classified from its authoritative
    # Nexus category (cached first, live page when online) and sorted into a
    # real folder. Only genuinely unclassifiable files remain rejects.
    rescued = {}
    if result.rejects and plus_batch:
        rescued = rescue_verified_rejects(
            folder, result.rejects, verified, storage.load_cache(folder))
        for rfn, (rcat, rsize) in rescued.items():
            result.rejects = [(f, s) for f, s in result.rejects if f != rfn]
            result.plan.setdefault(rcat, []).append((rfn, rsize))
        if rescued:
            print("Rescued %d verified mod(s) from rejects (Nexus category):"
                  % len(rescued))
            for rfn, (_rcat, _sz) in rescued.items():
                print("  -> %s" % rfn)

    # Rejects (report + prompt, mirroring the always-ask behaviour).
    if result.rejects and plus_batch:
        print("\n" + "=" * 70)
        print("REJECT PILE - action required")
        print("=" * 70)
        verified_rejects = [fn for fn, _ in result.rejects if fn in verified]
        unverified = [fn for fn, _ in result.rejects if fn not in verified]
        reject_sizes = dict(result.rejects)
        for fn, _size in result.rejects:
            print("  • %s  (no category after keyword + Nexus triple-check)" % fn)
        if unverified:
            print("\n  UNVERIFIED (left in place, never touched):")
            for fn in unverified:
                print("    • %s" % fn)
        if not verified_rejects:
            print("\n  No verified rejects to act on - all reject files kept.")
        else:
            try:
                mode = input_fn("  [b] Batch to _REJECTS | [i] Individual | "
                                "[r] Batch to _TRASH | [s] Skip: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                mode = "s"
            if mode == "s":
                print("  Skipping rejects - left in place.")
            elif mode == "i":
                for fn in verified_rejects:
                    print("\n  • %s (%s)" % (fn, human_size(reject_sizes[fn])))
                    act = input_fn("      [1] _REJECTS | [2] _TRASH | [k] keep: "
                                   "").strip().lower()
                    if act == "1":
                        _to_bin(folder, fn, REJECT_BIN, dry_run, input_fn)
                    elif act == "2":
                        _to_bin(folder, fn, TRASH_BIN, dry_run, input_fn)
            elif mode == "r":
                for fn in verified_rejects:
                    _to_bin(folder, fn, TRASH_BIN, dry_run, input_fn)
                print("  Batch: moved verified rejects to %s." % TRASH_BIN)
            else:
                for fn in verified_rejects:
                    _to_bin(folder, fn, REJECT_BIN, dry_run, input_fn)
                print("  Batch: moved verified rejects to %s." % REJECT_BIN)

    # Game-directory conflicts -> _ON_HOLD (a verified mod that would
    # overwrite an installed file is reviewed, not sorted into its category).
    held_conflicts = route_hold_conflicts(
        result, verified, dry_run=dry_run, input_fn=input_fn)

    # Plan destinations:
    #   listed author     -> <author>/<file>                (top-level folder)
    #   niche framework   -> <cat>/<framework>/<author?>/<file>
    #   otherwise         -> <cat>/<author?>/<file>
    # The framework folder lives INSIDE the mod's category, so a framework
    # (e.g. Virtual Atelier) can exist in several category folders while each
    # mod - including the core framework zip - stays within its own category.
    groups = {}
    if result.group_frameworks and plus_batch:
        try:
            groups = resolve_framework_groups(
                folder, result.kept, storage.load_cache(folder),
                toplevel_authors=toplevel_authors)
        except Exception:
            groups = {}
    for cat, files in result.plan.items():
        for fn, _ in files:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            author = extract_mod_author(fn)
            if author and _author_matches(author, toplevel_authors):
                auth_dir = os.path.join(folder, author)
                fs.guarded_makedirs(folder, auth_dir, input_fn=input_fn)
                dst = os.path.join(auth_dir, fn)
            elif fn in groups:
                cat_dir = os.path.join(folder, cat)
                fs.guarded_makedirs(folder, cat_dir, input_fn=input_fn)
                grp_dir = os.path.join(cat_dir, groups[fn])
                fs.guarded_makedirs(folder, grp_dir, input_fn=input_fn)
                if author:
                    auth_dir = os.path.join(grp_dir, author)
                    fs.guarded_makedirs(folder, auth_dir, input_fn=input_fn)
                    dst = os.path.join(auth_dir, fn)
                else:
                    dst = os.path.join(grp_dir, fn)
            else:
                cat_dir = os.path.join(folder, cat)
                fs.guarded_makedirs(folder, cat_dir, input_fn=input_fn)
                if author:
                    auth_dir = os.path.join(cat_dir, author)
                    fs.guarded_makedirs(folder, auth_dir, input_fn=input_fn)
                    dst = os.path.join(auth_dir, fn)
                else:
                    dst = os.path.join(cat_dir, fn)
            if _move_skip_collision(folder, src, dst, dry_run=dry_run,
                                    input_fn=input_fn):
                moved += 1

    # Already-organized files sitting in the wrong place -> relocate them to
    # where this mode would have put them (verified only).
    relocated = 0
    for fn, src, dst, _size in result.relocate:
        if fn not in verified:
            flagged.add(fn)
            continue
        fs.guarded_makedirs(folder, os.path.dirname(dst), input_fn=input_fn)
        if _move_skip_collision(folder, src, dst, dry_run=dry_run,
                                input_fn=input_fn):
            relocated += 1
    moved += relocated

    # Duplicates -> _DUPLICATES (verified only, listed authors in the
    # author-only mode).
    if relevant_dupes:
        dup_dir = os.path.join(folder, DUPLICATES_BIN)
        fs.guarded_makedirs(folder, dup_dir, input_fn=input_fn)
        for fn, _ in relevant_dupes:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            dst = os.path.join(dup_dir, fn)
            if _move_skip_collision(folder, src, dst, dry_run=dry_run,
                                    input_fn=input_fn):
                moved += 1

    if flagged:
        print("\nNOT TOUCHED (%d unverified - never moved/trashed):" % len(flagged))
        for fn in sorted(flagged):
            print("  • %s" % fn)

    # Repair stranded _REJECTS: a verified Nexus mod whose category now
    # resolves (cached ref, live Nexus page, or login-gated og:identity) is
    # pulled OUT of the reject bin and sorted into its folder. The bin may
    # have been caused by a transient lookup failure on an earlier run.
    # Only web-verified files move; everything else stays in the bin,
    # reported. Never deletes.
    rescued_bin = 0
    if plus_batch and bin_files:
        for rfn, (rcat, _rsize) in rescue_verified_rejects(
                folder, bin_files, verified, storage.load_cache(folder)).items():
            src = os.path.join(bin_dir, rfn)
            cat_dir = os.path.join(folder, rcat)
            fs.guarded_makedirs(folder, cat_dir, input_fn=input_fn)
            author = extract_mod_author(rfn)
            if author and _author_matches(author, toplevel_authors):
                auth_dir = os.path.join(cat_dir, author)
                fs.guarded_makedirs(folder, auth_dir, input_fn=input_fn)
                dst = os.path.join(auth_dir, rfn)
            else:
                dst = os.path.join(cat_dir, rfn)
            if _move_skip_collision(folder, src, dst, dry_run=dry_run,
                                    input_fn=input_fn):
                moved += 1
                rescued_bin += 1
                print("  rescued from %s: %s -> %s" % (REJECT_BIN, rfn, rcat))
        if rescued_bin:
            print("Rescued %d previously-binned verified mod(s) out of %s."
                  % (rescued_bin, REJECT_BIN))

    # Sweep empty folders left behind by the sort (only truly empty dirs).
    pruned = prune_empty_dirs(folder, dry_run=dry_run)

    _write_tags_safe(folder)
    return {
        "moved": moved,
        "to_rejects": 0,
        "rescued": len(rescued),
        "duplicates": len(result.duplicates),
        "archives": len(result.kept) + len(result.duplicates),
        "dry_run": bool(dry_run),
        "flagged_unverified": sorted(flagged),
        "relocated": relocated,
        "pruned": pruned,
        "held_conflicts": held_conflicts,
    }


def _move_skip_collision(folder, src, dst, dry_run=False, input_fn=None,
                         dup_bin=DUPLICATES_BIN):
    """Move src -> dst, but never abort the whole sort on a name collision.

    If `dst` already holds a file with the same name (a leftover root copy of a
    mod that is already organized/rejected below the workspace root), the
    source is a duplicate download: it is MOVED into `dup_bin` instead of
    erroring out, so one run can finish regardless of pre-existing copies.
    If the duplicate bin already holds that name too, the source is left in
    place (never overwritten, never deleted).
    """
    if os.path.abspath(src) == os.path.abspath(dst):
        return False
    if os.path.exists(dst):
        dup_dst = os.path.join(folder, dup_bin, os.path.basename(src))
        if os.path.exists(dup_dst):
            return False
        fs.guarded_makedirs(folder, os.path.dirname(dup_dst),
                            input_fn=input_fn or input,
                            strict=False)
        fs.guarded_move(folder, src, dup_dst, dry_run=dry_run,
                        input_fn=input_fn or input)
        storage.record_move(folder, src, dup_dst, dry_run)
        return True
    fs.guarded_makedirs(folder, os.path.dirname(dst), input_fn=input_fn or input)
    fs.guarded_move(folder, src, dst, dry_run=dry_run, input_fn=input_fn or input)
    storage.record_move(folder, src, dst, dry_run)
    return True


def run_batch_sort(folder, dry_run=False, to_rejects=True, toplevel_authors=None,
                   author_plus_batch=False, group_frameworks=False,
                   game_dir=None):
    """Headless, non-interactive sort (used by --apply and the agent bridge's
    batch-sort op). Returns a summary dict.

    SAFETY: only web-verified Cyberpunk 2077 mods are ever moved. Any file
    that is not confirmed (no Nexus mod id, or the page does not resolve to a
    real CP2077 mod) is routed to _REJECTS instead of being sorted or deleted.
    """
    from gigasort.core import tags as tags_mod, verify

    if toplevel_authors is None:
        toplevel_authors = list(TOPLEVEL_AUTHORS)
    else:
        toplevel_authors = list(toplevel_authors)

    result = scan_workspace(folder, toplevel_authors=toplevel_authors,
                            author_plus_batch=author_plus_batch,
                            group_frameworks=group_frameworks,
                            game_dir=game_dir)
    moved = 0
    plus_batch = author_plus_batch or result.author_plus_batch

    # In author-only mode only listed authors' files are ever touched.
    relevant_dupes = [(fn, s) for fn, s in result.duplicates
                      if plus_batch or _author_matches(
                          extract_mod_author(fn), toplevel_authors)]
    plan_files = [fn for files in result.plan.values() for fn, _ in files]
    reject_files = [fn for fn, _ in result.rejects] if plus_batch else []
    relocate_files = [(fn, s) for fn, _src, _dst, s in result.relocate]

    # Fetch dep data first so framework grouping is complete before moving.
    groups = {}
    if plus_batch and group_frameworks:
        try:
            nested = collect_nested_archives(folder, toplevel_authors)
            verify.fetch_dependencies(
                folder, [(fn, 0) for fn in plan_files + reject_files])
            verify.fetch_dependencies(
                folder, [(fn, sz) for fn, sz, _ in nested])
            cache = storage.load_cache(folder)
            groups = resolve_framework_groups(
                folder, result.kept, cache, toplevel_authors=toplevel_authors)
            result.relocate = find_misplaced(
                folder, toplevel_authors=toplevel_authors,
                author_plus_batch=plus_batch,
                group_frameworks=group_frameworks, cache=cache)
        except Exception:
            groups = {}
    relocate_files = [(fn, s) for fn, _src, _dst, s in result.relocate]

    # Also re-verify anything already sitting in the _REJECTS bin: a file may
    # have been binned by a TRANSIENT lookup failure (rate-limit/5xx) on an
    # earlier run even though it is a real Nexus mod. Including it in the
    # gate lets this run repair that - a verified mod is never stranded just
    # because one fetch hiccoughed.
    bin_dir = os.path.join(folder, REJECT_BIN)
    bin_files = []
    if os.path.isdir(bin_dir):
        bin_files = [(fn, 0) for fn in os.listdir(bin_dir)
                     if os.path.isfile(os.path.join(bin_dir, fn))]

    verified, flagged = build_verified_gate(
        folder, [(fn, 0) for fn in plan_files + reject_files]
        + relevant_dupes + relocate_files + bin_files)

    # Rescue verified mods from the reject pile (Nexus-category triple-check).
    rescued = {}
    if result.rejects and plus_batch:
        rescued = rescue_verified_rejects(
            folder, result.rejects, verified, storage.load_cache(folder))
        for rfn, (rcat, rsize) in rescued.items():
            result.rejects = [(f, s) for f, s in result.rejects if f != rfn]
            result.plan.setdefault(rcat, []).append((rfn, rsize))

    # Game-directory conflicts -> _ON_HOLD (reviewed, not placed normally).
    held_conflicts = route_hold_conflicts(result, verified, dry_run=dry_run)

    # Every planned move is allowed only if the file is verified.
    for cat, files in list(result.plan.items()):
        for fn, _ in files:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            author = extract_mod_author(fn)
            if author and _author_matches(author, toplevel_authors):
                auth_dir = os.path.join(folder, author)
                fs.guarded_makedirs(folder, auth_dir)
                dst = os.path.join(auth_dir, fn)
            elif fn in groups:
                cat_dir = os.path.join(folder, cat)
                fs.guarded_makedirs(folder, cat_dir)
                grp_dir = os.path.join(cat_dir, groups[fn])
                fs.guarded_makedirs(folder, grp_dir)
                if author:
                    auth_dir = os.path.join(grp_dir, author)
                    fs.guarded_makedirs(folder, auth_dir)
                    dst = os.path.join(auth_dir, fn)
                else:
                    dst = os.path.join(grp_dir, fn)
            else:
                cat_dir = os.path.join(folder, cat)
                fs.guarded_makedirs(folder, cat_dir)
                if author:
                    auth_dir = os.path.join(cat_dir, author)
                    fs.guarded_makedirs(folder, auth_dir)
                    dst = os.path.join(auth_dir, fn)
                else:
                    dst = os.path.join(cat_dir, fn)
            if _move_skip_collision(folder, src, dst, dry_run=dry_run):
                moved += 1

    # Verified rejects go to _REJECTS; unverified flagged files are NEVER
    # touched (left in place so nothing is auto-moved or lost). In the
    # author-only mode there are no rejects (other files stay in place).
    verified_rejects = [fn for fn, _ in result.rejects if fn in verified]
    if verified_rejects and to_rejects and plus_batch:
        bin_dir = os.path.join(folder, REJECT_BIN)
        fs.guarded_makedirs(folder, bin_dir)
        for fn in verified_rejects:
            storage.prepare_one_bin(folder, fn, REJECT_BIN, dry_run)
            src = os.path.join(folder, fn)
            dst = os.path.join(bin_dir, fn)
            if os.path.abspath(src) != os.path.abspath(dst):
                _move_skip_collision(folder, src, dst, dry_run=dry_run)

    # Duplicates: only verified duplicates may move (listed authors in the
    # author-only mode).
    if relevant_dupes:
        dup_dir = os.path.join(folder, DUPLICATES_BIN)
        fs.guarded_makedirs(folder, dup_dir)
        for fn, _ in relevant_dupes:
            if fn not in verified:
                flagged.add(fn)
                continue
            src = os.path.join(folder, fn)
            dst = os.path.join(dup_dir, fn)
            if _move_skip_collision(folder, src, dst, dry_run=dry_run):
                moved += 1

    # Already-organized files sitting in the wrong place -> relocate them to
    # where this mode would have put them (verified only).
    relocated = 0
    for fn, src, dst, _size in result.relocate:
        if fn not in verified:
            flagged.add(fn)
            continue
        fs.guarded_makedirs(folder, os.path.dirname(dst))
        if _move_skip_collision(folder, src, dst, dry_run=dry_run):
            relocated += 1
    moved += relocated

    # Repair stranded _REJECTS: a verified Nexus mod whose category now
    # resolves (cached ref, live Nexus page, or login-gated og:identity) is
    # pulled OUT of the reject bin and sorted into its folder. The bin may
    # have been caused by a transient lookup failure on an earlier run.
    # Only web-verified files move; everything else stays in the bin,
    # reported. Never deletes.
    rescued_bin = 0
    if plus_batch and bin_files:
        for rfn, (rcat, _rsize) in rescue_verified_rejects(
                folder, bin_files, verified, storage.load_cache(folder)).items():
            src = os.path.join(bin_dir, rfn)
            cat_dir = os.path.join(folder, rcat)
            fs.guarded_makedirs(folder, cat_dir)
            author = extract_mod_author(rfn)
            if author and _author_matches(author, toplevel_authors):
                auth_dir = os.path.join(cat_dir, author)
                fs.guarded_makedirs(folder, auth_dir)
                dst = os.path.join(auth_dir, rfn)
            else:
                dst = os.path.join(cat_dir, rfn)
            if _move_skip_collision(folder, src, dst, dry_run=dry_run):
                moved += 1
                rescued_bin += 1
                print("  rescued from %s: %s -> %s" % (REJECT_BIN, rfn, rcat))
        if rescued_bin:
            print("Rescued %d previously-binned verified mod(s) out of %s."
                  % (rescued_bin, REJECT_BIN))

    # Sweep empty folders left behind by the sort (only truly empty dirs).
    pruned = prune_empty_dirs(folder, dry_run=dry_run)

    _write_tags_safe(folder)

    return {
        "moved": moved,
        "to_rejects": len(verified_rejects) if to_rejects and plus_batch else 0,
        "rescued": len(rescued),
        "duplicates": len(result.duplicates),
        "archives": len(result.kept) + len(result.duplicates),
        "dry_run": bool(dry_run),
        "flagged_unverified": sorted(flagged),
        "relocated": relocated,
        "frameworks": sorted(set(groups.values())),
        "pruned": pruned,
        "held_conflicts": held_conflicts,
    }


def prune_empty_dirs(folder, dry_run=False):
    """Remove directories in the workspace that contain absolutely nothing.

    Only truly empty dirs are removed (os.rmdir fails on anything with
    content), so no user data is ever touched - consistent with the
    no-delete rule (empty folders hold no data). Any folder that is still
    needed is simply re-created on the next sort via guarded_makedirs.
    The workspace root itself is never pruned. Returns a list of the
    removed (or, on dry-run, would-remove) relative paths.
    """
    removed = []
    for root, dirs, _files in os.walk(folder, topdown=False):
        for d in list(dirs):
            p = os.path.join(root, d)
            try:
                if os.listdir(p):
                    continue
            except OSError:
                continue
            rel = os.path.relpath(p, folder)
            if not dry_run:
                try:
                    os.rmdir(p)
                    removed.append(rel)
                except OSError:
                    continue
            else:
                removed.append(rel)
    return removed


def _write_tags_safe(folder):
    try:
        from gigasort.core import tags as tags_mod
        tags_mod.write_tags(folder)
    except Exception:
        pass
