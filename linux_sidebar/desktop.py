"""Identifies the session and the desktop, and finds the desktop's own keyboard settings tool."""

import os

from .util import have

# Each entry is (desktop id, argv for its keyboard shortcut settings).
KEYBOARD_SETTINGS = [
    ("cinnamon", ["cinnamon-settings", "keyboard"]),
    ("gnome", ["gnome-control-center", "keyboard"]),
    ("kde", ["systemsettings", "kcm_keys"]),
    ("plasma", ["systemsettings", "kcm_keys"]),
    ("xfce", ["xfce4-keyboard-settings"]),
    ("mate", ["mate-keyboard-properties"]),
    ("budgie", ["budgie-control-center", "keyboard"]),
    ("lxqt", ["lxqt-config-globalkeyshortcuts"]),
    ("pantheon", ["io.elementary.settings", "keyboard"]),
    ("cosmic", ["cosmic-settings", "input"]),
    ("deepin", ["dde-control-center", "-s", "-p", "keyboard"]),
    ("sway", ["swaymsg", "-t", "get_binding_modes"]),
]


def desktop_names():
    """Returns the desktop identifiers from XDG_CURRENT_DESKTOP, lowercased."""
    raw = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
    return [part.strip().lower() for part in raw.split(":") if part.strip()]


def desktop_name():
    """Returns the primary desktop identifier, or 'unknown'."""
    names = desktop_names()
    return names[0] if names else "unknown"


def is_wayland():
    """Reports whether this is a Wayland session."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def has_x_server():
    """Reports whether an X server, real or XWayland, is reachable."""
    return bool(os.environ.get("DISPLAY"))


def keyboard_settings_argv():
    """Returns the argv for this desktop's keyboard settings, or None if none is installed."""
    names = desktop_names()
    for ident, argv in KEYBOARD_SETTINGS:
        if any(ident in name for name in names) and have(argv[0]):
            return argv
    for _ident, argv in KEYBOARD_SETTINGS:
        if have(argv[0]):
            return argv
    return None
