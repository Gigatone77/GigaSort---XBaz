# Changelog

All notable changes to **GigaSort** are listed here.

## [3.0.1] - 2026-09-11

### GUI launch fix + fully-offline cosmetics

- **`gigasort` now opens the GUI by default.** Running the command with no
  flags in an interactive terminal launches the GTK4 window instead of the
  CLI dry-run report; `gigasort --gui` forces it explicitly. Piped/non-tty
  invocations and all CLI flags (`--apply`, `--undo`, ...) behave exactly as
  before.
- **Network indicator removed.** The static top-corner "Offline" chip is gone
  from the Scan and Rejects & Overrides pages - this is a fully offline
  program, so no connectivity badge is shown anywhere.

## [3.0.0] - 2026-09-11

### Central state dir + companion tools as package modules

- **State centralized** to `~/.local/share/GigaSort/state/<folder>-<hash>`
  with one-time lossless migration; watched folders stay free of
  `_GigaSort_*` clutter (`GS_STATE_DIR` env override; scratch/stage live
  under the state dir).
- **Legacy `_GigaSort_*` files migrated** out of Mod Library / Downloads.
- **GigaSlim / CyberFlashSync / XBaz rewritten as real package modules**
  (`gigasort.core.gigaslim` / `cyberflash` / `xbaz`) with `main()`/`run()`
  entry points; GUI companion tabs launch them via
  `python -m gigasort.core.<tool>`; slim/cyberflash CLI flags rewired.
- **CyberFlashSync** tools item now copies repo files + the gigasort package
  to the drive; gigasort workspace/state backed up from the central state dir.
- Companion-page base supports MODULE launching (`python -m`) next to the old
  external-script path.

## [2.2.0] - 2026-09-10

### Total-rewrite hardening: merged engine, dry-run fix, WTNC variants

- **`net` module deleted** — `utils/net.py` is removed (the permanent offline
  stub from 2.1.0 had no remaining callers). No network-shaped symbols remain
  in the codebase.
- **Overview:** deep audit sweep of `gigasort/core/*` — 657 insertions /
  797 deletions across 22 files, dead imports and branches removed, all lint
  `F/E501/B` clean.
- **`core/sort.py` merged engine** — `execute_sort` + `run_batch_sort`
  (~230 duplicated lines) collapsed into a shared `_execute_plan()` with
  `reject_mode="prompt"` (interactive) vs `"auto"` (headless); also known.
- **`core/gamestructure.py` dry-run data-loss bug fixed** — `--gamestructure
  --dry-run` previously EXTRACTED archives, created destination folders,
  moved staged files, made backups and wrote a manifest. It now prints the
  full placement plan and writes **nothing** (verified: 0 files touched).
  New memoized reference-index cache; method label `nexus` → `offline-category`.
- **`core/tags.py` dependency-check bug fixed** — `present_ids` was always
  empty so every dependency looked missing; now computed from the verified
  cache, manifest src basenames and the mod index.
- **`core/superseded.py` context bug fixed** — `find_superseded` mis-reversed
  the `(category, author, filename, size)` context tuple; fixed.
- **`core/wtnc.py` CyberTHING variants** — parses `**WTNC**` / `**THING**`
  blocks in the bundled manifest and tags those mods as variant-specific
  (e.g. Stealthrunner, Trace Position Overhaul); surfaced in the sweep report
  and GUI. Report key `fetched` → `bundled` (offline wording).
- **GUI/CLI polish** — rejects page refresh wired into sort-complete; static
  Offline chip CSS consistent; WTNC combo wordings offline-accurate;
  `--verify` banner is now `== OFFLINE VERIFICATION ==`.

## [2.1.0] - 2026-09-10

### Fully offline rewrite

GigaSort no longer performs any network access. There is no online layer left
in the codebase (the `net` module is a permanent offline stub and no `urllib`/
`requests` import survives). Identity, verification, category history and the
Night City compatibility list all come from bundled + per-workspace data:

- **New `gigasort/core/signature.py`** — builds a per-workspace offline info
  archive `_GigaSort_sig_archive.json` that merges, with zero network access:
  the bundled knowledge base (`data/sig_seeds.json` — 222 Nexus-confirmed /
  sorted and framework records + every WTNC curated id), the bundled
  `data/wtnc_modlist.md`, per-mod `meta.ini` files from prior verified
  extractions, the approved verified cache, and archive-filename identity
  tokens. `verified: True` is only awarded on real evidence (bundled seed,
  extracted meta.ini, or an approved cache entry) — never from a bare
  filename token.
- The archive auto-seeds the slim ID cache `_GigaSort_references.json` (921
  verified records from 5), so `rescue_category`, verification, superseded
  enrichments and the GUI all work offline.
- `wtnc.py` reads the bundled `Modlist.md` (no GitHub fetch, no manifest
  cache, no network).
- GUI: connectivity chips are a static "Offline" badge; the Rejects page's
  "Run search protocol" is now a bundle/cache "Look up offline".
- `gamestructure` category fallback, `report` online flag and CLI network
  confirmations all removed.

## [2.0.4] - 2026-09-07

### Dead code sweep (follow-up)
- Removed the orphaned `gigasort/tui/` package (module CLI/GUI never import it;
  it was only referenced by the old single-file monolith).
- Removed unreferenced constants (`NEXUS_GAME_SLUG`, `NEXUS_BASE`,
  `NEXUS_SEARCH_TERMS`, `LAUNCH_BACKUP_FILENAME`, `KEY_CTRL_A/Z`, `KEY_ENTER`,
  `KEY_ESC`) and unreferenced helpers across `utils`/`core`
  (`guarded_remove`, `truncate`, `wrap`, `file_size`, `dir_size`, `read_key`
  + raw-key machinery, `notify_net_status`, `write_info_log`/`log_path`,
  `load_tags`, `print_plan`, `non_mod_items`/`warn_non_mod_items`
  /`NON_MOD_SKIP`, `withheld_paths`, `DUP_SUFFIX`, `_noop_input`).
- Reused the previously-dangling `GS_MOD_INDEX` constant in `tags.py`
  (it duplicated the literal `"_MOD_INFO.json"`). Final file-count
  `print_plan`/`warn_non_mod_items` were the last consumers of their own
  callers, so the whole chains went.
- Added `gi.require_version("Adw", "1")` to `gui/util.py` so a standalone
  import no longer warns.
- `ruff check --select F,E501,B ` clean repo-wide.

### Added
- **WTNC Collection tab + `--check-wtnc`** (new core module
  `gigasort/core/wtnc.py`, new GUI page `gui/pages/wtnc.py`): Welcome to
  Night City / Cyberpunk THING compatibility sweep against z9er's curated
  modlist (the open project repo that feeds Nexus collection `iszwwe`).
    - **Manifest**: fetches `Wabbajack/Modlist.md` from
      `github.com/z9er/CyberpunkTHING` and parses every Nexus mod id into
      `_GigaSort_wtnc.json` (cache-first, so offline runs reuse the last good
      parse; a failed fetch never raises).
    - **Sweep**: scans the WHOLE library (root archives + organized
      category/author/framework folders; `_`-prefixed bins and state/scratch
      dirs are skipped) and classifies every archive as on-the-list /
      not-on-the-list / uncertain-no-id. Mods whose Nexus id is absent from
      the WTNC modlist are moved into the **`_NOT_WTNC`** bin ("Not compatible
      with WTNC") - collision-safe, never overwrites, never deletes.
    - **Safety**: only archives with a classic `-NNNN-` Nexus id token or an
      approved verified-cache entry are ever moved; bare CCXL-candidate ids
      and id-less files are left in place and reported. CLI default asks for
      confirmation on a real move (`--yes` auto-approves); `--check-wtnc`
      + `--dry-run` previews. A per-run report is written to
      `_GigaSort_wtnc_report.json`.
    - **Extra-compat overrides** (`_GigaSort_wtnc_compat.json`): a small
      user-editable `{mod_id: note}` map of ids treated as compatible even
      when absent from the parsed `Modlist.md`. Auto-seeded on first run with
      the WTNC team's own WTNC Config (10426) - collection infra that ships
      with the collection but is deliberately not a line in the Wabbajack
      list - so the sweep does not false-positive on it. Add/remove ids there
      rather than editing the manifest.
    - The GUI tab defaults to preview and has "Fetch manifest from GitHub",
      "Run sweep (preview)" and "Move incompatible to _NOT_WTNC" actions; the
      manifest source chip shows live-GitHub vs cached.
    - **Freshness + preview polish (follow-up)**: a cached modlist older than
      7 days is now auto-refreshed from GitHub (falling back to the cached
      copy if offline) instead of being silently reused - a move that may
      relocate 1000+ files never runs on stale data. The CLI/GUI label now
      reports whether the sweep ran on a live fetch or a cached copy. The CLI
      truncates long lists to 50 lines (full data stays in
      `_GigaSort_wtnc_report.json`). The GUI dropped its redundant Refresh
      button; "Move incompatible" now previews first and asks for
      confirmation with the exact count before moving; the summary line shows
      the active extra-compat ids.

## [2.0.3] - 2026-09-06

### Added
- **Rejects & Overrides tab** (new GUI page, wired into the main-window
  sidebar alongside the core Scan/Undo/Workspace pages): lists everything the
  sorter could not route - archives parked in `_REJECTS` plus unrecognized
  archives still loose at the workspace root - and lets you act on them:
    - **Run search protocol**: fires the same no-CAPTCHA web search the sorter
      uses on a new mod (`utils/net.py investigate_mod`), showing the verified
      Nexus title, detected category folder (pre-selected in the dropdown) and
      the mod's GitHub repo when the search finds one.
    - **Apply override**: persists the chosen category as BOTH a new
      `_GigaSort_web_overrides.json` entry (the human-verified source that
      beats every keyword rule) and a `_GigaSort_references.json` mod-id record
      plus an approved `_GigaSort_verified.json` cache entry, then moves the
      archive into its category folder via `sort._move_skip_collision` (a
      destination collision goes to `_DUPLICATES` - never overwritten, never
      deleted). The next sort recognizes and routes the file by itself.
- **Simplified connectivity indicator**: the Network chip on the Scan page
  (and the new tab) now shows just **Online** / **Offline** instead of the
  verbose "online - <reason>" strings, matching the user-space ask that the
  indicator stay a simple at-a-glance status.
- **Web-category override layer**: `_GigaSort_web_overrides.json` in the
  workspace root maps exact archive filenames to the category folder a human
  verified ONLINE. `resolve_category()` now checks this BEFORE the offline
  filename-keyword rule, so a live-verified web category (Nexus page category /
  Google-confirmed identity) can never be silently reverted by a keyword guess
  on a later sort. Precedence: web override > offline keyword > cached
  `nexus_cat`. Used by scan_workspace, find_misplaced and the placement sweep.

### Fixed
- **Scan-tab target folder is now a text field** (GUI `pages/scan.py`): the
  workspace folder can be typed directly into an entry box (with `~`
  expansion) instead of only via the file-explorer dialog. The explorer
  `Browse...` button on the folder row was later removed (its folder-picker
  result could come back null); the Game-directory row keeps its own button.
- **GUI no longer defaults to `~/Downloads`** (`gui/window.py`, `gui/pages/
  scan.py`, `gui/pages/gamestructure.py`, CLI help): when launched without
  `--folder` the app opens with an EMPTY folder field instead of silently
  pointing at `~/Downloads`. No hard-coded Downloads path remains in the GUI
  code (headless CLI modes keep their documented default).
- **Empty-workspace launch crash fixed** (GUI): pages that scanned the
  workspace at startup (StatusPage) no longer crash when no folder is chosen
  yet - `refresh()` shows "not set" until a folder is entered. The workspace
  typed in the Scan tab is also propagated to Undo/Status/Rejects/Game
  Structure pages after a sort so they reflect the folder actually used.
- **Empty author box now means "sort everything"** (GUI `pages/scan.py`):
  with no author(s) typed and "Author + organize rest" unchecked, a scan
  planned nothing at all (`Nothing to move`, no Apply prompt). An empty
  author field now forces full-batch mode, so typing any path and hitting
  Scan produces a real plan and the Apply button. Typing specific authors
  still uses the author-folder-only behavior.
- **Folder picker `Browse...` button removed** (GUI `pages/scan.py`): the
  workspace folder is now entered by typing only. The file dialog could
  return null after selecting a folder; the text entry alone is simpler and
  reliable. (The Game-directory row keeps its own Browse button.)
- **Latent `NameError` in offline readme verification**
  (`core/verify.py` `verification_statuses`): the readme-fallback mod-id lookup
  called `compat.readme_mod_id` without importing `compat`, which would crash
  verification of any archive whose filename carries no Nexus id.
- **Rejects & Overrides row crash when no search result exists yet**
  (GUI `pages/rejects.py` `_OverrideRow`): a row created for a listed file
  that hadn't been searched crashed with
  `AttributeError: 'NoneType' object has no attribute 'get'` because the raw
  `found` parameter (None) was read instead of the normalized `self.found`
  (`found or {}`). Pre-selecting the category dropdown now reads `self.found`
  like every other call site.
- **Rejects & Overrides sidebar entry rendered with no text**
  (GUI `window.py`): the sidebar row title `Rejects & Overrides` contains a
  bare `&`, which libadwaita's `ActionRow` parses as Pango markup (its
  `use-markup` defaults to True). The invalid `& ` entity made GTK drop the
  whole title, so the tab button appeared blank. The title is now escaped
  (`&amp;`) via `gui.util.esc` like every other user-facing string.
- **Dynamic framework group folders now cite the Nexus mod id explicitly**
  (core `sort.py` `resolve_framework_groups`): when an unrecognized shared
  dependency groups two or more downloads, the folder is now named
  `Framework (Nexus mod <id>)` instead of the ambiguous `Framework <id>` - the
  `<id>` is that requirement's Nexus mod id, so the folder name reads as "the
  mod with code <id> on Nexus" (`nexusmods.com/cyberpunk2077/mods/<id>`).
- **Module-`os` shadowing** (`core/compat.py`): a function-local
  `import ... os` shadowed the module-level import - a latent
  `UnboundLocalError` hazard (ruff F823).

### Removed
- **Dead-code sweep**: 23 ruff F-rule findings across the package and the
  Games companion scripts (CyberFlashSync / GigaSlim / XBaz): unused imports
  (`sys`, `shutil`, `re`, `Gtk`, `os`, `Gio`, `tags_mod`, `errno`,
  `subprocess`), unused locals (`last`, `rows`, `inner`, `path_next`,
  `has_folder`, `here`, `dev`/`fstype`, `exc`, `m`), a duplicate `"Animations"`
  category key, and a dead `except ... as e` binding. No behavior change.

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
