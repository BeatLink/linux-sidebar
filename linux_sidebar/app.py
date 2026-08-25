"""The application: one instance per session, driven from the command line by later launches."""

import sys

from gi.repository import Gdk, Gio, GLib, Gtk

from . import APP_ID
from .config import Config
from .ui.sidebar import Sidebar
from .util import data_path, log

OPTIONS = [
    ("toggle", "Show or hide the sidebar"),
    ("show", "Show the sidebar"),
    ("hide", "Hide the sidebar"),
    ("settings", "Open the settings window"),
    ("reload", "Reread the settings and everything the plugins are showing"),
    ("next-tab", "Move to the next tab"),
    ("previous-tab", "Move to the previous tab"),
    ("quit", "Save and exit"),
]


class Application(Gtk.Application):
    """The single running sidebar, which later launches talk to rather than duplicating."""

    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.config = None
        # Tells this process's own launch apart from a later one asking to be revealed.
        self._first_command_line = True
        for name, description in OPTIONS:
            self.add_main_option(name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                                 description, None)

    def do_startup(self):
        """Loads the settings, the stylesheet and the window."""
        Gtk.Application.do_startup(self)
        self.config = Config()
        self._load_style()
        self.window = Sidebar(self, self.config)
        log("docking through %s" % self.window.backend.label)
        if not self.config["start_hidden"]:
            self.window.reveal()

    def _load_style(self):
        """Loads the stylesheet, which sets the sidebar's shape and leaves its colours to the theme."""
        provider = Gtk.CssProvider()
        style = data_path("style.css")
        try:
            provider.load_from_path(style)
        except GLib.Error as error:
            log("could not load %s: %s" % (style, error.message))
            return
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, command_line):
        """Acts on the options a launch was given, in this process or in the running one."""
        options = command_line.get_options_dict().end().unpack()

        if "quit" in options:
            self.window.shutdown()
            self.quit()
            return 0
        if "settings" in options:
            self.window.open_settings()
        elif "toggle" in options:
            self.window.toggle()
        elif "show" in options:
            self.window.reveal()
        elif "hide" in options:
            self.window.flush()
            self.window.hide()
        elif "next-tab" in options:
            self.window.reveal()
            self.window.cycle_tab(1)
        elif "previous-tab" in options:
            self.window.reveal()
            self.window.cycle_tab(-1)
        elif "reload" in options:
            self.config.load()
            self.window.settings_changed(relayout=True)
        else:
            # A launch with no options reveals the sidebar, except for the very first one
            # when start_hidden asked for it to stay out of the way.
            if not (self._first_command_line and self.config["start_hidden"]):
                self.activate()
        self._first_command_line = False
        return 0

    def do_activate(self):
        """Reveals the running instance, which is what a second launch amounts to."""
        if self.window is not None and not self.window.get_visible():
            self.window.reveal()


def main():
    """Runs the sidebar."""
    app = Application()
    try:
        return app.run(sys.argv)
    finally:
        if app.window is not None:
            app.window.shutdown()
