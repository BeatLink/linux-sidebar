"""Reads a typed task the way the X-Tasks app's Todoist quick-add syntax does (renderer syntax/todoist.ts).

A #tag or @tag names a tag, p1 to p4 name a priority, and a date or time anywhere in the text sets
the task's date. A "quoted phrase" is left alone, and every other word makes the title. The app's
repeats, such as "every monday", are not read here.
"""

import re
from datetime import datetime, timedelta

WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
MONTH_ABBREVIATIONS = {"jan": 0, "feb": 1, "mar": 2, "apr": 3, "jun": 5, "jul": 6, "aug": 7,
                       "sep": 8, "sept": 8, "oct": 9, "nov": 10, "dec": 11}
SHORT_WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "tues": 2, "wed": 3, "thu": 4, "thur": 4,
                  "thurs": 4, "fri": 5, "sat": 6}
UNIT = re.compile(r"^(day|week|month|year)s?$")

# The longest a day phrase runs, as in "in 3 weeks" or "march 30 2027".
LONGEST_DAY_PHRASE = 3


# Days --------------------------------------------------------------------------------------------

def today_of(now):
    """Returns midnight at the start of the day."""
    return datetime(now.year, now.month, now.day)


def js_weekday(day):
    """Returns the weekday with Sunday as 0, as the app counts them."""
    return (day.weekday() + 1) % 7


def add_days(day, days):
    """Returns the day a number of days on."""
    return day + timedelta(days=days)


def add_months(day, months):
    """Adds months, landing on the last day of a shorter month rather than spilling into the next."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    first_of_next = datetime(year + (month == 12), month % 12 + 1, 1)
    last = (first_of_next - timedelta(days=1)).day
    return datetime(year, month, min(day.day, last))


def add_units(day, amount, unit):
    """Adds days, weeks, months or years, named as the app names them."""
    if unit.startswith("day"):
        return add_days(day, amount)
    if unit.startswith("week"):
        return add_days(day, amount * 7)
    if unit.startswith("month"):
        return add_months(day, amount)
    return add_months(day, amount * 12)


def next_weekday(weekday, now):
    """Returns the next day after today falling on the weekday."""
    today = today_of(now)
    return add_days(today, (weekday - js_weekday(today)) % 7 or 7)


def real_day(year, month, day):
    """Returns the day if it exists, or None."""
    try:
        return datetime(year, month + 1, day)
    except ValueError:
        return None


def next_month_day(month, day, now):
    """Returns the next time a day without a year comes round, today included."""
    today = today_of(now)
    this_year = real_day(today.year, month, day)
    if this_year is None:
        return None
    return this_year if this_year >= today else real_day(today.year + 1, month, day)


def month_of(word):
    """Returns the month a word names, January as 0, or None."""
    if word in MONTHS:
        return MONTHS.index(word)
    return MONTH_ABBREVIATIONS.get(word)


def day_number_of(word):
    """Returns the day of the month in a word such as 27 or 27th, or None."""
    match = re.match(r"^(\d{1,2})(st|nd|rd|th)?,?$", word)
    day = int(match.group(1)) if match else 0
    return day if 1 <= day <= 31 else None


def read_day(words, now):
    """Returns the day all of the words name, such as tomorrow, next friday or in 3 weeks, or None."""
    today = today_of(now)
    first, second, third = (list(words) + ["", "", ""])[:3]

    if len(words) == 1:
        if first in ("today", "tod"):
            return today
        if first in ("tomorrow", "tmr", "tom"):
            return add_days(today, 1)
        if first == "yesterday":
            return add_days(today, -1)
        if first == "eom":
            return add_months(today.replace(day=1), 1) - timedelta(days=1)
        if first in WEEKDAYS:
            return next_weekday(WEEKDAYS.index(first), now)
        match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", first)
        return real_day(int(match[1]), int(match[2]) - 1, int(match[3])) if match else None

    if len(words) == 2 and first in ("next", "this"):
        if UNIT.match(second) and first == "next":
            return add_units(today, 1, second)
        weekday = WEEKDAYS.index(second) if second in WEEKDAYS else SHORT_WEEKDAYS.get(second)
        return next_weekday(weekday, now) if weekday is not None else None

    if len(words) == 3 and first == "in" and re.match(r"^\d+$", second) and UNIT.match(third):
        return add_units(today, int(second), third)
    if " ".join(words) == "end of month":
        return add_months(today.replace(day=1), 1) - timedelta(days=1)

    # "march 30", "30 march", either with a year after it.
    if len(words) in (2, 3):
        year = None
        if len(words) == 3:
            if not re.match(r"^\d{4}$", third):
                return None
            year = int(third)
        month_first = month_of(first.rstrip("."))
        day_first = day_number_of(first)
        if month_first is not None:
            month, day = month_first, day_number_of(second)
        elif day_first is not None:
            month, day = month_of(second), day_first
        else:
            return None
        if month is None or day is None:
            return None
        return next_month_day(month, day, now) if year is None else real_day(year, month, day)
    return None


# Times -------------------------------------------------------------------------------------------

def read_time(word):
    """Returns (hours, minutes) for a time such as 5pm, 5:30pm, 17:00 or noon, or None."""
    if word == "noon":
        return 12, 0
    if word == "midnight":
        return 0, 0
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)$", word)
    if match:
        hours, minutes = int(match[1]), int(match[2] or 0)
        if not 1 <= hours <= 12 or minutes > 59:
            return None
        return hours % 12 + (12 if match[3] == "pm" else 0), minutes
    match = re.match(r"^(\d{1,2}):(\d{2})$", word)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    return int(match[1]), int(match[2])


def read_time_at(words):
    """Returns ((hours, minutes), words used) for "at 5pm" or "5pm" at the front of the words, or None."""
    has_at = bool(words) and words[0] == "at"
    index = 1 if has_at else 0
    time = read_time(words[index]) if index < len(words) else None
    return (time, index + 1) if time else None


def find_task_date(words, start, now):
    """Returns (date text, words used) for the date starting at a word, or None; a time alone means today."""
    for length in range(min(LONGEST_DAY_PHRASE, len(words) - start), 0, -1):
        day = read_day(words[start:start + length], now)
        if day is None:
            continue
        found = read_time_at(words[start + length:])
        if found is None:
            return day.strftime("%Y-%m-%d"), length
        (hours, minutes), used = found
        return day.replace(hour=hours, minute=minutes).strftime("%Y-%m-%dT%H:%M"), length + used
    found = read_time_at(words[start:])
    if found is None:
        return None
    (hours, minutes), used = found
    return today_of(now).replace(hour=hours, minute=minutes).strftime("%Y-%m-%dT%H:%M"), used


# Tags --------------------------------------------------------------------------------------------

def name_key(name):
    """Returns a name without case, spaces, dashes or underscores, so #kitchen_renovation finds "Kitchen renovation"."""
    return re.sub(r"[\s_-]+", "", name.lower())


def tag_named(name, tags, groups):
    """Returns the first plain tag with the name, in sidebar order, or None."""
    order = {group["id"]: index for index, group in enumerate(groups)}
    found = [tag for tag in tags if name_key(tag["name"]) == name_key(name) and not tag.get("rule")]
    found.sort(key=lambda tag: (order.get(tag["group_id"], -1), tag.get("position", 0)))
    return found[0] if found else None


def priority_tag(rank, tags, groups):
    """Returns the tag a priority number names, 1 the highest, or None."""
    group = next((each for each in groups
                  if each.get("is_single_choice") and re.match(r"(?i)priority", each["name"])), None)
    if group is None:
        return None
    ranks = sorted((tag for tag in tags if tag["group_id"] == group["id"] and tag.get("parent_id") is None),
                   key=lambda tag: tag.get("position", 0))
    return ranks[rank - 1] if rank <= len(ranks) else None


def with_tag(tag_ids, tag, tags, groups):
    """Returns the tag ids with the tag added; a single-choice group's tag takes the place of its other one."""
    if tag["id"] in tag_ids:
        return tag_ids
    single = any(group["id"] == tag["group_id"] and group.get("is_single_choice") for group in groups)
    by_id = {each["id"]: each for each in tags}
    kept = [each for each in tag_ids
            if not single or by_id.get(each, {}).get("group_id") != tag["group_id"]]
    return kept + [tag["id"]]


# Quick add ---------------------------------------------------------------------------------------

def parse_quick_add(text, tags, groups, date_field, now):
    """Returns {"title", "tag_ids", "start_at", "due_at", "problems"} for what was typed."""
    words = [(match[1], True) if match[1] is not None else (match[2], False)
             for match in re.finditer(r'"([^"]*)"|(\S+)', text)]
    # A quoted phrase never reads as a date, so it stands in as a word no date contains.
    lowers = ['"' if literal else word.lower() for word, literal in words]
    title = []
    result = {"tag_ids": [], "start_at": None, "due_at": None, "problems": []}
    has_date = False

    index = 0
    while index < len(words):
        word, literal = words[index]
        index += 1
        if literal:
            title.append(word)
        elif re.match(r"^[#@].+", word):
            tag = tag_named(word[1:], tags, groups)
            if tag:
                result["tag_ids"] = with_tag(result["tag_ids"], tag, tags, groups)
            else:
                result["problems"].append("No tag is named %s" % word[1:])
        elif re.match(r"^p[1-4]$", word.lower()):
            rank = int(word[1])
            tag = priority_tag(rank, tags, groups)
            if tag:
                result["tag_ids"] = with_tag(result["tag_ids"], tag, tags, groups)
            elif rank != 4:
                result["problems"].append("No priority tag for %s" % word)
        else:
            found = None if has_date else find_task_date(lowers, index - 1, now)
            if found is None:
                title.append(word)
                continue
            date, used = found
            result["start_at" if date_field == "start" else "due_at"] = date
            has_date = True
            index += used - 1

    result["title"] = re.sub(r"\s+", " ", " ".join(title)).strip()
    return result
