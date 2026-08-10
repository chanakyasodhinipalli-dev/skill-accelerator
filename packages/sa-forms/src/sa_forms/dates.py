"""Natural-language date resolution.

Coercion used to accept only fully-written dates, so a speaker who said "next
Friday" or "Aug 15" — both unambiguous to a human — got the same "give me
2026-03-15" rejection three turns running. That is the form behaving like the
form it is supposed to replace.

Resolution here is deterministic and dependency-free: no model call, no
`dateutil`. Every result carries ``inferred``, true when the platform supplied
something the speaker did not actually say — a weekday resolved against today,
or a year filled in for a bare "15 Aug". An inferred date is held for
confirmation rather than accepted silently, because "next Friday" genuinely
means two different dates to two different people, and a change scheduled on
the wrong day is exactly the failure the target-date field exists to prevent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "weds": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

#: Shared with `durations`, which needs the same small vocabulary.
WORD_NUMBERS: dict[str, int] = {
    "a": 1,
    "an": 1,
    "couple": 2,
    "few": 3,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

#: "The last Sunday of September", "first Monday of next month". Release
#: calendars are written this way far more often than as a date.
_ORDINALS: dict[str, int] = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "last": -1,
    "final": -1,
}

_WEEKDAY_ALTERNATION = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_MONTH_ALTERNATION = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ORDINAL_ALTERNATION = "|".join(sorted(_ORDINALS, key=len, reverse=True))
_COUNT = r"\d+|" + "|".join(sorted(WORD_NUMBERS, key=len, reverse=True))


@dataclass(frozen=True, slots=True)
class ResolvedDate:
    """A natural-language date expression, resolved."""

    iso: str
    #: True when the platform supplied part of the answer — the year, or the
    #: reference point a relative expression was measured from. The caller holds
    #: these for confirmation instead of accepting them.
    inferred: bool
    #: The span that produced it, quoted back to the speaker when confirming.
    expression: str


def _next_weekday(reference: date, weekday: int) -> date:
    """The next occurrence strictly after ``reference``.

    "Next Friday" is ambiguous in ordinary speech — the coming Friday to some
    speakers, the Friday of the following week to others. Taking the nearer
    reading and confirming it out loud resolves the ambiguity with the one
    person who can settle it, and surfaces a wrong guess sooner.
    """
    delta = (weekday - reference.weekday()) % 7
    return reference + timedelta(days=delta or 7)


def _end_of_month(reference: date) -> date:
    if reference.month == 12:
        return date(reference.year, 12, 31)
    return date(reference.year, reference.month + 1, 1) - timedelta(days=1)


def _add_months(reference: date, months: int) -> date:
    total = reference.month - 1 + months
    year = reference.year + total // 12
    month = total % 12 + 1
    # Clamp rather than overflow: "in 1 month" from 31 January is end of February.
    last = _end_of_month(date(year, month, 1)).day
    return date(year, month, min(reference.day, last))


def _end_of_quarter(reference: date) -> date:
    final_month = ((reference.month - 1) // 3 + 1) * 3
    return _end_of_month(date(reference.year, final_month, 1))


def _count(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    return WORD_NUMBERS.get(token)


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation that never carries date meaning."""
    return " ".join(re.sub(r"[^\w\s/-]+", " ", text.lower()).split())


def resolve(text: str, *, reference: date | None = None) -> ResolvedDate | None:
    """Resolve a natural-language date expression, or return None.

    Only expressions that denote **one day** resolve. "Next Friday" and "the end
    of the month" each name a specific date; a bare "next quarter" names
    thirteen weeks, and picking a day out of it would invent a precision the
    speaker did not offer. Those still come back as None so the caller asks —
    which is the correct outcome, because the speaker has not decided yet.

    Fully-written dates are the caller's job. This is the layer underneath, for
    the phrasings a strict parser rejects.
    """
    today = reference or date.today()
    lowered = _normalise(text)
    if not lowered:
        return None

    for resolver in (
        _resolve_day_offset,
        # Before the bare weekday and weekend resolvers: "in two weeks on
        # Friday" is one expression, and reading only its second half lands two
        # weeks early.
        _resolve_relative_count,
        _resolve_boundary,
        # Before the bare weekday: "last Sunday of September" is one phrase,
        # and reading only its second word answers with the wrong date.
        _resolve_ordinal_weekday,
        _resolve_weekday,
        _resolve_weekend,
        _resolve_month_day,
    ):
        found = resolver(lowered, today)
        if found is not None:
            return found
    return None


def _hit(value: date, match: re.Match[str], *, inferred: bool = True) -> ResolvedDate:
    return ResolvedDate(iso=value.isoformat(), inferred=inferred, expression=match.group(0))


def _resolve_day_offset(text: str, today: date) -> ResolvedDate | None:
    # Longest phrase first: "day after tomorrow" contains "tomorrow".
    for pattern, offset in (
        (r"\bday after tomorrow\b", 2),
        (r"\btomorrow\b|\btmrw\b", 1),
        (r"\btoday\b", 0),
        (r"\btonight\b", 0),
    ):
        match = re.search(pattern, text)
        if match:
            return _hit(today + timedelta(days=offset), match)
    return None


def _resolve_relative_count(text: str, today: date) -> ResolvedDate | None:
    match = re.search(rf"\bin (?:a |an )?({_COUNT})\s+(?:of\s+)?(day|week|month|year)s?\b", text)
    if not match:
        return None
    amount = _count(match.group(1))
    if amount is None:
        return None
    unit = match.group(2)
    if unit == "day":
        return _hit(today + timedelta(days=amount), match)
    if unit == "week":
        landing = today + timedelta(weeks=amount)
        # "In a couple of weeks over the weekend" names a day, not a week. Both
        # halves are needed to get there, and dropping the second one is how a
        # perfectly clear answer gets asked for four more times.
        named = _named_day_in_week(text, landing)
        return _hit(named or landing, match)
    if unit == "month":
        return _hit(_add_months(today, amount), match)
    return _hit(_add_months(today, amount * 12), match)


def _named_day_in_week(text: str, landing: date) -> date | None:
    """A weekday or "the weekend" mentioned alongside a week offset."""
    monday = landing - timedelta(days=landing.weekday())
    if re.search(r"\bweekends?\b", text):
        return monday + timedelta(days=5)  # Saturday
    match = re.search(rf"\b({_WEEKDAY_ALTERNATION})\b", text)
    if match:
        return monday + timedelta(days=_WEEKDAYS[match.group(1)])
    return None


def _resolve_weekend(text: str, today: date) -> ResolvedDate | None:
    """ "Over the weekend" on its own — the coming Saturday."""
    match = re.search(r"\b(this|next|the|over the|coming)?\s*weekend\b", text)
    if not match:
        return None
    saturday = _next_weekday(today, 5)
    if re.search(r"\bnext weekend\b", text):
        saturday += timedelta(days=7)
    return _hit(saturday, match)


def _resolve_boundary(text: str, today: date) -> ResolvedDate | None:
    """ "end of the month", "start of next week" — checked before bare periods."""
    match = re.search(
        r"\b(end|close|beginning|start)\s+of\s+(?:the\s+)?(this\s+|next\s+)?"
        r"(week|month|quarter|year)\b",
        text,
    )
    if not match:
        return None
    edge, which, unit = match.group(1), (match.group(2) or "").strip(), match.group(3)
    at_end = edge in ("end", "close")

    anchor = today
    if which == "next":
        anchor = {
            "week": today + timedelta(weeks=1),
            "month": _add_months(today, 1),
            "quarter": _add_months(today, 3),
            "year": _add_months(today, 12),
        }[unit]

    if unit == "week":
        # Weeks run Monday to Sunday.
        start = anchor - timedelta(days=anchor.weekday())
        return _hit(start + timedelta(days=6) if at_end else start, match)
    if unit == "month":
        return _hit(_end_of_month(anchor) if at_end else anchor.replace(day=1), match)
    if unit == "quarter":
        end = _end_of_quarter(anchor)
        return _hit(end if at_end else _add_months(end, -2).replace(day=1), match)
    return _hit(date(anchor.year, 12, 31) if at_end else date(anchor.year, 1, 1), match)


def _nth_weekday(year: int, month: int, weekday: int, position: int) -> date | None:
    """The nth (or last) given weekday in a month."""
    if position < 0:
        final = _end_of_month(date(year, month, 1))
        return final - timedelta(days=(final.weekday() - weekday) % 7)
    first = date(year, month, 1)
    day = 1 + (weekday - first.weekday()) % 7 + (position - 1) * 7
    if day > _end_of_month(first).day:
        return None  # there is no fifth Monday in this month
    return date(year, month, day)


def _resolve_ordinal_weekday(text: str, today: date) -> ResolvedDate | None:
    """ "The last Sunday of September", "first Monday of next month".

    Checked before the bare weekday resolver, which would otherwise read only
    the "Sunday" and answer with the next one — an error that reads as a
    confident, specific, wrong date rather than as a failure to understand.
    """
    match = re.search(
        rf"\b({_ORDINAL_ALTERNATION})\s+({_WEEKDAY_ALTERNATION})\s+(?:of|in)\s+"
        rf"(?:the\s+|this\s+|next\s+)?({_MONTH_ALTERNATION}|month|quarter|year)\b",
        text,
    )
    if not match:
        return None

    position = _ORDINALS[match.group(1)]
    weekday = _WEEKDAYS[match.group(2)]
    unit = match.group(3)
    following = bool(re.search(r"\bnext\s+(?:month|quarter|year)\b", text))

    if unit in _MONTHS:
        month, year = _MONTHS[unit], today.year
    elif unit == "month":
        anchor = _add_months(today, 1) if following else today
        month, year = anchor.month, anchor.year
    elif unit == "quarter":
        # The last Sunday *of a quarter* is in the quarter's final month.
        anchor = _end_of_quarter(_add_months(today, 3) if following else today)
        month, year = anchor.month, anchor.year
    else:
        year = today.year + 1 if following else today.year
        month = 12

    for candidate_year in (year, year + 1):
        found = _nth_weekday(candidate_year, month, weekday, position)
        # A named month that has already gone means next year's.
        if found is not None and (found >= today or unit not in _MONTHS):
            return _hit(found, match)
    return None


def _resolve_weekday(text: str, today: date) -> ResolvedDate | None:
    match = re.search(
        rf"\b(?:(next|this|coming|following|on)\s+)?({_WEEKDAY_ALTERNATION})\b",
        text,
    )
    if not match:
        return None
    # "Last Friday" points backwards, and a target date in the past is not what
    # anyone means. Reading it forwards would be a guess dressed as an answer.
    if re.search(rf"\b(last|previous|past)\s+{re.escape(match.group(2))}\b", text):
        return None
    return _hit(_next_weekday(today, _WEEKDAYS[match.group(2)]), match)


def _resolve_month_day(text: str, today: date) -> ResolvedDate | None:
    """ "Aug 15" / "15th August" — a real date missing only its year."""
    match = re.search(rf"\b({_MONTH_ALTERNATION})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", text)
    if match:
        month, day = _MONTHS[match.group(1)], int(match.group(2))
    else:
        match = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALTERNATION})\b", text)
        if not match:
            return None
        month, day = _MONTHS[match.group(2)], int(match.group(1))

    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None  # 31 February is a typo, not a date to guess at
        # A bare month-day in the past almost always means next year — nobody
        # schedules a change for a date that has already gone.
        if candidate >= today:
            return _hit(candidate, match)
    return None


__all__ = ["ResolvedDate", "resolve"]
