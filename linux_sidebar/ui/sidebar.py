"""The docked window: a tab bar, a stack of tabs each holding collapsible plugin sections, and a footer."""

import cairo
import gi

gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from .. import docking, plugins
from ..clipboard import Clipboard
from ..util import log
from .section import Section

# How long a transient message such as "Saved" stays in the footer.
STATUS_MS = 1500


class Sidebar(Gtk.Window):
    """The sidebar window, docked by whichever backend this session supports."""

    def __init__(self, app, config):
        super().__init__(application=app)
        self.config = config
        self.backend = docking.choose(config)(self, config)
        self.clipboard = Clipboard(prefer_external=self.backend.name == "layer-shell")

        self._sections = {}
        self._instances = {}
        self._statuses = {}
        self._status_source = 0
        self._settings_window = None

        self._build()
        self.backend.attach()
        self.build_layout()
        self.apply_config()

    # Layout ---------------------------------------------------------------------------------

    def _build(self):
        """Builds the chrome that holds the tabs, leaving the tabs themselves to build_layout."""
        self.set_name("linux-sidebar")
        self.set_title("Linux Sidebar")

        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.frame.set_border_width(8)
        self.add(self.frame)

        self.tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.tab_bar.set_name("tab-bar")
        self.tab_bar.set_homogeneous(True)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(100)
        self.stack.connect("notify::visible-child-name", lambda *_: self._refresh_status())

        self.footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status = Gtk.Label(xalign=0.0)
        self.status.set_name("sidebar-status")
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.footer.pack_start(self.status, True, True, 0)

        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_image(Gtk.Image.new_from_icon_name("emblem-system-symbolic",
                                                      Gtk.IconSize.MENU))
        button.set_tooltip_text("Settings")
        button.connect("clicked", lambda _b: self.open_settings())
        self.footer.pack_end(button, False, False, 0)

        self.connect("key-press-event", self._on_key_press)
        self.connect("realize", lambda *_: self.backend.on_realize())
        self.connect("size-allocate", lambda *_: self._on_size_allocate())
        self.connect("focus-in-event", lambda *_: self._on_focus_in())
        self.connect("delete-event", lambda *_: self.hide() or True)

    def build_layout(self):
        """Rebuilds every tab and section from the layout in the settings."""
        self.teardown_plugins()
        for child in self.stack.get_children():
            self.stack.remove(child)
        for child in self.tab_bar.get_children():
            self.tab_bar.remove(child)
        for child in self.frame.get_children():
            self.frame.remove(child)

        self._pages = {}
        for tab in self.config.tabs():
            self.stack.add_titled(self._build_tab(tab), tab["id"], tab["title"])
            self.tab_bar.pack_start(self._build_tab_button(tab), True, True, 0)

        position = str(self.config["tab_position"]).lower()
        if position == "top" and len(self.config.tabs()) > 1:
            self.frame.pack_start(self.tab_bar, False, False, 0)
        self.frame.pack_start(self.stack, True, True, 0)
        if position == "bottom" and len(self.config.tabs()) > 1:
            self.frame.pack_start(self.tab_bar, False, False, 0)
        self.frame.pack_start(self.footer, False, False, 0)

        self._sync_tab_buttons()
        self.frame.show_all()
        self._apply_visibility()
        self.start_plugins()

    def _build_tab(self, tab):
        """Builds one tab: a scrollable column of the sections its plugins occupy."""
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        column.set_name("tab-page")
        for instance in tab["plugins"]:
            plugin = plugins.create(self, instance)
            if plugin is None:
                continue
            section = Section(instance, plugin, self._on_section_collapsed)
            self._sections[instance["id"]] = section
            self._instances[instance["id"]] = plugin
            column.pack_start(section, section.greedy, True, 0)

        # A viewport gives its child at least the height of the view, so a greedy section
        # fills the tab when the column is short and the column scrolls when it is not.
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(column)
        self._pages[tab["id"]] = (scroller, column)
        return scroller

    def _build_tab_button(self, tab):
        """Builds the tab bar's button for one tab."""
        button = Gtk.ToggleButton()
        button.set_name("tab-button")
        button.set_tooltip_text(tab["title"])
        if tab["icon"]:
            button.set_image(Gtk.Image.new_from_icon_name(tab["icon"], Gtk.IconSize.MENU))
        else:
            button.set_label(tab["title"])
        button.connect("toggled", self._on_tab_toggled, tab["id"])
        return button

    def _on_tab_toggled(self, button, tab_id):
        """Switches to the toggled tab, keeping the buttons in step."""
        if not button.get_active():
            if self.stack.get_visible_child_name() == tab_id:
                button.set_active(True)
            return
        self.stack.set_visible_child_name(tab_id)
        self._sync_tab_buttons()

    def _sync_tab_buttons(self):
        """Marks the button of the visible tab active and the rest not."""
        current = self.stack.get_visible_child_name()
        for button, tab in zip(self.tab_bar.get_children(), self.config.tabs()):
            active = tab["id"] == current
            if button.get_active() != active:
                button.handler_block_by_func(self._on_tab_toggled)
                button.set_active(active)
                button.handler_unblock_by_func(self._on_tab_toggled)

    # A greedy section shares the leftover space; the packing has to change with the fold.
    def _on_section_collapsed(self, section):
        """Repacks a tab after one of its sections was folded or unfolded, and saves the state."""
        for _scroller, column in self._pages.values():
            if section in column.get_children():
                column.child_set_property(section, "expand", section.greedy)
                column.child_set_property(section, "fill", True)
        self.config.save()

    # Settings -------------------------------------------------------------------------------

    def apply_config(self):
        """Applies the window settings, and the docking settings through the backend."""
        self.backend.apply()
        Gtk.Widget.set_opacity(self, max(0.1, min(1.0, float(self.config["opacity"]))))
        self._apply_input_region()
        self._apply_visibility()
        self._refresh_status()

    def _apply_visibility(self):
        """Shows or hides the footer and the tab bar according to the settings."""
        self.status.set_visible(bool(self.config["show_status"]))
        many = len(self.config.tabs()) > 1
        self.tab_bar.set_visible(many and str(self.config["tab_position"]).lower() != "hidden")

    # A full-height strip covers the screen corners, where the desktop's hot corners sit.
    def _apply_input_region(self):
        """Cuts a square out of each end of the input region so hot corners stay reachable."""
        surface = self.get_window()
        if surface is None:
            return
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        gap = int(self.config["hot_corner_gap"])
        if gap <= 0 or width <= 0 or height <= 0:
            surface.input_shape_combine_region(None, 0, 0)
            return
        gap = min(gap, width, height // 2)
        region = cairo.Region(cairo.RectangleInt(0, 0, width, height))
        # Only the outer edge of the strip touches a screen corner.
        x = width - gap if self.config["side"] == "right" else 0
        region.subtract(cairo.Region(cairo.RectangleInt(x, 0, gap, gap)))
        region.subtract(cairo.Region(cairo.RectangleInt(x, height - gap, gap, gap)))
        surface.input_shape_combine_region(region, 0, 0)

    def _on_size_allocate(self):
        """Keeps the input region in step with the window's size."""
        self._apply_input_region()
        self.backend.on_size_allocate()

    def _on_focus_in(self):
        """Lets the backend remember what held the keyboard before the sidebar took it."""
        if hasattr(self.backend, "note_focus_gained"):
            self.backend.note_focus_gained()

    def open_settings(self):
        """Opens the settings window, or brings the open one forward."""
        from .settings import SettingsWindow
        if self._settings_window is not None:
            self._settings_window.present()
            return

        def closed():
            self._settings_window = None

        self._settings_window = SettingsWindow(self.get_application(), self, closed)
        self._settings_window.show_all()

    def instance_settings_changed(self, instance_id):
        """Applies an edited plugin setting to the one instance it belongs to."""
        plugin = self._instances.get(instance_id)
        if plugin is not None:
            _guard(plugin.settings_changed, plugin)

    def settings_changed(self, relayout=False):
        """Saves the settings and applies them, rebuilding the tabs if the layout changed."""
        self.config.save()
        if relayout:
            self.build_layout()
        self.apply_config()
        if not relayout:
            for plugin in self._instances.values():
                _guard(plugin.settings_changed, plugin)

    # Status ---------------------------------------------------------------------------------

    def set_plugin_status(self, instance_id, text):
        """Records a plugin's status line and shows it if nothing transient is on screen."""
        if text:
            self._statuses[instance_id] = text
        else:
            self._statuses.pop(instance_id, None)
        self._refresh_status()

    def set_section_title(self, instance_id, text):
        """Changes the header text of one section."""
        section = self._sections.get(instance_id)
        if section is not None:
            section.set_title(text)

    def _refresh_status(self):
        """Puts the statuses of the visible tab's plugins into the footer."""
        if self._status_source:
            return
        tab = next((t for t in self.config.tabs()
                    if t["id"] == self.stack.get_visible_child_name()), None)
        order = [i["id"] for i in tab["plugins"]] if tab else list(self._statuses)
        parts = [self._statuses[i] for i in order if self._statuses.get(i)]
        self.status.set_text("  ".join(parts))
        self.status.set_visible(bool(self.config["show_status"]))

    def flash(self, message):
        """Shows a message in the footer for a moment, then restores the status line."""
        if self._status_source:
            GLib.source_remove(self._status_source)
        self.status.set_visible(True)
        self.status.set_text(message)

        def restore():
            self._status_source = 0
            self._refresh_status()
            return GLib.SOURCE_REMOVE

        self._status_source = GLib.timeout_add(STATUS_MS, restore)

    # Input ----------------------------------------------------------------------------------

    def release_keyboard(self):
        """Hands the keyboard back to the window underneath."""
        self.backend.release_keyboard()

    def _on_key_press(self, _widget, event):
        """Handles the shortcuts the sidebar itself owns."""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        key = Gdk.keyval_name(event.keyval)
        if key == "Escape":
            self.release_keyboard()
            return True
        if ctrl and key in ("Tab", "ISO_Left_Tab"):
            self.cycle_tab(-1 if event.state & Gdk.ModifierType.SHIFT_MASK else 1)
            return True
        return False

    def cycle_tab(self, step):
        """Moves to the next or previous tab, wrapping round."""
        tabs = [t["id"] for t in self.config.tabs()]
        if len(tabs) < 2:
            return
        try:
            index = tabs.index(self.stack.get_visible_child_name())
        except ValueError:
            index = 0
        self.stack.set_visible_child_name(tabs[(index + step) % len(tabs)])
        self._sync_tab_buttons()
        self._refresh_status()

    # Lifetime -------------------------------------------------------------------------------

    def start_plugins(self):
        """Starts every plugin instance, once the window has been shown."""
        for plugin in self._instances.values():
            _guard(plugin.start, plugin)

    def teardown_plugins(self):
        """Stops every plugin instance and forgets its section."""
        for plugin in self._instances.values():
            _guard(plugin.flush, plugin)
            _guard(plugin.stop, plugin)
        self._instances = {}
        self._sections = {}
        self._statuses = {}

    def flush(self):
        """Asks every plugin to write out anything still pending."""
        for plugin in self._instances.values():
            _guard(plugin.flush, plugin)

    def reload(self):
        """Asks every plugin to reread whatever it is showing."""
        for plugin in self._instances.values():
            _guard(plugin.reload, plugin)

    def reveal(self):
        """Shows the sidebar and applies the settings that only matter while it is visible."""
        self.show_all()
        self._apply_visibility()
        self.reload()

    def toggle(self):
        """Shows the sidebar if it is hidden, and hides it if it is not."""
        if self.get_visible():
            self.flush()
            self.hide()
        else:
            self.reveal()

    def shutdown(self):
        """Saves everything and releases the docking backend."""
        self.flush()
        self.teardown_plugins()
        if self._status_source:
            GLib.source_remove(self._status_source)
            self._status_source = 0
        self.backend.shutdown()


def _guard(call, plugin):
    """Runs a plugin callback, logging anything it raises rather than letting it escape."""
    try:
        call()
    except Exception as error:
        log("%s raised %s: %s" % (type(plugin).__name__, type(error).__name__, error))
