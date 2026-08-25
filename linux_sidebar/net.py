"""Asynchronous HTTP, so a slow or unreachable server never freezes the sidebar."""

import gi

from .util import log

try:
    gi.require_version("Soup", "3.0")
    from gi.repository import Soup
except (ImportError, ValueError):
    Soup = None

from gi.repository import GLib

_session = None


def available():
    """Reports whether libsoup is installed, which anything talking to a server needs."""
    return Soup is not None


def session():
    """Returns the one session every request shares, so connections are reused."""
    global _session
    if _session is None:
        _session = Soup.Session()
        _session.set_timeout(15)
        _session.set_idle_timeout(30)
    return _session


def request(method, uri, headers=None, body=None, content_type="text/plain",
            insecure=False, callback=None):
    """Sends a request and calls back with (ok, status, text)."""
    done = callback or (lambda *_args: None)
    if Soup is None:
        log("libsoup is not installed, so %s cannot be reached" % uri)
        done(False, 0, "libsoup is not installed")
        return

    try:
        message = Soup.Message.new(method, uri)
    except Exception as error:
        done(False, 0, "bad address: %s" % error)
        return
    if message is None:
        done(False, 0, "bad address: %s" % uri)
        return

    for name, value in (headers or {}).items():
        message.get_request_headers().append(name, value)
    if body is not None:
        message.set_request_body_from_bytes(content_type,
                                            GLib.Bytes.new(body.encode("utf-8")))
    # A server behind a private certificate authority is the normal case on a home network.
    if insecure:
        message.connect("accept-certificate", lambda *_args: True)

    def finished(soup_session, result):
        try:
            data = soup_session.send_and_read_finish(result)
        except GLib.Error as error:
            done(False, 0, error.message)
            return
        status = int(message.get_status())
        text = (data.get_data() or b"").decode("utf-8", "replace") if data else ""
        done(200 <= status < 300, status, text)

    session().send_and_read_async(message, GLib.PRIORITY_DEFAULT, None, finished)
