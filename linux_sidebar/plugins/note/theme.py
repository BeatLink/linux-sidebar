"""Reads the sidebar's palette out of the style context so the editor page is painted to match."""

from gi.repository import Gtk

# Each entry is (CSS variable, palette colour name, fallback). The palette is the one the
# application defines, so the page follows whichever theme the sidebar itself is taking.
COLOURS = [
    ("--sidebar-bg", "sidebar_bg", "#f6f5f4"),
    ("--sidebar-fg", "sidebar_fg", "#2e3436"),
    ("--sidebar-base", "sidebar_base", "#ffffff"),
    ("--sidebar-accent", "sidebar_selected_bg", "#3584e4"),
    ("--sidebar-accent-fg", "sidebar_selected_fg", "#ffffff"),
    ("--sidebar-link", "sidebar_selected_bg", "#1c71d8"),
]


def theme_css(widget, font_family, font_size, mono_family):
    """Returns the :root block of CSS variables the editor page is styled from."""
    context = widget.get_style_context()
    values = []
    for name, colour, fallback in COLOURS:
        found, rgba = context.lookup_color(colour)
        values.append("%s: %s;" % (name, _css_rgba(rgba) if found else fallback))

    found, fg = context.lookup_color("sidebar_fg")
    values.append("--sidebar-border: %s;" % (_css_rgba(fg, 0.25) if found else "rgba(0,0,0,.25)"))
    values.append("--sidebar-hover: %s;" % (_css_rgba(fg, 0.12) if found else "rgba(0,0,0,.12)"))
    values.append("--sidebar-font-family: %s;" % font_family)
    values.append("--sidebar-font-size: %dpt;" % int(font_size))
    values.append("--sidebar-mono-family: %s;" % mono_family)
    return ":root { %s }" % " ".join(values)


def default_font():
    """Returns the desktop's own interface font family, or a sensible stand-in."""
    description = Gtk.Settings.get_default().get_property("gtk-font-name") or "Sans 11"
    family = " ".join(part for part in description.split() if not part.isdigit())
    return family or "Sans"


def _css_rgba(rgba, alpha=None):
    """Formats a GdkRGBA as a CSS colour, optionally overriding its alpha."""
    return "rgba(%d, %d, %d, %s)" % (round(rgba.red * 255), round(rgba.green * 255),
                                     round(rgba.blue * 255),
                                     rgba.alpha if alpha is None else alpha)
