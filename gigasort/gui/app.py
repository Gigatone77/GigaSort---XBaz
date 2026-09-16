"""GigaSort GTK app — launches the desktop window."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gdk  # noqa: E402


from gigasort.gui.window import MainWindow

# Shared EXALTED dark/amber palette (matches biblelearn/EXALTED/PenguKit).
_GIGASORT_CSS = b"""
@define-color accent #f5a623;
@define-color accent_bg_color #f5a623;
window { background-color: #0d1117; color: #e6edf3; }
.sidebar,
.navigation-sidebar { background-color: #161b22; color: #e6edf3; }
.sidebar row:selected,
.navigation-sidebar row:selected {
  background-color: alpha(@accent, 0.18); color: #ffd479;
}
.dim-label { color: #8b949e; }
"""


class GigaSortApp(Adw.Application):
    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.workspace = workspace
        self.connect("activate", self._on_activate)
        self.connect("startup", self._on_startup)

    def _on_startup(self, app):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_data(_GIGASORT_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_activate(self, app):
        win = self.props.active_window
        if win is None:
            win = MainWindow(application=app, workspace=self.workspace)
        win.present()


def run_app(workspace=None):
    app = GigaSortApp(application_id="com.gigasort.app",
                      workspace=workspace)
    return app.run(None)
