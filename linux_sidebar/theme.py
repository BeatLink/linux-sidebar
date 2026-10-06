"""The sidebar's palette, taken either from the desktop shell's theme or from the GTK theme."""

import os
import re

from gi.repository import Gdk, Gio, GLib

from .util import log

# Where each shell theme puts the panel's own colours; themes differ, so each is a list tried in order.
PANEL = ["#panel", ".panel-bottom", ".panel-top", ".panel-left", ".panel-right"]
SELECTED = [".popup-menu-item:active", ".popup-menu-item.selected"]
SLIDER = [".slider", ".popup-slider-menu-item"]

# The colours style.css and the note editor are painted from. Each entry is (name, the
# (selector, property) pairs to look for in the shell's theme, the GTK theme colour, and the
# colour to use when the shell's theme has none, or None where the shell must supply it).
PALETTE = [
    ("sidebar_bg", [(s, "background-color") for s in PANEL], "@theme_bg_color", None),
    ("sidebar_fg", [(s, "color") for s in PANEL], "@theme_fg_color", None),
    # Menus can be lighter or darker than the panel, so with the shell the base is the panel's.
    ("sidebar_base", [], "@theme_base_color", "@sidebar_bg"),
    ("sidebar_selected_bg", [(s, "background-color") for s in SELECTED],
     "@theme_selected_bg_color", "alpha(@sidebar_fg, 0.2)"),
    ("sidebar_selected_fg", [(s, "color") for s in SELECTED],
     "@theme_selected_fg_color", "@sidebar_fg"),
    # A mid-tone accent reads on a light or a dark strip alike, so the GTK one is a safe stand-in.
    ("sidebar_accent", [(s, "-slider-active-background-color") for s in SLIDER],
     "@theme_selected_bg_color", "@theme_selected_bg_color"),
]

# Colours that only make sense together, so the shell supplies both or neither.
PAIRS = [("sidebar_bg", "sidebar_fg"), ("sidebar_selected_bg", "sidebar_selected_fg")]

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
    """Returns the @define-color rules the stylesheets read, and whether the shell supplied them."""
    shell = {} if source == "gtk" else shell_palette()
    if source == "shell" and not shell:
        _say("no desktop shell theme to read, falling back to the GTK theme")
    lines = []
    for name, _candidates, gtk, fallback in PALETTE:
        lines.append("@define-color %s %s;" % (name, shell.get(name, fallback if shell else gtk)))
    lines += ["@define-color %s %s;" % (name, value) for name, value in DERIVED]
    return "\n".join(lines) + "\n", bool(shell)


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
    for name, candidates, _gtk, _fallback in PALETTE:
        value = next((rules[c] for c in candidates if c in rules), None)
        if value is not None:
            found[name] = value
    for pair in PAIRS:
        if not all(name in found for name in pair):
            for name in pair:
                found.pop(name, None)
    if "sidebar_bg" not in found:
        _say("%s gives the panel no plain colours, so the GTK theme is used" % path)
        return {}
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
    wanted = {pair for _n, candidates, _g, _f in PALETTE for pair in candidates}
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
