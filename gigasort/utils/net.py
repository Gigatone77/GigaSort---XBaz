"""Network primitives and Nexus lookups.

The ONLY network access in GigaSort goes through `fetch()`. It is strictly
read-only (plain HTTP GET, never POSTs, never writes data to disk). All Nexus
URLs use the configurable game slug from constants.
"""

import re
import urllib.error
import urllib.parse
import urllib.request

try:
    import html as _html_mod
    _NET_OK = True
except Exception:  # pragma: no cover
    _NET_OK = False

from gigasort.constants import (
    NEXUS_BASE, NEXUS_CAT_MAP, NEXUS_CATEGORY_NAMES, NEXUS_SEARCH_TERMS,
    TITLE_MATCHERS,
)

USER_AGENT = "Mozilla/5.0 GigaSort/2.0"

ALLOW_NET = True  # module-level; flipped by confirm_network()


def nexus_page(mod_id):
    return "%s%s" % (NEXUS_BASE, mod_id)


def fetch(url, timeout=15):
    """Fetch a URL, returning decoded HTML (or None on failure). Read-only."""
    if not _NET_OK or not ALLOW_NET:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def check_connectivity(top_only=False):
    """True if the network is reachable. _NET_OK is import-ability; this does
    a real short-timeout GET."""
    if not _NET_OK:
        return False
    try:
        req = urllib.request.Request(
            "https://www.nexusmods.com/",
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.status < 500
    except Exception:
        return False


def notify_net_status():
    """Print a one-line banner showing current internet status; return it."""
    online = check_connectivity()
    if online:
        print("[net] online - live Nexus lookups available. "
              "Info is still cross-checked against your verified log/cache.")
    else:
        print("[net] OFFLINE - no live internet. Using ONLY your verified "
              "cache/log (local); online-only lookups are skipped.")
    return online


def confirm_network(feature, input_fn=input):
    """Prompt before an internet-dependent feature; set offline/online.

    Never blocks: on decline or offline, ALLOW_NET is set False and only the
    verified local data is used. Returns True if live lookups permitted.
    """
    global ALLOW_NET
    online = notify_net_status()
    if not online:
        ALLOW_NET = False
        print("  %s will use only your verified cache/log (offline)." % feature)
        return False
    print("  %s uses the internet (read-only). Prefer verified data?" % feature)
    try:
        ans = input_fn("  [l] live - allow read-only internet lookups | "
                       "[c] cache - offline only (verified log) [c]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "c"
    if ans in ("l", "live", "y", "yes"):
        ALLOW_NET = True
        print("  Live lookups enabled. Verified cache is still used first.")
        return True
    ALLOW_NET = False
    print("  Offline mode: only verified cache/log used (no live lookups).")
    return False


def _is_mod_page_title(title):
    """A real Nexus mod page <title> reads '<Mod Name> at Cyberpunk 2077
    Nexus - Mods and community'. The game home / landing / 404 / redirect
    pages read 'Cyberpunk 2077 Nexus - Mods and community' (no ' at ')."""
    low = (title or "").lower()
    return " at cyberpunk 2077 nexus" in low


def breadcrumb_category(html):
    """Extract the AUTHORITATIVE Nexus category display name from a mod
    page's breadcrumb (the '?categoryName=' value of the final crumb link).

    Returns the human-readable category name (e.g. 'Weapons', 'Armour and
    Clothing', 'Locations'), or None when the page has no usable breadcrumb.
    This is the category the mod AUTHOR set on their page -- much more
    reliable than guessing from body keywords.
    """
    if not html:
        return None
    m = re.search(r'[?&]categoryName=([^"&]+)', html)
    if not m:
        return None
    raw = m.group(1)
    name = urllib.parse.unquote_plus(raw).strip()
    if not name or name.lower() == "mods":
        return None
    return name


def lookup_nexus_category(mod_id, timeout=15):
    """Fetch a Nexus mod page, return (title, category_folder) or (None, None).

    The category always comes from the mod page's OWN breadcrumb
    ('categoryName=<author-set category>') when present, then falls back to
    the title/body keyword matchers. Whatever the source, the value is
    validated to be one of GigaSort's real destination folders -- a slug, a
    made-up name, or a landing/404/redirect page can NEVER contribute a
    category. Only real mod pages are trusted: unless the <title> proves it
    is a mod page ('<Name> at Cyberpunk 2077 Nexus...'), returns nothing.
    """
    url = "%s%s" % (NEXUS_BASE, mod_id)
    html = fetch(url, timeout=timeout)
    if not html:
        return None, None

    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    title = ""
    if m:
        title = _html_mod.unescape(m.group(1)).strip()
        title = re.sub(r"\s*\|\s*Nexus Mods.*$", "", title).strip()

    if not _is_mod_page_title(title):
        return None, None

    cat_name = breadcrumb_category(html)
    if cat_name in NEXUS_CATEGORY_NAMES:
        return title, NEXUS_CATEGORY_NAMES[cat_name]

    for word, folder in TITLE_MATCHERS:
        if word in title.lower():
            return title, folder

    low = html.lower()
    for term in NEXUS_SEARCH_TERMS:
        if term in low:
            folder = next((f for w, f in TITLE_MATCHERS if w == term), None)
            if folder:
                return title, folder
    return title, None


def fetch_nexus_title(mod_id, timeout=15):
    """Fetch a Nexus page and return the <title> string (or None).

    Unlike verified_nexus_title(), this does NOT check that the page is a
    CP2077 mod — it returns any valid Nexus page title. Useful for comparing
    mod names within the same author where the game context is already known.
    Read-only; never downloads.
    """
    if not mod_id:
        return None
    html = fetch("%s%s" % (NEXUS_BASE, mod_id), timeout=timeout)
    if not html:
        return None
    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if not m:
        return None
    title = _html_mod.unescape(m.group(1)).strip()
    title = re.sub(r"\s*\|\s*Nexus Mods.*$", "", title).strip()
    return title or None


def verified_nexus_title(mod_id, timeout=15):
    """Web-verify that `mod_id` is a REAL Cyberpunk 2077 mod on Nexus.

    Fetches the page under the cyberpunk2077 slug and returns the mod title
    only when it genuinely resolves to a CP2077 mod page (the <title> must be
    a mod page '<Name> at Cyberpunk 2077 Nexus ...' — the game home/landing
    page title 'Cyberpunk 2077 Nexus - Mods and community' is REJECTED, since
    a redirect/404 also lands there). Invalid/other-game/error pages return
    None, so callers can treat a non-None result as authoritative web
    verification. Read-only; never downloads.
    """
    if not mod_id:
        return None
    html = fetch("%s%s" % (NEXUS_BASE, mod_id), timeout=timeout)
    if not html:
        return None
    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if not m:
        return None
    title = _html_mod.unescape(m.group(1)).strip()
    low_title = title.lower()
    if not _is_mod_page_title(title):
        return None
    if "cyberpunk" not in low_title or "nexus" not in low_title:
        return None
    return title



def parse_required_deps(html):
    """Extract Nexus mod IDs from a page's Requirements section.

    Returns ([(game_slug, mod_id)], found) — a list and whether the section
    was found at all.
    """
    if not html:
        return [], False
    idx = html.lower().find("requirement")
    if idx == -1:
        return [], False
    window = html[idx: idx + 60000]
    seen = set()
    out = []
    for m in re.finditer(r"nexusmods\.com/([a-z0-9-]+)/mods/(\d+)", window):
        key = (m.group(1), m.group(2))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out, True
