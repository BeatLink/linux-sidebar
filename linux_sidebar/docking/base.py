"""What every docking backend has to provide, and the geometry they all share."""

from gi.repository import Gdk


class DockBackend:
    """Anchors the window to an edge of a monitor and, where it can, reserves its strip."""

    name = "base"
    label = "Base"
    reserves_space = False
    takes_focus_on_click = True

    @staticmethod
    def available():
        """Reports whether this backend can be used in this session."""
        return False

    def __init__(self, window, config):
        self.window = window
        self.config = config

    def attach(self):
        """Prepares the window before it is first realized."""

    def apply(self):
        """Applies the current settings to the docked window."""

    def on_realize(self):
        """Runs once the window has an underlying surface."""

    def on_size_allocate(self):
        """Runs whenever the window's size changes."""

    def release_keyboard(self):
        """Hands the keyboard back to whatever was focused before, where the backend can."""

    def shutdown(self):
        """Releases anything the backend is holding."""

    # Geometry -------------------------------------------------------------------------------

    def monitor(self):
        """Returns the monitor to dock to: the configured one, else where the pointer is."""
        display = Gdk.Display.get_default()
        if display is None:
            return None
        index = self.config["monitor"]
        if isinstance(index, int) and 0 <= index < display.get_n_monitors():
            return display.get_monitor(index)
        seat = display.get_default_seat()
        pointer = seat.get_pointer() if seat else None
        if pointer is not None:
            screen, x, y = pointer.get_position()
            found = display.get_monitor_at_point(x, y)
            if found is not None:
                return found
        return display.get_primary_monitor() or display.get_monitor(0)

    def strip(self):
        """Returns the (x, y, width, height) the sidebar should occupy on its monitor."""
        target = self.monitor()
        if target is None:
            return 0, 0, max(150, int(self.config["width"])), 600
        # The horizontal extent comes from the whole monitor rather than the work area,
        # since this window's own strut shrinks the work area it would be measured against.
        geometry = target.get_geometry()
        area = target.get_workarea()
        width = max(150, int(self.config["width"]))
        top = int(self.config["margin_top"])
        bottom = int(self.config["margin_bottom"])
        height = max(100, area.height - top - bottom)
        x = geometry.x if self.config["side"] == "left" else geometry.x + geometry.width - width
        return x, area.y + top, width, height

    def root_size(self):
        """Returns the size of the whole desktop, which struts are measured against."""
        display = Gdk.Display.get_default()
        if display is None:
            return 0, 0
        right = bottom = 0
        for index in range(display.get_n_monitors()):
            geometry = display.get_monitor(index).get_geometry()
            right = max(right, geometry.x + geometry.width)
            bottom = max(bottom, geometry.y + geometry.height)
        return right, bottom
