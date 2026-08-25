"""The settings window: the sidebar's own settings, the tab and plugin layout, and each plugin's settings.

It is an ordinary toplevel rather than a docked surface, so the window manager focuses
and decorates it like any other dialog.
"""

from gi.repository import Gdk, Gio, GLib, Gtk

from .. import config as config_module
from .. import desktop, docking, plugins
from ..util import launch_command, log
from . import widgets

COMMANDS = [("--toggle", "Show or hide the sidebar"), ("--show", "Show the sidebar"),
            ("--hide", "Hide the sidebar"), ("--next-tab", "Move to the next tab"),
            ("--settings", "Open this window"), ("--reload", "Reread the settings")]


class SettingsWindow(Gtk.Window):
    """Every setting the sidebar has, on one page per subject."""

    def __init__(self, app, sidebar, on_close):
        super().__init__(application=app, title="Linux Sidebar Settings")
        self.sidebar = sidebar
        self.config = sidebar.config
        self.set_default_size(560, 700)
        self.connect("destroy", lambda *_: on_close())

        self.notebook = Gtk.Notebook()
        self.add(self.notebook)
        self.notebook.append_page(self._sidebar_page(), Gtk.Label(label="Sidebar"))
        self.layout_page = _scrolled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18))
        self.notebook.append_page(self.layout_page, Gtk.Label(label="Tabs and plugins"))
        self.notebook.append_page(self._shortcuts_page(), Gtk.Label(label="Shortcuts"))
        self._build_layout_page()

    # The sidebar's own settings ---------------------------------------------------------------

    def _sidebar_page(self):
        """Builds the page holding the window's own settings."""
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page, self._controls = widgets.build_spec(config_module.SPEC, self.config,
                                                  self._core_changed)
        column.pack_start(page, False, False, 0)
        column.pack_start(_note("Docking: %s. This session is using %s."
                                % (docking.describe(), self.sidebar.backend.label)),
                          False, False, 0)
        column.pack_start(_note("Clipboard: %s." % self.sidebar.clipboard.describe()),
                          False, False, 0)
        self._update_sensitivity()
        return _scrolled(column)

    def _core_changed(self, _key):
        """Applies an edited sidebar setting straight away."""
        self._update_sensitivity()
        self.sidebar.settings_changed()

    def _update_sensitivity(self):
        """Greys out the settings that do not apply to the docking backend in use."""
        backend = self.sidebar.backend.name
        widgets.set_row_sensitive(self._controls, "x11_window_type", backend == "x11")
        widgets.set_row_sensitive(self._controls, "layer", backend == "layer-shell")
        widgets.set_row_sensitive(self._controls, "reserve_space",
                                  bool(self.sidebar.backend.reserves_space))

    # The layout -------------------------------------------------------------------------------

    def _build_layout_page(self):
        """Rebuilds the page listing every tab and the plugins inside it."""
        column = self.layout_page.get_child().get_child()
        for child in column.get_children():
            child.destroy()

        for index, tab in enumerate(self.config.tabs()):
            column.pack_start(self._tab_frame(index, tab), False, False, 0)

        add = Gtk.Button(label="Add a tab")
        add.set_halign(Gtk.Align.START)
        add.connect("clicked", lambda _b: self._add_tab())
        column.pack_start(add, False, False, 0)
        column.show_all()

    def _tab_frame(self, index, tab):
        """Builds the box of controls for one tab and the plugins it holds."""
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)
        frame.add(box)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Entry()
        title.set_text(tab["title"])
        title.set_hexpand(True)
        title.connect("changed", lambda w: self._set_tab(tab, "title", w.get_text()))
        header.pack_start(title, True, True, 0)

        icon = Gtk.Entry()
        icon.set_text(tab["icon"])
        icon.set_width_chars(20)
        icon.set_placeholder_text("Icon name")
        icon.connect("changed", lambda w: self._set_tab(tab, "icon", w.get_text()))
        header.pack_start(icon, False, False, 0)

        header.pack_start(self._move_button("go-up-symbolic", "Move up",
                                            lambda: self._move_tab(index, -1)), False, False, 0)
        header.pack_start(self._move_button("go-down-symbolic", "Move down",
                                            lambda: self._move_tab(index, 1)), False, False, 0)
        header.pack_start(self._move_button("user-trash-symbolic", "Remove this tab",
                                            lambda: self._remove_tab(index)), False, False, 0)
        box.pack_start(header, False, False, 0)

        for slot, instance in enumerate(tab["plugins"]):
            box.pack_start(self._instance_row(tab, slot, instance), False, False, 0)

        box.pack_start(self._add_plugin_row(tab), False, False, 0)
        return frame

    def _instance_row(self, tab, slot, instance):
        """Builds the row for one plugin instance, with its own settings folded underneath."""
        plugin = plugins.get(instance["plugin"])
        expander = Gtk.Expander()
        expander.set_label(instance.get("title") or (plugin.title if plugin else
                                                     "%s (missing)" % instance["plugin"]))

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label.pack_start(expander, True, True, 0)
        label.pack_start(self._move_button("go-up-symbolic", "Move up",
                                           lambda: self._move_instance(tab, slot, -1)),
                         False, False, 0)
        label.pack_start(self._move_button("go-down-symbolic", "Move down",
                                           lambda: self._move_instance(tab, slot, 1)),
                         False, False, 0)
        label.pack_start(self._move_button("user-trash-symbolic", "Remove this plugin",
                                           lambda: self._remove_instance(tab, slot)),
                         False, False, 0)
        row.pack_start(label, True, True, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_start(18)
        body.set_margin_top(8)
        name = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        name.pack_start(Gtk.Label(label="Section title", xalign=0.0), False, False, 0)
        entry = Gtk.Entry()
        entry.set_placeholder_text(plugin.title if plugin else "")
        entry.set_text(instance.get("title") or "")
        entry.connect("changed", lambda w: self._set_instance_title(instance, expander,
                                                                    w.get_text()))
        name.pack_start(entry, True, True, 0)
        body.pack_start(name, False, False, 0)

        if plugin is not None and plugin.settings_spec:
            page, _controls = widgets.build_spec(plugin.settings_spec, instance["settings"],
                                                 lambda _k: self._instance_changed(instance))
            body.pack_start(page, False, False, 0)
        elif plugin is None:
            body.pack_start(_note("This plugin is not installed, so its settings cannot be shown."),
                            False, False, 0)
        expander.add(body)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        column.pack_start(row, False, False, 0)
        return column

    def _add_plugin_row(self, tab):
        """Builds the control that adds another plugin to a tab."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chooser = Gtk.ComboBoxText()
        for plugin_id, plugin in sorted(plugins.registry().items()):
            chooser.append(plugin_id, plugin.title)
        chooser.set_active(0)
        row.pack_start(chooser, False, False, 0)

        button = Gtk.Button(label="Add plugin")
        button.connect("clicked", lambda _b: self._add_instance(tab, chooser.get_active_id()))
        row.pack_start(button, False, False, 0)
        return row

    def _move_button(self, icon, tooltip, action):
        """Builds one of the small icon buttons that reorder or remove a row."""
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(tooltip)
        button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
        button.connect("clicked", lambda _b: action())
        return button

    # Layout edits -----------------------------------------------------------------------------

    def _set_tab(self, tab, key, value):
        """Renames a tab or changes its icon, and rebuilds the sidebar."""
        tab[key] = value
        self._relayout(rebuild_page=False)

    def _add_tab(self):
        """Adds an empty tab."""
        self.config.tabs().append({"id": self.config.next_id("tab"), "title": "New tab",
                                   "icon": "view-list-symbolic", "plugins": []})
        self._relayout()

    def _remove_tab(self, index):
        """Removes a tab, keeping at least one."""
        tabs = self.config.tabs()
        if len(tabs) <= 1:
            self.sidebar.flash("The last tab cannot be removed")
            return
        tabs.pop(index)
        self._relayout()

    def _move_tab(self, index, step):
        """Moves a tab up or down the list."""
        tabs = self.config.tabs()
        target = index + step
        if 0 <= target < len(tabs):
            tabs.insert(target, tabs.pop(index))
            self._relayout()

    def _add_instance(self, tab, plugin_id):
        """Adds a plugin to a tab."""
        if not plugin_id:
            return
        tab["plugins"].append({"id": self.config.next_id(plugin_id), "plugin": plugin_id,
                               "title": "", "collapsed": False, "settings": {}})
        self._relayout()

    def _remove_instance(self, tab, slot):
        """Removes a plugin from a tab."""
        tab["plugins"].pop(slot)
        self._relayout()

    def _move_instance(self, tab, slot, step):
        """Moves a plugin up or down inside its tab."""
        target = slot + step
        if 0 <= target < len(tab["plugins"]):
            tab["plugins"].insert(target, tab["plugins"].pop(slot))
            self._relayout()

    def _set_instance_title(self, instance, expander, title):
        """Renames one section."""
        instance["title"] = title
        plugin = plugins.get(instance["plugin"])
        expander.set_label(title or (plugin.title if plugin else instance["plugin"]))
        self._relayout(rebuild_page=False)

    def _instance_changed(self, instance):
        """Applies an edited plugin setting to the running instance."""
        self.config.save()
        self.sidebar.instance_settings_changed(instance["id"])

    def _relayout(self, rebuild_page=True):
        """Saves the layout, rebuilds the sidebar and, unless told not to, this page."""
        self.sidebar.settings_changed(relayout=True)
        if rebuild_page:
            self._build_layout_page()

    # Shortcuts --------------------------------------------------------------------------------

    # Only the desktop can hold a global shortcut, so there is nothing for this window to
    # capture; it hands over the commands to bind and a way to get to where they are bound.
    def _shortcuts_page(self):
        """Builds the page listing the commands a global shortcut can be bound to."""
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        column.pack_start(_note(
            "A global shortcut belongs to the desktop, not to an application, so these are bound "
            "in %s rather than here. Add a custom shortcut for whichever command you want."
            % desktop.desktop_name().title()), False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        for index, (option, description) in enumerate(COMMANDS):
            grid.attach(Gtk.Label(label=description, xalign=0.0), 0, index, 1, 1)
            entry = Gtk.Entry()
            entry.set_text("%s %s" % (launch_command(), option))
            entry.set_editable(False)
            entry.set_width_chars(34)
            entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-copy-symbolic")
            entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Copy")
            entry.connect("icon-release", lambda w, *_: Gtk.Clipboard.get(
                Gdk.SELECTION_CLIPBOARD).set_text(w.get_text(), -1))
            grid.attach(entry, 1, index, 1, 1)
        column.pack_start(grid, False, False, 0)

        argv = desktop.keyboard_settings_argv()
        if argv is not None:
            button = Gtk.Button(label="Open the keyboard settings")
            button.set_halign(Gtk.Align.START)
            button.connect("clicked", lambda _b: _launch(argv))
            column.pack_start(button, False, False, 0)
        return _scrolled(column)


def _scrolled(column):
    """Wraps a column of controls in a scroller with a comfortable border."""
    column.set_border_width(18)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.add(column)
    return scroller


def _note(text):
    """Returns a small wrapped explanatory label."""
    label = Gtk.Label(xalign=0.0)
    label.set_line_wrap(True)
    label.set_markup("<small>%s</small>" % GLib.markup_escape_text(text))
    return label


def _launch(argv):
    """Starts a command and leaves it running."""
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
    except GLib.Error as error:
        log("could not run %s: %s" % (argv[0], error.message))
