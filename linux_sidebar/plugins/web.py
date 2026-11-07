"""Shows a web page in the sidebar, such as an X-Tasks server or any other web app.

Each instance keeps its own cookies and site data, so a page it has signed into stays signed in,
and the page is handed the sidebar's colours as CSS variables it can choose to follow.
"""

import os
from urllib.parse import urlsplit

from gi.repository import Gdk, GLib, Gtk

from .. import APP_NAME
from ..util import log
from .api import SidebarPlugin
from .note import theme
from .note.webview import WebKit, available

DATA_DIR = os.path.join(GLib.get_user_data_dir(), APP_NAME, "web")
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), APP_NAME, "web")
RETRY_SECONDS = 30


class WebPlugin(SidebarPlugin):
    """One web page, with its own signed-in session."""

    id = "web"
    title = "Web page"
    icon = "web-browser-symbolic"
    description = "A web page, such as an X-Tasks server, that stays signed in"
    settings_spec = [
        ("Page", [
            ("url", "Address", "entry", None),
            ("zoom", "Zoom, %", "spin", (30, 300, 10)),
            ("expands", "Fill the tab", "switch", None),
            ("height", "Height when not filling the tab", "spin", (100, 2000, 20)),
            ("match_theme", "Offer the page the sidebar's colours", "switch", None),
            ("open_links_outside", "Open other sites in the browser", "switch", None),
            ("allow_insecure_tls", "Accept an untrusted certificate from this address", "switch",
             None),
        ]),
    ]
    defaults = {
        "url": "",
        "zoom": 100,
        "expands": True,
        "height": 400,
        "match_theme": True,
        "open_links_outside": True,
        "allow_insecure_tls": False,
    }

    def __init__(self, host):
        super().__init__(host)
        self.expands = bool(self.settings.get("expands"))
        self.view = None
        self._loaded_url = ""
        self._matched_theme = False
        self._refused_uri = ""
        self._trusted_hosts = set()
        self._retry_source = 0

    # Building -------------------------------------------------------------------------------

    def build(self):
        """Builds the web view, or a note saying why there is none."""
        if not available():
            label = Gtk.Label(label="Showing a web page needs WebKitGTK, which is not installed.")
            label.set_line_wrap(True)
            return label

        folder = os.path.join(DATA_DIR, self.host.instance_id)
        manager = WebKit.WebsiteDataManager(
            base_data_directory=folder,
            base_cache_directory=os.path.join(CACHE_DIR, self.host.instance_id))
        os.makedirs(folder, exist_ok=True)
        manager.get_cookie_manager().set_persistent_storage(
            os.path.join(folder, "cookies.sqlite"), WebKit.CookiePersistentStorage.SQLITE)
        self.context = WebKit.WebContext.new_with_website_data_manager(manager)
        self.content = WebKit.UserContentManager()

        self.view = WebKit.WebView(web_context=self.context, user_content_manager=self.content)
        settings = self.view.get_settings()
        settings.set_enable_developer_extras(bool(os.environ.get("LINUX_SIDEBAR_INSPECTOR")))
        settings.set_javascript_can_open_windows_automatically(False)
        self.view.connect("decide-policy", self._on_policy)
        self.view.connect("create", self._on_new_window)
        self.view.connect("load-changed", self._on_load_changed)
        self.view.connect("load-failed", self._on_load_failed)
        self.view.connect("load-failed-with-tls-errors", self._on_tls_errors)
        self.view.connect("style-updated", lambda _v: self._apply_theme())
        self._apply_size()
        return self.view

    def header_widget(self):
        """Returns the button in the header that reloads the page."""
        if self.view is None:
            return None
        button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.MENU)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text("Reload")
        button.connect("clicked", lambda _b: self.reload())
        return button

    def start(self):
        """Loads the page."""
        if self.view is None:
            return
        self._apply_theme()
        self._load()

    # Settings -------------------------------------------------------------------------------

    def settings_changed(self):
        """Applies new settings, loading the page again only when its address changed."""
        self.expands = bool(self.settings.get("expands"))
        if self.view is None:
            return
        self._apply_size()
        self._apply_theme()
        # A page decides once, as it loads, whether to follow the colours, so a change needs a reload.
        matching = bool(self.settings.get("match_theme"))
        if self._address() != self._loaded_url or matching != self._matched_theme:
            self._load()

    def _address(self):
        """Returns the configured address, with a scheme added when it was left off."""
        url = (self.settings.get("url") or "").strip()
        if url and "://" not in url:
            url = "https://" + url
        return url

    def _apply_size(self):
        """Sets the zoom, and the height the section asks for when it does not fill the tab."""
        self.view.set_zoom_level(max(30, int(self.settings.get("zoom") or 100)) / 100)
        height = -1 if self.expands else int(self.settings.get("height") or 400)
        self.view.set_size_request(-1, height)

    # Themes ---------------------------------------------------------------------------------

    # The variables are the same ones the note editor is painted from, so one page can serve both.
    def _apply_theme(self):
        """Hands the page the sidebar's current colours and font as CSS variables."""
        self.content.remove_all_style_sheets()
        if not self.settings.get("match_theme"):
            return
        css = theme.theme_css(self.view, theme.default_font(), 11, "monospace")
        css += " :root { --sidebar-color-scheme: %s; }" % _colour_scheme(self.view)
        self.content.add_style_sheet(WebKit.UserStyleSheet(
            css, WebKit.UserContentInjectedFrames.TOP_FRAME, WebKit.UserStyleLevel.USER,
            None, None))

    # Loading --------------------------------------------------------------------------------

    def _load(self):
        """Opens the configured address, or says there is none yet."""
        self._cancel_retry()
        self._loaded_url = self._address()
        self._matched_theme = bool(self.settings.get("match_theme"))
        self._refused_uri = ""
        if not self._loaded_url:
            self.host.set_status("Set an address for the web page in its settings")
            self.view.load_html("", None)
            return
        self.view.load_uri(self._loaded_url)

    def reload(self):
        """Loads the page again, from the configured address if the last load failed."""
        if self.view is None:
            return
        if self.view.get_uri() and not self._retry_source:
            self.view.reload()
        else:
            self._load()

    def _on_load_changed(self, _view, event):
        """Clears an earlier error once a page has loaded."""
        if event == WebKit.LoadEvent.FINISHED and not self._retry_source and not self._refused_uri:
            self.host.set_status("")

    # A sidebar often starts before the network is up, so a failed page keeps trying by itself.
    def _on_load_failed(self, _view, _event, uri, error):
        """Reports a page that did not load and tries it again later."""
        if error.matches(WebKit.NetworkError.quark(), WebKit.NetworkError.CANCELLED):
            return False
        if error.matches(WebKit.PolicyError.quark(),
                         WebKit.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE):
            return False
        log("could not load %s: %s" % (uri, error.message))
        if uri == self._refused_uri:
            return False
        self.host.set_status("Could not load %s, retrying" % _host(uri))
        self._schedule_retry()
        return False

    def _schedule_retry(self):
        """Loads the configured address again after a pause."""
        self._cancel_retry()

        def retry():
            self._retry_source = 0
            self._load()
            return GLib.SOURCE_REMOVE

        self._retry_source = GLib.timeout_add_seconds(RETRY_SECONDS, retry)

    def _cancel_retry(self):
        """Drops a pending retry."""
        if self._retry_source:
            GLib.source_remove(self._retry_source)
            self._retry_source = 0

    # Only the configured host is trusted, so a link to elsewhere still gets WebKit's warning.
    def _on_tls_errors(self, view, uri, certificate, _errors):
        """Accepts an untrusted certificate from the configured host when the settings allow it."""
        host = _host(uri)
        allowed = bool(self.settings.get("allow_insecure_tls"))
        if not allowed or host != _host(self._loaded_url) or host in self._trusted_hosts:
            self._refused_uri = uri
            self.host.set_status("%s has a certificate that is not trusted" % host)
            return False
        self._trusted_hosts.add(host)
        self.context.allow_tls_certificate_for_host(certificate, host)
        view.load_uri(uri)
        return True

    # Links ----------------------------------------------------------------------------------

    def _on_policy(self, _view, decision, kind):
        """Sends a clicked link to another site to the desktop's browser."""
        if kind != WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        if not self.settings.get("open_links_outside"):
            return False
        action = decision.get_navigation_action()
        if action.get_navigation_type() != WebKit.NavigationType.LINK_CLICKED:
            return False
        uri = action.get_request().get_uri()
        if _origin(uri) == _origin(self._loaded_url):
            return False
        decision.ignore()
        self._open_outside(uri)
        return True

    def _on_new_window(self, _view, action):
        """Opens a link meant for a new window in the desktop's browser instead."""
        self._open_outside(action.get_request().get_uri())
        return None

    def _open_outside(self, uri):
        """Hands an address to the desktop's own handler."""
        try:
            Gtk.show_uri_on_window(self.view.get_toplevel(), uri, Gdk.CURRENT_TIME)
        except GLib.Error as error:
            log("could not open %s: %s" % (uri, error.message))

    def stop(self):
        """Stops retrying."""
        self._cancel_retry()


def _colour_scheme(widget):
    """Returns dark or light, from how bright the sidebar's background is."""
    found, background = widget.get_style_context().lookup_color("sidebar_bg")
    if not found:
        return "light dark"
    brightness = 0.2126 * background.red + 0.7152 * background.green + 0.0722 * background.blue
    return "dark" if brightness < 0.5 else "light"


def _host(url):
    """Returns the host name in an address, or an empty string."""
    return urlsplit(url or "").hostname or ""


def _origin(url):
    """Returns the scheme, host and port of an address."""
    parts = urlsplit(url or "")
    return (parts.scheme, parts.hostname, parts.port)


PLUGIN = WebPlugin
