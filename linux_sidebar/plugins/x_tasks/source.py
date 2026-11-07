"""Talks to an X-Tasks web server's API: reads tasks, tags and settings, and adds tasks.

Adding a task is the only call that changes anything on the server.
"""

import json

from ... import net
from ...util import log, run_shell

# What each token command printed, so a command that asks for a password runs once.
_tokens = {}

READS = ["list_tasks", "list_tags", "list_tag_groups", "get_settings"]


def load(settings, callback):
    """Calls back with ({"tasks", "tags", "groups", "settings"}, "") or with (None, what went wrong)."""
    calls = list(READS)
    results = {}

    def next_call():
        if not calls:
            callback({"tasks": results["list_tasks"], "tags": results["list_tags"],
                      "groups": results["list_tag_groups"], "settings": results["get_settings"]}, "")
            return
        name = calls.pop(0)

        def done(value, error):
            if error:
                callback(None, error)
                return
            results[name] = value
            next_call()

        _call(settings, name, [], done)

    next_call()


def add_task(settings, title, tag_ids, my_day_on, callback):
    """Adds a top-level task and calls back with (the new task, "") or with (None, what went wrong)."""
    _call(settings, "add_task", [title, None, tag_ids, my_day_on], callback)


def _call(settings, name, args, callback):
    """Posts one bridge call and calls back with (its decoded result, "") or with (None, what went wrong)."""
    base = (settings.get("server_url") or "").rstrip("/")
    if not base:
        callback(None, "no server is set")
        return

    def with_token(token):
        if token is None:
            callback(None, "the token command printed no token")
            return

        def done(ok, status, text):
            if status in (401, 403):
                # The next call runs the command again, in case the token was changed.
                _tokens.pop((settings.get("token_command") or "").strip(), None)
                callback(None, "the server refused the token")
                return
            try:
                value = json.loads(text) if ok else None
            except ValueError:
                value = None
            if value is None:
                log("%s failed: %s" % (name, text or status))
                callback(None, "could not reach the X-Tasks server")
                return
            callback(value, "")

        headers = {"Authorization": "Bearer %s" % token} if token else {}
        net.request("POST", "%s/api/%s" % (base, name), headers=headers, body=json.dumps(args),
                    content_type="application/json",
                    insecure=bool(settings.get("allow_insecure_tls")), callback=done)

    _token(settings, with_token)


def _token(settings, callback):
    """Calls back with the access token, which a command can print instead of it being kept in the settings.

    It calls back with None when the command printed nothing, so no request is sent without the token.
    """
    command = (settings.get("token_command") or "").strip()
    if not command:
        callback((settings.get("token") or "").strip())
        return
    if command in _tokens:
        callback(_tokens[command])
        return

    def done(ok, out):
        token = out.strip() if ok else ""
        if not token:
            callback(None)
            return
        _tokens[command] = token
        callback(token)

    run_shell(command, None, done)
