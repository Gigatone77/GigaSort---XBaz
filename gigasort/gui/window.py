"""GigaSort main window — sidebar navigation with scan/undo/status pages."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from gigasort import APP_NAME, __version__
from gigasort.constants import default_workspace
from gigasort.gui.pages.scan import ScanPage
from gigasort.gui.pages.undo import UndoPage
from gigasort.gui.pages.status import StatusPage
from gigasort.gui.pages.gigaslim import GigaSlimPage
from gigasort.gui.pages.cyberflash import CyberFlashSyncPage
from gigasort.gui.pages.xbaz import XBazPage
from gigasort.gui.pages.gamestructure import GameStructurePage

WINDOW_WIDTH = 960
WINDOW_HEIGHT = 640


class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "GigaSortMainWindow"

    def __init__(self, workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("%s %s" % (APP_NAME, __version__))
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.workspace = workspace or default_workspace()

        toolbar = Adw.ToolbarView()
        self.set_content(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        split = Adw.NavigationSplitView()
        split.set_min_sidebar_width(180)
        split.set_max_sidebar_width(220)

        sidebar_page = Adw.NavigationPage()
        sidebar_page.set_title("Navigation")

        sidebar_list = Gtk.ListBox()
        sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sidebar_list.add_css_class("navigation-sidebar")
        sidebar_list.add_css_class("compact-sidebar")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(200)

        self.scan_page = ScanPage(workspace=self.workspace)
        self.undo_page = UndoPage(workspace=self.workspace, scan_page=self.scan_page)
        self.status_page = StatusPage(workspace=self.workspace)
        self.scan_page.status_callback = self._on_sort_applied

        pages = [
            ("scan", "Scan and Sort", "view-list-symbolic", self.scan_page),
            ("undo", "Undo", "edit-undo-symbolic", self.undo_page),
            ("status", "Workspace", "folder-symbolic", self.status_page),
        ]

        def add_row(page_id, title, icon_name, page):
            row = Adw.ActionRow(title=title, icon_name=icon_name)
            row.set_activatable(True)
            row._page_id = page_id
            sidebar_list.append(row)
            self.stack.add_named(page, page_id)

        for page_id, title, icon_name, page in pages:
            add_row(page_id, title, icon_name, page)

        # Companion tools section — each is launched from gigasort but runs
        # its own GUI/options inside this window.
        sep = Gtk.Label(label="Companion Tools")
        sep.set_xalign(0)
        sep.add_css_class("heading")
        sep.add_css_class("dim-label")
        sep.set_margin_top(12)
        sep.set_margin_start(12)
        sep.set_margin_bottom(4)
        sidebar_list.append(sep)

        self.gigaslim_page = GigaSlimPage(workspace=self.workspace)
        self.cyberflash_page = CyberFlashSyncPage(workspace=self.workspace)
        self.xbaz_page = XBazPage(workspace=self.workspace)
        self.gamestructure_page = GameStructurePage(workspace=self.workspace)
        add_row("gigaslim", "GigaSlim", "edit-clear-symbolic",
                self.gigaslim_page)
        add_row("cyberflash", "CyberFlashSync", "document-save-symbolic",
                self.cyberflash_page)
        add_row("xbaz", "XBaz", "input-gaming-symbolic", self.xbaz_page)
        add_row("gamestructure", "Game Structure", "folder-symbolic",
                self.gamestructure_page)

        def on_row_activated(listbox, row):
            if hasattr(row, "_page_id"):
                self.stack.set_visible_child_name(row._page_id)

        sidebar_list.connect("row-activated", on_row_activated)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_child(sidebar_list)
        sidebar_scroll.set_vexpand(True)
        sidebar_page.set_child(sidebar_scroll)
        split.set_sidebar(sidebar_page)

        content_page = Adw.NavigationPage()
        content_page.set_title(APP_NAME)
        content_page.set_child(self.stack)
        split.set_content(content_page)

        toolbar.set_content(split)
        self.stack.set_visible_child_name("scan")
        sidebar_list.select_row(sidebar_list.get_row_at_index(0))

    def _on_sort_applied(self):
        self.undo_page.refresh()
        self.status_page.refresh()
