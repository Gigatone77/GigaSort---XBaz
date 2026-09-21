#!/usr/bin/env python3
"""Cross-pack conflicts by exact game-relative PATH, with content equality."""
import os, hashlib
from collections import defaultdict

G = "/var/home/Gigatone/Games"
PACKS = sorted(d for d in os.listdir(G) if d.endswith(" - GAME STRUCTURE"))
SKIP = {"MOD_LIST.txt", "meta.ini", "COMPATIBILITY_NOTES.txt", "placeholder.vortex"}

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

# relpath -> {pack: sha}
paths = defaultdict(dict)
for p in PACKS:
    root = os.path.join(G, p)
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if f in SKIP:
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, root)
            paths[rel][p] = sha(full)

print(f"{'game-relative path':70} {'#packs':7} same-id?  packs")
print("-" * 120)
for rel, packs in sorted(paths.items()):
    if len(packs) < 2:
        continue
    vals = set(packs.values())
    same = "IDENTICAL" if len(vals) == 1 else ("DIFFERENT" if len(vals) > 1 else "?")
    print(f"{rel:70} {len(packs):<7} {same:<9} {', '.join(sorted(packs))}")