"""Docks on X11 as an EWMH panel: an undecorated always-on-top window that claims a strut.

Every EWMH window manager keeps maximised windows clear of a _NET_WM_STRUT_PARTIAL, which
is the same reservation layer-shell's exclusive zone gives on Wayland.
"""

from gi.repository import Gdk

from .. import desktop
from ..util import log
from .base import DockBackend

try:
    from Xlib import display as xlib_display
    from Xlib import Xatom
except ImportError:
    xlib_display = None


class X11Backend(DockBackend):
    """An override-free X11 dock window whose strut the window manager honours."""

    name = "x11"
    label = "X11 dock"
    takes_focus_on_click = False

    @staticmethod
    def available():
        """Reports whether GDK is driving an X11 display."""
        display = Gdk.Display.get_default()
        return display is not None and type(display).__name__.startswith("X11")

    def __init__(self, window, config):
        super().__init__(window, config)
        self._xdisplay = None
        self._strut = None
        self._previous = None
        self._unshadowed = False

    @property
    def reserves_space(self):
        """Reports whether a strut can actually be set, which needs python-xlib."""
        return xlib_display is not None

    def attach(self):
        """Makes the window an undecorated, sticky, always-on-top strip outside the task list."""
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_keep_above(True)
        self.window.set_accept_focus(True)
        self.window.set_focus_on_map(True)
        self.window.stick()
        self.window.set_gravity(Gdk.Gravity.STATIC)
        self._apply_type_hint()

    # A window manager keeps NORMAL windows inside the work area, so a sidebar that reserves
    # its own strip would be pushed straight back out of it; only DOCK is placed where asked.
    # The escape hatch is for window managers that refuse a DOCK window the keyboard.
    def _apply_type_hint(self):
        """Applies the configured EWMH window type."""
        dock = str(self.config.get("x11_window_type", "dock")).lower() == "dock"
        self.window.set_type_hint(Gdk.WindowTypeHint.DOCK if dock
                                  else Gdk.WindowTypeHint.NORMAL)

    def apply(self):
        """Moves and sizes the strip, then claims or drops its strut."""
        self._apply_type_hint()
        x, y, width, height = self.strip()
        self.window.set_size_request(width, height)
        self.window.resize(width, height)
        self.window.move(x, y)
        self.window.set_keep_above(str(self.config["layer"]).lower() != "bottom")
        self._apply_strut()
        self._drop_shadow()

    # A window manager draws a dock a drop shadow and then leaves it out of a frame or two
    # whenever a window below is maximised, which reads as a flicker down the sidebar's edge.
    # Claiming frame extents, even empty ones, means the window says it draws its own edge.
    def _drop_shadow(self):
        """Asks the window manager not to draw a shadow around the strip."""
        if self._unshadowed or xlib_display is None:
            return
        xid = self._xid()
        if xid is None:
            return
        try:
            display = self._connect()
            if display is None:
                return
            window = display.create_resource_object("window", xid)
            window.change_property(display.intern_atom("_GTK_FRAME_EXTENTS"),
                                   Xatom.CARDINAL, 32, [0, 0, 0, 0])
            display.flush()
            self._unshadowed = True
        except Exception as error:
            log("could not drop the shadow: %s" % error)

    def on_realize(self):
        """Re-applies the placement once the window has a surface to place."""
        self.apply()

    def _apply_strut(self):
        """Writes _NET_WM_STRUT_PARTIAL, or removes it when space is not being reserved."""
        if xlib_display is None:
            if self.config["reserve_space"]:
                log("python-xlib is not installed, so windows cannot be kept out of the strip")
            return
        xid = self._xid()
        if xid is None:
            return
        strut = self._strut_values() if self.config["reserve_space"] else [0] * 12
        if strut == self._strut:
            return
        try:
            display = self._connect()
            if display is None:
                return
            window = display.create_resource_object("window", xid)
            window.change_property(display.intern_atom("_NET_WM_STRUT_PARTIAL"),
                                   Xatom.CARDINAL, 32, strut)
            window.change_property(display.intern_atom("_NET_WM_STRUT"),
                                   Xatom.CARDINAL, 32, strut[:4])
            display.flush()
            self._strut = strut
        except Exception as error:
            log("could not set the strut: %s" % error)

    def _strut_values(self):
        """Returns the twelve _NET_WM_STRUT_PARTIAL cardinals for the current strip."""
        x, y, width, height = self.strip()
        root_width, _root_height = self.root_size()
        left = right = 0
        if self.config["side"] == "left":
            left = x + width
        else:
            right = max(0, root_width - x)
        return [left, right, 0, 0, y, y + height - 1, y, y + height - 1, 0, 0, 0, 0]

    def _xid(self):
        """Returns the X window id of the realized window, or None."""
        surface = self.window.get_window()
        if surface is None or not hasattr(surface, "get_xid"):
            return None
        return surface.get_xid()

    def _connect(self):
        """Opens the Xlib connection used for the strut, reusing it once it exists."""
        if self._xdisplay is None and desktop.has_x_server():
            try:
                self._xdisplay = xlib_display.Display()
            except Exception as error:
                log("could not open the X display: %s" % error)
        return self._xdisplay

    # A window manager hands a DOCK window the pointer but never the keyboard, so the click
    # that focuses an ordinary window has to set the input focus itself.
    def take_focus(self):
        """Puts the keyboard on the sidebar, which a click on a dock does not do by itself."""
        if self.window.is_active():
            return
        self.note_focus_gained()
        display = self._connect()
        xid = self._xid()
        if display is None or xid is None:
            return
        try:
            from Xlib import X
            window = display.create_resource_object("window", xid)
            window.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
            display.flush()
        except Exception as error:
            log("could not take the focus: %s" % error)

    def note_focus_gained(self):
        """Remembers which window was active before the sidebar took the keyboard."""
        display = self._connect()
        if display is None:
            return
        try:
            root = display.screen().root
            active = root.get_full_property(display.intern_atom("_NET_ACTIVE_WINDOW"),
                                            Xatom.WINDOW)
            candidate = active.value[0] if active and active.value else None
            if candidate and candidate != self._xid():
                self._previous = candidate
        except Exception as error:
            log("could not read the active window: %s" % error)

    # X11 has no way to hand the keyboard back, so the window that held it is asked to take
    # it again through the same _NET_ACTIVE_WINDOW message a task switcher would send.
    def release_keyboard(self):
        """Asks the window manager to reactivate whatever was focused before the sidebar."""
        display = self._connect()
        if display is None or not self._previous:
            return
        try:
            from Xlib import X, protocol
            root = display.screen().root
            window = display.create_resource_object("window", self._previous)
            event = protocol.event.ClientMessage(
                window=window, client_type=display.intern_atom("_NET_ACTIVE_WINDOW"),
                data=(32, [2, X.CurrentTime, 0, 0, 0]))
            root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            display.flush()
        except Exception as error:
            log("could not restore the focus: %s" % error)

    def shutdown(self):
        """Drops the strut and closes the Xlib connection."""
        if self._xdisplay is not None:
            try:
                self._xdisplay.close()
            except Exception:
                pass
            self._xdisplay = None
