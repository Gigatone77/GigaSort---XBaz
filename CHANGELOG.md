# Changelog

All notable changes to **GigaSort** are listed here.

## [2.0.2] - 2026-09-06

### Added
- **Compatibility check noise filters** (`core/verify.py check_dependencies`):
  the web-referenced dependency report now treats always-installed CP2077
  frameworks (CET, RED4ext, TweakXL, ArchiveXL, Codeware, redscript, Input
  Loader, Mod Settings, Native Settings UI, Equipment-EX, Trigger Mode
  Control, Deceptious Quest Core, AMM) as satisfied, and skips self-referencing
  requirements, translation/language packs, and dev-tool-only entries
  (WolkenKit). Only genuine runtime gap downloads are reported.

### Changed
- **Live verification resilience**: transient Nexus errors (429, 5xx, socket
  timeout) are retried twice with backoff instead of failing the lookup,
  which had been rejecting real mods on flaky connections.
- **Bare-id downloads** now get LIVE verification (not just offline structure
  checks), so files whose Nexus id has no `-NNN-` filename token are
  classified correctly.
- **`_REJECTS` auto-rescue**: `--apply` re-verifies anything already sitting in
  the bin; web-verified mods are moved back to their correct category instead
  of staying stranded.
- **`11 Sensitive Content (18+)`**: the previously-named "Adult Content (18+)"
  folder (adult-gated Nexus pages identified via og:title/og:url). Renamed to
  reflect that not everything login-gated there is salacious.
- **World Building keywords**: `ramps`, `construction` added so vehicle ramp
  prop packs route to folder 10.

### Fixed
- **Dead code removed**: unused imports (`fs`, `Gtk` in `__main__`; `clean_name`,
  `net` in `compat`; `human_size` in `undo`; `json_load` in `gamestructure`;
  `Gdk`, `APP_NAME` in `app`; `Pango` in `companion`) and three unused helper
  functions (`_cat_folder_re`, `_size_of`, `_under`).

## [Unreleased]

### Added
- **Game-directory conflict detection** (`core/conflict.py`): once a Cyberpunk
  2077 install is set (GUI "Game directory" field, saved in
  `_GigaSort_settings.json`, or `--game-dir`), GigaSort compares every download
  against the actually-installed mod files (`archive/pc/mod`, `r6/scripts`,
  `red4ext/plugins`, engine/CET roots, etc.). Any archive that would OVERWRITE
  an already-installed file is routed to the **`_ON_HOLD`** review bin instead
  of its category folder, each with an explanation of exactly which installed
  file(s) it collides with. Strict exact-overwrite matching keeps false
  positives low. The check is a no-op when no game directory is configured.
- **On Hold tab** in the GUI showing conflicting mods + the installed files
  each would overwrite.

## [2.0.1] - 2026-09-06

### Fixed
- **XBaz GUI pane**: the "Swap sticks (L <-> R)" toggle title contained raw
  `<`/`>` characters, making GTK parse it as (invalid) Pango markup. The
  toggle now renders cleanly and no Gtk-WARNING is emitted at startup
  (`&lt;-&gt;` escaped).
- **`--check-superseded` crash**: dependency data was cached as
  `[game_slug, mod_id]` pairs (JSON lists), so `set(old_deps)` crashed with
  "cannot use 'list' as a set element". Deps are now normalized to plain
  mod-id strings when cached, and legacy pair-shaped entries are healed on
  load. Framework grouping (`sort.py`), the missing-dependency tag
  (`tags.py`) and superseded analysis all consumed this broken shape and now
  work off plain string ids.
- The verified/references caches on the real Downloads workspace were healed
  of legacy pair-shaped deps.

## [2.0.0] - 2026-09-03

Modular, redistributable rewrite shipping a GTK4 GUI + headless CLI.

### Added
- **GTK4 / libadwaita GUI** (`gigasort` with no flags). Core tabs: Scan &
  Sort, Undo, Workspace. A **Companion Tools** section adds one tab each for
  GigaSlim, CyberFlashSync, XBaz and **Game Structure**, each with a dedicated
  options sidebar and live output pane. The Game Structure tab drives the
  `--gamestructure` mode with source folder / game-dir / dry-run options.
- **Expanded CLI** (~35 flags), feature-parity with the published tool:
  `--verify --gate --check-deps --modlist --need-redownload --vram --preview
  --clean-dupes --trash --delete-rejects --extract --gamestructure --agent
  --cyberflash --gigaslim --reveal --setup --strict --yes --dry-run --json
  --undo --locate --keep` and multi-folder `--folder a,b` (each root run in its
  own subprocess so workspaces are never crossed).
- **HARD web-verification safety rule** (enforced in code): only web-verified
  Cyberpunk 2077 mods are ever moved, deleted, or touched. Deletion modes
  (`--trash`, `--delete-rejects`) are verified-only.
- New core modules: `setup`, `trash`, `cyberflash`, `gigaslim`, plus companion
  launcher GUI pages.
- Publishable distribution: `pyproject.toml` (hatchling), `README.md`, `LICENSE`
  (MIT), wheel + sdist under `dist/`.

### Fixed
- **Game-structure extraction** (`--gamestructure`): `_safe_extract` was
  overriding `dest_dir` with the workspace root (`fs.guard_under` returns the
  root), silently dumping extracted files into the source folder instead of
  the stage / game tree. Now it asserts containment and keeps `dest_dir`, so
  archives compile into the correct `GAMESTRUCTURE/<subpath>` tree and the
  source folder stays clean (temp stage is removed after the build).
- **Game-structure `--yes`**: the non-interactive confirm value (`confirm`)
  now satisfies the `[y/N]` prompt, so `--yes` proceeds without aborting.

### Packaging
- Install from source: `pip install .` -> `gigasort` command with GUI + CLI.
- Companion tools GigaSlim / CyberFlashSync / XBaz launch the reference
  `~/Games/*.py` scripts as subprocesses.

## [1.0.0] - 2026-09-01

Initial single-file release (`GigaSort.py`) with full-screen TUI, category
sorting, deduplication, offline-first Nexus verification, threat gate,
dependency check, game-structure sort, extraction mode, and the
CyberFlashSync / GigaSlim / XBaz base features. Superseded by the modular
2.0.0 package (the old single-file bundle is retained on the USB drive).
