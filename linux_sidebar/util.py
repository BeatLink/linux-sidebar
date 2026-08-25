"""Logging, subprocess helpers and the paths to the installed data files."""

import os
import shutil
import sys

from gi.repository import Gio, GLib

from . import APP_NAME

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
USER_PLUGIN_DIR = os.path.join(CONFIG_DIR, "plugins")


# Paths ------------------------------------------------------------------------------------------

def data_root():
    """Returns the directory holding style.css and vendor/, in the source tree or once installed."""
    override = os.environ.get("LINUX_SIDEBAR_DATA_DIR")
    if override:
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, os.pardir),
        os.path.join(here, os.pardir, os.pardir, "share", APP_NAME),
    ]
    for candidate in candidates:
        if os.path.exists(os.path.join(candidate, "style.css")):
            return os.path.normpath(candidate)
    return os.path.normpath(candidates[0])


def data_path(*parts):
    """Joins a path under the data root."""
    return os.path.join(data_root(), *parts)


def launch_command():
    """Returns the command to bind to a shortcut: the installed binary, else the dev runner."""
    installed = shutil.which(APP_NAME)
    if installed:
        return installed
    return os.path.normpath(data_path("run.sh"))


# Logging ----------------------------------------------------------------------------------------

def log(message):
    """Writes a tagged line to standard error."""
    print("[%s] %s" % (APP_NAME, message), file=sys.stderr)


# Subprocesses -----------------------------------------------------------------------------------

def have(program):
    """Reports whether a program is on PATH."""
    return shutil.which(program) is not None


def spawn_with_stdin(argv, text):
    """Starts a command, feeds it text and leaves it running."""
    try:
        process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDIN_PIPE)
        stream = process.get_stdin_pipe()
        stream.write_all(text.encode(), None)
        stream.close(None)
        return True
    except GLib.Error as error:
        log("could not run %s: %s" % (argv[0], error.message))
        return False


def run_argv(argv, stdin, callback):
    """Runs a command with no shell, handing (ok, stdout) to the callback."""
    flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    if stdin is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE

    def finished(process, result):
        try:
            _ok, out, err = process.communicate_utf8_finish(result)
        except GLib.Error as error:
            log("%s errored: %s" % (argv[0], error.message))
            callback(False, "")
            return
        if not process.get_successful():
            log("%s failed: %s" % (argv[0], (err or "").strip()))
            callback(False, "")
            return
        callback(True, out or "")

    try:
        process = Gio.Subprocess.new(argv, flags)
        process.communicate_utf8_async(stdin, None, finished)
    except GLib.Error as error:
        log("could not run %s: %s" % (argv[0], error.message))
        callback(False, "")


def run_shell(command, stdin, callback):
    """Runs a command through sh, so pipelines and redirection work."""
    if not (command or "").strip():
        callback(False, "")
        return
    run_argv(["sh", "-c", command], stdin, callback)
