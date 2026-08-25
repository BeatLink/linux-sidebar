"""A Trilium note, edited in the sidebar and kept in step with the Trilium side.

It is the note plugin with an ETAPI store behind it: a Trilium text note is HTML and so
is this editor's output, so the same note can be edited from either end.
"""

from gi.repository import GLib

from ...util import log
from ..note import NotePlugin
from .store import TriliumStore

SETTINGS_SPEC = [
    ("Trilium", [
        ("server_url", "Server", "entry", None),
        ("note_id", "Note id", "entry", None),
        ("token", "ETAPI token", "entry", None),
        ("token_command", "Token command, instead of the token", "entry", None),
        ("poll_interval", "Check Trilium every, s", "spin", (0, 3600, 5)),
        ("title_in_header", "Show the note title in the header", "switch", None),
        ("allow_insecure_tls", "Accept an untrusted certificate", "switch", None),
    ]),
    ("Editor", [
        ("toolbar", "Toolbar", "combo",
         [("full", "Full"), ("compact", "Compact"), ("hidden", "Hidden")]),
        ("spellcheck", "Check spelling", "switch", None),
        ("show_counter", "Show the word count", "switch", None),
        ("font_size", "Font size", "spin", (6, 32, 1)),
        ("monospace", "Monospace font", "switch", None),
        ("autosave_delay", "Autosave delay, ms", "spin", (100, 10000, 100)),
    ]),
]


class TriliumPlugin(NotePlugin):
    """One Trilium note, polled so that an edit made in Trilium turns up here on its own."""

    id = "trilium"
    title = "Trilium"
    icon = "accessories-dictionary-symbolic"
    description = "A Trilium note, edited here and kept in step over ETAPI"
    settings_spec = SETTINGS_SPEC
    defaults = {
        "server_url": "http://localhost:37840",
        "note_id": "root",
        "token": "",
        "token_command": "",
        "poll_interval": 15,
        "title_in_header": True,
        "allow_insecure_tls": False,
        "toolbar": "full",
        "spellcheck": True,
        "show_counter": True,
        "font_size": 11,
        "monospace": False,
        "autosave_delay": 1500,
    }

    def __init__(self, host):
        super().__init__(host)
        self.store = TriliumStore(self.settings)

    # The base class polls by rereading the whole note; here the metadata is asked first and
    # the content is only fetched once Trilium has actually moved it on.
    def _schedule_reload(self):
        """Restarts the timer that asks Trilium whether the note has changed."""
        if self._reload_source:
            GLib.source_remove(self._reload_source)
            self._reload_source = 0
        interval = int(self.settings.get("poll_interval", 0))
        if interval <= 0:
            return
        self._reload_source = GLib.timeout_add_seconds(interval, self._poll)

    def _poll(self):
        """Asks Trilium whether the note moved on, and rereads it if it did."""
        if self._dirty or not self._loaded:
            return GLib.SOURCE_CONTINUE

        def done(changed):
            if not changed:
                self._apply_title()
                return
            log("Trilium changed %s, rereading it" % self.store.note_id)
            self.host.flash("Updated from Trilium")
            self.load(force=True)

        self.store.poll(done)
        return GLib.SOURCE_CONTINUE

    def load(self, force=False):
        """Rereads the note and puts Trilium's title in the section header."""
        super().load(force=force)
        GLib.idle_add(self._apply_title)

    def _apply_title(self):
        """Puts the note's Trilium title in the section header, unless it was turned off."""
        if self.settings.get("title_in_header") and self.store.title:
            self.host.set_title(self.store.title)
        return GLib.SOURCE_REMOVE

    def settings_changed(self):
        """Applies the edited settings, dropping the cached revision so the next poll is fresh."""
        self.store.revision = None
        super().settings_changed()


PLUGIN = TriliumPlugin
