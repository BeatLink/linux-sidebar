"""The plain fallback editor, used where WebKitGTK is not installed.

It edits the note's source, so an HTML note shows its markup; the point is that the
sidebar still works rather than refusing to start.
"""

from gi.repository import Gdk, GLib, Gtk

from ...util import log


class TextEditor(Gtk.Box):
    """A GtkTextView with the same surface the note plugin drives the rich editor through."""

    def __init__(self, options, callbacks):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.options = options
        self.callbacks = callbacks
        self.ready = True
        self._applying = False

        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_accepts_tab(True)
        for setter in ("set_left_margin", "set_right_margin",
                       "set_top_margin", "set_bottom_margin"):
            getattr(self.view, setter)(8)
        self.buffer = self.view.get_buffer()
        self.buffer.connect("changed", self._on_changed)
        self.view.connect("key-press-event", self._on_key_press)

        self._css = Gtk.CssProvider()
        self.view.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        scroller = Gtk.ScrolledWindow()
        scroller.set_name("note-frame")
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.view)
        self.pack_start(scroller, True, True, 0)
        GLib.idle_add(self._announce_ready)

    def _announce_ready(self):
        """Tells the plugin the editor is usable, on the same footing as the rich one."""
        self.callbacks.get("ready", _ignore)()
        return GLib.SOURCE_REMOVE

    # Contents -------------------------------------------------------------------------------

    def _text(self):
        """Returns the whole buffer."""
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, False)

    def set_data(self, text, _note_format):
        """Replaces the buffer without reporting the replacement as an edit."""
        if text == self._text():
            return
        self._applying = True
        self.buffer.set_text(text or "")
        self._applying = False
        self._report_count()

    def get_data(self, callback):
        """Calls back with the buffer, immediately."""
        callback(self._text())

    def insert(self, text, _mime):
        """Inserts text at the cursor, replacing the selection."""
        self.buffer.delete_selection(True, True)
        self.buffer.insert_at_cursor(text)

    def focus_editor(self):
        """Puts the caret back in the note."""
        self.view.grab_focus()

    def reload_page(self):
        """Does nothing, since there is no page to rebuild."""

    def set_toolbar(self, _mode):
        """Does nothing, since there is no toolbar."""

    def set_theme(self, _css):
        """Applies the configured font, leaving the colours to the GTK theme."""
        family = "monospace" if self.options.get("monospace") else ""
        css = "textview, textview text { font-size: %dpt; %s }" % (
            int(self.options.get("font_size", 11)),
            "font-family: %s;" % family if family else "")
        try:
            self._css.load_from_data(css.encode())
        except GLib.Error as error:
            log("could not apply the font: %s" % error.message)

    # Input ----------------------------------------------------------------------------------

    def _on_changed(self, _buffer):
        """Reports an edit and the new counts."""
        self._report_count()
        if not self._applying:
            self.callbacks.get("change", _ignore)()

    def _report_count(self):
        """Reports the word and character counts."""
        text = self._text()
        self.callbacks.get("count", _ignore)(len(text.split()), len(text))

    def _on_key_press(self, _widget, event):
        """Routes the shortcuts the sidebar owns rather than letting GTK handle them."""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        key = Gdk.keyval_name(event.keyval)
        if key == "Escape":
            self.callbacks.get("escape", _ignore)()
            return True
        if not ctrl:
            return False
        if key in ("s", "S"):
            self.callbacks.get("save", _ignore)()
        elif key in ("v", "V"):
            self.callbacks.get("paste", _ignore)()
        elif key in ("c", "C", "x", "X"):
            bounds = self.buffer.get_selection_bounds()
            if not bounds:
                return True
            text = self.buffer.get_text(bounds[0], bounds[1], False)
            action = "copy" if key in ("c", "C") else "cut"
            self.callbacks.get("clipboard", _ignore)(action, text)
            if action == "cut":
                self.buffer.delete(bounds[0], bounds[1])
        else:
            return False
        return True


def _ignore(*_args):
    """Stands in for a callback the plugin did not provide."""
