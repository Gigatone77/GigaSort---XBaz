"""Compatibility checks: modlist matching, need-redownload, VRAM guard,
non-mod warnings, and archive install-shape preview."""

import os
import re
import zipfile

from gigasort.constants import (
    GAME_ROOT_DIRS, ARCHIVE_INSTALL_EXTS, VRAM_HIRES_WORDS,
    CP2077_STRONG_KEYWORDS,
)
from gigasort.core.categorize import extract_mod_id, candidate_mod_id, name_tokens
from gigasort.utils.format import human_size



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


# Text files inside an archive that may hold a Nexus URL / mod id / readme.
_README_NAME_RE = re.compile(
    r"(readme|read_?me|description|changelog|change ?log|update_?notes|"
    r"install|read ?i[nt]|about|info|nexus|mod ?id)", re.IGNORECASE)
_README_EXT_RE = re.compile(r"\.(txt|md|markdown|rtf|html?|lua|json|info|log)$",
                            re.IGNORECASE)
_NEXUS_URL_ID_RE = re.compile(
    r"nexusmods\.com/(?:cyberpunk2077|games/cyberpunk2077)/mods/(\d{2,6})",
    re.IGNORECASE)
_README_ID_RE = re.compile(
    r"(?:nexus[- ]?mod id|mod id|nexus id)\s*[:#\-]?\s*"
    r"(\d{3,6})\b", re.IGNORECASE)


def _read_entry_text(path, entry):
    """Best-effort text of one interior entry (zip: in-memory; rar/7z: extract
    to a temp file and read. Returns '' on any failure.)"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".zip":
            with zipfile.ZipFile(path) as zf:
                return zf.read(entry).decode("utf-8", "replace")
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _extract = {
                ".rar": ["unrar", "x", "-o+", path, entry],
                ".7z": ["7z", "e", path, entry, "-o%s" % tmp, "-y"],
            }.get(ext)
            if not _extract:
                return ""
            subprocess.run(_extract, capture_output=True, text=True)
            out = os.path.join(tmp, os.path.basename(entry))
            if os.path.isfile(out):
                with open(out, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read()
    except Exception:
        return ""
    return ""


def readme_mod_id(path, filename=None):
    """Try to recover a Nexus mod id from an archive's interior readme.

    Some authors never put the id in the filename (or use a 3-digit id the
    classic filename regex can miss). The readme / description / update-notes
    text often carries a nexusmods.com/.../mods/<id> URL or an explicit
    'Mod ID:' line - the strongest offline evidence a file is a real CP2077
    mod. Returns the first such id (str) or None. Best-effort, never raises.

    Prefers a full Nexus URL match over a bare 'Mod ID' line, so a random logo
    number inside install prose can't false-positive.
    """
    if not filename:
        filename = os.path.basename(path or "")
    try:
        entries = list_entries(path)
    except Exception:
        return []
    text_candidates = []
    for e in entries:
        base = os.path.basename(e).lower()
        if _README_EXT_RE.search(base) or _README_NAME_RE.search(base):
            text_candidates.append(e)
    # Read shortest candidates first (README.txt over long changelogs), scan
    # for a Nexus URL first, then a dated 'Mod ID:' line.
    text_candidates.sort(key=lambda e: (len(e), e))
    for e in text_candidates:
        text = _read_entry_text(path, e)
        if not text:
            continue
        for pat in (_NEXUS_URL_ID_RE, _README_ID_RE):
            m = pat.search(text)
            if m:
                return m.group(1)
    return None


def _zip_entries(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return sorted(zf.namelist())
    except Exception:
        return []


def _list_entries_7z(path):
    import subprocess
    r = subprocess.run(["7z", "l", "-slt", path], capture_output=True, text=True)
    out = []
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
        if any(os.path.splitext(e)[1].lower() in ARCHIVE_INSTALL_EXTS
               for e in entries):
            return "nested"
        return "nested"
    return "other"


# ---------------------------------------------------------------------------
# offline CP2077 structure detection
# ---------------------------------------------------------------------------
# Sub-paths that are unmistakable Cyberpunk 2077 (REDengine 4 / Cyberpunk)
# markers inside a downloaded mod archive. `r6`, `red4ext` and `engine` are
# CP2077-only (the Witcher 3 REDengine used `bin/x64` but never these), and
# `archive/pc/mod/*.archive` is the definitive CP2077 mod-data location.
CP2077_SIGNAL_TOPS = ("r6", "red4ext", "engine", "archive", "bin")
CP2077_STRONG_ROOTS = (
    "archive/pc/mod",
    "r6/config",
    "r6/scripts",
    "r6/cache",
    "red4ext/plugins",
    "red4ext/sdks",
    "engine/config",
    "engine/cache",
    "engine/tools",
    "mods",
    # Cyber Engine Tweaks (CET) - a CP2077-only mod loader. Its plugin path is
    # the strongest offline marker for utility/script mods that contain no
    # .archive files.
    "bin/x64/plugins/cyber_engine_tweaks",
)
# File extensions (case-insensitive) that only exist in CP2077 mods.
CP2077_STRONG_EXTS = (".archive", ".reds", ".xl", ".tweak")
# A single top-level wrapper folder common to many Nexus downloads.
_CP2077_WRAPPERS = ("archive", "r6", "engine", "red4ext", "mods")


def looks_like_cp2077_archive(path):
    """Offline signature check: does the archive's internal layout match a
    real Cyberpunk 2077 mod (REDengine 4 / CP2077-only paths)?

    Reads only the archive index (never extracts) and returns a confidence
    string so callers can decide how strictly to rely on it. This is the
    internet-free counterpart to Nexus verification — an archive whose entry
    tree contains CP2077 game-root folders (r6/, red4ext/, engine/,
    archive/pc/mod/*.archive) or CP2077-only file types (.archive/.reds/.xl)
    is very likely a genuine Cyberpunk 2077 mod regardless of connectivity.
    """
    entries = list_entries(path)
    if not entries:
        return "unknown"

    # Some authors ship the archive wrapped in the game's install folder
    # name ('Cyberpunk 2077/bin/...', 'cyberpunk2077/...'). Strip that common
    # wrapper so the real CP2077 signal directories are seen underneath.
    _GAME_WRAP = ("cyberpunk 2077", "cyberpunk2077", "cp2077", "the witcher")

    tops = set()
    roots_hit = set()
    ext_hit = False
    wrapper_hits = 0
    for e in entries:
        norm = e.replace("\\", "/").strip("/").lower()
        if not norm:
            continue
        first = norm.split("/")[0]
        if first in _GAME_WRAP:
            norm = "/".join(norm.split("/")[1:])
            if not norm:
                continue
        parts = norm.split("/")
        top = parts[0]
        if top:
            tops.add(top)
        if top in CP2077_SIGNAL_TOPS:
            for r in CP2077_STRONG_ROOTS:
                if norm == r or norm.startswith(r + "/"):
                    roots_hit.add(r)
                    break
        if norm.startswith(tuple(_CP2077_WRAPPERS + ("assets", "files", "content"))):
            wrapper_hits += 1
        base = parts[-1]
        if base.endswith(CP2077_STRONG_EXTS):
            ext_hit = True

    # Definitive: CP2077-only extension present OR a strong game-root path.
    if ext_hit:
        return "strong"
    if roots_hit:
        return "strong"
    return "unknown"


def is_cp2077_mod_file(filename, full_path, mod_id=None):
    """Combine the (offline) archive-structure signature with a Nexus mod id
    present in the filename (loose match for CCXL bare-number format): both
    together give a high-confidence, no-network determination that
    `full_path` is a real Cyberpunk 2077 mod archive.

    `mod_id` may be passed in when it was recovered from the archive's readme
    instead of the filename (a nexusmods URL / 'Mod ID:' line inside the
    archive is just as strong, when combined with the CP2077 layout).

    Also recognizes common CP2077 modding keywords (e.g. 'ccxl') in the
    filename — even when the archive interior can't be read (double-nested or
    otherwise unlistable) — so long as a Nexus mod id is present too."""
    if not (candidate_mod_id(filename) or mod_id):
        return False
    if name_has_cp2077_keyword(filename):
        return True
    try:
        return looks_like_cp2077_archive(full_path) == "strong"
    except Exception:
        return False


def cp2077_structure_match(filename, full_path):
    """Does this archive actually present a CP2077 game-path layout?

    True   - strong CP2077 naming keyword OR a CP2077 game-root interior
             (r6/red4ext/engine/archive/pc/mod or .archive/.reds/.xl files).
    False  - a CP2077-verifiable mod whose archive interior is NOT a CP2077
             layout ('Unstructured' — no game-path structure, needs manual
             handling / re-download).
    None   - interior cannot be read (unlistable). Never a hard indicator.
    """
    if name_has_cp2077_keyword(filename):
        return True
    try:
        return looks_like_cp2077_archive(full_path) == "strong"
    except Exception:
        return None


def name_has_cp2077_keyword(filename):
    """Return the first CP2077_STRONG_KEYWORDS term found in `filename`
    (case-insensitive), or None.

    Single-word terms are matched with word boundaries so e.g. 'ccxl' does not
    half-match inside an unrelated word; multi-word phrases are matched as
    whole phrases (any boundary) so 'virtual atelier' / 'cyber engine tweaks'
    are caught even with differing separators.
    """
    low = filename.lower()
    for kw in CP2077_STRONG_KEYWORDS:
        if " " in kw or "/" in kw or "_" in kw:
            if kw in low:
                return kw
        else:
            if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(kw), low):
                return kw
    return None


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
