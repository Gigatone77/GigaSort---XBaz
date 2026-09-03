# GigaSort — Cyberpunk 2077 Mod-Archive Organizer

GigaSort sorts raw Nexus-mod archives (`.zip` / `.rar` / `.7z`) from a download
folder into numbered content-type category folders, collapses duplicate
downloads, and **web-verifies each mod against its Nexus page before anything
is moved**.

This is the modular, redistributable package (v2.0.0). It ships a **GTK4 /
libadwaita GUI** plus a full headless CLI, and bundles three companion tools —
GigaSlim, CyberFlashSync and XBaz — each runnable from its own GUI tab.

> **Safety first (HARD rule):** GigaSort never moves, trashes, deletes, or
> otherwise touches any file that is not **web-verified** as a real Cyberpunk
> 2077 mod (a Nexus lookup, or an already-`APPROVED` local cache entry).
> Unverified files are always left in place and reported.

---

## Features

- **GUI** — `gigasort` with no flags opens a libadwaita window. Core tabs
  (Scan & Sort, Undo, Workspace) are unchanged; a **Companion Tools** section
  adds one tab per extra tool (GigaSlim, CyberFlashSync, XBaz), each with a
  dedicated options sidebar + live output pane.
- **Categorize** — sorts archives into 9 numbered content folders (Eyes &
  Lashes, Hair, Face & Body, Tattoos & Cyberware, Clothing & Armor, Weapons &
  Misc Items, Vehicles & Transport, Colors/Profiles/Resources,
  Cores/Fixes/Utilities).
- **Deduplicate** — collapses repeated-download `(1)`/`(2)` copies (moved to
  `_DUPLICATES`, never deleted).
- **Verify (offline-first / web-gated)** — reads each mod's Nexus mod ID from
  its filename and cross-checks against the Nexus page. A local `APPROVED`
  cache is honored before any live fetch. **Only verified files are ever
  touched by the sort.**
- **Threat gate** — withholds unverified or watchlisted mods before moving them.
- **Dependency check** — flags mods whose required dependencies aren't among
  your files, with Nexus links.
- **Game-structure sort** — builds a ready-to-use CP2077 folder tree that
  mirrors the real install root (`archive/`, `r6/`, `red4ext/`, `bin/`, ...).
- **Extraction mode** — unpacks each archive into `<type>/<author>/<name>/`
  with a per-mod info file.
- **Agent bridge** — a read-only, local-only opencode/local-agent integration.
- **GigaSlim** — makes a CP2077 install slimmer without deleting: bloat is
  moved to a backup store and recorded, so every trim restores.
- **CyberFlashSync** — one-command backup of customized CP2077 files to a USB
  flash drive (additive only).
- **XBaz** — Xbox Elite Series 2 controller manager (stock `xpad`/`hid-microsoft`
  baseline, back-paddle setup).

---

## Requirements

- Python 3.12+ (standard library only — no third-party pip dependencies)
- GUI: GTK 4 + libadwaita 1 (system packages, e.g. `gtk4` `libadwaita` on
  Fedora/Bazzite)
- Optional: `7z` and `unrar` for `.7z` / `.rar` preview and extraction
- Optional: network for live Nexus verification (works offline via the cache)
- Companion tools located at `~/Games/*.py` or the ToolBox bundle

## Install

```bash
git clone https://github.com/Gigatone77/gigasort.git
cd gigasort
pip install .
```

`gigasort` is then available anywhere:

```bash
gigasort                  # open the GTK GUI
gigasort --apply          # headless sort (verify-gated)
gigasort --help           # full CLI reference
```

## Quick start

```bash
gigasort                         # GUI
gigasort --apply --dry-run       # preview a sort, move nothing
gigasort --apply                 # headless sort: categorize + move verified mods
gigasort --folder /path --apply  # ... on a chosen workspace
gigasort --undo                  # reverse the previous run
```

### Command-line reference

```
gigasort                      open the GUI
gigasort --apply              headless sort - move VERIFIED mods only
gigasort --apply --keep       same, but leave rejects in place
gigasort --undo               reverse the previous run
gigasort --json               read-only machine-readable inventory
gigasort --locate             map of workspace folders + state files
gigasort --reveal             open workspace in the file manager
gigasort --setup              interactive setup (target folder, extract toggle)
gigasort --preview            report each archive's install shape
gigasort --verify             check each mod against Nexus, update APPROVED cache
gigasort --gate               threat/reputation gate
gigasort --check-deps         dependency dashboard (read-only)
gigasort --modlist FILE       fuzzy-match downloads against an MO2 modlist
gigasort --need-redownload FILE   xref downloads against a NEED_REDOWNLOAD list
gigasort --vram GB            report install footprint vs a VRAM budget
gigasort --clean-dupes        move duplicates to _DUPLICATES
gigasort --trash              manage _TRASH (delete VERIFIED-only)
gigasort --delete-rejects     delete VERIFIED-only items in _REJECTS
gigasort --extract            unpack mods into type/author/name folders
gigasort --gamestructure      build a ready-to-use CP2077 folder tree
gigasort --cyberflash         run CyberFlashSync (--with-game opt-in)
gigasort --gigaslim           run GigaSlim (--videos opt-in)
gigasort --folder a,b         sort each folder in its own subprocess
gigasort --strict             refuse all WARN-tier destructive actions
gigasort --yes                approve confirmations non-interactively
gigasort --dry-run            preview only, move nothing
```

---

## Safety model

Everything routes through a guard layer:

- **Boundary fence** — only ever touches the single folder you give it; any
  target resolving outside is hard-blocked (paths are `realpath`-resolved).
- **Web-verification gate (HARD rule, enforced in code)** — `--apply` and the
  agent `move` op move only files that are `APPROVED` in the verified cache or
  confirmed against a real CP2077 Nexus page at sort time. Everything else is
  left in place and reported.
- **Deletion modes are VERIFIED-ONLY** — `--trash` and `--delete-rejects`
  delete only web-verified CP2077 mods; unverified files/directories are never
  deleted, only reported.
- **Risk tiers** — *allow* / *warn* / *block*; deletes and overwrites are
  *warn*-tier (double-confirmed, or refused under `--strict`).
- **No auto-delete** — rejects/duplicates go into mutually-exclusive bins
  (`_REJECTS`, `_TRASH`, `_DUPLICATES`, `_ON_HOLD`).
- **Undo manifest** — every move is recorded, so `--undo` restores the last run.

### Non-mod files

GigaSort moves **only** categorized mod archives. Loose files or unrecognized
folders are warned about and left in place — never touched.

---

## Files GigaSort creates

Inside the target folder it manages:

```
_REJECTS / _TRASH / _DUPLICATES / _ON_HOLD   bins (never auto-deleted)
_GigaSort_settings.json       program config
_GigaSort_verified.json       web-verification cache (APPROVED set)
_GigaSort_verification_log.txt
_GigaSort_manifest.json       move records (for --undo)
_GigaSort_threats.json        local threat watchlist
_GigaSort_tags.json           processed-mods tags
_GigaSort_bridge/             agent/opencode bridge
```

---

## Companion tools

Each companion runs standalone or from its own **GUI tab** (they ship next to
this package / in `~/Games/` / on the ToolBox bundle):

- **GigaSlim** — `gigaslim` (analyze / apply / restore / status). Moves bloat
  (non-English languages, the launcher MSI, 13 GB cutscene archive with
  `--videos`, regenerable cache with `--cache`) to a restore-point backup
  store. Never touches load-bearing cache files or loading-screen art.
  Restore with `gigaslim restore`.
- **CyberFlashSync** — `cyberflashsync`. Additive home→USB backup of your
  customized CP2077 setup. Zips are replaced atomically only after a verify;
  the ~90 GB game dir is only included with `--with-game`.
- **XBaz** — `xbaz`. Xbox Elite Series 2 controller manager: `status`
  (read-only), `bind` / `reset` / `steam` (root via sudo), `paddles`
  (interactive back-paddle test).

## License

[MIT](LICENSE)

Companion tools GigaSlim, CyberFlashSync and XBaz are covered by the same MIT
license.
