"""Archive inspection and Cyberpunk 2077 structure detection (offline).

This module NEVER contacts the network. It inspects the interior of an
archive (and optional meta.ini) to decide whether it is a CP2077 mod and
where its files belong in the game tree.
"""

import os
import re
import zipfile

from gigasort.constants import (
    GAME_ROOT_DIRS, VRAM_HIRES_WORDS,
)

# Names that mark a game/mod folder because of their rollout layout.
SIGNAL_ROOTS = (
    "archive", "bin", "engine", "mods", "r6", "red4ext",
)


def list_entries(path):
    """List archive interior paths as posix-style strings.

    Supports .zip (stdlib). For .7z / .rar, attempts optional support via
    py7zr / rarfile when installed; otherwise returns [] so callers degrade
    gracefully."""

    def _zip():
        out = []
        try:
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    name = info.filename
                    if info.is_dir():
                        continue
                    out.append(name.rstrip("/"))
        except (OSError, zipfile.BadZipFile, KeyError):
            pass
        return out

    def _py7z():
        try:
            import py7zr
        except ImportError:
            return []
        out = []
        try:
            with py7zr.SevenZipFile(path, mode="r") as zf:
                for name in zf.getnames():
                    out.append(name.rstrip("/"))
        except Exception:  # noqa: BLE001 - corrupt/missing archives
            pass
        return out

    def _rar():
        try:
            import rarfile
        except ImportError:
            return []
        out = []
        try:
            with rarfile.RarFile(path) as rf:
                for info in rf.infolist():
                    if not info.is_dir():
                        out.append(info.filename.rstrip("/"))
        except Exception:  # noqa: BLE001
            pass
        return out

    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        return _zip()
    if ext == ".7z":
        return _py7z()
    if ext == ".rar":
        return _rar()
    return []


def looks_like_cp2077_archive(path, mod_id=None):
    """Return ('strong'|'partial'|'unknown', [details]).

    Stops at the first decision that disproves a CP2077 arrival: presence of
    a top-level game root wins ('strong'), a CET plugin path inside signal
    roots wins ('strong'), only binaries out of place gives 'partial'."""
    entries = list_entries(path)
    if not entries:
        return "unknown", []

    roots = {e.split("/")[0] for e in entries}
    if not (roots & set(GAME_ROOT_DIRS)):
        return "unknown", ["no CP2077 game root in archive"]

    strong = False
    for e in entries:
        top = e.split("/")[0]
        if top != "mods" and e.endswith((".archive", ".xl", ".reds",
                                          ".yaml", ".lua", ".dll", ".ini")):
            strong = True
            break
    if not strong:
        return "partial", ["has game roots but no mod files found"]
    return "strong", ["game-root layout + mod files"]


def _native_entries_any(path, wanted=("r6/scripts", "r6/tweaks",
                                      "engine/config/input",
                                      "archive/pc/mod")):
    entries = list_entries(path)
    return any(w in e for w in wanted for e in entries)


def is_cp2077_mod_file(path, mod_id=None):
    """Structural gate: a strong CP2077 layout OR a known-extensions archive
    under a game root. Used for offline verification."""
    status, _ = looks_like_cp2077_archive(path, mod_id)
    if status in ("strong", "partial"):
        return True
    return bool(mod_id and (status == "unknown") and _native_entries_any(path))


def readme_mod_id(path):
    """Look for a Nexus mod id inside an archive's readme/description, used
    as a fallback when the filename carries no usable id. Returns id or None."""
    entries = list_entries(path)
    candidates = [e for e in entries if
                  (e.endswith(".txt") or e.endswith(".md")
                   or e.endswith(".html") or "readme" in e.lower())]
    if not candidates:
        return None
    url_id_re = re.compile(r"nexusmods\.com/cyberpunk2077/mods/(\d{3,6})",
                           re.IGNORECASE)
    line_id_re = re.compile(r"(?:^|\s)mod\s*id[:\s]+(\d{3,6})\s*$",
                            re.IGNORECASE | re.MULTILINE)
    for rel in candidates:
        payload = _read_entry(path, rel, max_bytes=64 * 1024)
        if not payload:
            continue
        try:
            text = payload.decode("utf-8", errors="replace")
        except AttributeError:
            text = payload
        u = url_id_re.search(text)
        if u:
            return u.group(1)
        l = line_id_re.search(text)
        if l:
            return l.group(1)
    return None


def _read_entry(path, rel, max_bytes=256 * 1024):
    """Read a single archive entry as bytes (best effort)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".zip":
            with zipfile.ZipFile(path) as zf:
                return zf.read(rel)[:max_bytes]
        if ext == ".7z":
            import py7zr
            with py7zr.SevenZipFile(path, mode="r") as zf:
                for fname, bio in zf.read([rel]).items():
                    return bio.read()[:max_bytes]
        if ext == ".rar":
            import rarfile
            with rarfile.RarFile(path) as rf:
                return rf.open(rel).read(max_bytes)
    except Exception:  # noqa: BLE001
        pass
    return None


def modlist_archive(path):
    """Best-effort mount list from an archives' meta (Vortex-style) or an
    r6 archive list. Returns a list of file paths or []."""
    entries = list_entries(path)
    return [e for e in entries if e.startswith(("archive/pc/mod", "test.mods"))]


def mod_crc(dep_path):
    """Cheap archive fingerprint for a file (may be large — read in chunks)."""
    import hashlib
    h = hashlib.sha256()
    try:
        with open(dep_path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def vram_high_res(filename):
    """Flag an archive whose name suggests a high-res texture pack."""
    low = filename.lower()
    return any(w in low for w in VRAM_HIRES_WORDS)