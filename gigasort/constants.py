"""GigaSort — constants and configuration.

Centralised so every module shares one set of rules, bin names, state-file
names and Cyberpunk 2077 game-structure references. Anything a user might
want to tweak lives here (category rules, VRAM keywords, framework grouping).
"""

import os
import re

HOME = os.path.expanduser("~")
DEFAULT_WORKSPACE = os.path.join(HOME, "Downloads")

ARCHIVE_EXTS = (".zip", ".rar", ".7z")

# Bin folders inside the workspace (mutually exclusive where noted).
REJECT_BIN = "_REJECTS"      # review / uncategorized holder
TRASH_BIN = "_TRASH"          # marked for deletion (wiped only per-file)
HOLD_BIN = "_ON_HOLD"         # conflict gated, waiting on the user
DUPLICATES_BIN = "_DUPLICATES"
NOT_WTNC_BIN = "_NOT_WTNC"    # "Not compatible with WTNC" sweep bin

# State files (all written inside the workspace).
SETTINGS_FILENAME = "_GigaSort_settings.json"
CACHE_FILENAME = "_GigaSort_verified.json"
REFERENCE_FILENAME = "_GigaSort_references.json"
WEB_OVERRIDES_FILENAME = "_GigaSort_web_overrides.json"
LOG_FILENAME = "_GigaSort_verification_log.txt"
MANIFEST_FILENAME = "_GigaSort_manifest.json"
TAGS_FILENAME = "_GigaSort_tags.json"
THREAT_FILENAME = "_GigaSort_threats.json"
GS_MANIFEST = "_GigaSort_gamestruct.json"
SIG_ARCHIVE_FILENAME = "_GigaSort_sig_archive.json"
GS_MOD_INDEX = "_MOD_INFO.json"      # master index of extracted mods
GS_COLLECTION_CACHE = "_GigaSort_collection.json"
WTNC_REPORT_FILENAME = "_GigaSort_wtnc_report.json"
WTNC_EXTRA_COMPAT_FILENAME = "_GigaSort_wtnc_compat.json"

# Bundled (shipped) offline knowledge-base filenames in gigasort/data/.
SIG_SEEDS_BUNDLED = "sig_seeds.json"
WTNC_BUNDLED_MANIFEST = "wtnc_modlist.md"

# Game-structure sort.
GS_STRUCTURE_DIR = "GAMESTRUCTURE"   # staging output folder
GS_STAGE_DIR = "_GigaSort_stage"     # temporary extraction scratch
GS_BACKUP_DIR = "_GigaSort_backup"   # timestamped conflict backups

# Reference game-structure folder used by --gamestructure to map loose /
# non-game-shaped archives onto a verified, known-good layout (the user's
# cleaned WTNC-based "drop-ready package" that mirrors the CP2077 game root).
# Only used when the folder actually exists on disk; otherwise the offline
# category/manual resolution is used unchanged. Override with the env var
# GS_REFERENCE_GAME_STRUCTURE.
DEFAULT_REFERENCE_STRUCTURE = os.path.join(
    HOME, "Games", "Custom Mod Additions Archive - GAME STRUCTURE")

# Agent bridge.
BRIDGE_DIR = "_GigaSort_bridge"

# ---------------------------------------------------------------------------
# Nexus
# ---------------------------------------------------------------------------
# Filename token "-12xxxx-" (or "-1xxx-"/"-2xxxx-"), including LOW 3-digit
# ids ("-790-" = Appearance Menu Mod), is the Nexus mod id.
NEXUS_ID_RE = re.compile(r"-(\d{3,6})-", re.IGNORECASE)

# Author-name tokens that are never a real author.
AUTHOR_STOPWORDS = {
    "cyberpunk", "the", "collection", "all", "new", "mod",
    "file", "cdprojectred", "cdpr", "2077",
}

# Offline "strong" CP2077 keyword list (see CP2077_STRONG_KEYWORDS).
CP2077_STRONG_KEYWORDS = (
    "ccxl",
    "femv", "mascv", "feme v", "male v", "female v",
    "red4ext", "redscript", "cyber engine tweaks", "cyber_engine_tweaks",
    "cet",
    "virtual atelier", "meluminary", "sedth",
    "cyberware", "cyberdeck", "netrunner", "sandevistan",
    "monowire", "mantis blade", "gorilla arm", "kerensikov", "cyberpod",
    "night city", "barghest", "delamain",
    "caliburn", "quadra",
)

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
# Cyberpunk 2077 game structure (used by --preview and --gamestructure)
# ---------------------------------------------------------------------------
CP2077_ROOT_DIRS = ("archive", "bin", "engine", "mods", "r6", "red4ext", "tools")
GAME_ROOT_DIRS = CP2077_ROOT_DIRS

# File extensions that signal "place under archive/pc/mod".
ARCHIVE_INSTALL_EXTS = (".archive", ".dep", ".toc")

# Authors whose mods get their own top-level folder instead of being nested
# under the category.  Folder name = author name exactly as detected.
TOPLEVEL_AUTHORS = ("ScorpionTank",)

# Core CP2077 frameworks keyed by their Nexus mod id. Used by the framework
# grouping: mods that list one of these in their Nexus Requirements get
# grouped together in a top-level folder named after the framework, together
# with the framework mod itself.
#
# NOTE: only the NICHE frameworks form group folders. The universal deps that
# almost every CP2077 mod requires (see MAJOR_FRAMEWORKS below) would only
# create huge meaningless folders, so they are always ignored for grouping.
KNOWN_FRAMEWORKS = {
    "107": "CET",
    "2380": "RED4ext",
    "4197": "TweakXL",
    "4198": "ArchiveXL",
    "3518": "Native Settings UI",
    "790": "AMM",
    "4262": "Equipment-EX",
    "2987": "Virtual Atelier",
    "2750": "Input Loader",
    "5280": "Codeware",
}

# Universal/always-present dependency mods - required by a large share of the
# modding scene. Grouping by these would dump most downloads into one folder,
# so they are NEVER used to form framework groups.
MAJOR_FRAMEWORKS = {"107", "2380", "4197", "4198"}

# Keywords that flag likely high-res / oversized texture packs (VRAM guard).
VRAM_HIRES_WORDS = (
    "4k", "ultra", "hires", "high.res", "8k", "texture pack", "16k",
    "2k", "hd reworked", "hdr", "overhaul gfx",
)

# ---------------------------------------------------------------------------
# Categorization rules
# ---------------------------------------------------------------------------
# Ordered list of (folder_name, [regex keyword list]). First rule whose
# keywords appear in the (lowercased) filename wins. Ordering matters:
# specific mod features must come before broad "CCXL - <name>" hair rules.
RULES = [
    ("01 Eyes & Lashes", [
        r"\beyes?\b", r"eyes", r"cybereye", r"sclera", r"\bir[ei]s", r"pupil",
        r"\beyelashes?\b", r"eye ?lash", r"\blash", r"eyebrow", r"brows?\b",
        r"mascara", r"optics", r"gith eyes", r"heterochromia",
        r"eyeshadows?", r"eye ?make ?up", r"makeup", r"eye make",
        r"black line", r"white line", r"blackline", r"whiteline",
        r"natural - b", r"glow - b",
    ]),
    ("11 Sensitive Content (18+)", [
        r"nud", r"\bsex\b", r"sex anim", r"stripper", r"romanc",
        r"\bnsfw\b", r"\bescort", r"pleasures", r"joyride", r"enhanced body",
    ]),
    ("04 Tattoos & Cyberware", [
        r"tattoo", r"\bcyberware\b", r"implant", r"chrome", r"piercing",
        r"head cyberware", r"halo", r"cyber ?arm", r"cyberpod",
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
        r"bodysuit", r"leotard", r"lingerie", r"gymwear", r"catsuit",
        r"jumpsuit", r"dress\b", r"gown\b", r"bikini", r"bra\b",
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
        r"\bpak\b", r"length pak",
        r"hair pack", r"hairpack", r"hairstyles 2", r"hair collection",
        r"hair ?up", r"hairup", r"bottom ?bun", r"low ?pony",
        r"dusty_", r"19928", r"20175", r"npc.*hair", r"ccxl - [a-z]",
    ]),
    ("06 Weapons & Misc Items", [
        r"\bweapon", r"tron ?disk", r"yokai", r"netrunner", r"accessor",
        r"virtual atelier", r"store", r"\bshop\b", r"delta collection",
        r"\bshotgun", r"\bpump action", r"\bgun\b", r"\bguns\b",
        r"\brifles?\b", r"\bpistols?\b", r"\bhand ?guns?\b", r"\bsmg\b",
        r"\bsmg pack", r"\bsniper", r"\bblade\b", r"\bkatana",
        r"\bshiv\b", r"\bknives?\b", r"\bsword", r"\brevolver",
        r"\bglock", r"\bberetta", r"\bdesert eagle", r"\bvector",
        r"\bcaliber\b", r"grenade", r"\bbarrel\b", r"suppressor",
        r"\bmuzzle", r"\bcartridges?\b", r"\bturrets?\b", r"\bmissile",
        r"\btank (weapon|gun)", r"\bartillery", r"\bfirearm",
        r"\blauncher", r"\bcannon\b", r"\bmg-", r"\bmg \b", r"\bsaw\b",
        r"\bemkidnapper", r"\bgrenade ?launcher", r"\brake\b",
        r"\b10mm\b", r"\b40mm\b", r"\b5\.56\b", r"\b50 ?cal", r"\b9mm\b",
        r"\bdmr\b", r"\bsemis", r"\bsemi ?auto",
    ]),
    ("09 Vehicles & Transport", [
        r"\bvehicle", r"\bvehicles?", r"\bcar(s|s mod)?\b", r"\bmoto\b",
        r"\bmotorbike", r"\bmotorcycle", r"\bbike\b",
        r"\bquadra\b", r"\bcaliburn\b", r"\bnazare\b", r"\barch\b",
        r"\bmizutani\b", r"\btyger claw\b", r"hoverbike", r"vehical",
        r"car mod", r"delemain", r"\btaxi\b", r"\btruck\b", r"combat veh",
        r"\bkart\b",
    ]),
    ("10 World Building (Locations & Props)", [
        r"\blocation(s)?\b", r"\bprop(s)?\b", r"\binterior(s)?\b",
        r"\bapartment(s)?\b", r"\bmegabuilding", r"\bbuilding(s)?\b",
        r"\bskyline\b", r"\bscenery\b", r"\bbillboard(s)?\b",
        r"\bsignage\b", r"\bgraffiti\b", r"\bstatue(s)?\b",
        r"\bsculpture(s)?\b", r"\bfurniture\b", r"\bclutter\b",
        r"\bworld ?build", r"\bsightseeing\b", r"hidden gems",
        r"\blandmark(s)?\b", r"\bmonument(s)?\b", r"\bbedroom\b",
        r"\bloft\b", r"\bpenthouse\b", r"\bstorefront(s)?\b",
        r"\benvironment", r"\bramps?\b", r"construction",
    ]),
    ("12 Audio & Sound", [
        r"\baudio\b", r"\bsound\b", r"\bsfx\b", r"sound ?fx",
        r"\bmusic\b", r"radio", r"\bvoice", r"\bnarrator", r"\bambient\b",
        r"soundtrack", r"\bsongs?\b", r"\bdj\b", r"\blofi\b", r"\bbgm\b",
        r"sound ?replac", r"radio ?station", r"\bnoise\b",
    ]),
    ("13 Animations & Photo Mode", [
        r"\bposes?\b", r"pose ?pack", r"photomode", r"photo ?mode",
        r"photo-mode", r"photo ?pack", r"\banimations?\b", r"\banim\b",
        r"\bgestures?\b", r"locomotion", r"third ?person", r"\btpp\b",
        r"\bcamera\b", r"idle ?anim", r"walking animation",
        r"combat anim", r"character ?pose", r"framewalk", r"gait\b",
    ]),
    ("14 Quests & Story", [
        r"\bquests?\b", r"\bmissions?\b", r"\bdialogue\b", r"\bdialog\b",
        r"\bbraindance\b", r"\bconversation", r"\bheist\b", r"\bgig\b",
        r"\bstory\b", r"\bdate\b", r"add.?on quest", r"side ?job",
        r"\bpacifica\b", r"\bjournal\b",
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
    ("04 Tattoos & Cyberware", [
        r"jackie", r"warrior nun",
    ]),
]

# Nexus category id -> content-type folder (light mapping from the official
# Nexus category tree, used to sanity-check a cached category guess).
NEXUS_CAT_MAP = {
    "body": "03 Face & Body",
    "clothing": "05 Clothing & Armor",
    "armor": "05 Clothing & Armor",
    "player-cyberware": "04 Tattoos & Cyberware",
    "accessories": "06 Weapons & Misc Items",
    "weapons": "06 Weapons & Misc Items",
    "vehicles": "09 Vehicles & Transport",
    "world-model": "10 World Building (Locations & Props)",
    "locations": "10 World Building (Locations & Props)",
    "environments": "10 World Building (Locations & Props)",
    "clutter": "10 World Building (Locations & Props)",
    "props": "10 World Building (Locations & Props)",
    "interior-design": "10 World Building (Locations & Props)",
    "audio": "12 Audio & Sound",
    "sounds": "12 Audio & Sound",
    "music": "12 Audio & Sound",
    "voice": "12 Audio & Sound",
    "animations": "13 Animations & Photo Mode",
    "anim": "13 Animations & Photo Mode",
    "poses": "13 Animations & Photo Mode",
    "photo-mode": "13 Animations & Photo Mode",
    "photography": "13 Animations & Photo Mode",
    "camera": "13 Animations & Photo Mode",
    "quests": "14 Quests & Story",
    "dialogue": "14 Quests & Story",
    "dialogues": "14 Quests & Story",
    "missions": "14 Quests & Story",
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
    ("bodysuit", "05 Clothing & Armor"), ("leotard", "05 Clothing & Armor"),
    ("lingerie", "05 Clothing & Armor"), ("gymwear", "05 Clothing & Armor"),
    ("weapon", "06 Weapons & Misc Items"), ("pistol", "06 Weapons & Misc Items"),
    ("accessor", "06 Weapons & Misc Items"),
    ("vehicle", "09 Vehicles & Transport"), ("vehicles", "09 Vehicles & Transport"),
    ("car", "09 Vehicles & Transport"), ("bike", "09 Vehicles & Transport"),
    ("motorcycle", "09 Vehicles & Transport"), ("quadra", "09 Vehicles & Transport"),
    ("kart", "09 Vehicles & Transport"),
    ("location", "10 World Building (Locations & Props)"),
    ("locations", "10 World Building (Locations & Props)"),
    ("prop", "10 World Building (Locations & Props)"),
    ("props", "10 World Building (Locations & Props)"),
    ("interior", "10 World Building (Locations & Props)"),
    ("apartment", "10 World Building (Locations & Props)"),
    ("palette", "07 Colors, Profiles & Resources"),
    ("colour", "07 Colors, Profiles & Resources"),
    ("color", "07 Colors, Profiles & Resources"),
    ("complexion", "03 Face & Body"), ("skins", "03 Face & Body"),
    ("body", "03 Face & Body"), ("hair", "02 Hair"), ("eyes", "01 Eyes & Lashes"),
    ("audio", "12 Audio & Sound"), ("sound", "12 Audio & Sound"),
    ("sfx", "12 Audio & Sound"), ("music", "12 Audio & Sound"),
    ("radio", "12 Audio & Sound"), ("voice", "12 Audio & Sound"),
    ("ambient", "12 Audio & Sound"),
    ("pose", "13 Animations & Photo Mode"),
    ("photo mode", "13 Animations & Photo Mode"),
    ("photomode", "13 Animations & Photo Mode"),
    ("animation", "13 Animations & Photo Mode"), ("anim", "13 Animations & Photo Mode"),
    ("gesture", "13 Animations & Photo Mode"), ("camera", "13 Animations & Photo Mode"),
    ("third person", "13 Animations & Photo Mode"),
    ("locomotion", "13 Animations & Photo Mode"),
    ("quest", "14 Quests & Story"), ("quests", "14 Quests & Story"),
    ("dialogue", "14 Quests & Story"), ("dialog", "14 Quests & Story"),
    ("mission", "14 Quests & Story"), ("braindance", "14 Quests & Story"),
    ("gig", "14 Quests & Story"), ("story", "14 Quests & Story"),
]

# The folder names GigaSort itself creates (the "NN Name" style folders).
KNOWN_FOLDERS = frozenset({
    "01 Eyes & Lashes",
    "02 Hair",
    "03 Face & Body",
    "04 Tattoos & Cyberware",
    "05 Clothing & Armor",
    "06 Weapons & Misc Items",
    "07 Colors, Profiles & Resources",
    "08 Cores, Fixes & Utilities",
    "09 Vehicles & Transport",
    "10 World Building (Locations & Props)",
    "11 Sensitive Content (18+)",
    "12 Audio & Sound",
    "13 Animations & Photo Mode",
    "14 Quests & Story",
})

# User-editable {mod_id: note} list of WTNC extra-compatible ids. Auto-seeded
# on first run.
WTNC_EXTRA_COMPAT_SEED = {
    "10426": "WTNC Config - the WTNC team's own configuration mod (part of "
             "the collection; not listed in Wabbajack/Modlist.md)",
}


def default_workspace():
    """Resolve the default workspace once (kept a function so tests can
    override HOME cleanly)."""
    return DEFAULT_WORKSPACE