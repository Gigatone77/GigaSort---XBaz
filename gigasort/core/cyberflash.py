"""CyberFlashSync — one-command backup of your customized Cyberpunk 2077
files to a USB flash drive ("flash key").

Source -> destination is HOME -> FLASH DRIVE only. Nothing on this computer
is ever deleted. Drive zips are replaced atomically (create .tmp, verify,
then rename) so an interrupted run never leaves a half-baked backup.
Additive mirror/rsync backups never use --delete. Works standalone
(`python -m gigasort.core.cyberflash`) and in-process from the GigaSort GUI.

Modes
-----
    cyberflashsync               # sync (no game dir)
    cyberflashsync --dry-run     # preview only
    cyberflashsync --with-game   # ALSO full-game zip (~90 GB, OFF by default)
    cyberflashsync --only ID[,ID]   # run only the listed mapping ids
    cyberflashsync status        # read-only overview
    cyberflashsync menu          # interactive menu
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------
# Mappings. One item per entry: (id, type, source, dest_rel, enabled)
# ----------------------------------------------------------------------
MAPPINGS = [
    ("cleansettings", "mirror",
     os.path.join(HOME, "Documents", "cp2077-clean-state-20260830"),
     "GamesDRMfree/Cyberpunk 2077/cp2077-clean-state-20260830", True),
    ("custommodadded", "copy",
     os.path.join(HOME, "Documents", "Custom Mod Additions Archive.zip"),
     "GamesDRMfree/Cyberpunk 2077/Custom Mod Additions Archive.zip", True),
    ("customorganized", "copy",
     os.path.join(HOME, "Documents", "Custom Mod Additions Archive - ORGANIZED.zip"),
     "GamesDRMfree/Cyberpunk 2077/Custom Mod Additions Archive - ORGANIZED.zip", True),
    ("customgamestructure", "copy",
     os.path.join(HOME, "Documents", "Custom Mod Additions Archive - GAME STRUCTURE.zip"),
     "GamesDRMfree/Cyberpunk 2077/Custom Mod Additions Archive - GAME STRUCTURE.zip", True),
    ("wtncthing", "zip",
     os.path.join(HOME, "Games", "WTNC CyberpunkThing Mod Archive"),
     "GamesDRMfree/Cyberpunk 2077/WTNC CyberpunkTHING Archive.zip", True),
    ("rawmodpack", "zip",
     os.path.join(HOME, "Games", "raw_WTNCCT_mod_pack"),
     "GamesDRMfree/Cyberpunk 2077/raw_WTNCCT_mod_pack.zip", True),
    ("vehicles", "copy",
     os.path.join(HOME, "Documents", "Cyberpunk Vehicles Archive.zip"),
     "GamesDRMfree/Cyberpunk 2077/Cyberpunk Vehicles Archive.zip", True),
    # The whole GigaSort workspace (workspace passed via -w/--workspace,
    # else ~/Downloads). Dest resolved at runtime.
    ("gigasortworkspace", "gigasort", "", "", True),
    # GigaSort private state lives centrally (~/.local/share/GigaSort/state)
    # — backed up too so a sorted workspace re-imports cleanly.
    ("gigasortstate", "mirror",
     os.path.join(HOME, ".local", "share", "GigaSort", "state"),
     "GamesDRMfree/Cyberpunk 2077/GigaSort-state", True),
    # Live game dir: ~90 GB, OFF by default. Enable with --with-game.
    ("GAME", "zip",
     os.path.join(HOME, "Games", "Cyberpunk 2077"),
     "GamesDRMfree/Cyberpunk 2077/Cyberpunk 2077.zip", False),
    # The GigaSort program files (repo root + package) -> a Tools folder.
    ("tools", "tools", "", "GamesDRMfree/Cyberpunk 2077/GigaSort-Tools", True),
]

# Files bundled onto the drive under the Tools folder. Sourced from the
# GigaSort repo/package root (searched up from the module).
TOOLS_FILES = [
    ("README.md", "README.md"),
    ("LICENSE", "LICENSE"),
    ("CHANGELOG.md", "CHANGELOG.md"),
    ("pyproject.toml", "pyproject.toml"),
    ("resources/gigasort.png", "gigasort.png"),
]

DRIVE_LABELS = ("EEF4-351E", "Gigaflash01")
MARKER_FILE = "CYBERPUNK_SYNC.marker"
REFERENCE_FILE = "SYNC-REFERENCE.md"
MANIFEST_FILE = "SYNC-MANIFEST.log"

GAME_ITEM_ID = "GAME"

_rsync = shutil.which("rsync")
_zip = shutil.which("zip")
_unzip = shutil.which("unzip")

STATUS_OK = "OK"
STATUS_SKIP = "skip"
STATUS_NEW = "new"
STATUS_BLOCKED = "blocked"


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def human_size(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fT" % n


def _run_proc(argv, cwd=None):
    try:
        p = subprocess.Popen(argv, cwd=cwd)
        p.wait()
        return p.returncode
    except FileNotFoundError:
        print("  !! command not found: %s" % argv[0])
        return 127


def dir_size(path):
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
            for d in dirs:
                total += 4096
    except OSError:
        pass
    return total


def file_hash(path, chunk=1024 * 1024):
    try:
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return None
    except OSError:
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                b = fh.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def files_equal(a, b):
    try:
        sa, sb = os.path.getsize(a), os.path.getsize(b)
    except OSError:
        return False
    if sa != sb:
        return False
    fa, fb = file_hash(a), file_hash(b)
    if fa is None or fb is None:
        try:
            return abs(os.path.getmtime(a) - os.path.getmtime(b)) < 2
        except OSError:
            return False
    return fa == fb


def _repo_root():
    d = os.path.dirname(THIS_DIR)
    for _ in range(3):
        if os.path.isfile(os.path.join(d, "pyproject.toml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(THIS_DIR)


REPO_ROOT = _repo_root()


# ----------------------------------------------------------------------
# flash-drive detection
# ----------------------------------------------------------------------
def candidate_mounts():
    roots = []
    media = "/run/media"
    if os.path.isdir(media):
        for user in sorted(os.listdir(media)):
            u = os.path.join(media, user)
            if os.path.isdir(u):
                for mp in sorted(os.listdir(u)):
                    roots.append(os.path.join(u, mp))
    return roots


def detect_drive(explicit=None):
    if explicit:
        return os.path.abspath(explicit)
    for mp in candidate_mounts():
        if os.path.isfile(os.path.join(mp, MARKER_FILE)):
            return mp
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as fh:
            mounts = [l.split() for l in fh]
    except OSError:
        mounts = []
    for parts in mounts:
        if len(parts) < 4:
            continue
        mp = parts[1]
        if not mp.startswith("/run/media"):
            continue
        label = os.path.basename(mp)
        if label in DRIVE_LABELS:
            return mp
    return None


def write_drive_id(drive):
    try:
        with open(os.path.join(drive, MARKER_FILE), "w", encoding="utf-8") as fh:
            fh.write("CyberFlashSync backup drive. Managed by CyberFlashSync.\n")
    except OSError as exc:
        print("  !! could not write drive marker: %s" % exc)


# ----------------------------------------------------------------------
# GigaSort integration
# ----------------------------------------------------------------------
def gigasort_workspace():
    """The GigaSort workspace to back up (default ~/Downloads, or the
    user's current GigaSort workspace via storage settings)."""
    from gigasort.constants import DEFAULT_WORKSPACE
    default = os.path.abspath(DEFAULT_WORKSPACE)
    try:
        from gigasort.core.storage import load_settings
        tgt = load_settings(default).get("target_folder")
        if tgt and os.path.isdir(os.path.expanduser(tgt)):
            return os.path.abspath(os.path.expanduser(tgt))
    except Exception:  # noqa: BLE001
        pass
    return default


def _gigasort_item(workspace=None):
    ws = workspace or gigasort_workspace()
    if not os.path.isdir(ws):
        ws = os.path.abspath(gigasort_workspace())
    base = os.path.basename(ws.rstrip("/")) or "Downloads"
    return ("gigasortworkspace", "mirror", ws,
            "GamesDRMfree/Cyberpunk 2077/GigaSort-workspace-%s" % base)


# ----------------------------------------------------------------------
# each mapping type
# ----------------------------------------------------------------------
def _fsync_file(p):
    try:
        fd = os.open(p, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _fsync_dir(p):
    try:
        fd = os.open(p, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def do_copy(src, dst, dry):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isfile(dst) and files_equal(src, dst):
        return STATUS_SKIP, "identical"
    print("  copy  %s" % human_size(os.path.getsize(src)))
    if dry:
        return STATUS_NEW, "would copy"
    rv = _run_proc([_rsync, "-a", "--update", "--fsync", src, dst]) if _rsync else \
        shutil.copy2(src, dst)
    if rv == 0:
        if not _rsync:
            _fsync_file(dst)
        _fsync_dir(os.path.dirname(dst))
        return STATUS_NEW, "copied"
    return STATUS_BLOCKED, "copy failed"


def do_mirror(src, dst, dry):
    os.makedirs(dst, exist_ok=True)
    print("  mirror %s -> %s" % (src, dst))
    if dry:
        return STATUS_NEW, "would mirror"
    rv = _run_proc([_rsync, "-a", "--update", "--fsync", "--info=stats1",
              "--human-readable", "--", src.rstrip("/") + "/", dst + "/"])
    if rv == 0:
        _fsync_dir(dst)
        return STATUS_OK, "mirrored"
    return STATUS_BLOCKED, "mirror failed"


def do_zip(src, dst, dry, force=False):
    if not os.path.isdir(src):
        return STATUS_SKIP, "source missing"
    if not force and os.path.isfile(dst):
        try:
            newest = 0.0
            for root, _d, files in os.walk(src):
                for f in files:
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                    except OSError:
                        pass
            if os.path.getmtime(dst) >= newest:
                return STATUS_SKIP, "archive is current"
        except OSError:
            pass
    ddir = os.path.dirname(dst)
    os.makedirs(ddir, exist_ok=True)
    tmp = os.path.join(ddir, os.path.basename(dst) + ".tmp-%d" % os.getpid())
    size = dir_size(src)
    print("  zip   %s -> %s" % (human_size(size), dst))
    if dry:
        return STATUS_NEW, "would re-zip"
    if not (_zip and _unzip):
        return STATUS_BLOCKED, "zip/unzip not installed"
    rv = _run_proc([_zip, "-rq", tmp, "."], cwd=src)
    if rv != 0:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return STATUS_BLOCKED, "zip failed"
    if _run_proc([_unzip, "-tq", tmp]) != 0:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return STATUS_BLOCKED, "zip verify failed"
    _fsync_file(tmp)
    os.replace(tmp, dst)
    _fsync_dir(ddir)
    return STATUS_NEW, "re-zipped"


def do_tools(dst_dir, dry):
    """Copy the GigaSort suite files (README, LICENSE, icon, + the
    gigasort package itself) onto the drive."""
    os.makedirs(dst_dir, exist_ok=True)
    updated = 0
    for name, dname in TOOLS_FILES:
        src = os.path.join(REPO_ROOT, name)
        dst = os.path.join(dst_dir, dname)
        if not os.path.isfile(src):
            print("  (missing: %s)" % name)
            continue
        if os.path.isfile(dst) and files_equal(src, dst):
            continue
        print("  tool  %s" % name)
        if not dry:
            try:
                shutil.copy2(src, dst)
                updated += 1
            except OSError as exc:
                print("  !! could not copy %s: %s" % (name, exc))
    pkg_src = os.path.join(REPO_ROOT, "gigasort")
    if os.path.isdir(pkg_src):
        pkg_dst = os.path.join(dst_dir, "gigasort")
        print("  tool  gigasort/ (package)")
        if not dry:
            try:
                shutil.copytree(pkg_src, pkg_dst, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__",
                                                              "*.pyc"))
                updated += 1
            except OSError as exc:
                print("  !! could not copy gigasort package: %s" % exc)
    if dry and not updated:
        print("  (would copy the tool files that differ)")
    return STATUS_NEW, "tools synced" if not dry else "would sync tools"


def _item_table(workspace=None):
    rows = []
    for it in MAPPINGS:
        if it[0] == "gigasortworkspace":
            it = _gigasort_item(workspace)
        if len(it) == 4:
            it = it + (True,)
        mid, mtype, src, dst_rel, enabled = it
        exists = os.path.exists(src) if src else "n/a"
        rows.append((mid, mtype, src or "(GigaSort workspace)", dst_rel,
                     bool(enabled), exists))
    return rows


def run_status(workspace=None):
    drive = detect_drive()
    print("=" * 70)
    print("CYBERFLASHSYNC STATUS")
    print("=" * 70)
    if drive:
        print("  drive : %s" % drive)
        print("  free  : %s" % human_size(shutil.disk_usage(drive).free))
        print("  marker: %s" % os.path.isfile(os.path.join(drive, MARKER_FILE)))
    else:
        print("  drive : NOT FOUND - plug in the Cyberpunk backup drive "
              "(label %s)" % "/".join(DRIVE_LABELS))
    print()
    print("  ITEMS (id | type | source -> drive dest | enabled | source ok)")
    for mid, mtype, src, dst_rel, enabled, exists in _item_table(workspace):
        flag = "on " if enabled else "OFF"
        when = "game-dir zip, off by default" if mid == GAME_ITEM_ID else mtype
        print("  %-19s %-8s %s %s -> %s [%s] %s"
              % (mid, mtype, flag, src, dst_rel, exists, when))
    if drive:
        man = os.path.join(drive, MANIFEST_FILE)
        if os.path.isfile(man):
            print("\n  LAST MANIFEST (tail):")
            try:
                with open(man, encoding="utf-8", errors="replace") as fh:
                    lines = fh.read().splitlines()
                for ln in lines[-12:]:
                    print("    " + ln)
            except OSError:
                pass
    print()
    return 0


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="cyberflashsync", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="preview only - change nothing anywhere")
    ap.add_argument("--drive", metavar="PATH", default=None,
                    help="use this mount instead of auto-detecting")
    ap.add_argument("--with-game", action="store_true",
                    help="ALSO sync the live game directory (~90 GB; OFF by default)")
    ap.add_argument("--workspace", "-w", default=None,
                    help="GigaSort workspace to back up under the "
                         "'gigasortworkspace' item (default: ~/Downloads)")
    ap.add_argument("--only", metavar="IDS", default="",
                    help="comma-separated mapping ids to run (e.g. "
                         "customorganized,gigasortworkspace)")
    ap.add_argument("--json", action="store_true",
                    help="print a machine-readable summary (opencode/agents)")
    ap.add_argument("mode", nargs="?", default=None, choices=["menu", "status"],
                    help="standalone modes: 'menu' = interactive menu; "
                         "'status' = read-only overview of items + last manifest")
    args = ap.parse_args(argv)

    if args.mode == "menu":
        return _interactive_menu(args.workspace)
    if args.mode == "status":
        return run_status(args.workspace)

    results = []
    errors = []

    drive = detect_drive(args.drive)
    if not drive or not os.path.isdir(drive):
        print("CYBERFLASHSYNC: no flash drive found.")
        print("  Plug in the Cyberpunk backup drive (label %s, or one carrying "
              "the marker '%s'), then re-run."
              % ("/".join(DRIVE_LABELS), MARKER_FILE))
        return 1

    print("=" * 70)
    print("CYBERFLASHSYNC  ->  %s" % drive)
    print("=" * 70)

    want = set(x.strip() for x in args.only.split(",") if x.strip())
    ordered = []
    for it in MAPPINGS:
        if it[0] == "gigasortworkspace":
            ordered.append(_gigasort_item(args.workspace))
        else:
            ordered.append(it)
    run_items = []
    for it in ordered:
        if len(it) == 4:
            it = it + (True,)
        mid, mtype, src, dst_rel, enabled = it
        if mid == GAME_ITEM_ID:
            enabled = args.with_game
        if not enabled:
            continue
        if want and mid not in want:
            continue
        run_items.append(it)

    if not run_items:
        print("No items to sync (enable with --with-game / --only, or check config).")
        return 1

    avail = shutil.disk_usage(drive).free
    print("Drive free: %s\n" % human_size(avail))

    for mid, mtype, src, dst_rel, _enabled in run_items:
        dst = os.path.join(drive, dst_rel)
        est = 0
        label = "%s [%s]" % (mid, mtype)
        if mtype == "copy":
            if not os.path.isfile(src):
                print("[%s] SKIP: source missing '%s'" % (label, src))
                results.append((mid, STATUS_SKIP, "missing"))
                continue
            est = os.path.getsize(src)
        elif mtype in ("zip", "mirror"):
            est = dir_size(src)
        elif mtype == "tools":
            est = sum(os.path.getsize(os.path.join(REPO_ROOT, n))
                      for n, _ in TOOLS_FILES
                      if os.path.isfile(os.path.join(REPO_ROOT, n)))

        margin = 0
        if mtype == "mirror" and os.path.isdir(dst):
            existing = dir_size(dst)
            margin = max(0, est - existing)
        elif mtype == "copy" and os.path.isfile(dst):
            margin = max(0, est - os.path.getsize(dst))
        elif mtype == "zip":
            margin = est
        if margin and margin + (512 * 1024 * 1024) > avail:
            print("[%s] BLOCKED: needs ~%s, only %s free" %
                  (label, human_size(margin), human_size(avail)))
            results.append((mid, STATUS_BLOCKED, "no space"))
            continue

        print("-- %s" % label)
        if mtype == "copy":
            if _rsync is None:
                errors.append("%s: rsync missing" % mid)
                results.append((mid, STATUS_BLOCKED, "rsync missing"))
                continue
            status, why = do_copy(src, dst, args.dry_run)
        elif mtype == "mirror":
            if _rsync is None:
                errors.append("%s: rsync missing" % mid)
                results.append((mid, STATUS_BLOCKED, "rsync missing"))
                continue
            status, why = do_mirror(src, dst, args.dry_run)
        elif mtype == "zip":
            status, why = do_zip(src, dst, args.dry_run)
        elif mtype == "tools":
            status, why = do_tools(dst, args.dry_run)
        else:
            status, why = STATUS_BLOCKED, "unknown type '%s'" % mtype
        results.append((mid, status, why))
        print("[%s] %s: %s\n" % (label, status.upper(), why))

    write_drive_id(drive)
    _write_reference(drive)
    _append_manifest(drive, results, args.dry_run)

    print("=" * 70)
    print("SUMMARY")
    for mid, status, why in results:
        print("  %-22s %-9s %s" % (mid, status, why))
    if errors:
        print("\nErrors:")
        for e in errors:
            print("  - %s" % e)

    if args.json:
        print("\nJSON")
        print(json.dumps({
            "tool": "CyberFlashSync",
            "drive": drive,
            "dry_run": bool(args.dry_run),
            "items": [{"id": i, "status": s, "note": w} for i, s, w in results],
        }, indent=2))

    return 0 if not errors else 2


def run(argv=None):
    """In-process runner: return (returncode, output_text)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (2 if exc.code else 0)
    return rc, buf.getvalue()


# ----------------------------------------------------------------------
# drive-side reference info (opencode-readable) + manifest
# ----------------------------------------------------------------------
def _write_reference(drive):
    body = """# CyberFlashSync - backup reference

This drive is the **Cyberpunk 2077 backup** for the machine it was created on
(home -> this drive, additive only; nothing here is ever deleted by the tool).

## What is on this drive (`GamesDRMfree/Cyberpunk 2077/`)
| Drive file | Source on this PC |
|---|---|
| `Cyberpunk 2077.zip` | `Games/Cyberpunk 2077/` (ONLY with --with-game; off by default) |
| `Cyberpunk 2077 WTNC CybepunkTHING rev_481.zip` | earlier full-game snapshot |
| `Custom Mod Additions Archive.zip` | `Documents/Custom Mod Additions Archive.zip` |
| `Custom Mod Additions Archive - ORGANIZED.zip` | `Documents/Custom Mod Additions Archive - ORGANIZED.zip` |
| `Custom Mod Additions Archive - GAME STRUCTURE.zip` | `Documents/Custom Mod Additions Archive - GAME STRUCTURE.zip` |
| `Cyberpunk Vehicles Archive.zip` | `Documents/Cyberpunk Vehicles Archive.zip` |
| `raw_WTNCCT_mod_pack.zip` | `Games/raw_WTNCCT_mod_pack/` (zipped) |
| `WTNC CyberpunkTHING Archive.zip` | `Games/WTNC CyberpunkThing Mod Archive/` (zipped) |
| `cp2077-clean-state-20260830/` | `Documents/cp2077-clean-state-20260830/` |
| `GigaSort-workspace-*/` | GigaSort workspace (default `~/Downloads`) incl. category folders and bins |
| `GigaSort-state/` | central GigaSort state (`~/.local/share/GigaSort/state`) |
| `GigaSort-Tools/` | The GigaSort suite itself: README, LICENSE, pyproject, gigasort package, icon |

## How to re-run the sync
    python3 -m gigasort.core.cyberflash            # snapshot (no game dir)
    python3 -m gigasort.core.cyberflash --dry-run  # preview only
    python3 -m gigasort.core.cyberflash --with-game  # ALSO full-game zip (~90 GB)
    python3 -m gigasort.core.cyberflash menu       # standalone interactive menu
    python3 -m gigasort.core.cyberflash status     # standalone read-only overview

## Notes for an agent/opencode
* The live (working) game install is `Games/Cyberpunk 2077/`; it is NOT
  backed up every sync because it is ~90 GB and nearly incompressible -
  the item is disabled until `--with-game`.
* The workspace mirrors are ADDITIVE (rsync `--update`, no `--delete`).
* Manifest of every run: `SYNC-MANIFEST.log` on this drive.
* `cp2077-clean-state-20260830/` holds the clean-state restore kit
  (scripts, services, SHA256SUMS.txt) used to bring the game back to a known
  good state.
"""
    try:
        with open(os.path.join(drive, REFERENCE_FILE), "w", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        pass


def _append_manifest(drive, results, dry):
    try:
        with open(os.path.join(drive, MANIFEST_FILE), "a", encoding="utf-8") as fh:
            fh.write("%s  dry=%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), dry))
            for mid, status, why in results:
                fh.write("    %-22s %-9s %s\n" % (mid, status, why))
            fh.write("\n")
    except OSError:
        pass


def _interactive_menu(workspace=None):
    while True:
        drive = detect_drive()
        print("\033[2J\033[H", end="")
        print("=" * 70)
        print("CyberFlashSync  |  CP2077 backup to USB flash drive")
        print("=" * 70)
        print("  drive : %s (%s free)"
              % (drive or "NOT FOUND",
                 human_size(shutil.disk_usage(drive).free) if drive else "-"))
        print("  items :")
        for mid, mtype, src, dst_rel, enabled, exists in _item_table(workspace):
            mark = "x" if enabled else " "
            print("    [%s] %-19s %-8s %s" % (mark, mid, mtype, dst_rel))
        print()
        print("  a = run all enabled   d = dry-run all   s = status")
        print("  o = choose items      q = quit")
        try:
            choice = input("cyberflashsync> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  bye.")
            return 0
        if choice in ("q", "quit", "exit"):
            return 0
        if choice == "s":
            run_status(workspace)
            input("  press enter...")
            continue
        if choice == "d":
            rc, _ = run(["--dry-run"])
            del rc
            input("  (dry-run done) press enter...")
            continue
        if choice == "o":
            print("  ids: " + ", ".join(r[0] for r in _item_table(workspace)))
            ids = input("  run ids (comma separated, empty=all): ").strip()
            argv = []
            if ids:
                argv += ["--only", ids]
            rc, _ = run(argv)
            del rc
            input("  (done) press enter...")
            continue
        rc, _ = run([])
        del rc
        input("  (sync done) press enter...")


if __name__ == "__main__":
    sys.exit(main())