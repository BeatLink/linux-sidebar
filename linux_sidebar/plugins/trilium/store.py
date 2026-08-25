"""Reads and writes one Trilium note over ETAPI, and spots when Trilium changed it.

ETAPI offers no push, so a change on the Trilium side is found by polling the note's
metadata, which is cheap, and fetching the content only once its blob has moved.
"""

import json

from ... import net
from ...util import log, run_shell


class TriliumStore:
    """One Trilium note, reached over ETAPI."""

    def __init__(self, settings):
        self.settings = settings
        self.revision = None
        self.title = ""
        self._token = None
        self._token_source = None

    # A text note in Trilium is HTML, which is what this sidebar's editor produces.
    format = "html"

    @property
    def base(self):
        """Returns the ETAPI root, with any trailing slash trimmed off the configured URL."""
        return "%s/etapi" % (self.settings.get("server_url") or "").rstrip("/")

    @property
    def note_id(self):
        """Returns the note to edit, defaulting to Trilium's root note."""
        return (self.settings.get("note_id") or "root").strip()

    @property
    def insecure(self):
        """Reports whether an untrusted certificate should be accepted."""
        return bool(self.settings.get("allow_insecure_tls"))

    def identity(self):
        """Identifies the note, so a settings change that moves it can be spotted."""
        return "trilium:%s/%s" % (self.base, self.note_id)

    # Authentication ---------------------------------------------------------------------------

    def token(self, callback):
        """Calls back with the ETAPI token, running the token command the first time if there is one."""
        command = (self.settings.get("token_command") or "").strip()
        literal = (self.settings.get("token") or "").strip()
        if not command:
            callback(literal)
            return
        if self._token is not None and self._token_source == command:
            callback(self._token)
            return

        def done(ok, out):
            self._token = out.strip() if ok else ""
            self._token_source = command
            if not self._token:
                log("the token command produced nothing")
            callback(self._token)

        run_shell(command, None, done)

    def _call(self, method, path, body, callback, content_type="text/plain"):
        """Sends one ETAPI request, once the token is in hand."""
        if not self.settings.get("server_url"):
            callback(False, 0, "no server is configured")
            return

        def send(token):
            if not token:
                callback(False, 0, "no ETAPI token")
                return
            net.request(method, self.base + path, headers={"Authorization": token},
                        body=body, content_type=content_type, insecure=self.insecure,
                        callback=callback)

        self.token(send)

    # Reading and writing ----------------------------------------------------------------------

    def metadata(self, callback):
        """Calls back with the note's metadata, or with None."""
        def done(ok, status, text):
            if not ok:
                log("could not read the note metadata: %s" % (text or status))
                callback(None)
                return
            try:
                callback(json.loads(text))
            except ValueError as error:
                log("Trilium returned something that is not JSON: %s" % error)
                callback(None)

        self._call("GET", "/notes/%s" % self.note_id, None, done)

    def poll(self, callback):
        """Calls back with True when Trilium has moved the note on since it was last read."""
        def done(meta):
            if meta is None:
                callback(False)
                return
            self.title = meta.get("title") or self.title
            revision = meta.get("blobId") or meta.get("utcDateModified")
            changed = self.revision is not None and revision != self.revision
            self.revision = revision
            callback(changed)

        self.metadata(done)

    def load(self, callback):
        """Calls back with the note's content, or with None if it could not be read."""
        def got_content(ok, status, text):
            if not ok:
                callback(None)
                log("could not read the note: %s" % (text or status))
                return
            callback(text)

        def got_meta(meta):
            if meta is not None:
                self.title = meta.get("title") or self.title
                self.revision = meta.get("blobId") or meta.get("utcDateModified")
            self._call("GET", "/notes/%s/content" % self.note_id, None, got_content)

        self.metadata(got_meta)

    def save(self, text, callback):
        """Writes the note back, then rereads its revision so this write is not read as Trilium's."""
        def stored(ok, status, message):
            if not ok:
                log("could not save the note: %s" % (message or status))
                callback(False)
                return
            self.metadata(lambda meta: self._after_save(meta, callback))

        self._call("PUT", "/notes/%s/content" % self.note_id, text, stored)

    def _after_save(self, meta, callback):
        """Records the revision this write produced, so the next poll does not see it as a change."""
        if meta is not None:
            self.revision = meta.get("blobId") or meta.get("utcDateModified")
        callback(True)
