"""Picks the docking backend that suits the running session."""

from ..util import log
from .layershell import LayerShellBackend
from .plain import PlainBackend
from .x11 import X11Backend

BACKENDS = [LayerShellBackend, X11Backend, PlainBackend]


def by_name(name):
    """Returns the backend class with the given name, or None."""
    for backend in BACKENDS:
        if backend.name == name:
            return backend
    return None


def choose(config):
    """Returns the backend class to use, honouring the setting and falling back if it cannot."""
    wanted = str(config.get("dock_backend", "auto")).lower()
    if wanted != "auto":
        backend = by_name(wanted)
        if backend is not None and backend.available():
            return backend
        if backend is not None:
            log("%s is not available in this session, choosing automatically" % wanted)
    for backend in BACKENDS:
        if backend.available():
            return backend
    return PlainBackend


def describe():
    """Returns a human-readable list of which backends this session supports."""
    return ", ".join("%s%s" % (b.label, "" if b.available() else " (unavailable)")
                     for b in BACKENDS)
