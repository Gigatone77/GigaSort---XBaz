"""GigaSlim — make the Cyberpunk 2077 install directory lean and tidy.

Movable, restorable companion tool for GigaSort. Works both standalone
(`python -m gigasort.core.gigaslim <command>`) and in-process from the GUI.

Usage
-----
    gigaslim                  # analyze (read-only): list what is slimable
    gigaslim apply            # move default categories to backup store
    gigaslim apply --videos   # include the 13 GB cutscene archive
    gigaslim restore          # move everything back from the backup store
    gigaslim status           # what is slimmed, where the backup lives

Backup store priority:
1. CyberFlashSync flash drive (auto-detected)
2. --backup-dir override
3. ~/Documents/GigaSlim-Backups/ (same-disk, does NOT free space)

Safety: source files are only removed AFTER the backup copy verifies + fsyncs.
"""

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
import time

HOME = os.path.expanduser("~")
DEFAULT_GAME = os.path.join(HOME, "Games", "Cyberpunk 2077")
LOCAL_BACKUP = os.path.join(HOME, "Documents", "GigaSlim-Backups")
DRIVE_REL_BACKUP = "GamesDRMfree/Cyberpunk 2077/GigaSlim-Backups"
MARKER_FILE = "CYBERPUNK_SYNC.marker"
DRIVE_LABELS = ("EEF4-351E", "Gigaflash01")
MANIFEST = "_GigaSlim_restore.json"

CATEGORIES = {
    "language": ("non-English language archives", True),
    "launcher": ("REDlauncher-*.msi updater installer", True),
    "videos":   ("basegame_5_video.archive (13 GB prerendered cutscenes)", False),
    "cache":    ("r6/cache auto-regenerating files (final.redscripts.modded, "
                 "final.redscripts.ts)", False),
}
DEFAULT_KEEP_LANGS = {"en"}


def human_size(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fT" % n


def file_size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def dir_size(path):
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            total += file_size(os.path.join(root, f))
    return total


def on_removable(p):
    rp = os.path.realpath(p)
    for base in ("/run/media", "/media"):
        if os.path.isdir(base):
            try:
                if rp == base or rp.startswith(base + os.sep):
                    return True
            except OSError:
                pass
    return False


def match_language(rel, keep):
    m = re.match(
        r"archive/pc/(content|ep1)/lang_(?P<lang>[a-zA-Z-]+)_(voice|text)\.archive$",
        rel,
    )
    if not m:
        return None
    lang = m.group("lang")
    if lang in keep:
        return None
    return "language"


def classify(rel, keep):
    if match_language(rel, keep):
        return "language"
    if rel == "archive/pc/content/basegame_5_video.archive":
        return "videos"
    if os.path.basename(rel).startswith("REDlauncher-") and rel.count("/") == 0:
        return "launcher"
    if os.path.basename(rel) in ("final.redscripts.modded", "final.redscripts.ts"):
        return "cache"
    return None


def _load_ignore(game):
    candidates = [os.path.join(game, "_GigaSlim_ignore.json")]
    out = set()
    for p in candidates:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data = data.get("ignore", [])
        if isinstance(data, list):
            out.update(str(x) for x in data)
    return out


def scan(game, keep_langs):
    out = []
    game = os.path.realpath(game)
    ignore = _load_ignore(game)
    for root, dirs, files in os.walk(game):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("mod",)]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), game)
            cat = classify(rel, keep_langs)
            if cat and rel not in ignore:
                out.append((os.path.join(root, f), rel, "file",
                            file_size(os.path.join(root, f)), cat))
    return sorted(out, key=lambda x: -x[3])


# -----------------------------------------------------------------------
# flash-drive detection
# -----------------------------------------------------------------------
def detect_drive():
    for base in ("/run/media", "/media"):
        if not os.path.isdir(base):
            continue
        try:
            users = [u for u in sorted(os.listdir(base))
                     if os.path.isdir(os.path.join(base, u))]
        except OSError:
            continue
        for u in users:
            udir = os.path.join(base, u)
            try:
                mounts = sorted(os.listdir(udir))
            except OSError:
                continue
            for m in mounts:
                mp = os.path.join(udir, m)
                if os.path.isdir(mp) and os.path.isfile(os.path.join(mp, MARKER_FILE)):
                    return mp
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as fh:
            mounts = [l.split() for l in fh]
    except OSError:
        mounts = []
    for parts in mounts:
        if len(parts) >= 4 and parts[1].startswith("/run/media") \
                and os.path.basename(parts[1]) in DRIVE_LABELS:
            return parts[1]
    return None


def choose_backup_dir(game, explicit=None):
    if explicit:
        return os.path.abspath(explicit), os.path.abspath(explicit) != os.path.realpath(game)
    drive = detect_drive()
    if drive:
        return os.path.join(drive, DRIVE_REL_BACKUP), True
    return LOCAL_BACKUP, False


# -----------------------------------------------------------------------
# flash-safe file ops
# -----------------------------------------------------------------------
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


def _safe_move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp-%d" % os.getpid()
    try:
        if os.path.isdir(src):
            shutil.copytree(src, tmp)
            if dir_size(tmp) != dir_size(src):
                raise OSError("size mismatch after dir copy")
            for root, _dirs, files in os.walk(tmp):
                for f in files:
                    _fsync_file(os.path.join(root, f))
            _fsync_dir(tmp)
        else:
            shutil.copy2(src, tmp)
            if file_size(tmp) != file_size(src):
                raise OSError("size mismatch after copy")
            _fsync_file(tmp)
        os.replace(tmp, dst)
        _fsync_dir(os.path.dirname(dst))
    except BaseException:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        elif os.path.isfile(tmp):
            os.remove(tmp)
        raise
    if os.path.isdir(src):
        shutil.rmtree(src)
    else:
        os.remove(src)


# -----------------------------------------------------------------------
# actions
# -----------------------------------------------------------------------
def run_analyze(game, keep_langs):
    items = scan(game, keep_langs)
    print("=" * 70)
    print("GIGASLIM ANALYZE  (%s)" % game)
    print("=" * 70)
    if not items:
        print("  Nothing slimable found. The install is already tidy.")
        return 0
    per = {}
    for src, rel, kind, size, cat in items:
        per.setdefault(cat, []).append((rel, kind, size))
    grand = 0
    for cat in sorted(per):
        cat_items = per[cat]
        total = sum(s for _, _, s in cat_items)
        grand += total
        label, on_by_default = CATEGORIES[cat]
        mode = ("on by default" if on_by_default
                else ("--videos" if cat == "videos" else "--cache"))
        print("\n[%s]  %s  (%s, %s)"
              % (cat, label, human_size(total), mode))
        for rel, kind, size in cat_items:
            print("    %s %s  (%s)" % (kind, rel, human_size(size)))
    print("\n  TOTAL slimable: %s"
          % (human_size(grand) + ("  (~%.0f GB freed with default categories)"
                                  % (grand / (1024.0 ** 3)) if grand else "")))
    print("\n  Default apply moves only 'language' + 'launcher' (~%s). "
          "Add --videos for the 13 GB cutscene archive and --cache for the "
          "auto-regenerating cache files." % human_size(
              sum(s for _, _, s in per.get("language", []) +
                  (per.get("launcher", [])))))
    return 0


def run_apply(game, keep_langs, videos=False, cache=False,
              backup_dir=None, dry_run=False, yes=False):
    keep = keep_langs
    candidates = scan(game, keep)
    enabled = {c for c, (_, on) in CATEGORIES.items()
               if on or (c == "videos" and videos)
               or (c == "cache" and cache)}
    todo = [c for c in candidates if c[4] in enabled]
    if not todo:
        print("GigaSlim: nothing to slim in the enabled categories.\n"
              "  Tip: add --videos (13 GB) and/or --cache to include the big ones.")
        return 0

    need = sum(t[3] for t in todo)
    print("=" * 70)
    print("GIGASLIM APPLY")
    print("=" * 70)
    for _src, rel, kind, size, cat in sorted(todo, key=lambda x: -x[3]):
        print("  [%-9s] %s  (%s)" % (cat, rel, human_size(size)))
    print("  TOTAL: %s  in %d item(s)" % (human_size(need), len(todo)))

    backup, on_drive = choose_backup_dir(game, backup_dir)
    print("\n  backup store: %s" % backup)
    if not on_drive:
        if detect_drive() and not backup_dir:
            print("  !! your CyberFlashSync drive is plugged in; add --backup-dir "
                  "to use the drive instead.")
        print("  !! LOCAL backup: does NOT free disk space (source + backup are "
              "on the same disk).")
    else:
        free = shutil.disk_usage(os.path.dirname(backup)).free
        if need + (256 * 1024 * 1024) > free:
            print("  !! not enough space on the drive for this backup "
                  "(need ~%s, free %s). Use --backup-dir." %
                  (human_size(need), human_size(free)))
            return 1

    if dry_run:
        print("\nDRY-RUN: nothing moved. Re-run without --dry-run to apply.")
        return 0

    if not yes:
        ans = input("\nMove these to the backup store? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted - nothing changed in the game dir.")
            return 0

    manifest = {"tool": "GigaSlim", "game": os.path.realpath(game),
                "created": time.strftime("%Y-%m-%d %H:%M:%S"), "items": []}
    moved, failed = 0, 0
    for src, rel, kind, size, cat in todo:
        dst = os.path.join(backup, rel)
        try:
            _safe_move(src, dst)
            manifest["items"].append({"rel": rel, "kind": kind, "size": size,
                                      "category": cat})
            print("  moved  [%-9s] %s" % (cat, rel))
            moved += 1
        except Exception as exc:  # noqa: BLE001
            print("  FAILED [%-9s] %s: %s" % (cat, rel, exc))
            failed += 1

    os.makedirs(backup, exist_ok=True)
    mp = os.path.join(backup, MANIFEST)
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    _fsync_file(mp)
    _fsync_dir(backup)
    _write_notes(backup, manifest)
    print("\nDone: moved %d item(s) (%s), %d failed." %
          (moved, human_size(sum(i["size"] for i in manifest["items"])), failed))
    print("Restore with:  python3 -m gigasort.core.gigaslim restore "
          "(or see RESTORE-NOTES.txt in the backup store)")
    if failed:
        return 2
    return 0


def run_restore(game, backup_dir=None):
    backup, _ = choose_backup_dir(game, backup_dir)
    mp = os.path.join(backup, MANIFEST)
    if not os.path.isfile(mp):
        print("GigaSlim: no restore manifest at %s" % mp)
        return 1
    with open(mp, encoding="utf-8") as fh:
        manifest = json.load(fh)
    items = manifest.get("items", [])
    if not items:
        print("GigaSlim: manifest is empty - nothing to restore.")
        return 0
    print("GigaSlim: restoring %d item(s) to %s" % (len(items), game))
    restored, skipped, failed = 0, 0, 0
    for it in items:
        rel = it["rel"]
        src = os.path.join(backup, rel)
        dst = os.path.join(game, rel)
        if not os.path.exists(src):
            print("  missing in backup: %s (already gone?)" % rel)
            skipped += 1
            continue
        if os.path.exists(dst):
            print("  exists in game:    %s (skip - already present)" % rel)
            skipped += 1
            continue
        try:
            _safe_move(src, dst)
            print("  restored %s" % rel)
            restored += 1
        except Exception as exc:  # noqa: BLE001
            print("  FAILED %s: %s" % (rel, exc))
            failed += 1
    if restored:
        leftover = [i["rel"] for i in items
                    if os.path.exists(os.path.join(backup, i["rel"]))]
        if not leftover:
            try:
                os.remove(mp)
            except OSError:
                pass
            print("  manifest cleared (everything restored).")
    print("Restored %d, skipped %d, failed %d." % (restored, skipped, failed))
    return 0 if not failed else 2


def run_status(game):
    backup, on_drive = choose_backup_dir(game, None)
    print("=" * 70)
    print("GIGASLIM STATUS")
    print("=" * 70)
    print("  game dir  : %s (%s)" % (game, human_size(dir_size(game))))
    print("  backup    : %s (%s, %s)"
          % (backup, "flash drive" if on_drive else "local",
             human_size(shutil.disk_usage(os.path.dirname(backup)).free)
             if os.path.isdir(os.path.dirname(backup)) else "n/a"))
    mp = os.path.join(backup, MANIFEST)
    if os.path.isfile(mp):
        try:
            with open(mp, encoding="utf-8") as fh:
                m = json.load(fh)
            items = m.get("items", [])
            print("  slimmed   : %d item(s) on %s" % (len(items), m.get("created")))
            for it in items:
                print("    [%-9s] %s (%s)" % (it["category"], it["rel"],
                                               human_size(it["size"])))
        except Exception:  # noqa: BLE001
            print("  slimmed   : manifest unreadable")
    else:
        print("  slimmed   : nothing currently (this backup store is empty)")
    print("  categories:")
    for c, (label, default) in CATEGORIES.items():
        flagged = "--videos/-V" if c == "videos" else ("--cache/-C" if c == "cache" else "on by default")
        print("    %-10s %-55s %s" % (c, label, flagged))
    print("\n  flash drive: %s" % (detect_drive() or "not plugged in"))
    return 0


def _write_notes(backup, manifest):
    lines = [
        "GigaSlim - backup restore notes",
        "=" * 50,
        "Created : %s" % manifest.get("created"),
        "Game dir: %s" % manifest.get("game"),
        "",
        "What was slimmed (manifest: %s)" % MANIFEST,
        "-" * 50,
    ]
    by = {}
    for it in manifest.get("items", []):
        by.setdefault(it["category"], []).append(it)
    for cat, items in by.items():
        lines.append("[%s]  %s  (%s)" %
                     (cat, human_size(sum(i["size"] for i in items)),
                      ", ".join(i["rel"] for i in items)))
    lines += [
        "",
        "To restore everything:",
        "    python3 -m gigasort.core.gigaslim restore",
        "",
        "To restore everything onto a specific backup store:",
        "    python3 -m gigasort.core.gigaslim restore --backup-dir <this folder>",
        "",
        "Full-game restore points (they already exist):",
        "    - Flash drive 'GamesDRMfree/Cyberpunk 2077/Cyberpunk 2077.zip'",
        "    - Flash drive 'GamesDRMfree/Cyberpunk 2077/Cyberpunk 2077 WTNC "
        "CybepunkTHING rev_481.zip'",
        "",
        "Note: 'cache' items regenerate on next launch; 'videos' re-runs the",
        "prerendered cutscenes only while basegame_5_video.archive is present.",
    ]
    p = os.path.join(backup, "RESTORE-NOTES.txt")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p


# -----------------------------------------------------------------------
# CLI / in-process runner
# -----------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="gigaslim", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="analyze",
                    choices=["menu", "analyze", "apply", "restore", "status"],
                    help="analyze (default) | apply | restore | status | menu")
    ap.add_argument("--game", default=DEFAULT_GAME,
                    help="game install root (default: %s)" % DEFAULT_GAME)
    ap.add_argument("--keep", default="en",
                    help="comma-separated languages to KEEP (default: en)")
    ap.add_argument("--videos", "-V", action="store_true",
                    help="include basegame_5_video.archive (13 GB cutscenes)")
    ap.add_argument("--cache", "-C", action="store_true",
                    help="include r6/cache auto-regenerating files "
                         "(final.redscripts.modded, final.redscripts.ts)")
    ap.add_argument("--backup-dir", default=None,
                    help="backup store override (flash drive is auto-detected)")
    ap.add_argument("--dry-run", action="store_true", help="preview only")
    ap.add_argument("--yes", "-y", action="store_true", help="skip confirm")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.game):
        print("Not a directory: %s (use --game)" % args.game, file=sys.stderr)
        return 2

    if on_removable(args.game):
        print("Refusing to touch %s: it lives on a mounted flash/removable "
              "drive." % args.game, file=sys.stderr)
        return 2

    keep = set(x.lower().strip() for x in args.keep.split(",") if x.strip())

    if args.command == "analyze":
        return run_analyze(args.game, keep)
    if args.command == "apply":
        return run_apply(args.game, keep, videos=args.videos, cache=args.cache,
                         backup_dir=args.backup_dir, dry_run=args.dry_run,
                         yes=args.yes)
    if args.command == "restore":
        return run_restore(args.game, args.backup_dir)
    if args.command == "status":
        return run_status(args.game)
    if args.command == "menu":
        return _interactive_menu(args.game)
    return 0


def _interactive_menu(game):
    while True:
        os.system("clear" if os.name != "nt" else "cls")
        print("=" * 70)
        print("GigaSlim  |  slim the Cyberpunk 2077 install (movable, restorable)")
        print("=" * 70)
        print("  a = analyze   A = apply (default)   A+ = include 13 GB videos")
        print("  r = restore   s = status            q = quit")
        try:
            ch = input("gigaslim> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0
        if ch in ("q", "quit", "exit"):
            return 0
        if ch == "a":
            run_analyze(game, DEFAULT_KEEP_LANGS)
            input("  press enter...")
            continue
        if ch == "r":
            run_restore(game, None)
            input("  press enter...")
            continue
        if ch == "s":
            run_status(game)
            input("  press enter...")
            continue
        run_apply(game, DEFAULT_KEEP_LANGS, videos=(ch in ("a+", "videos", "y")),
                  cache=False, dry_run=False, yes=True, backup_dir=None)
        input("  press enter...")


def run(argv=None):
    """In-process runner for CLI and GUI. Returns (returncode, output_text)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (2 if exc.code else 0)
    return rc, buf.getvalue()


if __name__ == "__main__":
    sys.exit(main())
