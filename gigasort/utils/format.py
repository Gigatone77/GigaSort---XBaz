"""Formatting helpers: sizes, truncation, wrapping, directory sizes."""

import os


def human_size(n):
    """Human-readable file size (bytes -> B/K/M/G/T)."""
    n = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fT" % n


def truncate(text, width):
    """Truncate text to `width` with a trailing ellipsis if it overflows."""
    if width <= 1:
        return text[:1]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def wrap(text, width):
    """Simple greedy word-wrap returning a list of lines."""
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def dir_size(path):
    """Apparent size of a directory tree in bytes (fast, no data read)."""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                total += file_size(os.path.join(root, f))
    except OSError:
        pass
    return total
