"""A rich note, edited in CKEditor 5 and kept in a file or in whatever a pair of commands reaches."""

from gi.repository import GLib, Gtk

from ...util import log
from ..api import SidebarPlugin
from . import theme, webview
from .store import NoteStore
from .textview import TextEditor

SETTINGS_SPEC = [
    ("Note", [
        ("note_format", "Store the note as", "combo",
         [("html", "HTML"), ("markdown", "Markdown")]),
        ("toolbar", "Toolbar", "combo",
         [("full", "Full"), ("compact", "Compact"), ("hidden", "Hidden")]),
        ("spellcheck", "Check spelling", "switch", None),
        ("show_counter", "Show the word count", "switch", None),
        ("font_size", "Font size", "spin", (6, 32, 1)),
        ("monospace", "Monospace font", "switch", None),
    ]),
    ("Storage", [
        ("storage_backend", "Keep the note in", "combo",
         [("file", "A file"), ("command", "Custom commands")]),
        ("storage_file", "Note file", "entry", None),
        ("read_command", "Read command", "entry", None),
        ("write_command", "Write command", "entry", None),
        ("autosave_delay", "Autosave delay, ms", "spin", (100, 10000, 100)),
        ("reload_interval", "Reread interval, s", "spin", (0, 3600, 10)),
    ]),
]


class NotePlugin(SidebarPlugin):
    """One note: an editor, a store behind it, and the autosave that joins them."""

    id = "note"
    title = "Note"
    icon = "accessories-text-editor-symbolic"
    description = "A rich text note, edited in CKEditor and saved as you type"
    expands = True
    settings_spec = SETTINGS_SPEC
    defaults = {
        "note_format": "html",
        "toolbar": "full",
        "spellcheck": True,
        "show_counter": True,
        "font_size": 11,
        "monospace": False,
        "storage_backend": "file",
        "storage_file": "",
        "read_command": "",
        "write_command": "",
        "autosave_delay": 800,
        "reload_interval": 0,
    }

    def __init__(self, host):
        super().__init__(host)
        self.store = NoteStore(self.settings, host.instance_id)
        self.editor = None
        self._dirty = False
        # Set once the stored note has reached the editor; until then an edit cannot be
        # genuine and a save would write an empty note over whatever the store holds.
        self._loaded = False
        self._edited = False
        self._save_source = 0
        self._reload_source = 0
        self._counts = (0, 0)

    # Building -------------------------------------------------------------------------------

    def build(self):
        """Builds the editor, falling back to a plain text view where WebKitGTK is missing."""
        callbacks = {
            "ready": self._on_ready,
            "change": self._on_change,
            "count": self._on_count,
            "save": lambda: self.save(announce=True),
            "escape": self.host.release_keyboard,
            "paste": self._paste,
            "clipboard": self._copy,
            "error": self._on_error,
        }
        if webview.available():
            self.editor = webview.WebEditor(self._editor_options(), callbacks)
        else:
            log("WebKitGTK is not installed, so the note falls back to a plain text view")
            self.editor = TextEditor(self._editor_options(), callbacks)
        self.editor.set_size_request(-1, 180)
        return self.editor

    def _editor_options(self):
        """Returns the options the editor page is built from."""
        return {
            "format": self.store.format,
            "toolbar": str(self.settings.get("toolbar", "full")),
            "spellcheck": bool(self.settings.get("spellcheck")),
            "monospace": bool(self.settings.get("monospace")),
            "font_size": int(self.settings.get("font_size", 11)),
            "placeholder": "Write something",
            "theme_css": self._theme_css(),
        }

    def _theme_css(self):
        """Returns the CSS variables that paint the editor in the desktop's colours."""
        family = "monospace" if self.settings.get("monospace") else theme.default_font()
        return theme.theme_css(self.editor or Gtk.Label(), family,
                               self.settings.get("font_size", 11), "monospace")

    def start(self):
        """Starts the reread timer once the section is in place."""
        self._schedule_reload()

    def _on_ready(self):
        """Loads the note as soon as the editor can accept it."""
        self.editor.set_theme(self._theme_css())
        self.load(force=True)

    def _on_error(self, message):
        """Reports an editor that could not start."""
        self.host.set_status("Editor failed: %s" % message)

    # Contents -------------------------------------------------------------------------------

    def load(self, force=False):
        """Rereads the note from the store and puts it in the editor."""
        self._cancel_save()

        def done(text):
            if text is None:
                self.host.flash("Could not read the note")
                return
            if not force and self._dirty:
                return
            self._edited = False
            self.editor.set_data(text, self.store.format)
            self._loaded = True
            self._dirty = False
            self._update_status()

        self.store.load(done)

    def save(self, announce=False):
        """Writes the note out, unless the editor has nothing that was ever typed into it."""
        self._cancel_save()
        if self.editor is None or not self.editor.ready or not self._loaded:
            return

        def store(text):
            # An empty editor that was never edited means the note never loaded, and
            # writing it back would destroy whatever the store actually holds.
            if text is None or (not text.strip() and not self._edited):
                return
            self.store.save(text, done)

        def done(ok):
            if not ok:
                self.host.flash("Could not save the note")
                return
            self._dirty = False
            if announce:
                self.host.flash("Saved")
            else:
                self._update_status()

        self.editor.get_data(store)

    def flush(self):
        """Writes out immediately if a save was still waiting on the autosave delay."""
        if self._save_source:
            self.save()

    def reload(self):
        """Rereads the note, leaving unsaved edits alone."""
        self.load()

    def _on_change(self):
        """Marks the note dirty and restarts the autosave timer."""
        if not self._loaded:
            return
        self._dirty = True
        self._edited = True
        self._update_status()
        self._cancel_save()

        def autosave():
            self._save_source = 0
            self.save(announce=True)
            return GLib.SOURCE_REMOVE

        self._save_source = GLib.timeout_add(int(self.settings.get("autosave_delay", 800)),
                                             autosave)

    def _cancel_save(self):
        """Drops a pending autosave."""
        if self._save_source:
            GLib.source_remove(self._save_source)
            self._save_source = 0

    def _schedule_reload(self):
        """Restarts the timer that rereads the store, or stops it when the interval is zero."""
        if self._reload_source:
            GLib.source_remove(self._reload_source)
            self._reload_source = 0
        interval = int(self.settings.get("reload_interval", 0))
        if interval <= 0:
            return

        def poll():
            if not self._dirty:
                self.load()
            return GLib.SOURCE_CONTINUE

        self._reload_source = GLib.timeout_add_seconds(interval, poll)

    # Feedback -------------------------------------------------------------------------------

    def _on_count(self, words, characters):
        """Records the counts the editor reported and puts them in the footer."""
        self._counts = (words, characters)
        self._update_status()

    def _update_status(self):
        """Writes the word count, and whether there is an unsaved edit, into the footer."""
        if not self.settings.get("show_counter"):
            self.host.set_status("")
            return
        words, characters = self._counts
        text = "%d %s, %d characters" % (words, "word" if words == 1 else "words", characters)
        self.host.set_status(text + " - unsaved" if self._dirty else text)

    # Clipboard ------------------------------------------------------------------------------

    def _copy(self, _action, text):
        """Puts the selection on the clipboard; the editor has already cut it if it needed to."""
        if text:
            self.host.clipboard.write(text)

    def _paste(self):
        """Reads the clipboard and inserts it, as HTML where the note can hold it."""
        def insert(mime, text):
            if not text:
                return
            self.editor.insert(text, mime if self.store.format == "html" else "text/plain")

        self.host.clipboard.read_rich(insert,
                                      plain_only=self.store.format == "markdown")

    # Settings -------------------------------------------------------------------------------

    def settings_changed(self):
        """Applies the edited settings, rebuilding the editor when its format changed."""
        options = self._editor_options()
        rebuilt = options["format"] != self.editor.options.get("format")
        self.editor.options = options
        self._schedule_reload()
        self._update_status()
        if rebuilt:
            # The rebuilt page loads the note itself, once it reports that it is ready.
            self.flush()
            self._loaded = False
            self.editor.reload_page()
            return
        self.editor.set_theme(self._theme_css())
        self.editor.set_toolbar(options["toolbar"])
        self.load(force=True)

    def stop(self):
        """Drops the timers this instance is holding."""
        self._cancel_save()
        if self._reload_source:
            GLib.source_remove(self._reload_source)
            self._reload_source = 0


PLUGIN = NotePlugin
