# Changelog

All notable changes to **GigaSort** are listed here.

## [2.0.0] - 2026-09-03

Modular, redistributable rewrite shipping a GTK4 GUI + headless CLI.

### Added
- **GTK4 / libadwaita GUI** (`gigasort` with no flags). Core tabs: Scan &
  Sort, Undo, Workspace. A **Companion Tools** section adds one tab each for
  GigaSlim, CyberFlashSync and XBaz, each with a dedicated options sidebar and
  live output pane.
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
