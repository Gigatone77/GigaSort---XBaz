"""GigaSort GTK app — launches the desktop window."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gdk

from gigasort import APP_NAME
from gigasort.gui.window import MainWindow


class GigaSortApp(Adw.Application):
    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.workspace = workspace
        self.connect("activate", self._on_activate)
        self.connect("startup", self._on_startup)

    def _on_startup(self, app):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _on_activate(self, app):
        win = self.props.active_window
        if win is None:
            win = MainWindow(application=app, workspace=self.workspace)
        win.present()


def run_app(workspace=None):
    app = GigaSortApp(application_id="com.gigasort.app",
                      workspace=workspace)
    return app.run(None)
