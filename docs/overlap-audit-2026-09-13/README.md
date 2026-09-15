# Pack Overlap Audit — 2026-09-13

Baseline = **pure WTNC install** (`Games/raw_WTNCCT_mod_pack/`, 1916 files).
NOT the live game dir — the live game has extra curated mods and would give
false positives. All 26 GAME STRUCTURE packs compared against baseline AND
against each other by exact game-relative path + sha256.

## Baseline result
- **All 26 packs: ZERO overlap with the WTNC tree.** Nothing in any pack
  would overwrite a base+WTNC install. Clean.

## Cross-pack path collisions
- **227 game-relative paths present in >1 pack.** Of these:
  - **226 byte-identical** (sha256 equal) — harmless duplicates, still worth
    deduping for tidiness.
  - **1 real content conflict:**
    `r6/scripts/VirtualCarDealer/Config.reds`
    `02 Cars & Vehicles` vs `22 Vehicles - methodd`.
    methodd's copy adds:
    ```
    public class CarDealerConfig {
      public static func HandleColorVariantsAsSingleLot() -> Bool = false
    }
    ```
    Last pack dropped wins → pack 22 overrides pack 02's config. On a
    WTNC-base install with BOTH packs, config differs. Decision needed:
    keep pack 02's (VCD framework) and let pack 22 ride its own, or
    consolidate.

## Collision groups (all identical content unless noted)
1. **Pack 02 legacy car pack vs new per-author packs (biggest group).**
   Pack 02 (`Cars & Vehicles`) still bundles cars that now ship in the
   per-author packs 07/08/09/14/20:
   - 02 ∩ 07 Oranje3: `oranje3_supron_widebody`, `r6/tweaks/oranje3_supron_widebody`
   - 02 ∩ 08 void: ~75 files (Silvia S15, Skyline 2000GT-R, Skyline R34 sets)
   - 02 ∩ 09 Cornmilf: ~20 files (Mustang Boss 302, Mazda RX7 FD, 190E, Trackhawk)
   - 02 ∩ 14 aalexbug: `lexus_lc500` (+ xl)
   - 02 ∩ 20 DennisReactive: `ArchV4.xl`, `BDF_DRe_Arch_V4.archive`, all 8
     `r6/tweaks/ArchV4_*.tweak`
   - 02 ∩ 11 ErenN77: `r6/scripts/VehicleManufacturerFix.reds`
   Recommendation: pack 02 should be slimmed to ONLY its unique content
   (VCD framework, Car Mod Shop, whip delete, BabyDriverV2); the bundled
   cars it duplicates are now owned by packs 07+.

2. **01 QoL ∩ 04 Quests: `backgroundScanner/` redscript framework (~113 files).**
   Identical copies of the Kiroshi Deep Scan core in both packs
   (`r6/scripts/backgroundScanner/...`). Should live in 04 only.

3. **03 CCXL Eyes ∩ 05 CCXL Hair: `NUT_johnnyhairedits_CCXL` + `NUT_mullet_collection_CCXL`**
   (archive + xl, identical, 4 files). Present in BOTH cosmetics packs → keep
   in hair pack 05 (they are hairstyles), drop from 03.

4. **Shared CET module .lua basenames (11 ErenN77 ∩ 15 SDH0 ∩ 01/02).**
   `Cron.lua/GameSession.lua/GameUI.lua/init.lua/WindowUtils.lua/
   ControlPanel.lua/ResolutionPresets.lua/Styles.lua/settings.lua` — these are
   per-mod copies living under DIFFERENT relative paths
   (`mods/<modname>/modules/...`), so they are NOT drop-in conflicts. Each CET
   mod ships its own copy. Baseline vs SDH0/ErenN77 confirmed the copies are
   self-contained. NO ACTION needed; placement check should treat same-mod
   subfolders as distinct.

5. **06 Zenitex ∩ 02: `SetupNewSite.reds`/`SetupNewTab.reds` (Virtual Atelier store
   scripts)** — checked identical in pack_review; exact-path matches not flagged
   because they differed in content path... (see scripts). Minor: VA store files.
   Keep with the virtual atelier content pack (06), drop from 02 if it carries VA
   store scaffolding for Zenitex cars.

## GigaSort improvement candidates
- **Baseline-aware conflict check**: add `--baseline <tree>` to `check_placement`
  or a new `--conflicts` audit? Detect against a READ-ONLY reference tree
  (WTNC) instead of the live game dir.
- **Cross-pack same-path detection**: when two archives in the scan resolve to
  the same game-relative path, report IDENTICAL vs DIFFERENT (sha256 of the
  interior file) instead of a generic dup.
- These scripts (`docs/overlap-audit-2026-09-13/`) are the reference
  implementation for that feature.