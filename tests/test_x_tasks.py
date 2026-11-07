"""Tests for the X-Tasks plugin's rules and for reading from a server."""

import http.server
import json
import os
import threading
import time
import unittest
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib

from linux_sidebar.plugins.x_tasks import logic, source

NOW = datetime(2026, 11, 4, 12, 0)


def task(identifier, **fields):
    base = {"id": identifier, "title": identifier, "is_done": False, "parent_id": None,
            "due_at": None, "start_at": None, "recurrence": "", "my_day_on": None,
            "done_at": None, "tag_ids": []}
    return {**base, **fields}


def tag(identifier, **fields):
    return {**{"id": identifier, "name": identifier, "group_id": "g", "parent_id": None,
               "rule": None}, **fields}


class MyDayTests(unittest.TestCase):
    def test_today_counts_and_yesterday_does_not_when_it_clears(self):
        board = logic.Board([task("a", my_day_on="2026-11-04"),
                             task("b", my_day_on="2026-11-03")], [], NOW)
        since = logic.my_day_since({"auto_clear_my_day": True}, "2026-11-04")
        self.assertEqual([t["id"] for t in logic.in_my_day(board, False, since)], ["a"])

    def test_yesterday_stays_when_it_never_clears(self):
        board = logic.Board([task("b", my_day_on="2026-11-03")], [], NOW)
        since = logic.my_day_since({"auto_clear_my_day": False}, "2026-11-04")
        self.assertEqual(len(logic.in_my_day(board, False, since)), 1)

    def test_subtask_follows_its_parent_and_done_is_hidden(self):
        board = logic.Board([task("p", my_day_on="2026-11-04"), task("c", parent_id="p"),
                             task("d", parent_id="p", is_done=True)], [], NOW)
        shown = logic.in_my_day(board, False, "2026-11-04")
        self.assertEqual([t["id"] for t in shown], ["p", "c"])
        self.assertEqual([(t["id"], depth) for t, depth in logic.outline(shown, board)],
                         [("p", 0), ("c", 1)])


    def test_a_task_that_came_due_counts_when_the_app_adds_due_tasks(self):
        board = logic.Board([task("due", due_at="2026-11-04T09:00"),
                             task("later", due_at="2026-11-04T15:00"),
                             task("seen", due_at="2026-11-03"),
                             task("started", start_at="2026-11-04T10:00"),
                             task("child", parent_id="due")], [], NOW)
        settings = {"add_due_to_my_day": True, "due_added_to_my_day_until": "2026-11-04T08:00"}
        shown = logic.in_my_day(board, False, "2026-11-04", settings)
        self.assertEqual([t["id"] for t in shown], ["due", "child"])
        by_start = logic.in_my_day(board, False, "2026-11-04",
                                   {**settings, "task_date_field": "start"})
        self.assertEqual([t["id"] for t in by_start], ["started"])
        self.assertEqual(logic.in_my_day(board, False, "2026-11-04", {}), [])


class FilterTests(unittest.TestCase):
    def test_plain_tag_is_inherited_from_the_parent_task(self):
        board = logic.Board([task("p", tag_ids=["work"]), task("c", parent_id="p")],
                            [tag("work")], NOW)
        found = logic.under_filters(board, [board.tags[0]], "all", "subtags", False)
        self.assertEqual([t["id"] for t in found], ["p", "c"])

    def test_scope_decides_whether_child_tags_count(self):
        tags = [tag("work"), tag("clients", parent_id="work")]
        board = logic.Board([task("a", tag_ids=["clients"])], tags, NOW)
        self.assertEqual(len(logic.under_filters(board, [tags[0]], "all", "subtags", False)), 1)
        self.assertEqual(len(logic.under_filters(board, [tags[0]], "all", "own", False)), 0)

    def test_rule_tag_matches_by_its_rule_and_all_or_any_combine(self):
        overdue = tag("overdue", rule={"match": "all", "conditions": [
            {"kind": "due", "when": "overdue", "days": 0}]})
        work = tag("work")
        board = logic.Board([task("a", due_at="2026-11-01", tag_ids=["work"]),
                             task("b", due_at="2026-11-01"), task("c", tag_ids=["work"])],
                            [overdue, work], NOW)
        both = logic.under_filters(board, [overdue, work], "all", "subtags", False)
        either = logic.under_filters(board, [overdue, work], "any", "subtags", False)
        self.assertEqual([t["id"] for t in both], ["a"])
        self.assertEqual([t["id"] for t in either], ["a", "b", "c"])

    def test_actionable_style_rule(self):
        rule = {"match": "all", "conditions": [{"kind": "status", "is_done": False},
                                               {"kind": "open_subtasks", "has_open": False},
                                               {"kind": "start", "when": "passed_or_none"}]}
        actionable = tag("actionable", rule=rule)
        board = logic.Board([task("p"), task("c", parent_id="p"),
                             task("later", start_at="2026-12-01")], [actionable], NOW)
        found = logic.under_filters(board, [actionable], "all", "subtags", False)
        self.assertEqual([t["id"] for t in found], ["c"])

    def test_completed_within_reads_done_at_as_utc(self):
        # 23:30 UTC on Nov 1 is already Nov 2 in Tokyo, two days before NOW rather than three.
        zone = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Tokyo"
        time.tzset()
        try:
            within = tag("within", rule={"match": "all", "conditions": [
                {"kind": "completed_within", "days": 3}]})
            board = logic.Board([task("a", is_done=True, done_at="2026-11-01T23:30:00.000Z")],
                                [within], NOW)
            self.assertEqual(len(logic.under_filters(board, [within], "all", "subtags", True)), 1)
        finally:
            if zone is None:
                os.environ.pop("TZ")
            else:
                os.environ["TZ"] = zone
            time.tzset()

    def test_names_are_matched_without_case_and_unknown_ones_reported(self):
        found, unknown = logic.tags_named([" WORK ", "nope", ""], [tag("x", name="Work")])
        self.assertEqual(([t["id"] for t in found], unknown), (["x"], ["nope"]))


class DateTests(unittest.TestCase):
    def test_overdue_and_labels(self):
        self.assertTrue(logic.is_overdue("2026-11-03", NOW))
        self.assertFalse(logic.is_overdue("2026-11-04", NOW))
        self.assertTrue(logic.is_overdue("2026-11-04T09:00", NOW))
        self.assertEqual(logic.due_label("2026-11-05", NOW), "Tomorrow")
        self.assertEqual(logic.due_label("2026-11-04T09:30", NOW), "Today 09:30")
        self.assertEqual(logic.due_label("garbage", NOW), "")

    def test_the_chosen_date_field_picks_the_date(self):
        both = task("a", start_at="2026-11-01", due_at="2026-11-09")
        self.assertEqual(logic.task_date(both, "due"), "2026-11-09")
        self.assertEqual(logic.task_date(both, "start"), "2026-11-01")


def serve(replies, seen, status=200):
    """Starts a scratch server answering each bridge call from replies, and returns it."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization")))
            body = json.dumps(replies.get(self.path.rsplit("/", 1)[1])).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def load(settings):
    """Runs one read to the end and returns what it called back with."""
    loop = GLib.MainLoop()
    result = {}

    def done(data, error):
        result.update(data=data, error=error)
        loop.quit()

    GLib.timeout_add_seconds(10, loop.quit)
    source.load(settings, done)
    loop.run()
    return result


class ServerTests(unittest.TestCase):
    def setUp(self):
        source._tokens.clear()

    def test_load_posts_the_three_calls_with_the_token(self):
        seen = []
        replies = {"list_tasks": [task("a")], "list_tags": [tag("t")],
                   "get_settings": {"auto_clear_my_day": True}}
        server = serve(replies, seen)
        result = load({"server_url": "http://127.0.0.1:%d" % server.server_port,
                       "token": "scratch"})
        server.shutdown()
        self.assertEqual(result["error"], "")
        self.assertEqual(result["data"]["tasks"][0]["id"], "a")
        self.assertEqual(seen, [("/api/list_tasks", "Bearer scratch"),
                                ("/api/list_tags", "Bearer scratch"),
                                ("/api/get_settings", "Bearer scratch")])

    def test_a_refused_token_is_asked_for_again(self):
        seen = []
        server = serve({}, seen, status=401)
        settings = {"server_url": "http://127.0.0.1:%d" % server.server_port,
                    "token_command": "echo scratch"}
        result = load(settings)
        server.shutdown()
        self.assertEqual(result["error"], "the server refused the token")
        self.assertEqual(seen, [("/api/list_tasks", "Bearer scratch")])
        self.assertNotIn("echo scratch", source._tokens)

    def test_a_command_printing_nothing_sends_no_request(self):
        seen = []
        server = serve({}, seen)
        result = load({"server_url": "http://127.0.0.1:%d" % server.server_port,
                       "token_command": "true"})
        server.shutdown()
        self.assertEqual(result["error"], "the token command printed no token")
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
