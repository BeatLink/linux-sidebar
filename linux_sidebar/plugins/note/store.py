"""Reads and writes the note, through a file or through a pair of user commands.

Both paths report through a callback, because the command path must not run
synchronously on the UI thread.
"""

import os

from ...util import CONFIG_DIR, log, run_shell

EXTENSIONS = {"html": "html", "markdown": "md"}


class NoteStore:
    """The store behind one note, whichever backend its settings name."""

    def __init__(self, settings, instance_id):
        self.settings = settings
        self.instance_id = instance_id

    @property
    def mode(self):
        """Returns which backend is in use, 'file' or 'command'."""
        return "command" if self.settings.get("storage_backend") == "command" else "file"

    @property
    def format(self):
        """Returns the data format the note is stored in, 'html' or 'markdown'."""
        return "markdown" if self.settings.get("note_format") == "markdown" else "html"

    @property
    def path(self):
        """Returns the note file, defaulting to one named after the instance and the format."""
        custom = (self.settings.get("storage_file") or "").strip()
        if custom:
            return os.path.expanduser(custom)
        return os.path.join(CONFIG_DIR, "%s.%s" % (self.instance_id, EXTENSIONS[self.format]))

    def identity(self):
        """Identifies the target, so a settings change that moves it can be spotted."""
        if self.mode == "command":
            return "command:%s|%s" % (self.settings.get("read_command"),
                                      self.settings.get("write_command"))
        return "file:%s" % self.path

    # Reading and writing --------------------------------------------------------------------

    def load(self, callback):
        """Calls back with the note, or with None if it could not be read."""
        if self.mode == "command":
            command = self.settings.get("read_command")
            if not (command or "").strip():
                callback("")
                return
            run_shell(command, None, lambda ok, out: callback(out if ok else None))
        else:
            callback(self._load_file())

    def save(self, text, callback):
        """Calls back with True once the note has been stored."""
        if self.mode == "command":
            command = self.settings.get("write_command")
            if not (command or "").strip():
                callback(False)
                return
            run_shell(command, text, lambda ok, _out: callback(ok))
        else:
            callback(self._save_file(text))

    def _load_file(self):
        """Returns the note file's contents, '' if it is not there and None if it cannot be read."""
        try:
            with open(self.path) as handle:
                return handle.read()
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeDecodeError) as error:
            log("could not read %s: %s" % (self.path, error))
            return None

    def _save_file(self, text):
        """Writes the note file through a temporary file, so an interrupted save cannot truncate it."""
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w") as handle:
                handle.write(text)
            os.replace(temporary, self.path)
            return True
        except OSError as error:
            log("could not write %s: %s" % (self.path, error))
            return False
