"""The last resort: an ordinary always-on-top window, for sessions with no docking protocol at all.

GNOME's Wayland session implements neither layer-shell nor any way for a client to place
itself, so the sidebar can only ask to stay on top and hope the compositor obliges.
"""

from gi.repository import Gdk

from .base import DockBackend


class PlainBackend(DockBackend):
    """An undecorated utility window, positioned where the session allows it to be."""

    name = "plain"
    label = "Plain window"
    reserves_space = False

    @staticmethod
    def available():
        """Reports whether it can be used, which it always can."""
        return True

    def attach(self):
        """Makes the window an undecorated, sticky strip outside the task list."""
        self.window.set_decorated(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.window.stick()
        self.window.set_gravity(Gdk.Gravity.STATIC)

    def apply(self):
        """Sizes the strip and asks to be placed against the chosen edge."""
        x, y, width, height = self.strip()
        self.window.set_size_request(width, height)
        self.window.resize(width, height)
        self.window.move(x, y)
        self.window.set_keep_above(str(self.config["layer"]).lower() != "bottom")

    def on_realize(self):
        """Re-applies the placement once the window has a surface to place."""
        self.apply()

    # Nothing here can hand the keyboard to a chosen window, so the most this can do is
    # stop the sidebar's own widgets receiving it.
    def release_keyboard(self):
        """Takes the focus off whatever widget held it, and drops the window down the stack."""
        self.window.set_focus(None)
        surface = self.window.get_window()
        if surface is not None:
            surface.lower()
