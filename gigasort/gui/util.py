"""Shared GTK helpers for the GigaSort GUI."""

from gi.repository import GLib, Adw


def esc(text):
    """Escape a string for safe use as GTK markup (ActionRow title/subtitle)."""
    if text is None:
        return ""
    return GLib.markup_escape_text(str(text))


def show_error(widget, title, message):
    """Show a readable, scroll-safe error dialog.

    The status bar is a single ellipsized line, so long failure reasons get
    cut off there. This presents the full text in an alert dialog where it
    wraps and can be selected/copied.
    """
    dialog = Adw.AlertDialog.new(title, str(message))
    dialog.set_body_use_markup(False)
    dialog.add_response("ok", "OK")
    dialog.set_default_response("ok")
    dialog.present(widget)
