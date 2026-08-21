#!/usr/bin/env python3
"""A full-height note scratchpad docked to the side of the screen.

The window is a wlr-layer-shell surface, so the compositor itself anchors it to the
edge and reserves its strip through an exclusive zone. That is what a panel or a dock
does, and it means windows genuinely cannot occupy the space rather than being pushed
out of it afterwards. The surface takes keyboard focus on demand, so typing needs no
input grab.

The note is kept either in a plain text file or in whatever store a pair of user
commands reads from and writes to.
"""

import json
import os
import shutil
import sys

import cairo

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, GtkLayerShell as LayerShell, Gtk

APP_ID = "org.beatlink.SidebarScratchpad"
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "sidebar-scratchpad")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# How long a transient status message such as "Saved" stays on screen.
STATUS_MS = 1500

DEFAULTS = {
    "side": "right",
    "width": 360,
    "monitor": -1,
    "reserve_space": True,
    "layer": "auto",
    "margin_top": 0,
    "margin_bottom": 0,
    "font_size": 11,
    "monospace": False,
    "opacity": 1.0,
    "show_counter": True,
    "hot_corner_gap": 24,
    "start_hidden": False,
    "storage_backend": "file",
    "storage_file": "",
    "read_command": "",
    "write_command": "",
    "autosave_delay": 800,
    "reload_interval": 0,
}


def style_path():
    """Finds the stylesheet beside the script, or under share/ once installed."""
    override = os.environ.get("SIDEBAR_SCRATCHPAD_STYLE")
    if override:
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "style.css"),
        os.path.join(here, os.pardir, "share", "sidebar-scratchpad", "style.css"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return os.path.normpath(candidate)
    return candidates[0]


def launch_command():
    """The command to bind to a shortcut: the installed binary, else the dev runner."""
    installed = shutil.which("sidebar-scratchpad")
    if installed:
        return installed
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.sh")


def log(message):
    print("[sidebar-scratchpad] %s" % message, file=sys.stderr)


def run_argv(argv, stdin, callback):
    """Runs a command with no shell, handing its standard output to the callback."""
    flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    if stdin is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE

    def finished(process, result):
        try:
            ok, out, err = process.communicate_utf8_finish(result)
        except GLib.Error as error:
            log("%s errored: %s" % (argv[0], error.message))
            callback(False, "")
            return
        if not process.get_successful():
            log("%s failed: %s" % (argv[0], (err or "").strip()))
            callback(False, "")
            return
        callback(True, out or "")

    try:
        process = Gio.Subprocess.new(argv, flags)
        process.communicate_utf8_async(stdin, None, finished)
    except GLib.Error as error:
        log("could not run %s: %s" % (argv[0], error.message))
        callback(False, "")


class Config(dict):
    """The settings file, created with the defaults the first time it is read."""

    def __init__(self):
        super().__init__(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(CONFIG_PATH) as handle:
                stored = json.load(handle)
            unknown = set(stored) - set(DEFAULTS)
            if unknown:
                log("ignoring unknown settings: %s" % ", ".join(sorted(unknown)))
            self.update({k: v for k, v in stored.items() if k in DEFAULTS})
            if set(DEFAULTS) - set(stored):
                self.save()
        except FileNotFoundError:
            self.save()
        except (OSError, ValueError) as error:
            log("could not read %s, using defaults: %s" % (CONFIG_PATH, error))

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
            with open(CONFIG_PATH, "w") as handle:
                json.dump(dict(self), handle, indent=4)
                handle.write("\n")
        except OSError as error:
            log("could not write %s: %s" % (CONFIG_PATH, error))


class NoteStore:
    """Reads and writes the note, through a file or through a pair of user commands.

    Both paths report through a callback because the command path must not run
    synchronously on the UI thread.
    """

    def __init__(self, config):
        self.config = config

    @property
    def mode(self):
        return "command" if self.config["storage_backend"] == "command" else "file"

    @property
    def path(self):
        custom = (self.config["storage_file"] or "").strip()
        if not custom:
            return os.path.join(CONFIG_DIR, "scratchpad.txt")
        return os.path.expanduser(custom)

    def identity(self):
        """Identifies the target, so a settings change can be spotted."""
        if self.mode == "command":
            return "command:%s|%s" % (self.config["read_command"], self.config["write_command"])
        return "file:%s" % self.path

    def load(self, callback):
        """Calls back with the note text, or None if it could not be read."""
        if self.mode == "command":
            self._run(self.config["read_command"], None,
                      lambda ok, out: callback(out if ok else None))
        else:
            callback(self._load_file())

    def save(self, text, callback):
        """Calls back with True once the note has been stored."""
        if self.mode == "command":
            self._run(self.config["write_command"], text, lambda ok, out: callback(ok))
        else:
            callback(self._save_file(text))

    def _load_file(self):
        try:
            with open(self.path) as handle:
                return handle.read()
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeDecodeError) as error:
            log("could not read %s: %s" % (self.path, error))
            return None

    def _save_file(self, text):
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            # Write through a temporary file so an interrupted save cannot truncate the note.
            temporary = self.path + ".tmp"
            with open(temporary, "w") as handle:
                handle.write(text)
            os.replace(temporary, self.path)
            return True
        except OSError as error:
            log("could not write %s: %s" % (self.path, error))
            return False

    def _run(self, command, stdin, callback):
        """Runs a command through bash, so pipelines and redirection work."""
        if not (command or "").strip():
            log("no %s command is configured" % ("read" if stdin is None else "write"))
            callback(False, "")
            return

        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        if stdin is not None:
            flags |= Gio.SubprocessFlags.STDIN_PIPE

        def finished(process, result):
            try:
                ok, out, err = process.communicate_utf8_finish(result)
            except GLib.Error as error:
                log("command errored: %s: %s" % (command, error.message))
                callback(False, "")
                return
            if not process.get_successful():
                log("command failed: %s: %s" % (command, (err or "").strip()))
                callback(False, "")
                return
            callback(True, out or "")

        try:
            process = Gio.Subprocess.new(["bash", "-c", command], flags)
            process.communicate_utf8_async(stdin, None, finished)
        except GLib.Error as error:
            log("could not run: %s: %s" % (command, error.message))
            callback(False, "")


# Each row is (key, label, kind, detail); detail is the choices for a combo or the
# (minimum, maximum, step) for a spin button or scale.
SETTINGS_SPEC = [
    ("Placement", [
        ("side", "Dock to", "combo", [("left", "Left"), ("right", "Right")]),
        ("width", "Width", "spin", (150, 2000, 10)),
        ("monitor", "Monitor, -1 for automatic", "spin", (-1, 7, 1)),
        ("reserve_space", "Keep windows out", "switch", None),
        ("layer", "Layer", "combo",
         [("auto", "Automatic"), ("bottom", "Bottom"), ("top", "Top")]),
        ("hot_corner_gap", "Hot corner gap", "spin", (0, 200, 4)),
        ("margin_top", "Top margin", "spin", (0, 400, 4)),
        ("margin_bottom", "Bottom margin", "spin", (0, 400, 4)),
    ]),
    ("Appearance", [
        ("font_size", "Font size", "spin", (6, 32, 1)),
        ("monospace", "Monospace font", "switch", None),
        ("opacity", "Opacity", "scale", (0.3, 1.0, 0.05)),
        ("show_counter", "Show the word count", "switch", None),
        ("start_hidden", "Start hidden", "switch", None),
    ]),
    ("Storage", [
        ("storage_backend", "Keep the note in", "combo",
         [("file", "A plain text file"), ("command", "Custom commands")]),
        ("storage_file", "Note file", "entry", None),
        ("read_command", "Read command", "entry", None),
        ("write_command", "Write command", "entry", None),
        ("autosave_delay", "Autosave delay, ms", "spin", (100, 10000, 100)),
        ("reload_interval", "Reread interval, s", "spin", (0, 3600, 10)),
    ]),
]


class SettingsWindow(Gtk.Window):
    """An ordinary toplevel, deliberately not a layer-shell surface, so the window
    manager gives it focus and decorations like any other dialog."""

    def __init__(self, app, config, on_change, on_close):
        super().__init__(application=app, title="Sidebar Scratchpad Settings")
        self.config = config
        self.on_change = on_change
        self.set_default_size(460, 620)
        self.connect("destroy", lambda *_: on_close())

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.add(scroller)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        column.set_border_width(18)
        scroller.add(column)

        self._rows = {}
        for title, rows in SETTINGS_SPEC:
            heading = Gtk.Label(xalign=0.0)
            heading.set_markup("<b>%s</b>" % title)
            column.pack_start(heading, False, False, 0)

            grid = Gtk.Grid(column_spacing=12, row_spacing=8)
            column.pack_start(grid, False, False, 0)
            for index, (key, label, kind, detail) in enumerate(rows):
                caption = Gtk.Label(label=label, xalign=0.0)
                caption.set_hexpand(True)
                grid.attach(caption, 0, index, 1, 1)
                widget = self._build_widget(key, kind, detail)
                grid.attach(widget, 1, index, 1, 1)
                self._rows[key] = (caption, widget)

        self._add_shortcut_section(column)
        self._update_sensitivity()

    # Only the compositor can bind a global shortcut on Wayland, so there is nothing for
    # this window to capture. It hands over the command to bind and a way to get there.
    def _add_shortcut_section(self, column):
        heading = Gtk.Label(xalign=0.0)
        heading.set_markup("<b>Keyboard shortcuts</b>")
        column.pack_start(heading, False, False, 0)

        explanation = Gtk.Label(xalign=0.0)
        explanation.set_line_wrap(True)
        explanation.set_markup(
            "<small>On Wayland only the compositor can hold a global shortcut, so these are "
            "bound in Cinnamon rather than here. Add a custom shortcut for the command "
            "below; swap <tt>--toggle</tt> for <tt>--show</tt>, <tt>--hide</tt> or "
            "<tt>--settings</tt> for the others.</small>")
        column.pack_start(explanation, False, False, 0)

        command = Gtk.Entry()
        command.set_text("%s --toggle" % launch_command())
        command.set_editable(False)
        command.set_can_focus(True)
        command.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-copy-symbolic")
        command.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Copy")
        command.connect("icon-release", self._copy_command)
        column.pack_start(command, False, False, 0)

        button = Gtk.Button(label="Open Cinnamon Keyboard Settings")
        button.set_halign(Gtk.Align.START)
        button.connect("clicked", self._open_keyboard_settings)
        column.pack_start(button, False, False, 0)

    def _copy_command(self, entry, *_args):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(entry.get_text(), -1)

    def _open_keyboard_settings(self, _button):
        try:
            Gio.Subprocess.new(["cinnamon-settings", "keyboard"],
                               Gio.SubprocessFlags.NONE)
        except GLib.Error as error:
            log("could not open the keyboard settings: %s" % error.message)

    def _build_widget(self, key, kind, detail):
        value = self.config[key]

        if kind == "switch":
            widget = Gtk.Switch(halign=Gtk.Align.END)
            widget.set_active(bool(value))
            widget.connect("notify::active",
                           lambda w, _p: self._set(key, w.get_active()))
            return widget

        if kind == "combo":
            widget = Gtk.ComboBoxText()
            for ident, label in detail:
                widget.append(ident, label)
            widget.set_active_id(str(value))
            widget.connect("changed",
                           lambda w: self._set(key, w.get_active_id()))
            return widget

        if kind == "spin":
            low, high, step = detail
            widget = Gtk.SpinButton.new_with_range(low, high, step)
            widget.set_value(float(value))
            widget.connect("value-changed",
                           lambda w: self._set(key, int(w.get_value())))
            return widget

        if kind == "scale":
            low, high, step = detail
            widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
            widget.set_size_request(200, -1)
            widget.set_value(float(value))
            widget.set_digits(2)
            widget.connect("value-changed",
                           lambda w: self._set(key, round(w.get_value(), 2)))
            return widget

        widget = Gtk.Entry()
        widget.set_text(str(value or ""))
        widget.set_width_chars(24)
        # Commands only take effect once you finish typing them, never mid-keystroke.
        widget.connect("activate", lambda w: self._set(key, w.get_text()))
        widget.connect("focus-out-event", lambda w, _e: self._set(key, w.get_text()))
        return widget

    def _set(self, key, value):
        if self.config.get(key) == value:
            return
        self.config[key] = value
        self._update_sensitivity()
        self.on_change()

    # Only the rows that apply to the chosen storage backend stay usable.
    def _update_sensitivity(self):
        command = self.config["storage_backend"] == "command"
        for key, applies in (("storage_file", not command),
                             ("read_command", command),
                             ("write_command", command)):
            for widget in self._rows.get(key, ()):
                widget.set_sensitive(applies)


class Sidebar(Gtk.Window):

    def __init__(self, app, config):
        super().__init__(application=app)
        self.config = config
        self.store = NoteStore(config)

        self._loading = False
        self._dirty = False
        # Set once you actually edit the note. Until then an empty buffer is treated as
        # "nothing loaded yet" rather than as a note you emptied on purpose.
        self._edited = False
        self._save_source = 0
        self._status_source = 0
        self._reload_source = 0
        self._settings_window = None

        self._build()
        self._init_layer_shell()
        self.apply_config()
        self.load_note(force=True)

    # Layout ---------------------------------------------------------------------------

    def _build(self):
        self.set_name("sidebar-scratchpad")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        self.add(box)

        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_accepts_tab(True)
        self.view.set_left_margin(8)
        self.view.set_right_margin(8)
        self.view.set_top_margin(8)
        self.view.set_bottom_margin(8)
        # The font is driven through CSS; override_font is deprecated in GTK 3.
        self._font_css = Gtk.CssProvider()
        self.view.get_style_context().add_provider(
            self._font_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.buffer = self.view.get_buffer()
        self.buffer.connect("changed", self._on_changed)

        scroller = Gtk.ScrolledWindow()
        scroller.set_name("note-frame")
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.view)
        box.pack_start(scroller, True, True, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status = Gtk.Label(xalign=0.0)
        self.status.set_name("note-status")
        footer.pack_start(self.status, True, True, 0)

        self.settings_button = Gtk.Button()
        self.settings_button.set_relief(Gtk.ReliefStyle.NONE)
        self.settings_button.set_image(
            Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.MENU))
        self.settings_button.set_tooltip_text("Settings")
        self.settings_button.connect("clicked", self._open_settings)
        footer.pack_end(self.settings_button, False, False, 0)

        box.pack_start(footer, False, False, 0)

        self.view.connect("button-press-event", self._on_button_press)
        self.connect("key-press-event", self._on_key_press)
        self.connect("size-allocate", lambda *_: self._apply_input_region())
        self.connect("delete-event", lambda *_: self.hide() or True)

    def _init_layer_shell(self):
        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "sidebar-scratchpad")
        # ON_DEMAND lets the surface take focus when clicked without ever stealing it.
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)

    def _apply_anchors(self):
        side = LayerShell.Edge.LEFT if self.config["side"] == "left" else LayerShell.Edge.RIGHT
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                     LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM):
            # Anchoring top and bottom plus one side gives a full-height strip on that edge.
            LayerShell.set_anchor(self, edge, edge != (
                LayerShell.Edge.RIGHT if side == LayerShell.Edge.LEFT else LayerShell.Edge.LEFT))

        # Layer-shell has no layer meaning "above windows but below the shell's own panels",
        # so an auto-hide panel needs a margin held clear for it by hand.
        LayerShell.set_margin(self, LayerShell.Edge.TOP, int(self.config["margin_top"]))
        LayerShell.set_margin(self, LayerShell.Edge.BOTTOM, int(self.config["margin_bottom"]))

        monitor = self.config["monitor"]
        if isinstance(monitor, int) and monitor >= 0:
            display = Gdk.Display.get_default()
            target = display.get_monitor(monitor)
            if target:
                LayerShell.set_monitor(self, target)

    # A full-height strip covers the screen corners, and the compositor's hot corners
    # sit underneath it. Cutting those squares out of the input shape lets the pointer
    # reach them, at the cost of not being able to click the very corners of the note.
    def _apply_input_region(self):
        window = self.get_window()
        if window is None:
            return

        width = self.get_allocated_width()
        height = self.get_allocated_height()
        gap = int(self.config["hot_corner_gap"])

        if gap <= 0:
            window.input_shape_combine_region(None, 0, 0)
            return

        gap = min(gap, width, height // 2)
        region = cairo.Region(cairo.RectangleInt(0, 0, width, height))
        # Only the outer edge touches a screen corner; the inner edge faces the desktop.
        x = width - gap if self.config["side"] == "right" else 0
        region.subtract(cairo.Region(cairo.RectangleInt(x, 0, gap, gap)))
        region.subtract(cairo.Region(cairo.RectangleInt(x, height - gap, gap, gap)))
        window.input_shape_combine_region(region, 0, 0)

    # TOP draws above every window, which is what a dock wants, but also above the shell's
    # own panels, so margin_top and margin_bottom exist to keep an auto-hide panel clear.
    # BOTTOM lets the panels draw over the sidebar instead, at the cost of any window that
    # ignores the exclusive zone -- an already-maximised XWayland window, say -- covering it.
    def _apply_layer(self):
        choice = str(self.config["layer"]).lower()
        if choice not in ("top", "bottom"):
            # BOTTOM while the exclusive zone keeps windows out, since it lets the shell's
            # panels slide over the sidebar on their own. Without a zone, TOP is the only
            # way to stay visible at all.
            choice = "bottom" if self.config["reserve_space"] else "top"
        LayerShell.set_layer(self, LayerShell.Layer.BOTTOM if choice == "bottom"
                             else LayerShell.Layer.TOP)

    def apply_config(self):
        self._apply_anchors()
        self._apply_layer()

        width = max(150, int(self.config["width"]))
        self.set_size_request(width, -1)

        # The exclusive zone is the whole point: the compositor keeps this strip clear,
        # and stacks it against the zones the panels already claim.
        if self.config["reserve_space"]:
            LayerShell.set_exclusive_zone(self, width)
        else:
            LayerShell.set_exclusive_zone(self, 0)

        Gtk.Widget.set_opacity(self, max(0.1, min(1.0, float(self.config["opacity"]))))

        family = "font-family: monospace;" if self.config["monospace"] else ""
        css = "textview, textview text { font-size: %dpt; %s }" % (
            int(self.config["font_size"]), family)
        try:
            self._font_css.load_from_data(css.encode())
        except GLib.Error as error:
            log("could not apply the font: %s" % error.message)

        self.status.set_visible(bool(self.config["show_counter"]))
        self._apply_input_region()
        self._update_counter()
        self._schedule_reload()

    def _open_settings(self, _button):
        if self._settings_window is not None:
            self._settings_window.present()
            return

        def closed(*_args):
            self._settings_window = None

        self._settings_window = SettingsWindow(
            self.get_application(), self.config, self._settings_changed, closed)
        self._settings_window.show_all()

    def _settings_changed(self):
        identity = self.store.identity()
        self.config.save()
        self.apply_config()
        if self.store.identity() != identity:
            self.load_note(force=True)

    # Note contents --------------------------------------------------------------------

    def _text(self):
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, False)

    def load_note(self, force=False):
        self._cancel_save()
        before = self._text()

        def done(text):
            if text is None:
                self._flash("Could not read the note")
                return
            if not force and self._text() != before:
                return
            if text == self._text():
                return
            self._loading = True
            self.buffer.set_text(text)
            self._loading = False
            self._dirty = False
            self._update_counter()

        self.store.load(done)

    def save_note(self, announce=False):
        self._cancel_save()
        text = self._text()

        # Refuse to let an empty buffer overwrite a stored note you never emptied. A
        # startup or shutdown hiccup would otherwise silently destroy the note.
        if not text and not self._edited:
            self._update_counter()
            return

        def done(ok):
            if not ok:
                self._flash("Could not save the note")
                return
            self._dirty = False
            if announce:
                self._flash("Saved")
            else:
                self._update_counter()

        self.store.save(text, done)

    def _cancel_save(self):
        if self._save_source:
            GLib.source_remove(self._save_source)
            self._save_source = 0

    def flush(self):
        """Writes out immediately if a save was still waiting on the autosave delay."""
        if self._save_source:
            self.save_note()

    def _on_changed(self, _buffer):
        if self._loading:
            return
        self._dirty = True
        self._edited = True
        self._update_counter()
        self._cancel_save()

        def autosave():
            self._save_source = 0
            # Autosave announces itself, so a save is never silent while you watch it.
            self.save_note(announce=True)
            return GLib.SOURCE_REMOVE

        self._save_source = GLib.timeout_add(int(self.config["autosave_delay"]), autosave)

    def _schedule_reload(self):
        if self._reload_source:
            GLib.source_remove(self._reload_source)
            self._reload_source = 0
        interval = int(self.config["reload_interval"])
        if interval <= 0:
            return

        def reload():
            if not self.view.has_focus():
                self.load_note()
            return GLib.SOURCE_CONTINUE

        self._reload_source = GLib.timeout_add_seconds(interval, reload)

    # Feedback -------------------------------------------------------------------------

    def _update_counter(self):
        if not self.config["show_counter"] or self._status_source:
            return
        text = self._text()
        words = len(text.split())
        counts = "%d %s, %d characters" % (words, "word" if words == 1 else "words", len(text))
        self.status.set_text(counts + " - unsaved" if self._dirty else counts)

    def _flash(self, message):
        if self._status_source:
            GLib.source_remove(self._status_source)
        self.status.set_visible(True)
        self.status.set_text(message)

        def restore():
            self._status_source = 0
            self.status.set_visible(bool(self.config["show_counter"]))
            self._update_counter()
            return GLib.SOURCE_REMOVE

        self._status_source = GLib.timeout_add(STATUS_MS, restore)

    # Input ----------------------------------------------------------------------------

    def _on_key_press(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        key = Gdk.keyval_name(event.keyval)

        if ctrl and key in ("s", "S"):
            self.save_note(announce=True)
            return True
        # Muffin does not offer the clipboard selection to layer-shell surfaces, so GTK's
        # own cut, copy and paste have nothing to read. wl-clipboard talks to the
        # compositor directly and does.
        if ctrl and key in ("v", "V"):
            self._paste()
            return True
        if ctrl and key in ("c", "C"):
            self._copy()
            return True
        if ctrl and key in ("x", "X"):
            self._copy(cut=True)
            return True
        if key == "Escape":
            # Dropping to NONE and back releases the keyboard to whatever was focused
            # before, while leaving the surface clickable to take it again.
            LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
            LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)
            return True
        return False

    # A menu is its own surface, and the compositor places surfaces parented to a layer
    # shell one as though it were an ordinary window, which lands them off the sidebar
    # entirely. A popover is drawn inside the parent window instead, so it cannot be
    # misplaced. Its actions also route through wl-clipboard, which GTK's menu did not.
    def _on_button_press(self, _widget, event):
        if event.button != 3:
            return False

        popover = Gtk.Popover.new(self.view)
        popover.set_constrain_to(Gtk.PopoverConstraint.WINDOW)
        popover.set_position(Gtk.PositionType.BOTTOM)

        where = Gdk.Rectangle()
        where.x, where.y, where.width, where.height = int(event.x), int(event.y), 1, 1
        popover.set_pointing_to(where)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_border_width(6)
        has_selection = bool(self.buffer.get_selection_bounds())

        def add(label, handler, sensitive):
            button = Gtk.Button(label=label, xalign=0.0)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_sensitive(sensitive)

            def clicked(_b):
                popover.popdown()
                handler()

            button.connect("clicked", clicked)
            box.pack_start(button, False, False, 0)

        add("Cut", lambda: self._copy(cut=True), has_selection)
        add("Copy", lambda: self._copy(), has_selection)
        add("Paste", self._paste, True)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)
        add("Select All", lambda: self.buffer.select_range(*self.buffer.get_bounds()), True)

        popover.add(box)
        popover.connect("closed", lambda p: GLib.idle_add(p.destroy))
        box.show_all()
        popover.popup()
        return True

    def _paste(self):
        def done(ok, text):
            if not ok:
                self._flash("Could not read the clipboard")
                return
            if not text:
                return
            self.buffer.delete_selection(True, True)
            self.buffer.insert_at_cursor(text)

        run_argv(["wl-paste", "--no-newline"], None, done)

    def _copy(self, cut=False):
        bounds = self.buffer.get_selection_bounds()
        if not bounds:
            return
        start, end = bounds
        text = self.buffer.get_text(start, end, False)

        def done(ok, _out):
            if not ok:
                self._flash("Could not reach the clipboard")

        run_argv(["wl-copy"], text, done)
        if cut:
            self.buffer.delete(start, end)

    # Visibility -----------------------------------------------------------------------

    def toggle(self):
        if self.get_visible():
            self.flush()
            self.hide()
        else:
            self.show_all()
            self.status.set_visible(bool(self.config["show_counter"]))
            self.load_note()

    def shutdown(self):
        self.flush()
        self.save_note()
        for source in ("_save_source", "_status_source", "_reload_source"):
            if getattr(self, source):
                GLib.source_remove(getattr(self, source))
                setattr(self, source, 0)


class Application(Gtk.Application):

    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.config = None
        # Distinguishes this process's own launch from a later one asking to be revealed.
        self._first_command_line = True
        self.add_main_option("toggle", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Show or hide the sidebar", None)
        self.add_main_option("show", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Show the sidebar", None)
        self.add_main_option("hide", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Hide the sidebar", None)
        self.add_main_option("settings", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Open the settings window", None)
        self.add_main_option("reload", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Reread the settings file and the note", None)
        self.add_main_option("quit", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Save and exit", None)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        if not LayerShell.is_supported():
            log("this compositor does not support wlr-layer-shell, so the sidebar "
                "cannot dock; a Wayland session is required")
            sys.exit(1)
        self.config = Config()
        self._load_style()
        self.window = Sidebar(self, self.config)
        if not self.config["start_hidden"]:
            self.window.show_all()
            self.window.status.set_visible(bool(self.config["show_counter"]))

    def _load_style(self):
        provider = Gtk.CssProvider()
        style = style_path()
        try:
            provider.load_from_path(style)
        except GLib.Error as error:
            log("could not load %s: %s" % (style, error.message))
            return
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()

        if "quit" in options:
            self.window.shutdown()
            self.quit()
            return 0
        if "settings" in options:
            self.window._open_settings(None)
        elif "toggle" in options:
            self.window.toggle()
        elif "show" in options:
            self.window.show_all()
            self.window.status.set_visible(bool(self.config["show_counter"]))
            self.window.load_note()
        elif "hide" in options:
            self.window.flush()
            self.window.hide()
        elif "reload" in options:
            identity = self.window.store.identity()
            self.config.load()
            self.window.apply_config()
            self.window.load_note(force=self.window.store.identity() != identity)
        else:
            # A launch with no options reveals the sidebar, except for the very first one
            # when start_hidden asked for it to stay out of the way.
            first = self._first_command_line
            if not (first and self.config["start_hidden"]):
                self.activate()
        self._first_command_line = False
        return 0

    def do_activate(self):
        # A second launch reveals the running instance rather than starting another.
        if self.window and not self.window.get_visible():
            self.window.show_all()
            self.window.status.set_visible(bool(self.config["show_counter"]))


def main():
    app = Application()
    try:
        return app.run(sys.argv)
    finally:
        if app.window:
            app.window.shutdown()


if __name__ == "__main__":
    sys.exit(main())
