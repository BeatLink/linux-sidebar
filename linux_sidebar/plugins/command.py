"""Shows the output of a shell command, rerun on a timer.

One of these is a system monitor, a weather line or a calendar, depending only on the
command it is given, which is why it earns its place beside the note.
"""

import gi

gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

from ..util import run_shell
from .api import SidebarPlugin


class CommandPlugin(SidebarPlugin):
    """The standard output of a command, refreshed on a timer."""

    id = "command"
    title = "Command"
    icon = "utilities-terminal-symbolic"
    description = "The output of a shell command, rerun on a timer"
    settings_spec = [
        ("Command", [
            ("command", "Command", "entry", None),
            ("interval", "Rerun every, s", "spin", (0, 3600, 5)),
            ("monospace", "Monospace font", "switch", None),
            ("wrap", "Wrap long lines", "switch", None),
            ("expands", "Fill the tab", "switch", None),
        ]),
    ]
    defaults = {"command": "uptime", "interval": 60, "monospace": True,
                "wrap": True, "expands": False}

    def __init__(self, host):
        super().__init__(host)
        self._source = 0
        self.expands = bool(self.settings.get("expands"))

    def build(self):
        """Builds the label the output is written into."""
        self.label = Gtk.Label(xalign=0.0, yalign=0.0)
        self.label.set_name("command-output")
        self.label.set_selectable(True)
        self._apply_style()

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.add(self.label)
        return scroller

    def _apply_style(self):
        """Applies the wrapping and the font family to the label."""
        self.label.set_line_wrap(bool(self.settings.get("wrap")))
        self.label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        attributes = Pango.AttrList()
        if self.settings.get("monospace"):
            attributes.insert(Pango.attr_family_new("monospace"))
        self.label.set_attributes(attributes)

    def start(self):
        """Runs the command once, then on the configured interval."""
        self.reload()
        self._schedule()

    def _schedule(self):
        """Restarts the rerun timer, or stops it when the interval is zero."""
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
        interval = int(self.settings.get("interval", 0))
        if interval > 0:
            self._source = GLib.timeout_add_seconds(interval, self._poll)

    def _poll(self):
        """Reruns the command on the timer."""
        self.reload()
        return GLib.SOURCE_CONTINUE

    def reload(self):
        """Reruns the command and shows whatever it printed."""
        command = self.settings.get("command") or ""
        if not command.strip():
            self.label.set_text("")
            return
        run_shell(command, None, lambda ok, out:
                  self.label.set_text(out.rstrip("\n") if ok else "(the command failed)"))

    def settings_changed(self):
        """Applies the edited settings and reruns the command."""
        self._apply_style()
        self._schedule()
        self.reload()

    def stop(self):
        """Stops the rerun timer."""
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0


PLUGIN = CommandPlugin
