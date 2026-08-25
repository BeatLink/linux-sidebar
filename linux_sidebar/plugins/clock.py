"""A clock and date, so a sidebar with the panel hidden still says what time it is."""

from gi.repository import GLib, Gtk

from .api import SidebarPlugin


class ClockPlugin(SidebarPlugin):
    """The current time and date, formatted with strftime."""

    id = "clock"
    title = "Clock"
    icon = "preferences-system-time-symbolic"
    description = "The time and the date"
    settings_spec = [
        ("Clock", [
            ("time_format", "Time format", "entry", None),
            ("date_format", "Date format, blank for none", "entry", None),
        ]),
    ]
    defaults = {"time_format": "%H:%M", "date_format": "%A %e %B"}

    def __init__(self, host):
        super().__init__(host)
        self._source = 0

    def build(self):
        """Builds the two labels the clock is made of."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_name("clock")
        self.time = Gtk.Label()
        self.time.set_name("clock-time")
        self.date = Gtk.Label()
        self.date.set_name("clock-date")
        box.pack_start(self.time, False, False, 0)
        box.pack_start(self.date, False, False, 0)
        return box

    def start(self):
        """Starts the tick that redraws the clock every second."""
        self._tick()
        self._source = GLib.timeout_add_seconds(1, self._tick)

    def _tick(self):
        """Redraws the clock from the current time."""
        now = GLib.DateTime.new_now_local()
        self.time.set_text(now.format(self.settings.get("time_format") or "%H:%M") or "")
        date = self.settings.get("date_format") or ""
        self.date.set_text(now.format(date) or "" if date else "")
        self.date.set_visible(bool(date))
        return GLib.SOURCE_CONTINUE

    def settings_changed(self):
        """Redraws the clock in the new format."""
        self._tick()

    def stop(self):
        """Stops the tick."""
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0


PLUGIN = ClockPlugin
