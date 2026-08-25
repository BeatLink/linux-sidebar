"""Reads and writes the clipboard, through GTK where that works and through a helper where it does not.

Some compositors do not offer the clipboard selection to a docked layer-shell surface, so
GTK's own clipboard finds nothing there and an external helper has to be used instead.
"""

from gi.repository import Gdk, Gtk

from . import desktop
from .util import have, log, run_argv, spawn_with_stdin

HTML = "text/html"
PLAIN = "text/plain"


class Clipboard:
    """The clipboard, reached through whichever helper this session actually supports."""

    def __init__(self, prefer_external=False):
        self.prefer_external = prefer_external

    def backends(self):
        """Returns the helper names to try in order, ending with GTK's own clipboard."""
        external = []
        if desktop.has_x_server() and have("xclip"):
            external.append("xclip")
        if have("wl-copy") and have("wl-paste"):
            external.append("wl-clipboard")
        if self.prefer_external:
            return external + ["gtk"]
        return ["gtk"] + external

    def describe(self):
        """Returns the name of the helper that will actually be used."""
        return self.backends()[0]

    # Reading --------------------------------------------------------------------------------

    def read(self, callback):
        """Calls back with the clipboard as plain text, or with an empty string."""
        self.read_rich(lambda _mime, text: callback(text), plain_only=True)

    def read_rich(self, callback, plain_only=False):
        """Calls back with (mime type, text), preferring HTML unless plain text was asked for."""
        order = list(self.backends())

        def attempt():
            if not order:
                callback(PLAIN, "")
                return
            backend = order.pop(0)
            reader = getattr(self, "_read_" + backend.replace("-", "_"))
            reader(done, plain_only)

        def done(mime, text):
            if text:
                callback(mime, text)
                return
            attempt()

        attempt()

    def _read_gtk(self, callback, plain_only):
        """Reads through GTK, which works everywhere the surface is offered the selection."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        def plain():
            clipboard.request_text(lambda _c, text, _d: callback(PLAIN, text or ""), None)

        if plain_only:
            plain()
            return

        def got_html(_clipboard, selection, _data):
            text = ""
            if selection is not None and selection.get_length() > 0:
                text = (selection.get_data() or b"").decode("utf-8", "replace")
            if text:
                callback(HTML, text)
            else:
                plain()

        clipboard.request_contents(Gdk.Atom.intern(HTML, False), got_html, None)

    def _read_xclip(self, callback, plain_only):
        """Reads through xclip, which reaches the X selection the compositor bridges."""
        def plain():
            run_argv(["xclip", "-o", "-selection", "clipboard"], None,
                     lambda ok, out: callback(PLAIN, out if ok else ""))

        if plain_only:
            plain()
            return

        def got_html(ok, out):
            if ok and out.strip():
                callback(HTML, out)
            else:
                plain()

        run_argv(["xclip", "-o", "-selection", "clipboard", "-t", HTML], None, got_html)

    # wl-paste opens a surface and takes the keyboard to read the selection where the
    # compositor implements no data-control protocol, which hands focus to the window below.
    def _read_wl_clipboard(self, callback, plain_only):
        """Reads through wl-paste, which talks to the compositor directly."""
        def plain():
            run_argv(["wl-paste", "--no-newline"], None,
                     lambda ok, out: callback(PLAIN, out if ok else ""))

        if plain_only:
            plain()
            return

        def got_html(ok, out):
            if ok and out.strip():
                callback(HTML, out)
            else:
                plain()

        run_argv(["wl-paste", "--no-newline", "--type", HTML], None, got_html)

    # Writing --------------------------------------------------------------------------------

    def write(self, text):
        """Puts text on the clipboard through the first helper that accepts it."""
        for backend in self.backends():
            if backend == "gtk":
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
                return True
            if backend == "xclip":
                if spawn_with_stdin(["xclip", "-i", "-selection", "clipboard"], text):
                    return True
            if backend == "wl-clipboard":
                if spawn_with_stdin(["wl-copy"], text):
                    return True
        log("no clipboard helper could be reached")
        return False
