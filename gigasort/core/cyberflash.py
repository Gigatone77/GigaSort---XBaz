"""CyberFlashSync companion launcher (--cyberflash / --cyberflash-sync).

Backs up customized Cyberpunk 2077 files + the GigaSort workspace to a USB
flash drive. Additive only — nothing local is ever deleted. The ~90 GB
game-dir zip stays OFF unless --with-game is passed (passed through below).

A thin wrapper around the CyberFlashSync.py companion script, located across
the known install paths (ToolBox bundle, beside this package, ~/.local/bin).
"""

import os
import shutil
import subprocess
import sys

_CANDIDATES = [
    os.path.expanduser("~/Games/CyberFlashSync.py"),
    "/run/media/Gigatone/ToolBox/ToolBox/Cyberpunk-Tools/GigaSort-core-tools/CyberFlashSync.py",
]


def find_cyberflash():
    pkg = os.path.dirname(os.path.abspath(__file__))
    here = os.path.dirname(pkg)
    cands = list(_CANDIDATES)
    for base in (here, os.path.expanduser("~/.local/bin"),
                 os.path.expanduser("~/.local/share/gigasort")):
        cands.append(os.path.join(base, "CyberFlashSync.py"))
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def run_cyberflash(folder, dry_run=False, with_game=False):
    script = find_cyberflash()
    if not script:
        print("(CyberFlashSync not found — a USB drive bundle is required)")
        return 1
    argv = [sys.executable, script]
    if dry_run:
        argv.append("--dry-run")
    if with_game:
        argv.append("--with-game")
    print("[gigasort] launching CyberFlashSync (add --dry-run to preview):")
    return subprocess.call(argv)
