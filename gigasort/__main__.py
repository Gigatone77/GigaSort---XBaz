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
    gigaslim, cyberflash, fomodpacker, overlap, conflict as conflict_mod,
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
    g.add_argument("--fomodpacker", action="store_true",
                   help="list/customize FOMOD installers from the _FOMODS "
                        "bin (see --fomod-archive, --fomod-picks)")
    g.add_argument("--wtnc", action="store_true",
                   help="run the WTNC collection compatibility report")
    g.add_argument("--overlap", action="store_true",
                   help="overlap audit: cross-pack same-path + baseline "
                        "conflict check (see --baseline)")
    g.add_argument("--conflict-tags", action="store_true",
                   help="semantic conflict report: tags shared by two or "
                        "more installed/pending archives (blank schema; "
                        "users author own conflict_tags.json)")

    p.add_argument("--fomod-archive", default=None,
                   help="FOMODPacker: exact archive filename to inspect/"
                        "build (default: first FOMOD in _FOMODS)")
    p.add_argument("--fomod-picks", default=None,
                   help="FOMODPacker: JSON picks file "
                        '{"<step>":{"<group>":["<plugin>",...]}}')
    p.add_argument("--fomod-workspace", default=None,
                   help="FOMODPacker: output workspace for the built "
                        "game tree (default: same as -w/--workspace)")

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
    p.add_argument("--baseline", default=None,
                   help="overlap audit: read-only reference tree (e.g. unpicked "
                        "WTNC install) to check packs against")
    p.add_argument("--tree", action="append", default=[],
                   help="overlap audit: a game-relative tree to audit "
                        "(repeatable; default: the workspace)")
    p.add_argument("--context", action="append", default=[],
                   help="additional context folder (repeatable)")
    return p


def _print_gate(folder, files):
    gate = verify.build_verified_gate(folder, files)
    for f in sorted(files):
        print("%-6s %s" % ("PASS" if f in gate else "FAIL", f))
    return not (len(files) and not gate)


def _run_fomodpacker(workspace, args):
    """FOMODPacker: list FOMODs from the _FOMODS bin, or build one.

    Default (no --fomod-archive): enumerate _FOMODS and describe each.
    With --fomod-archive + --fomod-picks: build the FOMODPacker game tree.
    Mod identity is the Nexus mod id embedded in the archive name
    (same regex as the rest of GigaSort); filenames are never
    keyword-guessed for routing."""
    from gigasort.constants import FOMOD_BIN
    import json as _json

    fomod_dir = os.path.join(workspace, FOMOD_BIN)
    fomods = []
    if os.path.isdir(fomod_dir):
        fomods = sorted(n for n in os.listdir(fomod_dir)
                        if n.lower().endswith(".zip"))
    # also pick a -w/--workspace root archive if explicitly named
    if args.fomod_archive:
        cand = args.fomod_archive
        if os.path.dirname(cand) == "":
            for base in (fomod_dir, workspace):
                if os.path.isfile(os.path.join(base, cand)):
                    cand = os.path.join(base, cand)
                    break

    if not args.fomod_archive:
        if not fomods:
            print("FOMODPacker: no FOMOD installers in %s" % fomod_dir)
            return 1
        print("FOMODPacker — %d FOMOD(s) parked in %s:\n" % (
            len(fomods), fomod_dir))
        for name in fomods:
            path = os.path.join(fomod_dir, name)
            if fomodpacker.is_fomod(path):
                print(fomodpacker.describe(path))
                print()
        return 0

    if not os.path.isfile(cand):
        print("FOMODPacker: archive not found: %s" % cand)
        return 1
    if not fomodpacker.is_fomod(cand):
        print("FOMODPacker: %s is not a FOMOD zip" %
              os.path.basename(cand))
        return 2

    if not args.fomod_picks:
        # inspect-only mode: dump every step/group/plugin + mod id
        mid = None
        from gigasort.core.categorize import extract_mod_id
        mid = extract_mod_id(os.path.basename(cand))
        print(fomodpacker.describe(cand))
        print("\nmod id: %s" % (mid or "(none found)"))
        return 0

    try:
        with open(args.fomod_picks, encoding="utf-8") as fh:
            picks = _json.load(fh)
    except (OSError, _json.JSONDecodeError) as exc:
        print("FOMODPacker: bad picks file %s: %s" %
              (args.fomod_picks, exc))
        return 2

    out_ws = args.fomod_workspace or workspace
    os.makedirs(out_ws, exist_ok=True)
    result = fomodpacker.build(cand, picks, out_ws,
                               dry_run=args.dry_run)
    if not args.dry_run:
        fomodpacker.write_manifest(result, cand, picks)
        fomodpacker.write_modlist(result)
    print("FOMODPacker: %s" % result["root"])
    print("  files: %d" % result["files"])
    for step, plugs in result["steps"].items():
        print("  [%s] %s" % (step, ", ".join(plugs)))
    for issue in result["issues"]:
        print("  ! %s" % issue)
    return 0


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

    if args.overlap:
        trees = [os.path.abspath(t) for t in args.tree] or [primary]
        labels_and_paths = {}
        for t in trees:
            if not os.path.isdir(t):
                print("overlap audit: no such tree: %s" % t)
                return 1
            labels_and_paths[t] = overlap.rel_paths(t)
        result = overlap.audit(
            trees, labels_and_paths,
            baseline=os.path.abspath(args.baseline) if args.baseline else None)
        print(overlap.format_audit(result))
        if args.json:
            print(json.dumps({k: v for k, v in result.items()
                              if k not in ("counts",)}, indent=2))
        return 1 if (result["hard_overwrites"] or result["differing"]) else 0

    if args.conflict_tags:
        from gigasort.core import storage
        sc = conflict_mod.find_semantic_conflicts(
            primary, args.game_dir or (storage.load_settings(primary)
                                       .get("game_dir")))
        print(conflict_mod.format_semantic_conflicts(sc) or
              "no semantic conflicts found.")
        return 0

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

    if args.fomodpacker:
        return _run_fomodpacker(primary, args)

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