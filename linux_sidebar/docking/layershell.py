"""Docks through wlr-layer-shell, where the compositor itself anchors the strip and keeps it clear."""

import gi

from .base import DockBackend

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell as LayerShell
except (ImportError, ValueError):
    LayerShell = None


class LayerShellBackend(DockBackend):
    """A layer-shell surface, which the compositor anchors and whose exclusive zone it honours."""

    name = "layer-shell"
    label = "Wayland layer shell"
    reserves_space = True

    @staticmethod
    def available():
        """Reports whether the compositor implements zwlr_layer_shell_v1."""
        return LayerShell is not None and LayerShell.is_supported()

    def attach(self):
        """Turns the window into a layer-shell surface that takes focus only when clicked."""
        LayerShell.init_for_window(self.window)
        LayerShell.set_namespace(self.window, "linux-sidebar")
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.ON_DEMAND)

    def apply(self):
        """Applies the anchors, the layer, the margins and the exclusive zone."""
        self._apply_anchors()
        self._apply_layer()
        width = max(150, int(self.config["width"]))
        self.window.set_size_request(width, -1)
        LayerShell.set_exclusive_zone(self.window, width if self.config["reserve_space"] else 0)

    def _apply_anchors(self):
        """Anchors top, bottom and the chosen side, which gives a full-height strip."""
        left = self.config["side"] == "left"
        opposite = LayerShell.Edge.RIGHT if left else LayerShell.Edge.LEFT
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                     LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM):
            LayerShell.set_anchor(self.window, edge, edge != opposite)
        LayerShell.set_margin(self.window, LayerShell.Edge.TOP, int(self.config["margin_top"]))
        LayerShell.set_margin(self.window, LayerShell.Edge.BOTTOM,
                              int(self.config["margin_bottom"]))
        monitor = self.monitor()
        if monitor is not None and isinstance(self.config["monitor"], int) \
                and self.config["monitor"] >= 0:
            LayerShell.set_monitor(self.window, monitor)

    # Layer-shell has no layer meaning "above windows but below the shell's own panels", so
    # TOP covers panels that reserve no space of their own and BOTTOM sits under stray windows.
    def _apply_layer(self):
        """Chooses the layer, defaulting to whichever suits the space reservation setting."""
        choice = str(self.config["layer"]).lower()
        if choice not in ("top", "bottom"):
            choice = "bottom" if self.config["reserve_space"] else "top"
        LayerShell.set_layer(self.window, LayerShell.Layer.BOTTOM if choice == "bottom"
                             else LayerShell.Layer.TOP)

    # Dropping to NONE and back releases the keyboard while leaving the surface clickable.
    def release_keyboard(self):
        """Hands the keyboard back to whatever held it before the sidebar was clicked."""
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.NONE)
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.ON_DEMAND)
