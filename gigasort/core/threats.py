"""Threat tiers — user-visible safety flags attached to files.

Purely advisory: never gates a move by itself, but shows in the GUI Status
tab as Trusted / On-hold / Watched."""
from gigasort.constants import (
    TRUSTED, ON_HOLD, WATCHED,
    SUSPICIOUS_KEYWORDS,
)
from gigasort.core.tags import file_tags


def classify(filename, tags=None, suspicious_words=SUSPICIOUS_KEYWORDS):
    """Return the threat tier for a file given its tags."""
    tags = tags or []
    low = filename.lower()
    if any(k in low for k in suspicious_words):
        return WATCHED
    if any(t in ("risky", "broken") for t in tags):
        return WATCHED
    if any(t in ("favorite",) for t in tags):
        return TRUSTED
    if any(k in low for k in ("beta", "old version", "unstable")):
        return ON_HOLD
    return TRUSTED


def threat_for(folder, filename):
    return classify(filename, file_tags(folder, filename))