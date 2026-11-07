"""Decides which X-Tasks tasks belong in My Day or under a set of filter tags.

It follows the X-Tasks app's own rules (renderer/views.ts and renderer/rules.ts there), so
the sidebar lists exactly what the app lists. Tasks, tags and rules are the app's JSON shapes.
"""

from datetime import datetime


# Dates -------------------------------------------------------------------------------------------

def parse_date(text):
    """Returns the local time a YYYY-MM-DD or YYYY-MM-DDTHH:MM date names, or None if it is not one."""
    day, _separator, clock = (text or "").partition("T")
    try:
        year, month, day_of_month = (int(part) for part in day.split("-"))
        hours, minutes = (int(part) for part in (clock or "00:00").split(":")[:2])
        return datetime(year, month, day_of_month, hours, minutes)
    except ValueError:
        return None


def has_time(text):
    """Reports whether a task date carries a time of day."""
    return "T" in text


def parse_instant(text):
    """Returns the local time an ISO timestamp such as a task's done_at names, or None if it is not one."""
    try:
        moment = datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def task_date(task, field):
    """Returns the task's start date or due date, whichever the app's settings make its date."""
    return task.get("start_at") if field == "start" else task.get("due_at")


def days_between(first, second):
    """Returns the whole calendar days from one moment to another."""
    return (second.date() - first.date()).days


def is_overdue(text, now):
    """Reports whether a date has passed; a date without a time is overdue only once its day is over."""
    moment = parse_date(text)
    if moment is None:
        return False
    if has_time(text):
        return moment < now
    return moment.date() < now.date()


def due_label(text, now):
    """Returns a short name for a due date, such as Today, Tomorrow or Nov 9, with its time if it has one."""
    moment = parse_date(text)
    if moment is None:
        return ""
    offset = days_between(now, moment)
    names = {-1: "Yesterday", 0: "Today", 1: "Tomorrow"}
    day = names.get(offset) or moment.strftime("%b %-d" if moment.year == now.year else "%b %-d %Y")
    return "%s %s" % (day, moment.strftime("%H:%M")) if has_time(text) else day


# The task board ----------------------------------------------------------------------------------

class Board:
    """Every task and tag, with the lookups a rule needs."""

    def __init__(self, tasks, tags, now=None):
        self.tasks = tasks
        self.tags = tags
        self.now = now or datetime.now()
        self.task_by_id = {task["id"]: task for task in tasks}
        self._chains = {}

    def ancestors(self, task):
        """Returns the task followed by every task above it."""
        chain = [task]
        parent = self.task_by_id.get(task.get("parent_id"))
        while parent is not None and parent not in chain:
            chain.append(parent)
            parent = self.task_by_id.get(parent.get("parent_id"))
        return chain

    def chain_tag_ids(self, task):
        """Returns the tag ids of the task and of every task above it."""
        if task["id"] not in self._chains:
            self._chains[task["id"]] = {tag_id for each in self.ancestors(task)
                                        for tag_id in each.get("tag_ids") or ()}
        return self._chains[task["id"]]

    def subtree_ids(self, tag_id):
        """Returns the tag and every tag below it, at any depth."""
        found = {tag_id}
        pending = [tag_id]
        while pending:
            current = pending.pop()
            for tag in self.tags:
                if tag.get("parent_id") == current and tag["id"] not in found:
                    found.add(tag["id"])
                    pending.append(tag["id"])
        return found

    # Rules ----------------------------------------------------------------------------------

    def has_tag(self, task, tag_id):
        """Reports whether the task holds a tag; a rule tag is held whenever its rule matches."""
        tag = next((each for each in self.tags if each["id"] == tag_id), None)
        if tag is not None and tag.get("rule"):
            return self.rule_matches(tag["rule"], task)
        return tag_id in self.chain_tag_ids(task)

    def rule_matches(self, rule, task):
        """Reports whether a rule's conditions hold for the task, all of them or any."""
        conditions = rule.get("conditions") or []
        if rule.get("match") == "all":
            return all(self.condition_holds(each, task) for each in conditions)
        return not conditions or any(self.condition_holds(each, task) for each in conditions)

    def condition_holds(self, condition, task):
        """Reports whether one rule condition holds for the task."""
        kind = condition.get("kind")
        chain = self.chain_tag_ids(task)

        if kind == "status":
            return bool(task["is_done"]) == condition["is_done"]
        if kind == "tag":
            return bool(self.subtree_ids(condition["tag_id"]) & chain) == condition["has_tag"]
        if kind == "group":
            held = any(tag["group_id"] == condition["group_id"] and tag["id"] in chain
                       for tag in self.tags)
            return held == condition["has_tag"]
        if kind == "due":
            return self._due_holds(condition, task)
        if kind == "start":
            return self._start_holds(condition, task)
        if kind == "completed_within":
            done_at = parse_instant(task.get("done_at"))
            return bool(task["is_done"]) and done_at is not None and \
                days_between(done_at, self.now) < condition["days"]
        if kind == "recurring":
            return bool(task.get("recurrence")) == condition["is_recurring"]
        if kind == "subtask":
            return (task.get("parent_id") is not None) == condition["is_subtask"]
        if kind == "open_subtasks":
            opened = any(each.get("parent_id") == task["id"] and not each["is_done"]
                         for each in self.tasks)
            return opened == condition["has_open"]
        if kind == "tagged":
            return bool(chain) == condition["is_tagged"]
        if kind == "title":
            return condition["text"].strip().lower() in task["title"].lower()
        return False

    def _due_holds(self, condition, task):
        """Reports whether a due date condition holds."""
        when = condition["when"]
        due = task.get("due_at")
        if when == "none":
            return due is None
        moment = parse_date(due) if due else None
        if moment is None:
            return False
        if when == "overdue":
            return is_overdue(due, self.now)
        offset = days_between(self.now, moment)
        if when == "today":
            return offset == 0
        if when == "within_days":
            return 0 <= offset <= condition["days"]
        return True

    def _start_holds(self, condition, task):
        """Reports whether a start date condition holds."""
        when = condition["when"]
        start = task.get("start_at")
        if when == "none":
            return start is None
        moment = parse_date(start) if start else None
        started = moment is not None and moment <= self.now
        if when == "passed_or_none":
            return start is None or started
        return started if when == "started" else not started


# Views -------------------------------------------------------------------------------------------

def my_day_since(settings, today):
    """Returns the earliest day whose My Day tasks still count, or "" when My Day never clears."""
    return today if settings.get("auto_clear_my_day", True) else ""


def due_moment(task, field):
    """Returns the minute a task comes due by its chosen date, as YYYY-MM-DDTHH:MM, or None without one."""
    text = task_date(task, field)
    if not text:
        return None
    return text if has_time(text) else text + "T00:00"


def in_my_day(board, show_done, since, settings=None):
    """Returns the tasks in My Day, which a subtask enters by following its parent.

    With the app's add-due-tasks setting on, a task that came due since the app last looked is
    counted too, since the app puts it in My Day the next time it runs.
    """
    settings = settings or {}
    field = settings.get("task_date_field", "due")
    now = board.now.strftime("%Y-%m-%dT%H:%M")
    after = settings.get("due_added_to_my_day_until") or ""
    adds_due = bool(settings.get("add_due_to_my_day"))

    def added(task):
        day = task.get("my_day_on")
        if day is not None and day >= since:
            return True
        moment = due_moment(task, field) if adds_due and not task["is_done"] else None
        return moment is not None and after < moment <= now

    return [task for task in board.tasks
            if (show_done or not task["is_done"]) and any(added(each) for each in board.ancestors(task))]


def tags_named(names, tags):
    """Returns the tags whose names are in the list, ignoring case, and the names that match none."""
    wanted = {name.strip().lower() for name in names if name.strip()}
    found = [tag for tag in tags if tag["name"].lower() in wanted]
    unknown = sorted(wanted - {tag["name"].lower() for tag in found})
    return found, unknown


def under_filters(board, filter_tags, match, scope, show_done):
    """Returns the tasks holding every one of the tags, or at least one, with the tags below each unless scoped to its own."""
    def holds(task, tag):
        ids = {tag["id"]} if scope == "own" else board.subtree_ids(tag["id"])
        return any(board.has_tag(task, tag_id) for tag_id in ids)

    if not filter_tags:
        return []
    combine = any if match == "any" else all
    return [task for task in board.tasks
            if (show_done or not task["is_done"])
            and combine(holds(task, tag) for tag in filter_tags)]


def outline(visible, board):
    """Returns (task, depth) pairs in reading order, each task under its nearest ancestor that is also shown."""
    shown = {task["id"] for task in visible}
    children = {}
    top = []
    for task in visible:
        parent = board.task_by_id.get(task.get("parent_id"))
        while parent is not None and parent["id"] not in shown:
            parent = board.task_by_id.get(parent.get("parent_id"))
        (children.setdefault(parent["id"], []) if parent else top).append(task)

    pairs = []

    def walk(tasks, depth, seen):
        for task in tasks:
            if task["id"] in seen:
                continue
            pairs.append((task, depth))
            walk(children.get(task["id"], []), depth + 1, seen | {task["id"]})

    walk(top, 0, frozenset())
    return pairs
