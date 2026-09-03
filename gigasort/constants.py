"""GigaSort — constants and configuration.

Centralised so every module shares one set of rules, bin names, state-file
names and Cyberpunk 2077 game-structure references. Anything a user might
want to tweak lives here (category rules, Nexus game slug, VRAM keywords).
"""

import os
import re

# ---------------------------------------------------------------------------
# Workspace / generic
# ---------------------------------------------------------------------------
HOME = os.path.expanduser("~")
DEFAULT_WORKSPACE = os.path.join(HOME, "Downloads")

ARCHIVE_EXTS = (".zip", ".rar", ".7z")

# Bin folders inside the workspace (mutually exclusive where noted).
REJECT_BIN = "_REJECTS"      # review / uncategorized holder
TRASH_BIN = "_TRASH"          # marked for deletion (wiped only per-file)
HOLD_BIN = "_ON_HOLD"         # threat-gated, waiting on the user
DUPLICATES_BIN = "_DUPLICATES"

# State files (all written inside the workspace).
SETTINGS_FILENAME = "_GigaSort_settings.json"
CACHE_FILENAME = "_GigaSort_verified.json"
LOG_FILENAME = "_GigaSort_verification_log.txt"
MANIFEST_FILENAME = "_GigaSort_manifest.json"
TAGS_FILENAME = "_GigaSort_tags.json"
THREAT_FILENAME = "_GigaSort_threats.json"
LAUNCH_BACKUP_FILENAME = "_GigaSort_launch_backup.json"
GS_MANIFEST = "_GigaSort_gamestruct.json"

# Game-structure sort.
GS_STRUCTURE_DIR = "GAMESTRUCTURE"   # staging output folder
GS_STAGE_DIR = "_GigaSort_stage"     # temporary extraction scratch
GS_BACKUP_DIR = "_GigaSort_backup"   # timestamped conflict backups
GS_MOD_INDEX = "_MOD_INFO.json"      # master index of extracted mods

# Agent bridge.
BRIDGE_DIR = "_GigaSort_bridge"

# ---------------------------------------------------------------------------
# Nexus
# ---------------------------------------------------------------------------
# The Nexus game slug. Cyberpunk 2077 is the default/target.
NEXUS_GAME_SLUG = "cyberpunk2077"
NEXUS_BASE = "https://www.nexusmods.com/%s/mods/" % NEXUS_GAME_SLUG

# Filename token "-12xxxx-" (or "-1xxx-"/"-2xxxx-") is the Nexus mod id.
NEXUS_ID_RE = re.compile(r"-(\d{4,6})-", re.IGNORECASE)

# Author-name tokens that are never a real author.
AUTHOR_STOPWORDS = {
    "cyberpunk", "the", "collection", "all", "new", "mod",
    "file", "cdprojectred", "cdpr", "2077",
}

# ---------------------------------------------------------------------------
# Categorization rules
# ---------------------------------------------------------------------------
# Ordered list of (folder_name, [regex keyword list]). First rule whose
# keywords appear in the (lowercased) filename wins. Ordering matters:
# specific mod features must come before broad "CCXL - <name>" hair rules.
RULES = [
    ("01 Eyes & Lashes", [
        r"\beyes?\b", r"eyes", r"cybereye", r"sclera", r"\bir[ei]s", r"pupil",
        r"eyelash", r"eye ?lash", r"lash", r"eyebrow", r"brows?\b",
        r"mascara", r"optics", r"gith eyes", r"heterochromia",
        r"eyeshadows?", r"eye ?make ?up", r"makeup", r"eye make",
        r"black line", r"white line", r"blackline", r"whiteline",
        r"natural - b", r"glow - b",
    ]),
    ("04 Tattoos & Cyberware", [
        r"tattoo", r"\bcyberware\b", r"implant", r"chrome", r"piercing",
        r"head cyberware", r"halo", r"cyber ?arm", r"cyberpod",
        r"jackie", r"warrior nun",
        r"sandevistan", r"sande?evistan", r"optic flare", r"monowire",
        r"mantis blade", r"gorilla arm", r"kerensikov",
    ]),
    ("05 Clothing & Armor", [
        r"armor", r"\bvest\b", r"helmet", r"\bboots?\b", r"\bgloves?\b",
        r"\bjacket\b", r"\bpants?\b", r"\bsuit\b", r"holster",
        r"\bgoggles?\b", r"gpnv", r"\bmask\b", r"respirator",
        r"backpack", r"leggings?", r"underwear", r"swimsuit",
        r"\bpads?\b", r"shield", r"shoes?", r"balaclava", r"visors?",
        r"turtleneck", r"tshirt", r"t-shirt", r"vest", r"combat ",
        r"military", r"zenitex", r"assault ", r"/ledger\b",
    ]),
    ("03 Face & Body", [
        r"complexion", r"\bskin\b", r"\bmesh(es)?\b", r"\bteeth\b",
        r"body toggle", r"body part", r"hide body", r"\btorso\b",
        r"fem ?v\b", r"female", r"male", r"masculine",
    ]),
    ("02 Hair", [
        r"\bhair\b", r"hairstyle", r"\bhairs\b", r"\bbob\b", r"ponytail",
        r"\bpony\b", r"\bbun\b", r"buns\b", r"crown bun", r"fringe",
        r"wolfcut", r"mullet", r"bang", r"braid", r"pigtail", r"updo",
        r"upstyle", r"top ?knot", r"mohawk", r"slick ?back", r"shag",
        r"side swept", r"sideswept", r"curls?", r"wavy", r"strands?",
        r"hime", r"pixie", r"comb ?over", r"top ?bun", r"messy",
        r"mullethawk", r"rivia", r"motoko",
        r"\bpak\b",
        r"length pak",
        r"hair pack", r"hairpack", r"hairstyles 2", r"hair collection",
        r"hair ?up", r"hairup", r"bottom ?bun", r"low ?pony",
        r"dusty_",
        r"19928",
        r"20175",
        r"npc.*hair",
        r"ccxl - [a-z]",
    ]),
    ("06 Weapons & Misc Items", [
        r"weapon", r"tron ?disk", r"yokai", r"netrunner", r"accessor",
        r"virtual atelier", r"store", r"\bshop\b", r"delta collection",
    ]),
    ("09 Vehicles & Transport", [
        r"\bvehicle", r"\bvehicles?", r"\bcar(s|s mod)?\b", r"\bmoto\b",
        r"\bmotorbike", r"\bmotorcycle", r"\bmotorcycle\b", r"\bbike\b",
        r"\bquadra\b", r"\bcaliburn\b", r"\bnazare\b", r"\barch\b",
        r"\bmizutani\b", r"\btyger claw\b", r"hoverbike", r"vehical",
        r"car mod", r"delemain", r"\btaxi\b", r"\btruck\b", r"combat veh",
    ]),
    ("07 Colors, Profiles & Resources", [
        r"hair ?colou?r", r"hair ?color", r"palette", r"colour", r"color",
        r"hair profiles", r"profiles", r"resource", r"toolkit",
        r"template", r"multicolor", r"colorblock", r"solid",
        r"split ?dye", r"dye\b", r"pigment", r"shader", r"style kit",
        r"the community palette", r"opposites", r"complimentar",
        r"colour wheel", r"colourful",
        r"natural californian lighting", r"\bnclm\b", r"world lighting",
        r"lighting overhaul", r"californian",
    ]),
    ("08 Cores, Fixes & Utilities", [
        r"\bcore\b", r"\bfix\b", r"\bresource\b", r"fps", r"toggle",
        r"framework", r"utility", r"\bcompatibility\b", r"\bpatch\b",
        r"hair profiles compatibility", r"\bengine\b", r"\btool\b",
        r"atlas", r"_turned_", r"simple_", r"fix_",
        r"begone", r"fast ?launch", r"load ?begone", r"skip ?continue",
        r"skip ?intro", r"splash", r"no ?preloader", r"recoded",
        r"video ?mod", r"quick ?load", r"no ?videos?", r"cutscene",
        r"\bconfig\b", r"\b\.ini\b", r"\bwtnc\b", r"settings",
    ]),
]

# Nexus category id -> content-type folder (light mapping from the official
# Nexus category tree, used to sanity-check the keyword guess).
NEXUS_CAT_MAP = {
    "body": "03 Face & Body",
    "clothing": "05 Clothing & Armor",
    "armor": "05 Clothing & Armor",
    "player-cyberware": "04 Tattoos & Cyberware",
    "accessories": "06 Weapons & Misc Items",
    "weapons": "06 Weapons & Misc Items",
    "vehicles": "09 Vehicles & Transport",
    "ui-modification": "08 Cores, Fixes & Utilities",
    "facial-skin-complexions": "03 Face & Body",
    "eyes": "01 Eyes & Lashes",
    "hair": "02 Hair",
    "tattoos": "04 Tattoos & Cyberware",
    "visuals": "07 Colors, Profiles & Resources",
    "colors-textures": "07 Colors, Profiles & Resources",
    "textures": "07 Colors, Profiles & Resources",
    "bug-fixes": "08 Cores, Fixes & Utilities",
    "utilities": "08 Cores, Fixes & Utilities",
    "framework": "08 Cores, Fixes & Utilities",
    "qol": "08 Cores, Fixes & Utilities",
    "gameplay": "08 Cores, Fixes & Utilities",
}

NEXUS_SEARCH_TERMS = [
    "eyes", "lashes", "eyelashes", "eyebrow", "brows", "hair", "hairstyle",
    "bob", "ponytail", "bun", "wig", "tattoo", "cyberware", "implant",
    "piercing", "chrome", "armor", "armour", "vest", "helmet", "boots",
    "gloves", "jacket", "pants", "suit", "goggles", "mask", "skins",
    "complexion", "body", "weapon", "accessory", "color", "colour", "palette",
    "texture", "utility", "framework", "pistol", "holster",
]

TITLE_MATCHERS = [
    ("bob", "02 Hair"), ("ponytail", "02 Hair"), ("hairstyle", "02 Hair"),
    ("pigtail", "02 Hair"), ("wig", "02 Hair"), ("bun", "02 Hair"),
    ("fringe", "02 Hair"), ("mullet", "02 Hair"), ("eyelash", "01 Eyes & Lashes"),
    ("lashes", "01 Eyes & Lashes"), ("eyebrow", "01 Eyes & Lashes"),
    ("brows", "01 Eyes & Lashes"), ("sclera", "01 Eyes & Lashes"),
    ("irises", "01 Eyes & Lashes"), ("iris", "01 Eyes & Lashes"),
    ("tattoo", "04 Tattoos & Cyberware"), ("cyberware", "04 Tattoos & Cyberware"),
    ("implant", "04 Tattoos & Cyberware"), ("piercing", "04 Tattoos & Cyberware"),
    ("helmet", "05 Clothing & Armor"), ("armor", "05 Clothing & Armor"),
    ("armour", "05 Clothing & Armor"), ("jacket", "05 Clothing & Armor"),
    ("boots", "05 Clothing & Armor"), ("gloves", "05 Clothing & Armor"),
    ("pants", "05 Clothing & Armor"), ("goggles", "05 Clothing & Armor"),
    ("mask", "05 Clothing & Armor"), ("vest", "05 Clothing & Armor"),
    ("weapon", "06 Weapons & Misc Items"), ("pistol", "06 Weapons & Misc Items"),
    ("accessor", "06 Weapons & Misc Items"),
    ("vehicle", "09 Vehicles & Transport"), ("vehicles", "09 Vehicles & Transport"),
    ("car", "09 Vehicles & Transport"), ("bike", "09 Vehicles & Transport"),
    ("motorcycle", "09 Vehicles & Transport"), ("quadra", "09 Vehicles & Transport"),
    ("palette", "07 Colors, Profiles & Resources"),
    ("colour", "07 Colors, Profiles & Resources"),
    ("color", "07 Colors, Profiles & Resources"),
    ("complexion", "03 Face & Body"), ("skins", "03 Face & Body"),
    ("body", "03 Face & Body"), ("hair", "02 Hair"), ("eyes", "01 Eyes & Lashes"),
]

# ---------------------------------------------------------------------------
# Verification statuses / threat tiers
# ---------------------------------------------------------------------------
APPROVED = "approved"
MISMATCH = "mismatch"
UNVERIFIED = "unverified"
NOMODID = "no-mod-id"
AUTO = "auto-assigned"

TRUSTED = "trusted"
ON_HOLD = "on-hold"
WATCHED = "watched"

RISK_ALLOW = "allow"
RISK_WARN = "warn"
RISK_BLOCK = "block"

SUSPICIOUS_KEYWORDS = (
    "crack", "keygen", "activator", "crypto", "bitcoin", "malware",
    "trojan", "backdoor", "rat",
)

# ---------------------------------------------------------------------------
# Keyboard (TUI)
# ---------------------------------------------------------------------------
KEY_CTRL_A = "\x01"
KEY_CTRL_Z = "\x1a"
KEY_ENTER = "\r"
KEY_ESC = "\x1b"

# ---------------------------------------------------------------------------
# Cyberpunk 2077 game structure (used by --preview and --gamestructure)
# ---------------------------------------------------------------------------
CP2077_ROOT_DIRS = (
    "archive", "bin", "engine", "mods", "r6", "red4ext", "tools",
)
GAME_ROOT_DIRS = CP2077_ROOT_DIRS

# File extensions that signal "place under archive/pc/mod".
ARCHIVE_INSTALL_EXTS = (".archive", ".dep", ".toc")

# Keywords that flag likely high-res / oversized texture packs (VRAM guard).
VRAM_HIRES_WORDS = (
    "4k", "ultra", "hires", "high.res", "8k", "texture pack", "16k",
    "2k", "hd reworked", "hdr", "overhaul gfx",
)


def default_workspace():
    """Resolve the default workspace once (kept a function so tests can
    override HOME cleanly)."""
    return DEFAULT_WORKSPACE
