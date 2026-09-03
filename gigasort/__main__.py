"""GigaSort CLI — Cyberpunk 2077 mod-archive organizer."""

import argparse
import os
import subprocess
import sys

from gigasort import __version__
from gigasort.constants import default_workspace


def _expand_folders(value):
    """Comma-separated --folder a,b -> list of absolute workspace roots."""
    if not value:
        return None
    return [os.path.abspath(os.path.expanduser(r.strip()))
            for r in value.split(",") if r.strip()]


def build_parser():
    p = argparse.ArgumentParser(
        prog="gigasort",
        description="Cyberpunk 2077 mod-archive organizer",
    )
    p.add_argument("-V", "--version", action="version", version="%(prog)s " + __version__)
    p.add_argument("-w", "--workspace", "--folder", dest="workspace", default=None,
                   help="Mod workspace folder (default: ~/Downloads); "
                        "comma-separated to sort several folders")

    g = p.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true",
                   help="Non-interactive batch sort (verify-gated)")
    g.add_argument("--undo", action="store_true",
                   help="Reverse the last sort from the manifest")
    g.add_argument("--json", action="store_true",
                   help="Emit a read-only JSON report")
    g.add_argument("--locate", action="store_true",
                   help="Show the workspace map (dirs + state files)")
    g.add_argument("--preview", action="store_true",
                   help="Show archive layout / install shape (flat/game-shaped)")
    g.add_argument("--verify", action="store_true",
                   help="Run Nexus verification of candidate mods")
    g.add_argument("--gate", action="store_true",
                   help="Run the threat/reputation gate")
    g.add_argument("--check-deps", action="store_true",
                   help="Check for missing required dependencies")
    g.add_argument("--modlist", metavar="PATH",
                   help="Fuzzy-match downloads against an MO2 modlist")
    g.add_argument("--need-redownload", metavar="PATH",
                   help="Cross-reference downloads against a NEED_REDOWNLOAD list")
    g.add_argument("--vram", metavar="GB", type=float,
                   help="Report install footprint vs a VRAM budget (GB)")
    g.add_argument("--clean-dupes", action="store_true",
                   help="Categorize and move duplicate archives to _DUPLICATES")
    g.add_argument("--trash", action="store_true",
                   help="Manage the _TRASH bin (move selected to ~deleted; never deletes)")
    g.add_argument("--delete-rejects", action="store_true",
                   help="Move verified _REJECTS items to ~deleted (restorable, never deletes)")
    g.add_argument("--extract", action="store_true",
                   help="Extract archives into <Type>/<Author>/<Name>/")
    g.add_argument("--gamestructure", action="store_true",
                   help="Compile archives into a game-ready folder tree")
    g.add_argument("--agent", metavar="REQUEST",
                   help="Process an agent bridge request.json")
    g.add_argument("--cyberflash", "--cyberflash-sync", dest="cyberflash",
                   action="store_true", help="Run CyberFlashSync USB backup")
    g.add_argument("--gigaslim", action="store_true",
                   help="Slim a CP2077 install (moves bloat, never deletes)")

    p.add_argument("--dry-run", action="store_true",
                   help="Show what would happen without moving files")
    p.add_argument("--strict", action="store_true",
                   help="Refuse all WARN-tier (destructive/overwrite) actions")
    p.add_argument("--yes", action="store_true",
                   help="Approve confirmations non-interactively")
    p.add_argument("--game-dir", default=None,
                   help="Target game directory for --gamestructure")
    p.add_argument("--with-game", action="store_true",
                   help="Include the full game-dir zip in --cyberflash")
    p.add_argument("--videos", action="store_true",
                   help="(gigaslim) include videos in the move")
    p.add_argument("--keep", action="store_true",
                   help="Keep rejects in place instead of moving them")
    p.add_argument("--reveal", action="store_true",
                   help="Reveal the workspace folder in the file manager")
    p.add_argument("--setup", action="store_true",
                   help="Run interactive workspace setup")
    return p


def _require_dir(folder):
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        sys.exit("Not a directory (and cannot touch it): %s" % folder)
    return folder


def _noop_input(*a):
    return ""


def _yes_input(*a):
    return "confirm"


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)

    # Multi-folder: dispatch each root through its own subprocess (like the
    # published tool) so state/manifest never cross workspaces.
    roots = _expand_folders(args.workspace)
    if roots and len(roots) > 1:
        rc = 0
        for idx, root in enumerate(roots, start=1):
            print("[GigaSort] workspace %d/%d : %s" % (idx, len(roots), root))
            a = [sys.executable, "-m", "gigasort"]
            skip = False
            for i, x in enumerate(sys.argv[1:]):
                if skip:
                    skip = False
                    continue
                if x in ("--folder", "--workspace", "-w"):
                    skip = True
                    continue
                if x.startswith("--folder=") or x.startswith("--workspace="):
                    continue
                a.append(x)
            a += ["--folder", root]
            r = subprocess.run(a)
            if r.returncode:
                rc = r.returncode
        return rc

    folder = _require_dir(args.workspace or default_workspace())
    input_fn = _yes_input if args.yes else input

    from gigasort.core import storage
    from gigasort.core import sort
    from gigasort.utils import fs

    if args.json:
        from gigasort.core.report import run_json_report
        run_json_report(folder)
        return 0

    if args.locate:
        from gigasort.core.report import run_locate
        run_locate(folder)
        return 0

    if args.reveal:
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Gtk, Gio
            Gio.AppInfo.launch_default_for_uri(
                "file://" + folder, None)
            print("Revealed: %s" % folder)
        except Exception as e:
            print("reveal failed: %s" % e)
        return 0

    if args.setup:
        from gigasort.core.setup import run_setup
        run_setup(folder)
        return 0

    if args.undo:
        from gigasort.core.undo import run_undo
        run_undo(folder, dry_run=args.dry_run,
                 input_fn=input_fn if not args.yes else _yes_input)
        return 0

    if args.preview:
        from gigasort.core import compat
        result = sort.scan_workspace(folder)
        files = [f for f, _ in result.kept] + [f for f, _ in result.duplicates] \
            + [f for f, _ in result.rejects]
        print("== ARCHIVE LAYOUT / INSTALL SHAPE ==")
        for fn in files:
            layout = compat.preview_archive(os.path.join(folder, fn))
            print("  %-14s %s" % (layout, fn))
        return 0

    if args.cyberflash:
        from gigasort.core.cyberflash import run_cyberflash
        return run_cyberflash(folder, dry_run=args.dry_run,
                              with_game=args.with_game)

    if args.gigaslim:
        from gigasort.core.gigaslim import run_gigaslim
        return run_gigaslim(folder, dry_run=args.dry_run, videos=args.videos)

    if args.trash:
        from gigasort.core.trash import manage_trash
        return manage_trash(folder, dry_run=args.dry_run,
                            non_interactive=not sys.stdin.isatty() or args.yes)

    if args.delete_rejects:
        from gigasort.core.trash import delete_rejects
        return delete_rejects(folder, dry_run=args.dry_run,
                              yes=args.yes, strict=args.strict)

    if args.agent:
        from gigasort.core.agent import execute_agent_request
        return execute_agent_request(folder, args.agent)

    if args.gamestructure:
        from gigasort.core.gamestructure import run_gamestructure
        run_gamestructure(folder, game_dir=args.game_dir, dry_run=args.dry_run,
                          input_fn=input_fn)
        return 0

    if args.apply:
        summary = sort.run_batch_sort(folder, dry_run=args.dry_run,
                                      to_rejects=not args.keep)
        print("Done: %d moved, %d dupes, %d rejects%s." % (
            summary["moved"], summary["duplicates"],
            summary["to_rejects"],
            " (dry run)" if summary["dry_run"] else "",
        ))
        if args.keep:
            print("--keep set: rejects left in place.")
        if summary.get("flagged_unverified"):
            print("Unverified (left untouched):")
            for fn in summary["flagged_unverified"]:
                print("  • %s" % fn)
        return 0

    # Scan + verification + threat + deps report (no GUI) when any of the
    # analysis flags are present.
    result = sort.scan_workspace(folder)
    cache = storage.load_cache(folder)

    from gigasort.core import verify, threats, compat

    if args.modlist or args.need_redownload or args.vram is not None:
        if args.modlist:
            compat.check_modlist(folder, args.modlist,
                                 [f for f, _ in result.kept])
        if args.need_redownload:
            compat.check_need_redownload(folder, args.need_redownload,
                                         [f for f, _ in result.kept])
        if args.vram is not None:
            compat.vram_guard(folder, args.vram,
                              result.kept + result.duplicates)
        return 0

    if args.gate:
        gated = threats.run_threat_gate(folder, result.kept, cache)
        print("== THREAT / REPUTATION GATE ==")
        for fn, (verdict, reason) in gated.items():
            print("  [%s] %-40s %s" % (verdict, fn, reason))
        return 0

    if args.verify:
        v = verify.verify_categories(result.kept, cache, result.rejects)
        print("== NEXUS VERIFICATION ==")
        for fn, (cat, title, ncat, status) in v.items():
            print("  [%-8s] %-40s -> %s  (%s)" % (status, fn, cat or "?", title or "?"))
        if not args.dry_run:
            storage.save_cache(folder, _merge_verify(cache, v))
        return 0

    if args.check_deps:
        missing = verify.check_dependencies(folder, result.kept, args.dry_run)
        if not missing:
            print("All required dependencies appear present.")
        return 0

    if args.clean_dupes:
        n = _move_dupes(folder, result, args.dry_run)
        print("Moved %d duplicate archive(s) to _DUPLICATES." % n)
        return 0

    # No flags -> launch the GUI. CLI modes above remain headless.
    from gigasort.gui.app import run_app
    return run_app(workspace=folder)


def _merge_verify(cache, verify_map):
    """Fold a --verify result map into the persistent verified cache."""
    cache = dict(cache or {})
    for fn, (cat, title, ncat, status) in verify_map.items():
        cache[fn] = {
            "status": status, "category": cat,
            "nexus_title": title, "nexus_cat": ncat,
        }
    return cache


def _move_dupes(folder, result, dry_run):
    from gigasort.constants import DUPLICATES_BIN
    from gigasort.core import storage
    import shutil

    dup_dir = os.path.join(folder, DUPLICATES_BIN)
    if dry_run:
        return len(result.duplicates)
    os.makedirs(dup_dir, exist_ok=True)
    n = 0
    for fn, _ in result.duplicates:
        src = os.path.join(folder, fn)
        dst = os.path.join(dup_dir, fn)
        if os.path.abspath(src) != os.path.abspath(dst):
            try:
                shutil.move(src, dst)
                storage.record_move(folder, src, dst)
                n += 1
            except Exception:
                pass
    return n


if __name__ == "__main__":
    sys.exit(main())
