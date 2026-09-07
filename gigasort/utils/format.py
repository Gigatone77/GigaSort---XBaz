"""Formatting helper: human-readable sizes."""


def human_size(n):
    """Human-readable file size (bytes -> B/K/M/G/T)."""
    n = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fT" % n
