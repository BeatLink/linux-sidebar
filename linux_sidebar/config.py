"""The settings file: the window's own settings plus the tab and plugin layout."""

import json
import os

from gi.repository import GLib

from . import APP_NAME
from .util import CONFIG_DIR, CONFIG_PATH, log

LEGACY_DIR = os.path.join(GLib.get_user_config_dir(), "sidebar-scratchpad")

DEFAULTS = {
    "side": "right",
    "width": 380,
    "monitor": -1,
    "dock_backend": "auto",
    "x11_window_type": "normal",
    "reserve_space": True,
    "layer": "auto",
    "margin_top": 0,
    "margin_bottom": 0,
    "opacity": 1.0,
    "hot_corner_gap": 24,
    "start_hidden": False,
    "show_status": True,
    "tab_position": "top",
}

# Each row is (key, label, kind, detail); detail is the choices for a combo or the
# (minimum, maximum, step) for a spin button or a scale.
SPEC = [
    ("Placement", [
        ("side", "Dock to", "combo", [("left", "Left"), ("right", "Right")]),
        ("width", "Width", "spin", (150, 2000, 10)),
        ("monitor", "Monitor, -1 for automatic", "spin", (-1, 7, 1)),
        ("dock_backend", "Docking method", "combo",
         [("auto", "Automatic"), ("layer-shell", "Wayland layer shell"),
          ("x11", "X11 dock"), ("plain", "Plain window")]),
        ("x11_window_type", "X11 window type", "combo",
         [("normal", "Normal, always focusable"), ("dock", "Dock, stacks like a panel")]),
        ("reserve_space", "Keep windows out", "switch", None),
        ("layer", "Layer", "combo",
         [("auto", "Automatic"), ("bottom", "Bottom"), ("top", "Top")]),
        ("hot_corner_gap", "Hot corner gap", "spin", (0, 200, 4)),
        ("margin_top", "Top margin", "spin", (0, 400, 4)),
        ("margin_bottom", "Bottom margin", "spin", (0, 400, 4)),
    ]),
    ("Appearance", [
        ("opacity", "Opacity", "scale", (0.3, 1.0, 0.05)),
        ("tab_position", "Tab bar", "combo",
         [("top", "Top"), ("bottom", "Bottom"), ("hidden", "Hidden")]),
        ("show_status", "Show the status line", "switch", None),
        ("start_hidden", "Start hidden", "switch", None),
    ]),
]

DEFAULT_TABS = [
    {
        "id": "tab-1",
        "title": "Notes",
        "icon": "accessories-text-editor-symbolic",
        "plugins": [{"id": "note-1", "plugin": "note", "collapsed": False, "settings": {}}],
    },
]


class Config(dict):
    """The settings file, created with the defaults the first time it is read."""

    def __init__(self):
        super().__init__(DEFAULTS)
        self["tabs"] = json.loads(json.dumps(DEFAULT_TABS))
        self.load()

    # Reading and writing --------------------------------------------------------------------

    def load(self):
        """Rereads the settings file, falling back to the defaults for anything missing."""
        stored = self._read(CONFIG_PATH)
        if stored is None:
            stored = self._migrate()
        if stored is None:
            self.save()
            return
        unknown = set(stored) - set(DEFAULTS) - {"tabs"}
        if unknown:
            log("ignoring unknown settings: %s" % ", ".join(sorted(unknown)))
        self.update({k: v for k, v in stored.items() if k in DEFAULTS})
        self["tabs"] = normalise_tabs(stored.get("tabs"))
        if set(DEFAULTS) - set(stored) or "tabs" not in stored:
            self.save()

    def save(self):
        """Writes the settings file, creating its directory if it is not there yet."""
        try:
            os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
            temporary = CONFIG_PATH + ".tmp"
            with open(temporary, "w") as handle:
                json.dump(dict(self), handle, indent=4)
                handle.write("\n")
            os.replace(temporary, CONFIG_PATH)
        except OSError as error:
            log("could not write %s: %s" % (CONFIG_PATH, error))

    def _read(self, path):
        """Returns the parsed contents of a settings file, or None if it cannot be read."""
        try:
            with open(path) as handle:
                stored = json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            log("could not read %s, using defaults: %s" % (path, error))
            return None
        return stored if isinstance(stored, dict) else None

    # The settings of the single-purpose scratchpad this grew out of become the settings of
    # the one note plugin in the default layout.
    def _migrate(self):
        """Folds a sidebar-scratchpad settings file into the new shape, or returns None."""
        old = self._read(os.path.join(LEGACY_DIR, "config.json"))
        if old is None:
            return None
        log("migrating settings from %s" % LEGACY_DIR)
        moved = {}
        for key in ("font_size", "monospace", "show_counter", "storage_backend",
                    "storage_file", "read_command", "write_command", "autosave_delay",
                    "reload_interval"):
            if key in old:
                moved[key] = old.pop(key)
        # Markdown, because the note it is carrying over is plain text and stays readable.
        moved.setdefault("note_format", "markdown")
        tabs = json.loads(json.dumps(DEFAULT_TABS))
        instance = tabs[0]["plugins"][0]
        instance["settings"] = moved
        if moved.get("storage_backend", "file") == "file":
            self._copy_legacy_note(moved, instance["id"])
        old["tabs"] = tabs
        return old

    # The note is copied rather than pointed at, so nothing afterwards depends on the old
    # directory still being there.
    def _copy_legacy_note(self, settings, instance_id):
        """Copies the scratchpad's note into this instance's own file."""
        source = (settings.get("storage_file") or "").strip()
        source = os.path.expanduser(source) if source else \
            os.path.join(LEGACY_DIR, "scratchpad.txt")
        target = os.path.join(CONFIG_DIR, "%s.md" % instance_id)
        settings["storage_file"] = ""
        if os.path.exists(target):
            return
        try:
            with open(source) as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as error:
            log("could not read the old note at %s: %s" % (source, error))
            return
        try:
            os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
            with open(target, "w") as handle:
                handle.write(text)
            log("copied the old note into %s" % target)
        except OSError as error:
            log("could not write %s: %s" % (target, error))

    # Layout ---------------------------------------------------------------------------------

    def tabs(self):
        """Returns the tab list."""
        return self["tabs"]

    def instances(self):
        """Yields every (tab, plugin instance) pair in the layout."""
        for tab in self["tabs"]:
            for instance in tab["plugins"]:
                yield tab, instance

    def next_id(self, prefix):
        """Returns an identifier of the given prefix that nothing in the layout uses yet."""
        taken = {tab["id"] for tab in self["tabs"]}
        taken |= {instance["id"] for _tab, instance in self.instances()}
        index = 1
        while "%s-%d" % (prefix, index) in taken:
            index += 1
        return "%s-%d" % (prefix, index)


def normalise_tabs(tabs):
    """Returns a stored tab list with every field filled in, or the default layout."""
    if not isinstance(tabs, list) or not tabs:
        return json.loads(json.dumps(DEFAULT_TABS))
    clean = []
    for index, tab in enumerate(tabs):
        if not isinstance(tab, dict):
            continue
        plugins = []
        for slot in tab.get("plugins") or []:
            if not isinstance(slot, dict) or not slot.get("plugin"):
                continue
            plugins.append({
                "id": str(slot.get("id") or "%s-%d" % (slot["plugin"], len(plugins) + 1)),
                "plugin": str(slot["plugin"]),
                "title": str(slot.get("title") or ""),
                "collapsed": bool(slot.get("collapsed")),
                "settings": slot.get("settings") if isinstance(slot.get("settings"), dict) else {},
            })
        clean.append({
            "id": str(tab.get("id") or "tab-%d" % (index + 1)),
            "title": str(tab.get("title") or "Tab %d" % (index + 1)),
            "icon": str(tab.get("icon") or ""),
            "plugins": plugins,
        })
    return clean or json.loads(json.dumps(DEFAULT_TABS))
