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

from linux_sidebar.plugins.x_tasks import logic, source, syntax

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

    def test_a_new_task_takes_plain_filter_tags_and_one_per_single_choice_group(self):
        groups = [{"id": "priority", "is_single_choice": True}, {"id": "area", "is_single_choice": False}]
        tags = [tag("high", group_id="priority"), tag("low", group_id="priority"),
                tag("work", group_id="area"), tag("home", group_id="area"),
                tag("actionable", rule={"match": "all", "conditions": []})]
        self.assertEqual(logic.tags_for_new_task(tags, groups), ["high", "work", "home"])

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
            sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = replies.get(self.path.rsplit("/", 1)[1])
            reply = reply(sent) if callable(reply) else reply
            # The real server answers a call with no result with an empty 204.
            body = b"" if reply == "" else json.dumps(reply).encode()
            self.send_response(204 if reply == "" and status == 200 else status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(call, *args):
    """Runs one source call to the end and returns what it called back with."""
    loop = GLib.MainLoop()
    result = {}

    def done(data, error):
        result.update(data=data, error=error)
        loop.quit()

    GLib.timeout_add_seconds(10, loop.quit)
    call(*args, done)
    loop.run()
    return result


def load(settings):
    """Runs one read to the end and returns what it called back with."""
    return run(source.load, settings)


class ServerTests(unittest.TestCase):
    def setUp(self):
        source._tokens.clear()

    def test_load_posts_the_four_calls_with_the_token(self):
        seen = []
        replies = {"list_tasks": [task("a")], "list_tags": [tag("t")], "list_tag_groups": [],
                   "get_settings": {"auto_clear_my_day": True}}
        server = serve(replies, seen)
        result = load({"server_url": "http://127.0.0.1:%d" % server.server_port,
                       "token": "scratch"})
        server.shutdown()
        self.assertEqual(result["error"], "")
        self.assertEqual(result["data"]["tasks"][0]["id"], "a")
        self.assertEqual(seen, [("/api/list_tasks", "Bearer scratch"),
                                ("/api/list_tags", "Bearer scratch"),
                                ("/api/list_tag_groups", "Bearer scratch"),
                                ("/api/get_settings", "Bearer scratch")])

    def test_add_task_posts_the_title_tags_and_my_day(self):
        seen, sent = [], []

        def add(args):
            sent.append(args)
            return task("new", title=args[0])

        server = serve({"add_task": add}, seen)
        result = run(source.add_task, {"server_url": "http://127.0.0.1:%d" % server.server_port,
                                       "token": "scratch"}, "Buy milk", ["t"], "2026-11-04")
        server.shutdown()
        self.assertEqual(result, {"data": task("new", title="Buy milk"), "error": ""})
        self.assertEqual(sent, [["Buy milk", None, ["t"], "2026-11-04"]])
        self.assertEqual(seen, [("/api/add_task", "Bearer scratch")])

    def test_set_task_schedule_posts_the_dates_and_accepts_an_empty_reply(self):
        seen, sent = [], []
        server = serve({"set_task_schedule": lambda args: sent.append(args) or ""}, seen)
        result = run(source.set_task_schedule, {"server_url": "http://127.0.0.1:%d" % server.server_port,
                                                "token": "scratch"}, "n1", None, "2026-11-05")
        server.shutdown()
        self.assertEqual(result["error"], "")
        self.assertEqual(sent, [["n1", {"start_at": None, "due_at": "2026-11-05", "recurrence": ""}]])

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


class SyntaxTests(unittest.TestCase):
    GROUPS = [{"id": "area", "name": "Area", "is_single_choice": False},
              {"id": "prio", "name": "Priority", "is_single_choice": True}]
    TAGS = [tag("work", name="Work", group_id="area", position=0),
            tag("kitchen", name="Kitchen renovation", group_id="area", position=1),
            tag("high", name="High", group_id="prio", position=0),
            tag("low", name="Low", group_id="prio", position=1)]

    def parse(self, text, field="due", now=NOW):
        return syntax.parse_quick_add(text, self.TAGS, self.GROUPS, field, now)

    def test_tags_priority_and_a_dated_time_come_out_of_the_title(self):
        found = self.parse("Buy milk tomorrow at 9am #work p1")
        self.assertEqual((found["title"], found["due_at"], found["start_at"]),
                         ("Buy milk", "2026-11-05T09:00", None))
        self.assertEqual(found["tag_ids"], ["work", "high"])

    def test_a_later_priority_replaces_an_earlier_one_and_names_ignore_case_and_spaces(self):
        found = self.parse("p1 p2 @kitchen_renovation")
        self.assertEqual(found["tag_ids"], ["low", "kitchen"])

    def test_day_phrases(self):
        due = lambda text: self.parse(text)["due_at"]
        self.assertEqual(due("call friday"), "2026-11-06")
        self.assertEqual(due("call next monday"), "2026-11-09")
        self.assertEqual(due("report in 3 weeks"), "2026-11-25")
        self.assertEqual(due("party march 30"), "2027-03-30")
        self.assertEqual(due("party 30 november 2027"), "2027-11-30")
        self.assertEqual(due("tax eom"), "2026-11-30")
        self.assertEqual(due("sync 2026-12-01 17:30"), "2026-12-01T17:30")
        self.assertEqual(due("stand up at 5pm"), "2026-11-04T17:00")

    def test_a_month_end_does_not_spill_over(self):
        self.assertEqual(self.parse("x next month", now=datetime(2027, 1, 31, 8, 0))["due_at"], "2027-02-28")

    def test_the_chosen_date_field_gets_the_date(self):
        found = self.parse("plan tomorrow", field="start")
        self.assertEqual((found["start_at"], found["due_at"]), ("2026-11-05", None))

    def test_only_the_first_date_counts(self):
        found = self.parse("move tomorrow to friday")
        self.assertEqual((found["title"], found["due_at"]), ("move to friday", "2026-11-05"))

    def test_quotes_and_short_weekdays_stay_in_the_title(self):
        found = self.parse('"tomorrow" was sat there')
        self.assertEqual((found["title"], found["due_at"]), ("tomorrow was sat there", None))

    def test_an_unknown_tag_or_priority_is_reported_and_kept_out_of_the_title(self):
        found = self.parse("do it #nope p3")
        self.assertEqual(found["title"], "do it")
        self.assertEqual(found["problems"], ["No tag is named nope", "No priority tag for p3"])


if __name__ == "__main__":
    unittest.main()
