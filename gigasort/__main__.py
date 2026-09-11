"""GigaSort v3 — command-line interface.

Fully offline. Guarded by the same hard rule as every other entry point:
no file is ever moved/trashed/deleted unless it has passed the offline
verification gate (see gigasort.core.verify).
"""

import argparse
import json
import os
import sys

from gigasort import __version__, APP_NAME
from gigasort.constants import DEFAULT_WORKSPACE
from gigasort.core import (
    verify, engine, report, setup, wtnc,
    superseded, collection, gamestructure, extract, agent,
    gigaslim, cyberflash,
)
from gigasort.core.scan import scan_workspace


def _expand_folders(args):
    """Resolve --folder/-w/--workspace (comma-separated extra contexts)."""
    primary = args.workspace or args.folder or DEFAULT_WORKSPACE
    extra = []
    if args.folder and "," in args.folder:
        parts = [p.strip() for p in args.folder.split(",") if p.strip()]
        primary = parts[0]
        extra = parts[1:]
    return os.path.abspath(primary), extra


def build_parser():
    p = argparse.ArgumentParser(
        prog="gigasort",
        description="%s — Cyberpunk 2077 mod-archive organizer (offline)" % APP_NAME)
    p.add_argument("-V", "--version", action="version",
                   version="%(prog)s " + __version__)
    p.add_argument("-w", "--workspace", default=None,
                   help="workspace folder (default ~/Downloads)")
    p.add_argument("--folder", default=None,
                   help="alias of --workspace; comma-separated adds context "
                        "folders (first = primary)")

    g = p.add_mutually_exclusive_group()
    g.add_argument("--gui", action="store_true",
                   help="launch the GTK4 desktop GUI (default when no flags)")
    g.add_argument("--apply", action="store_true", help="run the sort for real")
    g.add_argument("--undo", action="store_true", help="revert the last sort")
    g.add_argument("--json", action="store_true",
                   help="print a machine-readable run report")
    g.add_argument("--locate", action="store_true",
                   help="print where each verified file goes")
    g.add_argument("--preview", action="store_true",
                   help="dry-run plan (nothing moves)")
    g.add_argument("--verify", action="store_true",
                   help="verify only (no moves)")
    g.add_argument("--gate", action="store_true",
                   help="show which files pass the safety gate")
    g.add_argument("--setup", action="store_true",
                   help="one-time workspace initialization")
    g.add_argument("--agent", action="store_true",
                   help="serve a single agent op from a JSON payload file")
    g.add_argument("--trash", action="store_true",
                   help="move rejects/reject-bin files to the restorable "
                        "~deleted bin")
    g.add_argument("--delete-rejects", action="store_true",
                   help="relocate _REJECTS entries into the restorable "
                        "~deleted sub-bin (never deletes)")
    g.add_argument("--superseded", action="store_true",
                   help="check for possibly-superseded downloads (read-only)")
    g.add_argument("--collection", action="store_true",
                   help="cache ordered collection downloads (zw_)")
    g.add_argument("--gamestructure", action="store_true",
                   help="stage extracted mods into a game-shaped tree")
    g.add_argument("--extract", action="store_true",
                   help="extract archives into per-mod folders")
    g.add_argument("--gigaslim", action="store_true",
                   help="run the packaged GigaSlim module (analyze default game)")
    g.add_argument("--cyberflash", action="store_true",
                   help="run the packaged CyberFlashSync module")
    g.add_argument("--cyberflash-sync", action="store_true",
                   help="alias of --cyberflash")
    g.add_argument("--wtnc", action="store_true",
                   help="run the WTNC collection compatibility report")

    p.add_argument("--dry-run", action="store_true",
                   help="print the plan without moving anything")
    p.add_argument("--strict", action="store_true",
                   help="treat unverified as an error (exit 2)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="assume yes for confirmations")
    p.add_argument("--one-bin", action="store_true",
                   help="send rejects into a single trash bin")
    p.add_argument("--only-categories", default=None,
                   help="comma-separated category folders to restrict moves to")
    p.add_argument("--game-dir", default=None,
                   help="CP2077 game install root (conflict / structure checks)")
    p.add_argument("--context", action="append", default=[],
                   help="additional context folder (repeatable)")
    return p


def _print_gate(folder, files):
    gate = verify.build_verified_gate(folder, files)
    for f in sorted(files):
        print("%-6s %s" % ("PASS" if f in gate else "FAIL", f))
    return not (len(files) and not gate)


def main(argv=None):
    # Detect whether any CLI flags were actually passed.
    raw = argv if argv is not None else sys.argv[1:]
    explicit_flags = any(a.startswith("-") for a in raw)

    args = build_parser().parse_args(argv)
    primary, _context = _expand_folders(args)

    # Launch the GUI when no flags were given (interactive terminal) or --gui.
    if args.gui or (not explicit_flags and sys.stdin.isatty()):
        from gigasort.gui.app import run_app
        return run_app(workspace=primary)

    # --setup short-circuit (no scan needed)
    if args.setup:
        w, built, seeded = setup.setup_workspace(primary,
                                                 game_dir=args.game_dir)
        print("workspace ready: %s" % w)
        print("offline archive built: %s  refs seeded: %d" % (built, seeded))
        return 0

    # --worker: process a single agent request delivered via a JSON file
    if os.environ.get("GS_AGENT_PAYLOAD"):
        payload_path = os.environ.get("GS_AGENT_PAYLOAD")
        payload = {}
        if os.path.exists(payload_path):
            with open(payload_path, encoding="utf-8") as fh:
                payload = json.load(fh)
        result = agent.handle(primary, payload.get("op", "info"),
                              payload.get("payload"),
                              payload.get("origin", "cli"))
        print(json.dumps(result, indent=2))
        return 0

    # Y/N confirmation for real mutations
    if not args.yes and (args.apply or args.trash or args.delete_rejects):
        sys.stdout.write("GigaSort: move verified mods into organized folders? "
                         "[y/N] ")
        choice = sys.stdin.readline().strip().lower() if sys.stdin.isatty() \
            else "n"
        if choice not in ("y", "yes"):
            print("aborted.")
            return 1

    if args.gigaslim:
        rc, out = gigaslim.run()
        sys.stdout.write(out)
        return rc
    if args.cyberflash or args.cyberflash_sync:
        rc, out = cyberflash.run()
        sys.stdout.write(out)
        return rc

    if args.wtnc:
        rep = wtnc.run_wtnc_report(primary)
        print("WTNC report: manifest %d, extra compat %d, archives %d" % (
            rep["manifest_total"], rep["extra_compat_total"],
            len(rep["archives"])))
        for a in rep["archives"]:
            print("  %-5s %s" % (a["kind"], a["file"]))
        return 0

    if args.collection:
        state = collection.cache_collection_state(primary)
        print(json.dumps(state, indent=2))
        return 0

    if args.superseded:
        pairs = superseded.find_superseded(primary)
        if not pairs:
            print("no superseded candidates.")
        for pair in pairs:
            print("%5.2f  %-40s <- %s  (%s)" % (
                pair["score"], pair["newer"], pair["older"], pair["reason"]))
        issues = superseded.check_placement(primary)
        for i_ in issues:
            print("[%s] %s  want %s  got %s" % (
                i_["kind"], i_["file"], i_["expected"], i_["current"]))
        return 0

    if args.gamestructure:
        root, outcomes = gamestructure.stage_entries(
            primary, dry_run=args.dry_run,
            reference=os.environ.get("GS_REFERENCE_GAME_STRUCTURE"))
        print("structure tree: %s" % root)
        for k, v in sorted(outcomes.items()):
            print("  %-40s %s" % (k, v))
        return 0

    if args.extract:
        ok, failed = extract.extract_workspace(primary)
        print("extracted: %d, failed: %d" % (len(ok), len(failed)))
        for name in failed:
            print("  FAILED  %s" % name)
        return 0

    # trace: everything else requires a scan
    result = scan_workspace(primary)

    if args.verify:
        res = verify.verify_allowlist(primary)
        passed = [p for p, r in res.items() if r.status in ("approved",
                                                            "mismatch")]
        print("verified %d/%d" % (len(passed), len(res)))
        for p_, r in sorted(res.items()):
            print("  %-12s %-8s %s" % (r.status, r.source or "-",
                                       os.path.basename(p_)))
        return 0 if len(passed) > 0 else 1

    if args.gate:
        files = sorted(n for n in os.listdir(primary)
                       if n.lower().endswith((".zip", ".rar", ".7z")))
        return 0 if _print_gate(primary, files) else 1

    if args.locate:
        for base, dest in result.plan.items():
            print("%-80s -> %s" % (base, dest or "(keep)"))
        return 0

    if args.undo:
        from gigasort.core.undo import undo_move, list_undone
        entries = list_undone(primary)
        if not entries:
            print("nothing to undo.")
            return 0
        undone, skipped = undo_move(primary, dry_only=args.dry_run)
        print("undone %d, skipped %d" % (undone, skipped))
        return 0

    # report the plan (shared by default / --preview / --dry-run / --json)
    dry = args.dry_run or args.preview or not args.apply
    rep = report.build_report(result, dry_run=dry)

    if args.json or not dry:
        pass  # counts below are real once applied

    if dry:
        if args.json:
            print(json.dumps(rep, indent=2))
        else:
            print(report.format_summary(rep))
        return 0

    moved, dup, rej, holds = 0, 0, 0, 0
    res = engine.execute_sort(
        primary, result, dry_run=False, one_bin=args.one_bin,
        only_categories=([c.strip() for c in args.only_categories.split(",")]
                         if args.only_categories else None),
        game_dir=args.game_dir)
    moved, dup = res.get("moved", 0), res.get("duplicates", 0)
    rej, holds = res.get("rejects_moved", 0), res.get("holds", 0)
    rep["counts"].update({"moved_now": moved, "duplicates_now": dup,
                          "rejects_now": rej, "holds_now": holds})
    flagged = res.get("flagged_unverified", [])
    if flagged:
        print("%d UNVERIFIED file(s) left in place (never moved):"
              % len(flagged))
        for n in flagged:
            print("  \u2022 %s" % n)
    print(report.format_summary(rep))
    if args.json:
        print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())