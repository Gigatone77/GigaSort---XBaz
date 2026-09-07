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
REFERENCE_FILENAME = "_GigaSort_references.json"
WEB_OVERRIDES_FILENAME = "_GigaSort_web_overrides.json"
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
GS_COLLECTION_CACHE = "_GigaSort_collection.json"  # recognized modlist cache

# Agent bridge.
BRIDGE_DIR = "_GigaSort_bridge"

# ---------------------------------------------------------------------------
# Nexus
# ---------------------------------------------------------------------------
# The Nexus game slug. Cyberpunk 2077 is the default/target.
NEXUS_GAME_SLUG = "cyberpunk2077"
NEXUS_BASE = "https://www.nexusmods.com/%s/mods/" % NEXUS_GAME_SLUG

# Filename token "-12xxxx-" (or "-1xxx-"/"-2xxxx-"), including LOW 3-digit
# ids ("-790-" = Appearance Menu Mod), is the Nexus mod id.
NEXUS_ID_RE = re.compile(r"-(\d{3,6})-", re.IGNORECASE)

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
        r"\beyelashes?\b", r"eye ?lash", r"\blash", r"eyebrow", r"brows?\b",
        r"mascara", r"optics", r"gith eyes", r"heterochromia",
        r"eyeshadows?", r"eye ?make ?up", r"makeup", r"eye make",
        r"black line", r"white line", r"blackline", r"whiteline",
        r"natural - b", r"glow - b",
    ]),
    # 18+ content: strong, unambiguous markers (outweigh the clothing words
    # below - a "Lingerie AND nude after shower" add-on is sensitive content,
    # not apparel). "Sensitive" because not every 18+-tagged mod is sexual in
    # nature - body-enhanced/romance packs land the same way.
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
        r"\bmotorbike", r"\bmotorcycle", r"\bmotorcycle\b", r"\bbike\b",
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
    # Official Nexus 'Audio' category: sound configs, music/radio reworks,
    # voice/ambience packs. Kept after weapons so "silencer sound" style
    # weapon mods still route to 06, not here.
    ("12 Audio & Sound", [
        r"\baudio\b", r"\bsound\b", r"\bsfx\b", r"sound ?fx",
        r"\bmusic\b", r"radio", r"\bvoice", r"\bnarrator", r"\bambient\b",
        r"soundtrack", r"\bsongs?\b", r"\bdj\b", r"\blofi\b", r"\bbgm\b",
        r"sound ?replac", r"radio ?station", r"\bnoise\b",
    ]),
    # Official Nexus 'Animations' category + Photo Mode tag: poses, AI /
    # locomotion, third-person, camera. Word-bounded anim so it never matches
    # inside unrelated words.
    ("13 Animations & Photo Mode", [
        r"\bposes?\b", r"pose ?pack", r"photomode", r"photo ?mode",
        r"photo-mode", r"photo ?pack", r"\banimations?\b", r"\banim\b",
        r"\bgestures?\b", r"locomotion", r"third ?person", r"\btpp\b",
        r"\bcamera\b", r"idle ?anim", r"walking animation",
        r"combat anim", r"character ?pose", r"framewalk", r"gait\b",
    ]),
    # Nexus tag 'Quests' (Braindance / gigs / missions / dialogues). 'romanc'
    # stays gated by the Adult rule above - these are story content.
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
    # Low-priority tribute markers: a character-name reference ("V jackie
    # tribute", "warrior nun") routes to 04 Tattoos & Cyberware ONLY when no
    # more specific item/category keyword has already matched earlier in the
    # list. Kept last so "Jackie Jacket Archive XL" -> Clothing, not Tattoos.
    ("04 Tattoos & Cyberware", [
        r"jackie", r"warrior nun",
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

# Authoritative Nexus category display names (the value behind the
# `?categoryName=` query the mod page breadcrumb links to) mapped to our
# destination folders. Preferred over the slug map above: the breadcrumb is
# the category the MOD AUTHOR set, not a keyword guess.
NEXUS_CATEGORY_NAMES = {
    # map both the URL-encoded token (as it appears in the breadcrumb href)
    # and its human-readable form to be defensive about how pages render.
    "Animations": "13 Animations & Photo Mode",
    "Appearance": "03 Face & Body",
    "Appearance+Menu+Mod+Preset": "03 Face & Body",
    "Appearance Menu Mod Preset": "03 Face & Body",
    "Appearance+Change+Unlocker+Preset": "03 Face & Body",
    "Appearance Change Unlocker Preset": "03 Face & Body",
    "Armour+and+Clothing": "05 Clothing & Armor",
    "Armor+and+Clothing": "05 Clothing & Armor",
    "Armour and Clothing": "05 Clothing & Armor",
    "Armor and Clothing": "05 Clothing & Armor",
    "Atelier+Shop": "06 Weapons & Misc Items",
    "Atelier Shop": "06 Weapons & Misc Items",
    "Audio": "12 Audio & Sound",
    "Audio+Replacer": "12 Audio & Sound",
    "Audio Replacer": "12 Audio & Sound",
    "AI+Voices": "12 Audio & Sound",
    "AI Voices": "12 Audio & Sound",
    "Characters": "03 Face & Body",
    "Crafting": "08 Cores, Fixes & Utilities",
    "Gameplay": "08 Cores, Fixes & Utilities",
    "Locations": "10 World Building (Locations & Props)",
    "Add-On+Apartment": "10 World Building (Locations & Props)",
    "Add-On Apartment": "10 World Building (Locations & Props)",
    "Apartment": "10 World Building (Locations & Props)",
    "Miscellaneous": "06 Weapons & Misc Items",
    "Modders+Resources": "07 Colors, Profiles & Resources",
    "Modders Resources": "07 Colors, Profiles & Resources",
    "Props+and+Decorations": "10 World Building (Locations & Props)",
    "Props and Decorations": "10 World Building (Locations & Props)",
    "Scripts": "08 Cores, Fixes & Utilities",
    "User+Interface": "08 Cores, Fixes & Utilities",
    "User Interface": "08 Cores, Fixes & Utilities",
    "Utilities": "08 Cores, Fixes & Utilities",
    "Vehicles": "09 Vehicles & Transport",
    "Visuals+and+Graphics": "07 Colors, Profiles & Resources",
    "Visuals and Graphics": "07 Colors, Profiles & Resources",
    "Weapons": "06 Weapons & Misc Items",
    "World+Model": "10 World Building (Locations & Props)",
    "World Model": "10 World Building (Locations & Props)",
}

NEXUS_SEARCH_TERMS = [
    "eyes", "lashes", "eyelashes", "eyebrow", "brows", "hair", "hairstyle",
    "bob", "ponytail", "bun", "wig", "tattoo", "cyberware", "implant",
    "piercing", "chrome", "armor", "armour", "vest", "helmet", "boots",
    "gloves", "jacket", "pants", "suit", "goggles", "mask", "skins",
    "complexion", "body", "weapon", "accessory", "color", "colour", "palette",
    "texture", "utility", "framework", "pistol", "holster",
    "location", "prop", "interior", "apartment", "building", "world building",
    "bodysuit", "leotard", "lingerie", "gymwear", "kart",
    "audio", "sound", "sfx", "music", "radio", "voice", "ambient",
    "pose", "photo mode", "photomode", "animation", "anim", "gesture",
    "camera", "third person", "locomotion",
    "quest", "dialogue", "dialog", "mission", "braindance", "gig", "story",
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

# ---------------------------------------------------------------------------
# Verification statuses / threat tiers
# ---------------------------------------------------------------------------
# The folder names GigaSort itself creates (the "NN Name" style folders).
# Used to validate cached/live 'nexus_cat' values: the value must be one of
# these REAL folders, never a slug or a made-up guess.
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

# Authors whose mods get their own top-level folder instead of being nested
# under the category.  Folder name = author name exactly as detected.
TOPLEVEL_AUTHORS = (
    "ScorpionTank",
)

# Core CP2077 frameworks keyed by their Nexus mod id. Used by the framework
# grouping: mods that list one of these in their Nexus Requirements get
# grouped together in a top-level folder named after the framework, together
# with the framework mod itself. Ids that never appear simply produce no
# group. Shared dependencies not in this map are still grouped dynamically
# ("Framework (Nexus mod <id>)", where <id> is the dependency's Nexus mod id)
# when two or more downloads require the same one.
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
# so they are NEVER used to form framework groups (only niche ids are).
# Adjust this set freely: add a framework here to stop grouping by it.
MAJOR_FRAMEWORKS = {"107", "2380", "4197", "4198"}

# Keywords that flag likely high-res / oversized texture packs (VRAM guard).
VRAM_HIRES_WORDS = (
    "4k", "ultra", "hires", "high.res", "8k", "texture pack", "16k",
    "2k", "hd reworked", "hdr", "overhaul gfx",
)

# ---------------------------------------------------------------------------
# CP2077 modding-convention keywords (offline recognition)
# ---------------------------------------------------------------------------
# Strong, low-false-positive markers that identify a real Cyberpunk 2077 mod
# download from its *filename* alone, with no need for a live Nexus lookup.
# These are the consistent naming conventions the CP2077 modding community
# (CCXL / Virtual Atelier / RED4ext / CET authors) uses. A filename carrying
# one of these AND a Nexus mod id is treated as a Cyberpunk 2077 mod even when
# the machine is offline and the archive interior can't be inspected.
#
# NOTE: keep these genuinely CP2077-specific. Avoid generic words a Witcher 3 /
# other-game mod could also use, since this list also feeds the offline safety
# gate (which otherwise requires live web verification). Multi-word phrases are
# matched as whole phrases (boundary-tolerant); single words are matched with
# word boundaries.
CP2077_STRONG_KEYWORDS = (
    # Hair / appearance framework (the dominant CP2077 custom-content scene).
    "ccxl",
    # CP2077 protagonist body references (female/male V).
    "femv", "mascv", "feme v", "male v", "female v",
    # REDengine 4 software / loaders (Cyberpunk-only).
    "red4ext", "redscript", "cyber engine tweaks", "cyber_engine_tweaks",
    # 'cet' = Cyber Engine Tweaks, the CP2077-only script loader; matched as a
    # whole word and gated to filenames that also carry a Nexus mod id.
    "cet",
    # Established CP2077 mod authors / store frameworks.
    "virtual atelier", "meluminary", "sedth",
    # CP2077 augmentation / body-kit vocabulary.
    "cyberware", "cyberdeck", "netrunner", "sandevistan",
    "monowire", "mantis blade", "gorilla arm", "kerensikov", "cyberpod",
    # In-game factions / structures specific to Night City.
    "night city", "barghest", "delamain",
    # Iconic CP2077 vehicles that appear in downloaded archive names.
    "caliburn", "quadra",
)


def default_workspace():
    """Resolve the default workspace once (kept a function so tests can
    override HOME cleanly)."""
    return DEFAULT_WORKSPACE
