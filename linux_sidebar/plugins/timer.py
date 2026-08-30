"""A countdown timer, so a pomodoro or a kettle does not need a window of its own.

The countdown runs off the monotonic clock rather than off a count of ticks, so a
sidebar that was hidden, or a machine that was busy, still finishes on time.
"""

import math

from gi.repository import GLib, Gtk

from ..util import run_shell
from .api import SidebarPlugin

# How often the display is recomputed, in milliseconds, which is finer than a second so the
# seconds it shows turn over close to when they really do.
TICK_MS = 200


def _format(seconds):
    """Returns a whole number of seconds as h:mm:ss, or mm:ss under an hour."""
    total = max(0, int(math.ceil(seconds - 0.001)))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    return "%02d:%02d" % (minutes, seconds)


def _presets(text):
    """Returns the preset lengths in minutes parsed from a comma separated list."""
    lengths = []
    for piece in (text or "").replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            minutes = float(piece)
        except ValueError:
            continue
        if 0 < minutes and minutes not in lengths:
            lengths.append(minutes)
    return lengths[:6]


def _preset_label(minutes):
    """Returns the caption of a preset button, without a trailing .0 on whole minutes."""
    if minutes == int(minutes):
        return "%dm" % int(minutes)
    return "%gm" % minutes


class TimerPlugin(SidebarPlugin):
    """A countdown with presets, which runs a command of your choosing when it reaches zero."""

    id = "timer"
    title = "Timer"
    icon = "alarm-symbolic"
    description = "A countdown timer that alerts you when it runs out"
    settings_spec = [
        ("Timer", [
            ("duration", "Countdown, min", "spin", (1, 600, 1)),
            ("presets", "Presets, minutes", "entry", None),
            ("count_in_title", "Show the countdown in the header", "switch", None),
        ]),
        ("When it finishes", [
            ("alert_command", "Command", "entry", None),
            ("alert_message", "Footer message", "entry", None),
        ]),
    ]
    defaults = {
        "duration": 25,
        "presets": "5, 10, 25",
        "count_in_title": True,
        "alert_command": 'notify-send "Timer" "Time is up"',
        "alert_message": "The timer finished",
    }

    def __init__(self, host):
        super().__init__(host)
        self._source = 0
        self._deadline = 0
        self._remaining = self._duration()
        self._running = False
        self._finished = False
        self._shown = None

    # Building -------------------------------------------------------------------------------

    def build(self):
        """Builds the countdown, the preset row and the two controls under it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_name("timer")

        self.display = Gtk.Label()
        self.display.set_name("timer-time")
        box.pack_start(self.display, False, False, 0)

        self.presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.presets.set_name("timer-presets")
        self.presets.set_homogeneous(True)
        box.pack_start(self.presets, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        controls.set_homogeneous(True)
        self.toggle = Gtk.Button()
        self.toggle.connect("clicked", lambda _b: self.toggle_running())
        controls.pack_start(self.toggle, True, True, 0)
        self.reset_button = Gtk.Button(label="Reset")
        self.reset_button.set_tooltip_text("Put the countdown back to its full length")
        self.reset_button.connect("clicked", lambda _b: self.reset())
        controls.pack_start(self.reset_button, True, True, 0)
        box.pack_start(controls, False, False, 0)

        self._build_presets()
        return box

    def _build_presets(self):
        """Fills the preset row with one button per configured length."""
        for child in self.presets.get_children():
            self.presets.remove(child)
        lengths = _presets(self.settings.get("presets"))
        for minutes in lengths:
            button = Gtk.Button(label=_preset_label(minutes))
            button.set_tooltip_text("Start a %s countdown" % _preset_label(minutes))
            button.connect("clicked", lambda _b, m=minutes: self.start_for(m * 60))
            self.presets.pack_start(button, True, True, 0)
        self.presets.set_visible(bool(lengths))
        self.presets.set_no_show_all(not lengths)
        self.presets.show_all()

    def start(self):
        """Shows the full countdown, stopped, until it is started."""
        self._refresh()

    # Running --------------------------------------------------------------------------------

    def _duration(self):
        """Returns the configured countdown length in seconds."""
        return max(1, int(self.settings.get("duration") or 1)) * 60

    def toggle_running(self):
        """Starts the countdown, or pauses one that is already running."""
        if self._running:
            self._pause()
        else:
            self._resume()

    def start_for(self, seconds):
        """Restarts the countdown at the given length and runs it."""
        self._finished = False
        self._remaining = seconds
        self._resume()

    def _resume(self):
        """Sets the deadline from the time left and starts the tick."""
        if self._finished or self._remaining <= 0:
            self._finished = False
            self._remaining = self._duration()
        self._deadline = GLib.get_monotonic_time() + int(self._remaining * 1000000)
        self._running = True
        self._schedule()
        self._refresh()

    def _pause(self):
        """Stops the tick, keeping whatever time is left."""
        self._remaining = self._left()
        self._running = False
        self._unschedule()
        self._refresh()

    def reset(self):
        """Stops the countdown and puts it back to its full length."""
        self._running = False
        self._finished = False
        self._remaining = self._duration()
        self._unschedule()
        self._refresh()

    def _left(self):
        """Returns the seconds still to run."""
        if not self._running:
            return self._remaining
        return max(0.0, (self._deadline - GLib.get_monotonic_time()) / 1000000.0)

    def _schedule(self):
        """Starts the tick that redraws the countdown."""
        self._unschedule()
        self._source = GLib.timeout_add(TICK_MS, self._tick)

    def _unschedule(self):
        """Stops the tick."""
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0

    def _tick(self):
        """Redraws the countdown, and finishes it once the deadline has passed."""
        if self._left() <= 0:
            self._source = 0
            self._finish()
            return GLib.SOURCE_REMOVE
        self._refresh()
        return GLib.SOURCE_CONTINUE

    def _finish(self):
        """Marks the countdown finished and raises the alert."""
        self._running = False
        self._finished = True
        self._remaining = 0
        self._refresh()
        message = self.settings.get("alert_message") or ""
        if message:
            self.host.flash(message)
        command = self.settings.get("alert_command") or ""
        if command.strip():
            run_shell(command, None, lambda _ok, _out: None)

    # Display --------------------------------------------------------------------------------

    def _refresh(self):
        """Writes the time left into the countdown, the header and the buttons."""
        text = _format(self._left())
        if text != self._shown:
            self._shown = text
            self.display.set_text(text)
        context = self.display.get_style_context()
        if self._finished:
            context.add_class("finished")
        else:
            context.remove_class("finished")
        self.toggle.set_label("Pause" if self._running else "Start")
        self.toggle.set_tooltip_text("Pause the countdown" if self._running
                                     else "Start the countdown")
        self.reset_button.set_sensitive(self._running or self._finished
                                        or self._remaining != self._duration())
        self._refresh_title()

    def _base_title(self):
        """Returns the title of this section, which the layout may have renamed."""
        return self.host.instance.get("title") or self.title

    def _refresh_title(self):
        """Puts the time left beside the section's title, if that is wanted."""
        title = self._base_title()
        if not self.settings.get("count_in_title"):
            self.host.set_title(title)
        elif self._running:
            self.host.set_title("%s  %s" % (title, self._shown))
        elif self._finished:
            self.host.set_title("%s  done" % title)
        else:
            self.host.set_title(title)

    def settings_changed(self):
        """Rebuilds the presets, and takes the new length if nothing is counting down."""
        self._build_presets()
        if not self._running and not self._finished:
            self._remaining = self._duration()
        self._refresh()

    def reload(self):
        """Puts the countdown back to its full length, as a reset does."""
        self.reset()

    def stop(self):
        """Stops the tick and clears anything the instance left in the sidebar."""
        self._unschedule()
        self.host.set_title(self._base_title())


PLUGIN = TimerPlugin
