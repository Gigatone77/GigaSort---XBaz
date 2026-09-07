"""Network primitives and no-CAPTCHA search lookups.

The online sources GigaSort uses are anonymous search engines that answer
plain read-only GETs WITHOUT human verification (no login, no CAPTCHA, no
browser fingerprinting): DuckDuckGo Lite is the primary channel (Google
AI Mode and the plain web view bot-wall anonymous requests with 429s/anomaly
pages, so they are only kept as a final fallback). Every "verify this Nexus
mod id" goes through the search result page - the Nexus site itself is never
fetched. GitHub is an INFO resource only (public read-only release API),
found through the same search, and is never a verification gate.
"""

import re
import socket
import urllib.error
import urllib.parse
import urllib.request

try:
    import html as _html_mod
    _NET_OK = True
except Exception:  # pragma: no cover
    _NET_OK = False

from gigasort.constants import (
    NEXUS_CATEGORY_NAMES, TITLE_MATCHERS,
)

USER_AGENT = "GigaSort/2.0 (Linux; +https://github.com/Gigatone77/gigasort)"

ALLOW_NET = True  # module-level; flipped by confirm_network()


def _probe_one(url, timeout):
    """GET `url`; return (ok, reason). ok=True means ANY HTTP response
    arrived (the network reached the host); reason is a short string for
    failures (and for a reachable-but-blocking HTTP status)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status < 400:
                return True, None
            return True, "HTTP %d from %s" % (resp.status, _host_of(url))
    except urllib.error.HTTPError as e:
        return True, "HTTP %d from %s" % (e.code, _host_of(url))
    except socket.gaierror:
        return False, "DNS resolution failed"
    except socket.timeout:
        return False, "connection timed out"
    except urllib.error.URLError as e:
        msg = str(getattr(e, "reason", "") or e) or "unreachable"
        return False, msg[:60]
    except OSError as e:
        return False, (str(e).strip() or "network error")[:60]
    except Exception:
        return False, "network error"


def _host_of(url):
    try:
        return urllib.parse.urlsplit(url).netloc
    except Exception:
        return url


def mod_question(mod_id):
    """The search question that doubles as a lookup AND a handshake."""
    return "what is the cyberpunk 2077 nexus mod %s?" % mod_id


def probe_connectivity(query=None, timeout=6):
    """Probe whether a search engine answers without human verification;
    return (online, reason).

    The handshake IS a real question (`query`) fired at the primary
    no-CAPTCHA engine - the same ask a lookup makes. Returns (True, None)
    when that engine answers with real results; on failure, a SHORT human
    reason. When the network works but the engine bot-walls the request
    (anomaly/CAPTCHA/429 page) we report online with that wall as the reason,
    so lookups then fail fast instead of hanging.
    """
    if not _NET_OK:
        return False, "network module unavailable"
    if _search_gave_up:
        return False, "search engines blocked this run (rate-limited)"
    q = urllib.parse.quote_plus(query) if query else "what+is+this"
    ok, reason = _probe_primary(_LITE_ENDPOINT % q, timeout)
    if ok and not reason:
        return True, None
    net_ok, net_reason = _probe_one("https://httpbin.org/get", timeout)
    if net_ok:
        return False, ("search engines block anonymous lookups (%s)"
                       % (reason or "human-verification wall"))
    return False, reason or net_reason or "no response"


def _probe_primary(url, timeout):
    """GET the primary search URL; return (ok, reason).

    ok=True means an HTTP response arrived AND the body looks like real
    results (has result links and is not an anomaly/CAPTCHA wall). reason
    is None when truly answering, else a short description of the wall.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return _probe_one(url, timeout)
    if _usable_results(body):
        return True, None
    return True, "blocked by bot-wall / CAPTCHA"


def check_connectivity(top_only=False):
    """True if the network is reachable (bool form of probe_connectivity())."""
    return probe_connectivity()[0]


def notify_net_status():
    """Print a single Online/Offline connectivity line; return `online`.

    Just 'offline - <why>' when there is a problem, so the reason is always
    stated without any extra prose.
    """
    online, reason = probe_connectivity()
    if online:
        print("[net] online" if not reason else "[net] online - %s" % reason)
    else:
        print("[net] offline - %s" % reason)
    return online


def confirm_network(feature, input_fn=input):
    """Prompt before an internet-dependent feature; set offline/online.

    Never blocks: on decline or offline, ALLOW_NET is set False and only the
    verified local data is used. Returns True if live lookups permitted.
    """
    global ALLOW_NET
    online, reason = probe_connectivity()
    if not online:
        ALLOW_NET = False
        print("[net] offline - %s: %s uses only the verified cache." % (reason, feature))
        return False
    if reason:
        print("[net] online - %s." % reason)
    print("[net] online: %s uses the internet (read-only)." % feature)
    try:
        ans = input_fn("  [l] live | [c] cache (verified only) [c]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "c"
    if ans in ("l", "live", "y", "yes"):
        ALLOW_NET = True
        print("  Live lookups enabled (verified cache still checked first).")
        return True
    ALLOW_NET = False
    print("  Offline mode: verified cache/log only.")
    return False


def _serp_has_mod(html, mod_id):
    """True when a search result page carries the official Nexus page for
    `mod_id`. Accepts the plain mods/<id>, Google-rewritten, and URL-encoded
    (%2F) link forms - DuckDuckGo wraps every result in a /l/?uddg=
    redirect, which URL-encodes the mods/<id> path. That exact-id official
    link is GigaSort's web-verification marker -- dead ids produce no such
    link.
    """
    if not html or not mod_id:
        return False
    low = html.lower()
    return (("/mods/%s" % mod_id) in low
            or ("mods%%2f%s" % mod_id) in low
            or ("mods%%252f%s" % mod_id) in low)


def _serp_title_for(html, mod_id):
    """The headline of the search result that links the mod page.

    Works for Brave (direct links, breadcrumb + title inside one anchor),
    DuckDuckGo Lite (plain anchor text, /l/?uddg= encoded URLs), and
    rendered Google (h2/h3 headline inside the anchor). The mod id must
    directly follow the /mods/ path separator (slashes or their %2F /
    %252F encodings). Returns a clean title string or None. Never raises.
    """
    if not html or not mod_id:
        return None
    m = re.search(
        r'<a[^>]+href="(?P<url>[^"]*mods(?:%%252f|%%2f|/)+%s[^"]*)"[^>]*>'
        r'(?P<body>.*?)</a>' % mod_id,
        html, re.I | re.S)
    if not m:
        return None
    body = m.group("body")
    h = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', body, re.I | re.S)
    if h:
        body = h.group(1)
    title = _html_mod.unescape(re.sub(r"<[^>]+>", " ", body))
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None
    # Brave repeats the breadcrumb inside the title text and the mod name
    # begins right after the mod id token ("… › mods › 31304 Name (…) at
    # Cyberpunk 2077 Nexus …"). Slice there only when a nexus breadcrumb
    # precedes the id; DDG/Google titles carry no id token and stay as-is.
    pos = title.rfind(mod_id)
    if pos != -1 and "nexusmods" in title[:pos].lower():
        title = title[pos + len(mod_id):].strip(" :,.-›|")
    return re.sub(r"\s+", " ", title).strip() or None


def _title_category_folder(title):
    """Folder from a search-result mod title's '<Name> at Cyberpunk 2077
    Nexus - <Category> - Mods and community' crumb, exact-matched against
    the real Nexus category names (and GigaSort folder names). None when
    absent."""
    title = re.sub(r"\s+", " ", (title or ""))
    low = title.lower()
    idx = low.find("at cyberpunk 2077 nexus")
    if idx == -1:
        return None
    rest = title[idx + len("at cyberpunk 2077 nexus"):].strip(" :,.-")
    parts = [p.strip().strip(" .-") for p in re.split(r"[-,]", rest)
             if p.strip()]
    for part in parts:
        pl = part.lower()
        if not pl or pl in ("mods and community", "nexus mods and community"):
            continue
        return _CATEGORY_FOLDER_BY_NAME.get(pl)
    return None


# Lowercased lookup: Nexus category name / GigaSort folder -> destination.
_CATEGORY_FOLDER_BY_NAME = {}
for _name, _folder in NEXUS_CATEGORY_NAMES.items():
    _CATEGORY_FOLDER_BY_NAME.setdefault(_name.lower(), _folder)
    _CATEGORY_FOLDER_BY_NAME.setdefault(_folder.lower(), _folder)


# Anonymous, no-human-verification search endpoints. Plain honest GETs: no
# login, no CAPTCHA, no browser impersonation/TLS fingerprinting. Brave
# Search answers scripted requests here with direct result links; DuckDuckGo
# Lite works but rate-limits bursts into an anomaly wall (DDG html and
# Google bot-wall/429 us, so they stay as final fallbacks). One question is
# sent to the first engine that returns real results; lookups never re-ask.
_SEARCH_ENDPOINTS = (
    "https://search.brave.com/search?q=%s",
    "https://lite.duckduckgo.com/lite/?q=%s",
    "https://html.duckduckgo.com/html/?q=%s",
    "https://www.google.com/search?q=%s&udm=50",
)
_LITE_ENDPOINT = _SEARCH_ENDPOINTS[0]


def _usable_results(html):
    """True when a fetched page actually carries search results rather than
    a bot-wall / pre-JS shell.

    Wall pages: DDG's 'anomaly' page (no result links), Google's 92KB
    pre-JS shell (1 lone support link, no results), bare challenges, and
    forward-only redirect shells. Real result pages (Brave/DDG/Google-
    rendered) carry MANY external links. A result page can legitimately
    contain the substring "captcha" (Brave ships its CAPTCHA dictionary
    inside its JS bundle), so a bare substring match is never treated as a
    wall - only a page with too few external links is.
    """
    if not html:
        return False
    low = html.lower()
    if low.count('href="http') + low.count(
            "href='http") + low.count("href=/l/") < 14:
        return False
    if "anomaly" in low and "uddg=" not in low:
        return False
    return True


# When EVERY engine wall-blocks in a row, further live lookups cannot succeed
# this run, so after a couple of consecutive all-engine failures the chain
# gives up and every following question returns None instantly (never burns
# timeouts). The refs cache + archive-structure gate cover the rest offline.
_SEARCH_STRIKES_MAX = 2
_search_strikes = 0
_search_gave_up = False


def _search_strike():
    """Record one all-engines failure; give up after the burst threshold."""
    global _search_strikes, _search_gave_up
    _search_strikes += 1
    if _search_strikes >= _SEARCH_STRIKES_MAX:
        _search_gave_up = True


def _search_strikes_reset():
    global _search_strikes
    _search_strikes = 0


def _search_html(query, timeout=5):
    """Return real search-result HTML from the first engine that answers
    (or None). Read-only plain GETs only.

    One question, one linear pass down the engine chain - never re-asked.
    After a few consecutive all-engine wall-blocks the whole run gives up on
    live lookups, so a rate-limited burst can never turn into a long hang:
    the verify path then relies on the offline refs cache + archive-structure
    gate instead (already the designed fallback).
    """
    global _search_gave_up
    if _search_gave_up:
        return None
    q = urllib.parse.quote_plus(query)
    for endpoint in _SEARCH_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint % q, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status >= 400:
                    continue
                html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue
        if _usable_results(html):
            _search_strikes_reset()
            return html
    _search_strike()
    return None


def _serp_keyword_folder(title):
    """Category folder from keyword-scanning a mod title only.

    Returns a GigaSort folder when the VERIFIED MOD'S OWN TITLE carries a
    known category keyword (engines snapshot Nexus '<Name> at Cyberpunk 2077
    Nexus - <Category>' crumbs in the title). Only the mod's own headline is
    scanned - never the surrounding page/sidebar text - so a category word in
    an unrelated result snippet (e.g. 'Sharingan eyes' near a weapon mod)
    can't leak in and misfile the mod. Called only AFTER a link to the mod
    itself was confirmed, using that same result's title. Never raises.
    """
    if not title:
        return None
    try:
        low = re.sub(r"\s+", " ", (title or "")).lower()
        for word, folder in TITLE_MATCHERS:
            if word in low:
                return folder
    except Exception:
        pass
    return None


def _mod_anchor_html(html, mod_id):
    """The raw inner HTML of the result anchor that links the mod page.

    Everything surrounding the anchor (page chrome, sidebar, other results)
    is excluded so info like a GitHub repo is only ever read from the mod's
    own result context. None when the link cannot be isolated.
    """
    if not html or not mod_id:
        return None
    m = re.search(
        r'<a[^>]+href="(?P<url>[^"]*mods(?:%%252f|%%2f|/)+%s[^"]*)"'
        r'[^>]*>(?P<body>.*?)</a>' % mod_id,
        html, re.I | re.S)
    return m.group("url") + " " + m.group("body") if m else None


def investigate_mod(mod_id, query=None, timeout=5):
    """One linear search question per mod: single fetch, single parse.

    Returns a dict with every piece of info that one read-only, no-CAPTCHA
    search question yields, or None when no engine answers:
      verified: the official nexusmods.com/cyberpunk2077/mods/<id> link is
                present in the results (GigaSort's web-verification marker).
      title:    the result headline of that Nexus page.
      folder:   category folder from the title crumb, else a single keyword
                pass over the same page (never a second query).
      github:   'owner/repo' if the results surfaced a GitHub repo for it
                (info-only resource - often carries newer/more current info;
                never a verification gate).
    The Nexus site itself is never contacted. One question, one fetch, one
    parse - no retries, no forked queries.
    """
    if not ALLOW_NET or not _NET_OK or not mod_id:
        return None
    q = query or mod_question(mod_id)
    html = _search_html(q, timeout=timeout)
    if not html:
        return None
    out = {"verified": False}
    if _serp_has_mod(html, mod_id):
        title = _serp_title_for(html, mod_id) or "Cyberpunk 2077 mod %s" % mod_id
        folder = (_title_category_folder(title)
                  or _serp_keyword_folder(title))
        out.update({"verified": True, "title": title, "folder": folder})
        # GitHub is an INFO resource only (often newer/more current than
        # Nexus, never a verification gate). It is only trusted when the
        # repo appears in the SAME result anchor as the official Nexus link,
        # so unrelated sidebar/snippet repos can never be attached to this
        # mod. Repo URLs inside DDG's /l/?uddg= redirects are URL-encoded,
        # so every redirect target is decoded before scanning.
        anchor = _mod_anchor_html(html, mod_id) or ""
        scan = anchor
        for m in re.finditer(r'uddg=([^&"\']+)', anchor):
            try:
                scan += " " + urllib.parse.unquote(m.group(1))
            except Exception:
                pass
        m = re.search(
            r'github\.com/(?P<owner>[\w.-]+)/(?P<repo>[A-Za-z0-9_.-]+)', scan)
        if m:
            out["github"] = "%s/%s" % (m.group("owner"), m.group("repo"))
    return out


def lookup_nexus_category(mod_id, query=None, timeout=5):
    """Google-only mod verification: return (title, category_folder).

    A mod id web-verifies when the single Google question for it carries
    its official nexusmods.com/cyberpunk2077/mods/<id> link. Returns
    (None, None) when there is no usable evidence. Read-only; the Nexus
    page itself is never fetched.
    """
    res = investigate_mod(mod_id, query=query, timeout=timeout)
    if not res or not res.get("verified"):
        return None, None
    return res.get("title"), res.get("folder")


def fetch_nexus_title(mod_id, query=None, timeout=5):
    """Google-only mod title for a Nexus id (never fetches Nexus itself).

    Returns the SERP headline of the official nexusmods.com/.../mods/<id>
    result, or None when the id does not web-verify. Read-only.
    """
    res = investigate_mod(mod_id, query=query, timeout=timeout)
    if not res or not res.get("verified"):
        return None
    return res.get("title")


def github_latest_release(owner_repo, timeout=10):
    """Newest release tag of a GitHub repo via the public read-only API
    (no auth, no writes). Returns the tag string or None."""
    if not ALLOW_NET or not _NET_OK or not owner_repo or "/" not in owner_repo:
        return None
    url = "https://api.github.com/repos/%s/releases/latest" % owner_repo
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                return None
            data = resp.read().decode("utf-8", "replace")
        m = re.search(r'"tag_name"\s*:\s*"([^"]+)"', data)
        return m.group(1) if m else None
    except Exception:
        return None
