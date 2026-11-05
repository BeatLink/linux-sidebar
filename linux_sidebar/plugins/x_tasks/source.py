"""Reads X-Tasks tasks, tags and settings from its web server's API.

Only list and get calls are sent, so nothing on the server is ever changed.
"""

import json

from ... import net
from ...util import log, run_shell

# What each token command printed, so a command that asks for a password runs once.
_tokens = {}


def load(settings, callback):
    """Calls back with ({"tasks", "tags", "settings"}, "") or with (None, what went wrong)."""
    base = (settings.get("server_url") or "").rstrip("/")
    if not base:
        callback(None, "no server is set")
        return

    def with_token(token):
        calls = ["list_tasks", "list_tags", "get_settings"]
        results = {}

        def next_call():
            if not calls:
                callback({"tasks": results["list_tasks"], "tags": results["list_tags"],
                          "settings": results["get_settings"]}, "")
                return
            name = calls.pop(0)

            def done(ok, status, text):
                if status in (401, 403):
                    callback(None, "the server refused the token")
                    return
                try:
                    results[name] = json.loads(text) if ok else None
                except ValueError:
                    results[name] = None
                if results[name] is None:
                    log("%s failed: %s" % (name, text or status))
                    callback(None, "could not reach the X-Tasks server")
                    return
                next_call()

            headers = {"Authorization": "Bearer %s" % token} if token else {}
            net.request("POST", "%s/api/%s" % (base, name), headers=headers, body="[]",
                        content_type="application/json",
                        insecure=bool(settings.get("allow_insecure_tls")), callback=done)

        next_call()

    _token(settings, with_token)


def _token(settings, callback):
    """Calls back with the access token, which a command can print instead of it being kept in the settings."""
    command = (settings.get("token_command") or "").strip()
    if not command:
        callback((settings.get("token") or "").strip())
        return
    if command in _tokens:
        callback(_tokens[command])
        return

    def done(ok, out):
        token = out.strip() if ok else ""
        if token:
            _tokens[command] = token
        callback(token)

    run_shell(command, None, done)
