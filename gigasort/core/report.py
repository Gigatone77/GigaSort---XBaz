"""Reports — the machine-readable + human summaries of a sort run."""

import json
import os
import time



def build_report(result, dry_run=True, counts=None):
    """Assemble a dict summarizing a ScanResult."""
    folder = result.folder
    counts = counts or (0, 0, 0, 0)
    moved, duplicates, rejects, holds = counts
    return {
        "workspace": folder,
        "dry_run": dry_run,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {
            "kept": len(result.kept),
            "duplicates": len(result.duplicates),
            "rejects": len(result.rejects),
            "moved_now": moved,
            "duplicates_now": duplicates,
            "rejects_now": rejects,
            "holds_now": holds,
        },
        "kept": sorted(f for f, _ in result.kept),
        "duplicates": sorted(f for f, _ in result.duplicates),
        "rejects": sorted(f for f, _ in result.rejects),
        "plan": {k: v for k, v in result.plan.items()},
        "toplevel_authors": sorted(result.toplevel_authors),
        "toplevel_files": sorted(dict(result.plan_groups)),
        "framework_groups": result.framework_of,
        "relocate": [(a, b, c) for (a, b, c, _s) in result.relocate],
        "misplaced": result.relocate,
        "hold_conflicts": {k: len(v) for k, v in result.hold_conflicts.items()},
        "unverified_never_moved": sorted(
            n for n in result.plan
            if n not in result.gate),
    }


def write_json_report(folder, report, filename=None):
    filename = filename or "_GigaSort_report.json"
    path = os.path.join(folder, filename)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    except OSError:
        pass
    return path


def format_summary(report):
    """Human-readable block printed after a run."""
    c = report["counts"]
    lines = [
        "GigaSort report — %s" % report["workspace"],
        "dry run : %s" % ("yes (nothing moved)" if report["dry_run"] else "no"),
    ]
    lines += [
        "kept        : %d" % c["kept"],
        "duplicates  : %d (%d moved)" % (c["duplicates"], c["duplicates_now"]),
        "rejects     : %d (%d moved)" % (c["rejects"], c["rejects_now"]),
        "moved now   : %d" % c["moved_now"],
        "on hold     : %d" % c["holds_now"],
    ]
    if report.get("misplaced"):
        lines.append("misplaced (review with --locate):")
        for fn, src, dst, _sz in report["misplaced"][:20]:
            lines.append("  %-40s %s -> %s" % (fn, src, dst))
    return "\n".join(lines) + "\n"