"""Shared GTK helpers for the GigaSort GUI."""

from gi.repository import GLib


def esc(text):
    """Escape a string for safe use as GTK markup (ActionRow title/subtitle)."""
    if text is None:
        return ""
    return GLib.markup_escape_text(str(text))
