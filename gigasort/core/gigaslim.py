"""GigaSlim companion launcher (--gigaslim).

Trims a Cyberpunk 2077 install for gameplay efficiency WITHOUT deleting —
bloat is moved to a backup store and recorded, so every trim restores.
The prerendered-cutscene archive (--videos) is opt-in.

A thin wrapper around the GigaSlim.py companion script, located across the
known install paths.
"""

import os
import subprocess
import sys

_CANDIDATES = [
    os.path.expanduser("~/Games/GigaSlim.py"),
    "/run/media/Gigatone/ToolBox/ToolBox/Cyberpunk-Tools/GigaSort-core-tools/GigaSlim.py",
]


def find_gigaslim():
    pkg = os.path.dirname(os.path.abspath(__file__))
    here = os.path.dirname(pkg)
    cands = list(_CANDIDATES)
    for base in (here, os.path.expanduser("~/.local/bin"),
                 os.path.expanduser("~/.local/share/gigasort")):
        cands.append(os.path.join(base, "GigaSlim.py"))
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def run_gigaslim(folder, dry_run=False, videos=False):
    script = find_gigaslim()
    if not script:
        print("(GigaSlim not found — a ToolBox bundle is required)")
        return 1
    argv = [sys.executable, script]
    if dry_run:
        argv.append("--dry-run")
    if videos:
        argv.append("--videos")
    print("[gigasort] launching GigaSlim (add --dry-run to preview; "
          "restore with 'gigaslim restore'):")
    return subprocess.call(argv)
