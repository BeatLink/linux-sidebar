"""Finds the plugins that ship with the sidebar and the ones dropped into the user's plugin directory."""

import importlib
import importlib.util
import os
import pkgutil
import traceback

from ..util import USER_PLUGIN_DIR, log
from .api import PluginHost, SidebarPlugin

_registry = None


def _register(module, source, found):
    """Adds a module's PLUGIN class to the registry, complaining if it is not usable."""
    plugin = getattr(module, "PLUGIN", None)
    if plugin is None or not isinstance(plugin, type) or not issubclass(plugin, SidebarPlugin):
        log("%s defines no PLUGIN class, skipping it" % source)
        return
    if not plugin.id:
        log("%s has no id, skipping it" % source)
        return
    if plugin.id in found:
        log("%s is already provided by another plugin, skipping %s" % (plugin.id, source))
        return
    found[plugin.id] = plugin


def _load_builtin(found):
    """Imports every module in this package, each of which may provide a plugin."""
    for info in pkgutil.iter_modules(__path__):
        if info.name == "api":
            continue
        try:
            module = importlib.import_module("%s.%s" % (__name__, info.name))
        except Exception:
            log("could not load the built-in plugin %s:\n%s" % (info.name, traceback.format_exc()))
            continue
        _register(module, info.name, found)


# A plugin the user dropped in is ordinary Python running in this process, so a broken one is
# caught and reported rather than being allowed to take the sidebar down with it.
def _load_user(found):
    """Imports every module and package in the user's plugin directory."""
    if not os.path.isdir(USER_PLUGIN_DIR):
        return
    for entry in sorted(os.listdir(USER_PLUGIN_DIR)):
        path = os.path.join(USER_PLUGIN_DIR, entry)
        if entry.startswith((".", "_")):
            continue
        if os.path.isdir(path):
            path = os.path.join(path, "__init__.py")
            name = entry
        elif entry.endswith(".py"):
            name = entry[:-3]
        else:
            continue
        if not os.path.exists(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("linux_sidebar_user_%s" % name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            log("could not load the plugin %s:\n%s" % (path, traceback.format_exc()))
            continue
        _register(module, path, found)


def registry():
    """Returns every known plugin class, keyed by id, loading them the first time it is asked."""
    global _registry
    if _registry is None:
        found = {}
        _load_builtin(found)
        _load_user(found)
        _registry = found
    return _registry


def reload_registry():
    """Forgets the loaded plugins so the next lookup finds them again."""
    global _registry
    _registry = None


def get(plugin_id):
    """Returns the plugin class with the given id, or None."""
    return registry().get(plugin_id)


def create(sidebar, instance):
    """Builds the plugin instance for a layout slot, or returns None if it cannot be built."""
    plugin = get(instance["plugin"])
    if plugin is None:
        log("no plugin named %s is installed" % instance["plugin"])
        return None
    try:
        return plugin(PluginHost(sidebar, instance, plugin))
    except Exception:
        log("could not start %s:\n%s" % (instance["plugin"], traceback.format_exc()))
        return None
