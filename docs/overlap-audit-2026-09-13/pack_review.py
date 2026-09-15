#!/usr/bin/env python3
"""For each pack 01-26: find overlaps vs WTNC baseline tree and vs other packs."""
import os
from collections import defaultdict

G = "/var/home/Gigatone/Games"
WTNC = os.path.join(G, "raw_WTNCCT_mod_pack")
PACKS = sorted(
    (d for d in os.listdir(G) if d.endswith(" - GAME STRUCTURE")),
    key=lambda d: (0, d) if d[:2].isdigit() else (1, d),
)

def rels(root):
    out = set()
    for dp, dn, fn in os.walk(root):
        for f in fn:
            out.add(os.path.relpath(os.path.join(dp, f), root))
    return out

print(f"WTNC baseline: {os.path.join(WTNC)} ({len(rels(WTNC))} files)\n")

wtnc = rels(WTNC)
pack_rels = {p: rels(os.path.join(G, p)) for p in PACKS}

# map basename->packs for cross-pack
base_map = defaultdict(list)
for p in PACKS:
    for rel in pack_rels[p]:
        base_map[p].append(os.path.basename(rel))
        _ = base_map  # placeholder

# For cross check: full filename (basename) collisions across packs
by_basename = defaultdict(list)
for p in PACKS:
    for b in base_map[p]:
        by_basename[b].append(p)

for p in PACKS:
    pr = pack_rels[p]
    print("=" * 78)
    print(f"PACK {p}")
    print(f"  files: {len(pr)}")
    # 1) vs WTNC baseline
    ov = sorted(pr & wtnc)
    if ov:
        print(f"  [WTNC OVERLAP] {len(ov)} file(s) already in unpicked WTNC baseline:")
        for rel in ov:
            print(f"      {rel}")
    else:
        print("  [WTNC OVERLAP] none")
    # 2) vs other packs (exact basename present in another pack)
    cross = defaultdict(set)
    for b in base_map[p]:
        for other in by_basename.get(b, []):
            if other != p:
                cross[b].add(other)
    if cross:
        print(f"  [CROSS-PACK] {len(cross)} basename(s) also present in other pack(s):")
        for b, others in sorted(cross.items()):
            print(f"      {b}")
            print(f"          also in: {', '.join(sorted(others))}")
    else:
        print("  [CROSS-PACK] none")
print("=" * 78)