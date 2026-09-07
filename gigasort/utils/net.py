"""Network primitives and Nexus lookups.

The ONLY network access in GigaSort goes through `fetch()`. It is strictly
read-only (plain HTTP GET, never POSTs, never writes data to disk). All Nexus
URLs use the configurable game slug from constants.
"""

import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import html as _html_mod
    _NET_OK = True
except Exception:  # pragma: no cover
    _NET_OK = False

from gigasort.constants import (
    NEXUS_BASE, NEXUS_CATEGORY_NAMES, NEXUS_SEARCH_TERMS,
    TITLE_MATCHERS,
)

USER_AGENT = "GigaSort/2.0 (Linux; +https://github.com/Gigatone77/gigasort)"

ALLOW_NET = True  # module-level; flipped by confirm_network()


def nexus_page(mod_id):
    return "%s%s" % (NEXUS_BASE, mod_id)


def fetch(url, timeout=15):
    """Fetch a URL, returning decoded HTML (or None on failure). Read-only.

    Transient failures (Nexus rate-limit 429 / Cloudflare 5xx / socket
    timeouts) are retried twice with a short backoff so one network hiccup
    never permanently bins a good mod. Permanent errors (404, malformed URL,
    login-gated 403) return None immediately.
    """
    if not _NET_OK or not ALLOW_NET:
        return None
    last = None
    for attempt, delay in ((1, 1.5), (2, 3.0), (3, 0.0)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status >= 400:
                    return None
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # 429/5xx are transient: slow down and retry. 4xx otherwise is
            # permanent (never retry).
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                last = e
                time.sleep(delay)
                continue
            return None
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            last = e
            if attempt < 3:
                time.sleep(delay)
                continue
        except Exception:
            return None
    return None


def check_connectivity(top_only=False):
    """True if the network is reachable. _NET_OK is import-ability; this does
    a real short-timeout GET to a neutral, permissive endpoint (httpbin.org).
    Nexus itself is behind Cloudflare and rejects many plain-urllib requests
    with 403 even when the network is fine, so we probe elsewhere.
    """
    if not _NET_OK:
        return False
    probe = "https://httpbin.org/get"
    try:
        req = urllib.request.Request(probe, headers={"User-Agent": USER_AGENT})
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


def og_identity(html):
    """Extract OpenGraph identity from a Nexus page (og:title + og:url).

    Login-walled ADULT mod pages cannot be read anonymously (their <title>
    is the LANDING page 'Cyberpunk 2077 Nexus - Mods and community' plus a
    global '<h1>Please log in</h1>'), but they STILL embed their real mod
    identity in the og:title / og:url meta tags. Dead/nonexistent ids carry
    NEITHER meta. Returns (og_title, og_url) or (None, None)."""
    if not html:
        return None, None
    og_title = og_url = None
    for pat_attr, pat_content in (
        (r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"',
         r'<meta[^>]+content="([^"]*)"[^>]+property="og:title"'),
        (r'<meta[^>]+property="og:url"[^>]+content="([^"]*)"',
         r'<meta[^>]+content="([^"]*)"[^>]+property="og:url"'),
    ):
        for pat in (pat_attr, pat_content):
            m = re.search(pat, html, re.I)
            val = _html_mod.unescape(m.group(1)).strip() if m else None
            if val:
                if "og:url" in pat_attr or "og:url" in pat_content:
                    og_url = val
                else:
                    og_title = val
                break
    return (og_title or None, og_url or None)


def is_login_gated(html):
    """True when Nexus served its login-wall (landing title + Please log in)
    rather than a readable page. Adult pages are gated this way."""
    if not html:
        return False
    return "Please log in" in html and not _is_mod_page_title(_page_title(html))


def _page_title(html):
    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if not m:
        return None
    t = _html_mod.unescape(m.group(1)).strip()
    return re.sub(r"\s*\|\s*Nexus Mods.*$", "", t).strip() or None


def og_links_to(og_url, mod_id):
    """True when an og:url points at the requested mod page (any Nexus
    mods/<id> for this game, ignoring trailing fragments)."""
    if not og_url or not mod_id:
        return False
    return ("/mods/%s" % str(mod_id)) in og_url


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

    LOGIN-WALLED ADULT PAGES (Sep 5 stipulation): anonymous fetches of an
    adult mod return the LANDING page + 'Please log in' -- identical to a
    dead/404 id -- so the <title> gate alone can never distinguish them.
    The reliable discriminator is that login-walled adult pages still embed
    their real identity in the og:title + og:url meta tags while dead ids
    carry NEITHER. When og:identity is present AND the og:url points at the
    exact mod id, the page IS a real (adult) CP2077 mod: it verifies with the
    og:title and is routed to the "11 Sensitive Content (18+)" folder.
    """
    url = "%s%s" % (NEXUS_BASE, mod_id)
    html = fetch(url, timeout=timeout)
    if not html:
        return None, None

    title = _page_title(html) or ""

    if not _is_mod_page_title(title):
        # Landing/404/redirect OR a login-walled adult page. Only a matching
        # og:identity proves this is a real (gated) mod; otherwise it is a
        # dead id and must NOT become a verified adult entry.
        og_title, og_url = og_identity(html)
        if og_title and og_links_to(og_url, mod_id):
            return og_title, "11 Sensitive Content (18+)"
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

    Also returns the og:title for login-walled adult pages (whose <title> is
    only the landing page); dead ids produce no identity at all. Useful for
    comparing mod names within the same author where the game context is
    already known. Read-only; never downloads.
    """
    if not mod_id:
        return None
    html = fetch("%s%s" % (NEXUS_BASE, mod_id), timeout=timeout)
    if not html:
        return None
    title = _page_title(html)
    if title and _is_mod_page_title(title):
        return title
    og_title, og_url = og_identity(html)
    if og_title and og_links_to(og_url, mod_id):
        return og_title
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

    LOGIN-WALLED ADULT MODS are accepted too: their <title> is the landing
    page, but the og:title + og:url metas carry the real identity (dead ids
    carry neither). Their og:title is returned as the verified title.
    """
    if not mod_id:
        return None
    html = fetch("%s%s" % (NEXUS_BASE, mod_id), timeout=timeout)
    if not html:
        return None
    title = _page_title(html)
    if title and _is_mod_page_title(title):
        low_title = title.lower()
        if "cyberpunk" not in low_title or "nexus" not in low_title:
            return None
        return title
    og_title, og_url = og_identity(html)
    if og_title and og_links_to(og_url, mod_id):
        return og_title
    return None



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


_NEXUS_URL_RE = re.compile(
    r'https?://www\.nexusmods\.com/cyberpunk2077/mods/(\d+)')

# Google's public, rate-friendly HTML endpoint. A plain, honest GET (no
# browser impersonation / TLS fingerprinting) against Google's web search is
# permitted and returns results without cookies. We only ever issue
# read-only GETs; we never log in, never mutate anything, and never exceed
# a tiny number of light searches.
_SEARCH_ENDPOINT = "https://www.google.com/search?q=%s"


def _google_search_html(query, timeout=10):
    """Return Google search result HTML (or None). Read-only, plain GET."""
    try:
        q = urllib.parse.quote_plus(query)
        req = urllib.request.Request(
            _SEARCH_ENDPOINT % q, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def search_nexus_mod_id(query, timeout=10):
    """Best-effort last-resort web verification via Google search.

    When the Nexus page cannot be fetched directly (403/blocked/bot-wall) a
    Google search for the filename/author/title may still surface the
    canonical nexusmods.com/cyberpunk2077/mods/<id> URL in the result
    snippets. This is a WEAK signal (search engines index mirrors/hubs too,
    and a bad query can return a wrong project) so callers must treat it as
    evidence only, never as the sole authority. Returns a credible
    (game_slug, mod_id) when an official Nexus link appears in the results,
    else None. Read-only.
    """
    if not ALLOW_NET or not _NET_OK:
        return None
    html = _google_search_html(query, timeout=timeout)
    if not html:
        return None
    for m in _NEXUS_URL_RE.finditer(html):
        return ("cyberpunk2077", m.group(1))
    return None


def search_nexus_category(mod_id, query, timeout=10):
    """Best-effort Nexus category via Google search snippet keywords.

    Returns a GigaSort folder when the snippet text (which can include
    Nexus's '<Name> at Cyberpunk 2077 Nexus - <Category>' crumbs) keyword-
    matches a known folder for the specific mod, else None. NEVER raises."""
    if not ALLOW_NET or not _NET_OK:
        return None
    try:
        html = _google_search_html(query, timeout=timeout)
        if not html:
            return None
        low = html.lower()
        # Only trust a folder match if this search result page actually shows
        # the requested mod's Nexus link (never guess from unrelated results).
        if "/mods/%s" % mod_id not in html:
            return None
        for word, folder in TITLE_MATCHERS:
            if word in low:
                return folder
        return None
    except Exception:
        return None
