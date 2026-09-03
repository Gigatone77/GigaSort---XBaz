"""Filename parsing and categorization (name-based rules + metadata)."""

import os
import re

from gigasort.constants import (
    RULES, NEXUS_ID_RE, AUTHOR_STOPWORDS,
)

DUP_SUFFIX = re.compile(r"^(.*?)(?: ?\((\d+)\))?(\.[A-Za-z0-9]+)$")


def clean_name(path):
    """Strip the ' (1)' / ' (2)' suffix the browser adds to repeated downloads."""
    stem, ext = os.path.splitext(path)
    m = re.match(r"^(.*?)(?: ?\((\d+)\))?$", stem)
    if m and m.group(2) is not None:
        return m.group(1) + ext
    return path


def categorize(filename):
    """Return the category folder name, or None if it matches nothing."""
    low = filename.lower()
    for folder, patterns in RULES:
        for pat in patterns:
            if re.search(pat, low):
                return folder
    return None


def extract_mod_id(filename):
    """Pull the Nexus mod id from a downloaded filename, or None."""
    m = NEXUS_ID_RE.search(filename)
    return m.group(1) if m else None


def extract_mod_author(filename):
    """Best-effort Nexus author for a downloaded filename, or None.

    Standard Nexus names are '<Author>-<Mod>-<version>...-<id>-...'. The
    author is the first hyphen-segment, after dropping an optional leading
    '[tag]' (collection) prefix and any '-<digits>' version suffix."""
    base = os.path.basename(filename)
    base = re.sub(r"^\s*\[[^\]]*\]\s*", "", base)
    if "-" not in base:
        return None
    head = base.split("-", 1)[0]
    head = re.sub(r"-\d+(\.\d+)*\s*$", "", head)
    head = head.replace("_", " ").strip()
    head = re.sub(r"\s+", " ", head).strip(" ._-")
    if not head or head.lower() in AUTHOR_STOPWORDS:
        return None
    return head


def name_tokens(name):
    """Strip Nexus IDs, versions, extensions, dup suffixes; return lowercase
    word tokens for fuzzy matching."""
    n = re.sub(r"-\d{4,6}-.*$", "", name)
    n = os.path.splitext(n)[0]
    n = re.sub(r"^\d+(\.\d+)*\s*$", "", n)
    n = clean_name(n)
    n = re.sub(r"[-_.]", " ", n)
    return set(w for w in n.lower().split() if w)
