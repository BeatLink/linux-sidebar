"""One plugin's slice of a tab: a header you can click to fold it away, and the plugin's widget."""

import traceback

import gi

gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

from ..util import log


class Section(Gtk.Box):
    """A collapsible section holding one plugin instance, whose folded state is persisted."""

    def __init__(self, instance, plugin, on_collapse):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.instance = instance
        self.plugin = plugin
        self.on_collapse = on_collapse
        self.set_name("sidebar-section")

        self.header = Gtk.Button()
        self.header.set_name("section-header")
        self.header.set_relief(Gtk.ReliefStyle.NONE)
        self.header.connect("clicked", lambda _b: self.set_collapsed(not self.collapsed))

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.arrow = Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU)
        row.pack_start(self.arrow, False, False, 0)
        self.label = Gtk.Label(xalign=0.0)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        row.pack_start(self.label, True, True, 0)
        self.header.add(row)

        self.header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.header_row.pack_start(self.header, True, True, 0)
        self.pack_start(self.header_row, False, False, 0)

        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.revealer.set_transition_duration(120)
        self.pack_start(self.revealer, True, True, 0)

        self._build_body()
        self.set_title(instance.get("title") or plugin.title)
        self._apply_collapsed()

    # Contents -------------------------------------------------------------------------------

    def _build_body(self):
        """Asks the plugin for its widget, showing the failure in place if it cannot build one."""
        try:
            body = self.plugin.build()
        except Exception:
            log("%s could not build its widget:\n%s"
                % (self.instance["plugin"], traceback.format_exc()))
            body = _failure_label(self.instance["plugin"])
        self.revealer.add(body)
        try:
            extra = self.plugin.header_widget()
        except Exception:
            extra = None
        if extra is not None:
            self.header_row.pack_end(extra, False, False, 0)

    def set_title(self, text):
        """Sets the text shown in the header."""
        self.label.set_text(text or self.plugin.title)

    # Folding --------------------------------------------------------------------------------

    @property
    def collapsed(self):
        """Reports whether the section is currently folded away."""
        return bool(self.instance.get("collapsed"))

    @property
    def greedy(self):
        """Reports whether this section should take the space left over in its tab."""
        return bool(self.plugin.expands) and not self.collapsed

    def set_collapsed(self, collapsed):
        """Folds or unfolds the section and remembers which it now is."""
        if collapsed == self.collapsed:
            return
        self.instance["collapsed"] = bool(collapsed)
        self._apply_collapsed()
        self.on_collapse(self)

    def _apply_collapsed(self):
        """Applies the folded state to the revealer and the arrow."""
        collapsed = self.collapsed
        self.revealer.set_reveal_child(not collapsed)
        self.arrow.set_from_icon_name("pan-end-symbolic" if collapsed else "pan-down-symbolic",
                                      Gtk.IconSize.MENU)
        self.set_vexpand(self.greedy)


def _failure_label(name):
    """Returns the placeholder shown where a plugin failed to build its widget."""
    label = Gtk.Label(xalign=0.0)
    label.set_line_wrap(True)
    label.set_name("section-error")
    label.set_markup("<small>%s could not start. Its error is on standard error.</small>"
                     % GLib.markup_escape_text(name))
    return label
