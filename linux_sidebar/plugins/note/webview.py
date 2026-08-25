"""Hosts CKEditor 5 in a WebKitGTK view and bridges it to the sidebar.

Everything crosses the boundary as a JSON message the page posts, and as calls into the
small set of functions the page hangs on window.
"""

import json
import os

import gi

from ...util import data_path, log

WebKit = None
# WebKit 6.0 is the GTK 4 build, so only the GTK 3 namespace is any use here.
for _version in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", _version)
        from gi.repository import WebKit2 as WebKit
        break
    except (ImportError, ValueError):
        continue

from gi.repository import Gdk, GLib, Gtk

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def available():
    """Reports whether WebKitGTK is installed, which the rich editor needs."""
    return WebKit is not None


class WebEditor(Gtk.Box):
    """The CKEditor instance, wrapped as a widget the note plugin can put in its section."""

    def __init__(self, options, callbacks):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.options = options
        self.callbacks = callbacks
        self.ready = False
        self._requests = {}
        self._next_request = 1
        self._pending_data = None

        manager = WebKit.UserContentManager()
        manager.register_script_message_handler("sidebar")
        manager.connect("script-message-received::sidebar", self._on_message)

        self.view = WebKit.WebView.new_with_user_content_manager(manager)
        self.view.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        self.view.connect("context-menu", lambda *_: True)
        self.view.connect("decide-policy", self._on_policy)
        self.pack_start(self.view, True, True, 0)
        self._configure()
        self.reload_page()

    def _configure(self):
        """Turns off everything a local note editor has no use for."""
        settings = self.view.get_settings()
        settings.set_enable_developer_extras(bool(os.environ.get("LINUX_SIDEBAR_INSPECTOR")))
        settings.set_enable_write_console_messages_to_stdout(True)
        settings.set_enable_page_cache(False)
        settings.set_enable_html5_database(False)
        settings.set_enable_html5_local_storage(False)
        settings.set_javascript_can_open_windows_automatically(False)
        settings.set_enable_tabs_to_links(False)
        context = self.view.get_context()
        context.set_spell_checking_enabled(bool(self.options.get("spellcheck")))
        if self.options.get("spellcheck"):
            context.set_spell_checking_languages([_language()])

    # Loading --------------------------------------------------------------------------------

    def reload_page(self):
        """Rebuilds the page, which is how a change of format or toolbar takes effect."""
        self.ready = False
        with open(os.path.join(ASSETS, "editor.html")) as handle:
            html = handle.read()
        replacements = {
            "__CKEDITOR_CSS__": _url(data_path("vendor", "ckeditor5", "ckeditor5.css")),
            "__CKEDITOR_JS__": _url(data_path("vendor", "ckeditor5", "ckeditor5.umd.js")),
            "__EDITOR_CSS__": _url(os.path.join(ASSETS, "editor.css")),
            "__EDITOR_JS__": _url(os.path.join(ASSETS, "editor.js")),
            "__OPTIONS__": json.dumps(self.options),
            "__THEME__": self.options.get("theme_css", ""),
        }
        for token, value in replacements.items():
            html = html.replace(token, value)
        self.view.load_html(html, "file://%s/" % ASSETS)

    # Bridge ---------------------------------------------------------------------------------

    def _run(self, script):
        """Runs a snippet in the page, through whichever call this WebKit provides."""
        if hasattr(self.view, "evaluate_javascript"):
            self.view.evaluate_javascript(script, -1, None, None, None, None, None)
        else:
            self.view.run_javascript(script, None, None, None)

    def set_data(self, text, note_format):
        """Puts a note into the editor, holding it back until the page is ready."""
        if not self.ready:
            self._pending_data = (text, note_format)
            return
        self._run("window.sidebarSetData(%s, %s);"
                  % (json.dumps(text or ""), json.dumps(note_format)))

    def get_data(self, callback):
        """Asks the page for the note and calls back with it."""
        if not self.ready:
            callback(None)
            return
        request = self._next_request
        self._next_request += 1
        self._requests[request] = callback
        self._run("window.sidebarGetData(%d);" % request)

    def insert(self, text, mime):
        """Inserts text at the cursor, as HTML when the clipboard offered it."""
        self._run("window.sidebarInsert(%s, %s);" % (json.dumps(text), json.dumps(mime)))

    def set_theme(self, css):
        """Repaints the page in the desktop's current colours and font."""
        self.options["theme_css"] = css
        if self.ready:
            self._run("window.sidebarSetTheme(%s);" % json.dumps(css))

    def set_toolbar(self, mode):
        """Shows or hides the toolbar without rebuilding the editor."""
        self.options["toolbar"] = mode
        if self.ready:
            self._run("window.sidebarSetToolbar(%s);" % json.dumps(mode))

    def focus_editor(self):
        """Puts the caret back in the note."""
        if self.ready:
            self._run("window.sidebarFocus();")

    # Messages -------------------------------------------------------------------------------

    def _on_message(self, _manager, result):
        """Dispatches a message the page posted to the matching callback."""
        try:
            raw = result.to_string() if hasattr(result, "to_string") else \
                result.get_js_value().to_string()
            message = json.loads(raw)
        except (AttributeError, ValueError) as error:
            log("could not read a message from the editor: %s" % error)
            return

        kind = message.get("type")
        if kind == "ready":
            self.ready = True
            self.set_theme(self.options.get("theme_css", ""))
            if self._pending_data is not None:
                self.set_data(*self._pending_data)
                self._pending_data = None
            self.callbacks.get("ready", _ignore)()
        elif kind == "data":
            callback = self._requests.pop(message.get("id"), None)
            if callback is not None:
                callback(message.get("value", ""))
        elif kind == "count":
            self.callbacks.get("count", _ignore)(message.get("words", 0),
                                                 message.get("characters", 0))
        elif kind == "change":
            self.callbacks.get("change", _ignore)()
        elif kind == "save":
            self.callbacks.get("save", _ignore)()
        elif kind == "escape":
            self.callbacks.get("escape", _ignore)()
        elif kind == "paste":
            self.callbacks.get("paste", _ignore)()
        elif kind == "clipboard":
            self.callbacks.get("clipboard", _ignore)(message.get("action"),
                                                     message.get("text", ""))
        elif kind == "error":
            log("the editor failed to start: %s" % message.get("message"))
            self.callbacks.get("error", _ignore)(message.get("message", ""))

    # A link the note holds belongs in the browser, not in this two-hundred-pixel view.
    def _on_policy(self, _view, decision, kind):
        """Sends any navigation away from the editor page to the desktop's own handler."""
        if kind != WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        action = decision.get_navigation_action()
        if action.get_navigation_type() != WebKit.NavigationType.LINK_CLICKED:
            return False
        uri = action.get_request().get_uri()
        decision.ignore()
        try:
            Gtk.show_uri_on_window(self.get_toplevel(), uri, Gdk.CURRENT_TIME)
        except GLib.Error as error:
            log("could not open %s: %s" % (uri, error.message))
        return True


def _url(path):
    """Turns an absolute path into a file URL the page can load."""
    return "file://" + GLib.uri_escape_string(path, "/", False)


def _language():
    """Returns the spell checking language, taken from the session's locale."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value and value not in ("C", "POSIX"):
            return value.split(".")[0]
    return "en_US"


def _ignore(*_args):
    """Stands in for a callback the plugin did not provide."""
