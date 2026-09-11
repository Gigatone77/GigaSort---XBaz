"""Read-only scanning and planning for the workspace.

This module NEVER moves or deletes a file. It reads the workspace, verifies
each archive against the offline knowledge base, and produces a plan of
destination folders per top-level item. Execution lives in engine.py.
"""

import os
import dataclasses

from gigasort.constants import (
    REJECT_BIN, TRASH_BIN, HOLD_BIN, DUPLICATES_BIN,
    KNOWN_FOLDERS, TOPLEVEL_AUTHORS, KNOWN_FRAMEWORKS, MAJOR_FRAMEWORKS,
)
from gigasort.core import verify
from gigasort.core import signature
from gigasort.core import conflict as conflict_mod
from gigasort.core.categorize import (
    clean_name, categorize, extract_mod_id, extract_mod_author,
)


@dataclasses.dataclass
class ScanResult:
    folder: str
    kept: list = None                  # [(fn, size)]
    duplicates: list = None            # [(fn, size)]
    rejects: list = None               # [(fn, size)]
    relocate: list = None              # [(fn, src, dst, size)]
    plan: dict = None                  # {src_basename: dest relpath}
    plan_groups: dict = None           # {category: [(fn, size)]} (display)
    hold_conflicts: dict = None        # {fn: [paths]}
    framework_of: dict = None          # {fn: framework}
    toplevel_authors: list = None
    author_plus_batch: bool = True
    group_frameworks: bool = False
    total_bytes: int = 0
    gate: set = None                   # verified basenames (never moved unverified)

    def __post_init__(self):
        self.kept = self.kept or []
        self.duplicates = self.duplicates or []
        self.rejects = self.rejects or []
        self.relocate = self.relocate or []
        self.plan = self.plan or {}
        self.hold_conflicts = self.hold_conflicts or {}
        self.framework_of = self.framework_of or {}
        self.toplevel_authors = self.toplevel_authors or []
        self.gate = self.gate or set()
        if self.plan_groups is None:
            groups = {}
            for base, dest in self.plan.items():
                dest = str(dest)
                key = dest.split("/")[0] if "/" in dest else dest
                groups.setdefault(key, []).append(
                    (base, _size(os.path.join(self.folder, base))))
            self.plan_groups = groups


def _is_archive(name):
    return name.lower().endswith((".zip", ".rar", ".7z"))


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _web_override(name, overrides):
    return overrides.get(clean_name(name)) or overrides.get(name)


def _find_existing_clean(folder, clean, organized):
    """If a cleaned archive name already exists inside an organized folder,
    return its category folder (duplicate), else None."""
    for d in sorted(organized):
        candidate = os.path.join(folder, d, clean)
        if os.path.exists(candidate):
            return d
    return None


def _framework_group_for(name):
    """Return the niche framework group folder for a filename, or None.
    Universal frameworks (CET/RED4ext/TweakXL/ArchiveXL) never group."""
    low = name.lower()
    for fw_name in ("virtual atelier", "equipment-ex", "amm", "input loader",
                    "codeware", "native settings ui"):
        if fw_name in low:
            return "Virtual Atelier" if fw_name == "virtual atelier" \
                else fw_name.title()
    return None


def scan_workspace(folder, toplevel_authors=None, author_plus_batch=None,
                   group_frameworks=False, game_dir=None, rebuild=True):
    """Scan + plan, fully read-only. Returns a ScanResult with everything the
    GUI and CLI need (sizes, relocate list, hold conflicts, framework map)."""
    result = ScanResult(folder=os.path.abspath(folder))
    folder = result.folder
    signature.ensure_archive(folder)

    from gigasort.core import storage
    overrides = storage.load_web_overrides(folder)
    settings = storage.load_settings(folder)

    toplevel_authors = toplevel_authors if toplevel_authors is not None \
        else settings.get("toplevel_authors", [])
    toplevel_authors = [str(a).strip() for a in toplevel_authors if str(a).strip()]
    if author_plus_batch is None:
        author_plus_batch = bool(settings.get("author_plus_batch", True))
    if not toplevel_authors:
        author_plus_batch = True
    result.author_plus_batch = author_plus_batch
    result.group_frameworks = group_frameworks

    state = {REJECT_BIN, TRASH_BIN, HOLD_BIN, DUPLICATES_BIN}
    try:
        for n in os.listdir(folder):
            if n.startswith("_") and os.path.isdir(os.path.join(folder, n)):
                state.add(n)
    except OSError:
        return result

    dirs = {n for n in os.listdir(folder)
            if os.path.isdir(os.path.join(folder, n))}
    organized = set()
    for d in sorted(dirs - state):
        if d in KNOWN_FOLDERS or d in TOPLEVEL_AUTHORS \
                or d in set(KNOWN_FRAMEWORKS.values()):
            organized.add(d)

    files = []
    for n in os.listdir(folder):
        if not _is_archive(n) or n in state:
            continue
        if os.path.isfile(os.path.join(folder, n)):
            files.append(n)
    files.sort(key=str.lower)

    # verify (offline; build gate = the ONLY files allowed to move)
    result.gate = verify.build_verified_gate(folder, files)

    # author-only mode: everything not for a listed author stays put
    for name in files:
        size = _size(os.path.join(folder, name))
        clean = clean_name(name)
        author = extract_mod_author(clean)
        ov = _web_override(name, overrides)

        # duplicates first (whole-tree check)
        dest = _find_existing_clean(folder, clean, organized)
        if dest and ov is None:
            result.duplicates.append((name, size))
            if name in result.gate:
                result.plan[name] = os.path.join(DUPLICATES_BIN, name)
            continue

        # unverified never leave place
        if name not in result.gate:
            result.rejects.append((name, size))
            continue

        # web override wins
        if ov:
            result.plan[name] = os.path.join(str(ov), name)
            result.kept.append((name, size))
            result.total_bytes += size
            continue

        cat = categorize(clean)
        author_ok = author and author in toplevel_authors

        if not author_plus_batch and not author_ok:
            continue  # author-only mode, not this author: stay in place

        if not cat:
            result.rejects.append((name, size))
            continue

        if author_ok:
            dest = os.path.join(author, cat, name)
        elif group_frameworks and _framework_group_for(clean):
            fw = _framework_group_for(clean)
            result.framework_of[name] = fw
            dest = os.path.join(fw, cat, name)
        else:
            dest = os.path.join(cat, name)
        result.plan[name] = dest
        result.kept.append((name, size))
        result.total_bytes += size

    # relocations (read-only plan, engine applies) + hold conflicts
    try:
        result.relocate = find_misplaced(folder,
                                         toplevel_authors=toplevel_authors,
                                         author_plus_batch=author_plus_batch,
                                         group_frameworks=group_frameworks)
    except Exception:  # noqa: BLE001 - never fail the whole scan
        result.relocate = []
    for _fn, _src, _dst, _sz in result.relocate:
        if os.path.basename(_src) in result.gate:
            result.plan.setdefault(os.path.basename(_src), _dst)
        result.relocate = []
    try:
        if game_dir or settings.get("game_dir"):
            result.hold_conflicts = conflict_mod.find_conflicts(
                folder, game_dir or settings.get("game_dir"))
    except Exception:  # noqa: BLE001
        result.hold_conflicts = {}

    return result


def resolve_framework_groups(folder, kept, cache=None, toplevel_authors=None,
                             **kwargs):
    """Map each kept file to the niche framework its deps require. Read-only."""
    from gigasort.core import storage
    cache = cache or storage.load_references(folder)
    out = {}
    for fn in [(f if isinstance(f, str) else f[0]) for f in kept]:
        fw = _framework_group_for(fn)
        if fw:
            out[fn] = fw
            continue
        mid = extract_mod_id(fn)
        if mid and cache:
            for dep in (cache.get(mid) or {}).get("deps") or []:
                dep_id = extract_mod_id(str(dep))
                if dep_id in KNOWN_FRAMEWORKS \
                        and dep_id not in MAJOR_FRAMEWORKS:
                    out[fn] = KNOWN_FRAMEWORKS[dep_id]
                    break
    return out


def rescue_verified_rejects(folder, rejects, verified_ids, cache=None):
    """Move rejects whose category is now resolvable back into the plan.

    Returns {fn: (category, size)} for files that got a folder. Read-only
    planning — the caller applies the plan."""
    from gigasort.core import storage
    from gigasort.core.categorize import categorize, clean_name
    overrides = storage.load_web_overrides(folder)
    cache = cache or storage.load_references(folder)
    out = {}
    for fn in [(f if isinstance(f, str) else f[0]) for f in rejects]:
        size = _size(os.path.join(folder, fn))
        ov = overrides.get(fn)
        if ov:
            out[fn] = (str(ov), size)
            continue
        cat = categorize(clean_name(fn))
        if cat:
            out[fn] = (cat, size)
    return out


# ---------------------------------------------------------------------------
# Nested-archive duplicate detection (whole tree)
# ---------------------------------------------------------------------------
def collect_nested_archives(workspace, **kwargs):
    """Scan every folder under the workspace recursively and return a list of
    (rel_dir, cleaned_basename, size) for every archive found."""
    out = []
    for root, _dirs, files in os.walk(workspace):
        rel = os.path.relpath(root, workspace)
        if rel == ".":
            continue
        for name in files:
            if _is_archive(name):
                full = os.path.join(root, name)
                out.append((rel, name, _size(full)))
    return out


# ---------------------------------------------------------------------------
# Misplacement checks (read-only)
# ---------------------------------------------------------------------------
def find_misplaced(folder, items=None, **kwargs):
    """Return a list of (fn, src_abs, dst_abs, size) for archives found the
    wrong place vs the sort rules."""
    from gigasort.core import storage
    overrides = storage.load_web_overrides(folder)
    out = []

    for root, _dirs, files in os.walk(folder):
        rel = os.path.relpath(root, folder)
        if rel == ".":
            continue
        if any(seg.startswith("_") for seg in rel.split(os.sep)):
            continue
        first = rel.split(os.sep)[0]
        if first not in KNOWN_FOLDERS and first not in TOPLEVEL_AUTHORS \
                and first not in set(KNOWN_FRAMEWORKS.values()):
            continue
        for name in files:
            if not _is_archive(name):
                continue
            clean = clean_name(name)
            ov = overrides.get(name)
            cat = categorize(clean)
            want = ov or cat
            if not want:
                continue
            if first == want:
                continue  # top-level category right
            if want in rel.replace(os.sep, "/").split("/"):
                continue  # inside the expected category path
            src = os.path.join(root, name)
            if ov:
                dst = os.path.join(folder, ov, name)
            elif cat:
                dst = os.path.join(folder, cat, name)
            else:
                dst = src
            out.append((name, src, dst, _size(src)))
    return out


def _prune_empty_dirs(folder):
    """Remove only empty DIRECTORY shells (os.rmdir never touches files)."""
    bins = {REJECT_BIN, TRASH_BIN}
    for root, _dirs, _files in os.walk(folder, topdown=False):
        if root == folder:
            continue
        try:
            if not os.listdir(root) and os.path.basename(root) not in bins:
                os.rmdir(root)
        except OSError:
            pass


def prune_empty_dirs(folder):
    """Public API for --prune (folders only, contents never removed)."""
    _prune_empty_dirs(folder)