#!/usr/bin/env python3
"""Inventory all GAME STRUCTURE packs; find overlapping files across packs."""
import os
from collections import defaultdict

G = "/var/home/Gigatone/Games"
PACKS = sorted(d for d in os.listdir(G) if d.endswith(" - GAME STRUCTURE"))
print(f"{len(PACKS)} packs found\n")

# relative path -> list of (pack, size)
relpath = defaultdict(list)
# basename -> list of (pack, relpath)
basename = defaultdict(list)
# per-pack: relpath -> sha256 (for identical-content detection)
shas = {}

for p in PACKS:
    root = os.path.join(G, p)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            relpath[rel].append((p, os.path.getsize(full)))
            basename[fn].append((p, rel))

print("=== 1) SAME RELATIVE PATH in >1 pack (would overwrite on drop-in) ===")
any_x = False
for rel, locs in sorted(relpath.items()):
    packs = sorted({p for p, _ in locs})
    if len(packs) > 1:
        any_x = True
        print(f"\n{rel}")
        for p, s in locs:
            print(f"    {s:>9}  {p}")
if not any_x:
    print("  (none)")

print("\n=== 2) SAME BASENAME in >1 pack (potential clash even at different rel path) ===")
any_b = False
for fn, locs in sorted(basename.items()):
    packs = sorted({p for p, _ in locs})
    if len(packs) > 1:
        # skip pure meta.ini / known list files
        if fn in ("meta.ini", "MOD_LIST.txt", "COMPATIBILITY_NOTES.txt"):
            continue
        any_b = True
        print(f"\n{fn}")
        for p, rel in locs:
            print(f"    {p}  ::  {rel}")
if not any_b:
    print("  (none)")

print("\n=== 3) Per-pack total file count ===")
for p in PACKS:
    root = os.path.join(G, p)
    n = sum(len(f) for _, _, f in os.walk(root))
    print(f"  {n:5d}  {p}")