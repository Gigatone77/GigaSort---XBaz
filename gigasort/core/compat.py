"""Compatibility checks: modlist matching, need-redownload, VRAM guard,
non-mod warnings, and archive install-shape preview."""

import os
import re
import zipfile

from gigasort.constants import (
    GAME_ROOT_DIRS, ARCHIVE_INSTALL_EXTS, VRAM_HIRES_WORDS,
)
from gigasort.core.categorize import extract_mod_id, name_tokens, clean_name
from gigasort.utils.format import human_size
from gigasort.utils import net


# Names GigaSort itself manages in a workspace -> excluded from the
# non-mod-items warning.
NON_MOD_SKIP = {
    "_DUPLICATES", "_REJECTS", "_TRASH", "_ON_HOLD", "_GigaSort_stage",
    "GAMESTRUCTURE", "_GigaSort_backup",
}


# ---------------------------------------------------------------------------
# archive listing / preview
# ---------------------------------------------------------------------------
def list_entries(path):
    """Return a sorted list of entry paths (no size) for a zip/7z/rar."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        return _zip_entries(path)
    try:
        if ext == ".7z":
            return _list_entries_7z(path)
        if ext == ".rar":
            return _list_entries_rar(path)
    except Exception:
        return []
    return []


def _zip_entries(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return [-1, sorted(zf.namelist())] if False else sorted(zf.namelist())
    except Exception:
        return []


def _list_entries_7z(path):
    import subprocess
    r = subprocess.run(["7z", "l", "-slt", path], capture_output=True, text=True)
    out = []
    path_next = False
    for line in (r.stdout or "").splitlines():
        if line.startswith("Path = "):
            p = line[7:].strip()
            if p:
                out.append(p)
    return out


def _list_entries_rar(path):
    import subprocess
    r = subprocess.run(["unrar", "lb", path], capture_output=True, text=True)
    return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]


def preview_archive(path):
    """Return a layout flag: flat | game-shaped | nested | double | other."""
    entries = list_entries(path)
    if not entries:
        return "unknown"

    # double archive: contains another archive at the top
    for e in entries:
        base = os.path.basename(e).lower()
        if base.endswith((".zip", ".7z", ".rar")):
            return "double"

    tops = set()
    for e in entries:
        parts = e.split("/")
        if parts and parts[0]:
            tops.add(parts[0].lower())
    if not tops:
        return "flat"

    if tops <= set(dir.lower() for dir in GAME_ROOT_DIRS):
        return "game-shaped"
    if len(tops) == 1:
        # single top-level wrapper (nested bundle)
        inner = list(tops)[0]
        if any(os.path.splitext(e)[1].lower() in ARCHIVE_INSTALL_EXTS
               for e in entries):
            return "nested"
        return "nested"
    return "other"


# ---------------------------------------------------------------------------
# modlist / need-redownload / vram / non-mod
# ---------------------------------------------------------------------------
def _modlist_tokens(path):
    entries = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith(("+", "-")):
                name = s[1:].strip()
                entries.append((name, name_tokens(name)))
    return entries


def _nr_ids(path):
    ids = set()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.search(r"mods/(\d{4,6})", line)
            if m:
                ids.add(m.group(1))
    return ids


def check_modlist(folder, modlist_path, downloads):
    """Fuzzy-match downloads against an MO2 modlist; report overlaps."""
    if not modlist_path or not os.path.isfile(modlist_path):
        return
    entries = _modlist_tokens(modlist_path)
    if not entries:
        return
    print("\n== MODLIST CHECK (fuzzy) ==")
    for fn in downloads:
        toks = name_tokens(fn)
        if not toks:
            continue
        best, bestn = None, -1
        for name, etoks in entries:
            inter = len(toks & etoks)
            if inter > bestn:
                best, bestn = name, inter
        if bestn >= 1:
            union = len(toks | set(name_tokens(best)))
            score = bestn / union if union else 0
            if score >= 0.6:
                print("  already : %s  (~%.0f%% %s)" % (fn, score * 100, best))
            elif score >= 0.3:
                print("  similar : %s  (~%.0f%% %s)" % (fn, score * 100, best))


def check_need_redownload(folder, nr_path, downloads):
    if not nr_path or not os.path.isfile(nr_path):
        return
    ids = _nr_ids(nr_path)
    if not ids:
        return
    print("\n== NEED-REDOWNLOAD xref ==")
    for fn in downloads:
        mid = extract_mod_id(fn)
        if mid and mid in ids:
            print("  %s  (mod id %s is on your NEED_REDOWNLOAD list)" % (fn, mid))


def vram_guard(folder, vram_gb, archives):
    """Summarize install footprint, flag oversized packs vs VRAM budget."""
    total = sum(s for _, s in archives)
    print("\n== VRAM / SIZE GUARD (%.1f GB budget) ==" % vram_gb)
    print("  install footprint : %s across %d archive(s)"
          % (human_size(total), len(archives)))
    if vram_gb:
        budget_bytes = vram_gb * (1024 ** 3)
        for fn, size in archives:
            if size > budget_bytes:
                print("  [oversized vs %gGB] %s (%s)" % (vram_gb, fn, human_size(size)))
            low = fn.lower()
            if any(w in low for w in VRAM_HIRES_WORDS):
                print("  [high-res flag]   %s (%s)" % (fn, human_size(size)))


def non_mod_items(folder):
    """Detect non-archive, non-GigaSort files/folders in the workspace."""
    miss = []
    try:
        for fn in os.listdir(folder):
            if fn.startswith("_"):
                continue
            if fn in NON_MOD_SKIP:
                continue
            full = os.path.join(folder, fn)
            if os.path.isdir(full):
                miss.append((fn, True))
            elif os.path.isfile(full) and not fn.lower().endswith(
                    (".zip", ".rar", ".7z")):
                miss.append((fn, False))
    except OSError:
        pass
    return miss


def warn_non_mod_items(folder):
    miss = non_mod_items(folder)
    if not miss:
        return
    print("\n-- NOTE: the workspace also contains non-mod items --")
    for fn, is_dir in miss:
        print("   %s %s" % ("[dir]" if is_dir else "[file]", fn))
