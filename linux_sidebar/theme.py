"""The sidebar's palette, taken either from the desktop shell's theme or from the GTK theme."""

import os
import re

from gi.repository import Gdk, Gio, GLib

from .util import log

# The colours style.css and the note editor are painted from. Each entry is
# (name, shell selector, shell property, GTK theme colour).
PALETTE = [
    ("sidebar_bg", "#panel", "background-color", "@theme_bg_color"),
    ("sidebar_fg", "#panel", "color", "@theme_fg_color"),
    ("sidebar_base", ".popup-menu-content", "background-color", "@theme_base_color"),
    ("sidebar_selected_bg", ".popup-menu-item:active", "background-color",
     "@theme_selected_bg_color"),
    ("sidebar_selected_fg", ".popup-menu-item:active", "color", "@theme_selected_fg_color"),
]

# Shades of the foreground, so a theme that gives no hover colour of its own still gets one
# that belongs with the rest of the palette.
DERIVED = [
    ("sidebar_hover", "alpha(@sidebar_fg, 0.1)"),
    ("sidebar_active", "alpha(@sidebar_fg, 0.14)"),
    ("sidebar_border", "alpha(@sidebar_fg, 0.2)"),
]

# Where a shell keeps its stylesheet: the desktop it belongs to, the settings schema and key
# naming the theme, the theme's subdirectory, and the built-in stylesheet used when no theme
# is chosen.
SHELLS = [
    ("cinnamon", "org.cinnamon.theme", "name",
     os.path.join("cinnamon", "cinnamon.css"), os.path.join("cinnamon", "theme", "cinnamon.css")),
    ("gnome", "org.gnome.shell.extensions.user-theme", "name",
     os.path.join("gnome-shell", "gnome-shell.css"), None),
]

# A theme of this name is the shell's own built-in one rather than a directory to read.
BUILT_IN = ("", "cinnamon", "default", "adwaita")

# The last thing said about where the colours came from, so rereading the settings is quiet.
_said = None


def palette_css(source):
    """Returns the block of @define-color rules the stylesheet and the note editor read."""
    shell = {} if source == "gtk" else shell_palette()
    if source == "shell" and not shell:
        _say("no desktop shell theme to read, falling back to the GTK theme")
    lines = ["@define-color %s %s;" % (name, shell.get(name, fallback))
             for name, _selector, _property, fallback in PALETTE]
    lines += ["@define-color %s %s;" % (name, value) for name, value in DERIVED]
    return "\n".join(lines) + "\n"


def shell_palette():
    """Returns the colours read out of the running shell's theme, empty if there are none."""
    path = shell_stylesheet()
    if path is None:
        return {}
    try:
        with open(path) as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        log("could not read %s: %s" % (path, error))
        return {}
    rules = _rules(text)
    found = {}
    for name, selector, prop, _fallback in PALETTE:
        value = rules.get((selector, prop))
        if value is not None:
            found[name] = value
    if found:
        _say("colours taken from %s" % path)
    return found


def shell_stylesheet():
    """Returns the path of the running shell's stylesheet, or None if there is none to read."""
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    for shell, schema, key, subpath, built_in in SHELLS:
        if shell not in desktop:
            continue
        name = _setting(schema, key)
        if name.lower() not in BUILT_IN:
            path = _find_theme(name, subpath)
            if path is not None:
                return path
            _say("the %s theme %s has no stylesheet" % (shell, name))
        return _find_data(built_in) if built_in else None
    return None


def _say(message):
    """Logs a message about the palette, unless it is the one already logged."""
    global _said
    if message != _said:
        _said = message
        log(message)


def _setting(schema, key):
    """Returns a string setting, or an empty string if the schema is not installed."""
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(schema, True) is None:
        return ""
    return Gio.Settings.new(schema).get_string(key) or ""


def _find_theme(name, subpath):
    """Returns the path of a named theme's stylesheet, or None if no theme directory holds it."""
    roots = [os.path.expanduser("~/.themes"), os.path.join(GLib.get_user_data_dir(), "themes")]
    roots += [os.path.join(root, "themes") for root in GLib.get_system_data_dirs()]
    return _first(os.path.join(root, name, subpath) for root in roots)


def _find_data(relative):
    """Returns the path of a file under the first data directory holding it, or None."""
    roots = [GLib.get_user_data_dir()] + list(GLib.get_system_data_dirs())
    return _first(os.path.join(root, relative) for root in roots)


def _first(paths):
    """Returns the first path that exists, or None."""
    return next((path for path in paths if os.path.exists(path)), None)


# The shell's stylesheet is not GTK CSS, so only the handful of colours above are taken from
# it; everything that is read is checked against GDK's parser before it reaches the sidebar.
def _rules(text):
    """Returns the colour declarations of a shell stylesheet, keyed by (selector, property)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    wanted = {(selector, prop) for _n, selector, prop, _f in PALETTE}
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        names = [part.strip() for part in selectors.split(",")]
        declarations = dict(_declarations(body))
        for selector in names:
            for prop, value in declarations.items():
                if (selector, prop) in wanted and _is_colour(value):
                    # A later rule wins, as it would in the shell itself.
                    found[(selector, prop)] = value
    return found


def _declarations(body):
    """Yields the (property, value) pairs of a rule body."""
    for declaration in body.split(";"):
        prop, sep, value = declaration.partition(":")
        if sep:
            yield prop.strip(), value.strip()


def _is_colour(value):
    """Reports whether GDK can read the value as a colour."""
    return Gdk.RGBA().parse(value)
