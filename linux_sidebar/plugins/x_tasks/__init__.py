"""Shows X-Tasks tasks in the sidebar: either My Day, or the tasks under a set of filter tags.

It only reads. Clicking a task opens it in the X-Tasks app through its x-tasks:// link.
"""

from datetime import datetime

import gi

gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

from ...util import run_argv
from ..api import SidebarPlugin
from . import logic, source

MODE_NAMES = {"my_day": "My Day", "filters": "Filters"}


class XTasksPlugin(SidebarPlugin):
    """A list of X-Tasks tasks, refreshed on a timer."""

    id = "x-tasks"
    title = "X-Tasks"
    icon = "emblem-ok-symbolic"
    description = "My Day, or the tasks under a set of X-Tasks filters"
    settings_spec = [
        ("Show", [
            ("view_mode", "Show", "combo", [("my_day", "My Day"), ("filters", "Filters")]),
            ("filters", "Filter tags, comma separated", "entry", None),
            ("filter_match", "A task must have", "combo",
             [("all", "Every filter"), ("any", "Any filter")]),
            ("show_done", "Show completed tasks", "switch", None),
            ("limit", "Most tasks shown, 0 for all", "spin", (0, 500, 1)),
            ("refresh_interval", "Refresh every, s", "spin", (0, 3600, 5)),
            ("expands", "Fill the tab", "switch", None),
        ]),
        ("X-Tasks server", [
            ("server_url", "Server", "entry", None),
            ("token", "Access token", "entry", None),
            ("token_command", "Token command, instead of the token", "entry", None),
            ("allow_insecure_tls", "Accept an untrusted certificate", "switch", None),
        ]),
    ]
    defaults = {
        "view_mode": "my_day",
        "filters": "Actionable",
        "filter_match": "all",
        "show_done": False,
        "limit": 0,
        "refresh_interval": 30,
        "expands": True,
        "server_url": "http://127.0.0.1:3918",
        "token": "",
        "token_command": "",
        "allow_insecure_tls": False,
    }

    def __init__(self, host):
        super().__init__(host)
        self.expands = bool(self.settings.get("expands"))
        self._source = 0
        self._request = 0
        self._stopped = False
        self._data = None

    # Building -------------------------------------------------------------------------------

    def build(self):
        """Builds the scrolling list the tasks are drawn into."""
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.list.set_name("x-tasks")
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.add(self.list)
        return scroller

    def header_widget(self):
        """Returns the button in the header that switches between My Day and the filters."""
        self.switch = Gtk.Button()
        self.switch.set_relief(Gtk.ReliefStyle.NONE)
        self.switch.set_name("x-tasks-switch")
        self.switch.connect("clicked", lambda _b: self._switch_mode())
        self._label_switch()
        return self.switch

    def _label_switch(self):
        """Names the view the switch button would change to."""
        other = "filters" if self._mode() == "my_day" else "my_day"
        self.switch.set_label(MODE_NAMES[other])
        self.switch.set_tooltip_text("Show %s instead" % MODE_NAMES[other])

    def _mode(self):
        """Returns the view being shown, which is My Day unless the filters were chosen."""
        return "filters" if self.settings.get("view_mode") == "filters" else "my_day"

    def _switch_mode(self):
        """Flips between My Day and the filters and remembers the choice."""
        self.settings["view_mode"] = "filters" if self._mode() == "my_day" else "my_day"
        self.host.save_settings()
        self._label_switch()
        self._draw()

    # Running --------------------------------------------------------------------------------

    def start(self):
        """Reads the tasks now and then on the refresh interval."""
        self.reload()
        self._schedule()

    def _schedule(self):
        """Restarts the refresh timer, or stops it when the interval is zero."""
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
        interval = int(self.settings.get("refresh_interval") or 0)
        if interval > 0:
            self._source = GLib.timeout_add_seconds(interval, self._poll)

    def _poll(self):
        """Rereads the tasks on the timer."""
        self.reload()
        return GLib.SOURCE_CONTINUE

    def reload(self):
        """Reads the tasks again, ignoring any earlier read that is still on its way."""
        self._request += 1
        request = self._request

        def loaded(data, error):
            if self._stopped or request != self._request:
                return
            if data is None:
                self.host.set_status("X-Tasks: %s" % error)
                return
            self.host.set_status("")
            self._data = data
            self._draw()

        source.load(self.settings, loaded)

    def settings_changed(self):
        """Applies the edited settings and rereads the tasks."""
        self.expands = bool(self.settings.get("expands"))
        self._label_switch()
        self._schedule()
        self.reload()

    # Drawing --------------------------------------------------------------------------------

    def _draw(self):
        """Works out the tasks to show from the last read and redraws the list."""
        if self._data is None:
            return
        now = datetime.now()
        board = logic.Board(self._data["tasks"], self._data["tags"], now)
        app_settings = self._data["settings"]
        show_done = bool(self.settings.get("show_done"))

        if self._mode() == "my_day":
            since = logic.my_day_since(app_settings, now.strftime("%Y-%m-%d"))
            visible = logic.in_my_day(board, show_done, since)
            title, empty = "My Day", "Nothing in My Day"
        else:
            names = (self.settings.get("filters") or "").split(",")
            filter_tags, unknown = logic.tags_named(names, board.tags)
            visible = logic.under_filters(board, filter_tags, self.settings.get("filter_match"),
                                          app_settings.get("tag_scope", "subtags"), show_done)
            title = ", ".join(tag["name"] for tag in filter_tags) or "Filters"
            empty = ("No tag named %s" % ", ".join(unknown) if unknown and not filter_tags
                     else "No tasks match" if filter_tags else "Name a filter tag in the settings")

        rows = logic.outline(visible, board)
        limit = int(self.settings.get("limit") or 0)
        if limit > 0:
            rows = rows[:limit]
        self.host.set_title("%s · %d" % (title, len(visible)))
        self._fill(rows, empty, now)

    def _fill(self, rows, empty, now):
        """Replaces the list's contents with one button per task, or a line saying there are none."""
        for child in self.list.get_children():
            child.destroy()
        if not rows:
            label = Gtk.Label(label=empty, xalign=0.0)
            label.set_name("x-tasks-empty")
            self.list.pack_start(label, False, False, 0)
        for task, depth in rows:
            self.list.pack_start(self._row(task, depth, now), False, False, 0)
        self.list.show_all()

    def _row(self, task, depth, now):
        """Builds the button for one task: its state, its title and its due date."""
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        line.set_margin_start(depth * 14)

        state = Gtk.Label(label="☑" if task["is_done"] else "☐")
        line.pack_start(state, False, False, 0)

        title = Gtk.Label(label=task["title"] or "(untitled)", xalign=0.0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        if task["is_done"]:
            title.set_markup("<s>%s</s>" % GLib.markup_escape_text(task["title"]))
        line.pack_start(title, True, True, 0)

        due = task.get("due_at")
        if due:
            label = Gtk.Label(label=logic.due_label(due, now))
            label.set_name("x-tasks-due")
            if not task["is_done"] and logic.is_overdue(due, now):
                label.get_style_context().add_class("overdue")
            line.pack_end(label, False, False, 0)

        button = Gtk.Button()
        button.set_name("x-tasks-row")
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(task["title"])
        button.add(line)
        button.connect("clicked", lambda _b: run_argv(
            ["xdg-open", "x-tasks://task/%s" % task["id"]], None, lambda *_args: None))
        return button

    def stop(self):
        """Stops the refresh timer and ignores any read still on its way."""
        self._stopped = True
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0


PLUGIN = XTasksPlugin
