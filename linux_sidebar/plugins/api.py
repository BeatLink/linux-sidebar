"""What a sidebar plugin is, and what the sidebar gives it to work with.

A plugin is a class deriving from SidebarPlugin in a module that names it PLUGIN. One
instance is created per slot in the layout, each with its own persisted settings.
"""


class PluginHost:
    """The handle a plugin instance uses to talk back to the sidebar it is living in."""

    def __init__(self, sidebar, instance, plugin):
        self.sidebar = sidebar
        self.instance = instance
        self.plugin = plugin

    @property
    def settings(self):
        """Returns this instance's own persisted settings."""
        return self.instance["settings"]

    @property
    def clipboard(self):
        """Returns the sidebar's clipboard, which is set up for the docking backend in use."""
        return self.sidebar.clipboard

    @property
    def instance_id(self):
        """Returns the identifier this instance has in the layout."""
        return self.instance["id"]

    def save_settings(self):
        """Writes the settings file after this instance's settings have changed."""
        self.sidebar.config.save()

    def set_status(self, text):
        """Puts a persistent line in the sidebar's footer, or clears it with an empty string."""
        self.sidebar.set_plugin_status(self.instance["id"], text)

    def flash(self, text):
        """Shows a message in the footer for a moment, then restores the status line."""
        self.sidebar.flash(text)

    def set_title(self, text):
        """Changes the title shown in this instance's section header."""
        self.sidebar.set_section_title(self.instance["id"], text)

    def release_keyboard(self):
        """Hands the keyboard back to the window underneath the sidebar."""
        self.sidebar.release_keyboard()


class SidebarPlugin:
    """A thing that can occupy a section of a sidebar tab."""

    # Identity, overridden by every plugin.
    id = ""
    title = "Plugin"
    icon = "application-x-executable-symbolic"
    description = ""

    # Whether the section should take the space left over in its tab rather than its own height.
    expands = False

    # The settings this plugin adds, in the same (key, label, kind, detail) shape the sidebar uses.
    settings_spec = []
    defaults = {}

    def __init__(self, host):
        self.host = host
        for key, value in self.defaults.items():
            self.host.settings.setdefault(key, value)

    @property
    def settings(self):
        """Returns this instance's settings."""
        return self.host.settings

    def build(self):
        """Returns the widget for this instance's section."""
        raise NotImplementedError

    def start(self):
        """Runs once the section has been added to a tab."""

    def settings_changed(self):
        """Runs after any of this instance's settings have been edited."""

    def flush(self):
        """Writes out anything still pending, before hiding or exiting."""

    def reload(self):
        """Rereads whatever the plugin is showing."""

    def header_widget(self):
        """Returns a widget for the right of the section header, or None."""
        return None

    def stop(self):
        """Releases timers and other resources when the instance goes away."""
