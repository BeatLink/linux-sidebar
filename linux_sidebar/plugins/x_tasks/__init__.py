"""Shows X-Tasks tasks in the sidebar: either My Day, or the tasks under a set of filter tags.

Clicking a task opens it in the X-Tasks app through its x-tasks:// link, and the box above the
list adds a task to the view being shown, reading the app's Todoist quick-add syntax.
"""

from datetime import datetime

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from ...util import run_argv
from ..api import SidebarPlugin
from . import logic, source, syntax

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
            ("show_add", "Show the box for adding a task", "switch", None),
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
        "show_add": True,
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
        self._drawn = None
        self._due_labels = []

    # Building -------------------------------------------------------------------------------

    def build(self):
        """Builds the box for adding a task above the scrolling list the tasks are drawn into."""
        self.entry = Gtk.Entry()
        self.entry.set_name("x-tasks-add")
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "list-add-symbolic")
        self.entry.connect("activate", lambda _e: self._add())
        self.entry.connect("key-press-event", self._on_entry_key)
        self.entry.set_no_show_all(True)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.list.set_name("x-tasks")
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.add(self.list)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        body.pack_start(self.entry, False, False, 0)
        body.pack_start(scroller, True, True, 0)
        self._show_entry()
        return body

    def _show_entry(self):
        """Shows the box for adding a task unless the settings hide it, and says where a task goes."""
        self.entry.set_visible(bool(self.settings.get("show_add")))
        where = ", ".join(self._filter_names()) if self._mode() == "filters" else "My Day"
        self.entry.set_placeholder_text("Add a task to %s" % (where or "the filters"))

    def _filter_names(self):
        """Returns the filter tag names typed into the settings."""
        return [name.strip() for name in (self.settings.get("filters") or "").split(",") if name.strip()]

    def _on_entry_key(self, _entry, event):
        """Hands the keyboard back on Escape."""
        if event.keyval == Gdk.KEY_Escape:
            self.entry.set_text("")
            self.host.release_keyboard()
            return True
        return False

    def _add(self):
        """Adds the typed task to My Day, or under the filters, with the tags and dates it names."""
        text = self.entry.get_text().strip()
        if not text:
            return
        if self._mode() == "filters" and self._data is None:
            self.host.flash("X-Tasks: the filters have not loaded yet")
            return

        parsed = {"title": text, "tag_ids": [], "start_at": None, "due_at": None, "problems": []}
        if self._data is not None and self._data["settings"].get("quick_add_syntax", "todoist") == "todoist":
            field = self._data["settings"].get("task_date_field", "due")
            parsed = syntax.parse_quick_add(text, self._data["tags"], self._data["groups"], field,
                                            datetime.now())
            # Typing only a date leaves no title, so the text itself is kept as one.
            parsed["title"] = parsed["title"] or text

        tag_ids, my_day_on = list(parsed["tag_ids"]), None
        if self._mode() == "my_day":
            my_day_on = datetime.now().strftime("%Y-%m-%d")
        else:
            filter_tags, _unknown = logic.tags_named(self._filter_names(), self._data["tags"])
            for tag_id in logic.tags_for_new_task(filter_tags, self._data["groups"]):
                if tag_id not in tag_ids:
                    tag_ids.append(tag_id)

        self.entry.set_sensitive(False)

        def finished(error):
            if self._stopped:
                return
            self.entry.set_sensitive(True)
            if error:
                self.host.flash("X-Tasks: %s" % error)
                return
            self.entry.set_text("")
            self.entry.grab_focus()
            if parsed["problems"]:
                self.host.flash("X-Tasks: %s" % ", ".join(parsed["problems"]))
            self.reload()

        def added(task, error):
            if task is None:
                finished(error)
            elif parsed["start_at"] or parsed["due_at"]:
                source.set_task_schedule(self.settings, task["id"], parsed["start_at"],
                                         parsed["due_at"], lambda _value, error: finished(error))
            else:
                finished("")

        source.add_task(self.settings, parsed["title"], tag_ids, my_day_on, added)

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
        self._show_entry()
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
        self._show_entry()
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
            visible = logic.in_my_day(board, show_done, since, app_settings)
            title, empty = "My Day", "Nothing in My Day"
        else:
            names = self._filter_names()
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
        # A name given to the section by hand is kept in place of the view's.
        title = self.host.instance.get("title") or title
        self.host.set_title("%s · %d" % (title, len(visible)))
        self._fill(rows, empty, now, app_settings.get("task_date_field", "due"))

    def _fill(self, rows, empty, now, field):
        """Replaces the list's contents with one button per task, or a line saying there are none."""
        # Rebuilding on every read would drop the hover and can jump the scroll, so an unchanged list is left alone.
        drawn = (empty, [(task["id"], task["title"], task["is_done"], depth,
                          logic.due_label(logic.task_date(task, field), now)) for task, depth in rows])
        if drawn == self._drawn:
            self._mark_overdue(now)
            return
        self._drawn = drawn
        for child in self.list.get_children():
            child.destroy()
        self._due_labels = []
        if not rows:
            label = Gtk.Label(label=empty, xalign=0.0)
            label.set_name("x-tasks-empty")
            self.list.pack_start(label, False, False, 0)
        for task, depth in rows:
            self.list.pack_start(self._row(task, depth, now, field), False, False, 0)
        self._mark_overdue(now)
        self.list.show_all()

    def _mark_overdue(self, now):
        """Marks the dates that have passed since the list was built."""
        for label, text, is_done in self._due_labels:
            context = label.get_style_context()
            if not is_done and logic.is_overdue(text, now):
                context.add_class("overdue")
            else:
                context.remove_class("overdue")

    def _row(self, task, depth, now, field):
        """Builds the button for one task: its state, its title and its due date."""
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        line.set_margin_start(depth * 14)

        state = Gtk.Label(label="☑" if task["is_done"] else "☐")
        line.pack_start(state, False, False, 0)

        text = task["title"] or "(untitled)"
        title = Gtk.Label(label=text, xalign=0.0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        if task["is_done"]:
            title.set_markup("<s>%s</s>" % GLib.markup_escape_text(text))
        line.pack_start(title, True, True, 0)

        due = logic.task_date(task, field)
        if due:
            label = Gtk.Label(label=logic.due_label(due, now))
            label.set_name("x-tasks-due")
            self._due_labels.append((label, due, task["is_done"]))
            line.pack_end(label, False, False, 0)

        button = Gtk.Button()
        button.set_name("x-tasks-row")
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(text)
        button.add(line)
        button.connect("clicked", lambda _b: run_argv(
            ["xdg-open", "x-tasks://task/%s" % task["id"]], None, lambda *_args: None))
        return button

    def stop(self):
        """Stops the refresh timer and ignores any read still on its way."""
        self._stopped = True
        self.host.set_status("")
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0


PLUGIN = XTasksPlugin
