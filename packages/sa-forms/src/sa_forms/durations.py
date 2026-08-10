"""How long is it?

Two questions that look different and are the same: "how long will it be down?"
("12 hours", "4-6 hours", "up to 90 minutes") and "how long is the window?"
("08:00-23:00 IST", "Saturday 02:00-04:00"). Both resolve to a number of
minutes, which is what makes them comparable — and comparing them is the point,
because a change that needs longer than the outage it was given is a scheduling
error that nobody notices until the night itself.

This exists because a model was asked to do the comparison and reported that
"the expected downtime of 12 hours exceeds the maintenance window of 8AM to
11PM, which is 15 hours". The reading of both values was right and the
arithmetic was backwards, which is the worst possible failure: a confident,
specific, wrong contradiction that costs the person a turn to refute. Arithmetic
belongs in code.

A range resolves to its **upper bound**. "4-6 hours" has to fit in the window on
its worst day, not its best.
"""

from __future__ import annotations

import re

from .dates import WORD_NUMBERS

#: Minutes per unit, in every spelling operations teams use.
_UNITS: dict[str, float] = {
    "s": 1 / 60,
    "sec": 1 / 60,
    "secs": 1 / 60,
    "second": 1 / 60,
    "seconds": 1 / 60,
    "m": 1,
    "min": 1,
    "mins": 1,
    "minute": 1,
    "minutes": 1,
    "h": 60,
    "hr": 60,
    "hrs": 60,
    "hour": 60,
    "hours": 60,
    "d": 1440,
    "day": 1440,
    "days": 1440,
    "w": 10080,
    "wk": 10080,
    "wks": 10080,
    "week": 10080,
    "weeks": 10080,
}

_UNIT_ALTERNATION = "|".join(sorted(_UNITS, key=len, reverse=True))
_WORD_ALTERNATION = "|".join(sorted(WORD_NUMBERS, key=len, reverse=True))

#: A digit may abut its unit ("2h"); a spelled-out number may not. Without that
#: asymmetry "as soon as possible" parses as nothing — "a" is a word for one and
#: "s" is a word for seconds, and the two sit together inside "as".
_AMOUNT = rf"(?:(?P<num{{n}}>\d+(?:\.\d+)?)\s*|(?P<word{{n}}>{_WORD_ALTERNATION})\s+(?:of\s+)?)"

#: "none", "no downtime", "zero" — a real answer meaning nothing.
_NO_TIME = re.compile(r"^(none|nil|no|zero|0|no downtime|no outage|not expected)$")

#: "4-6 hours", "4 to 6 hours", "between 2 and 3 days". The unit trails both.
_RANGE = re.compile(
    r"\b(?:(?P<lower>\d+(?:\.\d+)?)|(?P<lower_word>" + _WORD_ALTERNATION + r"))\s*"
    r"(?:-|to|and)\s*" + _AMOUNT.format(n="") + rf"(?P<unit>{_UNIT_ALTERNATION})\b"
)

#: "90 minutes", "2 hrs", "three days" — summed, so "1 hour 30 minutes" works.
_QUANTITY = re.compile(r"\b" + _AMOUNT.format(n="") + rf"(?P<unit>{_UNIT_ALTERNATION})\b")

#: "Half an hour" has to be read before the quantity scan, which would
#: otherwise see the "an hour" inside it and answer sixty.
_HALVES: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\bhalf an? (hour|hr)\b"), 30),
    (re.compile(r"\bhalf an? day\b"), 720),
)

#: Set phrases carrying a number without stating one. Checked last: a message
#: that also states a quantity means the quantity.
_PHRASES: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\bovernight\b"), 480),
    (re.compile(r"\ball day\b"), 1440),
)

#: A clock time: 12-hour with a meridiem, or 24-hour with a colon. The branches
#: are ordered so "2:30 PM" is read whole rather than as a bare 2:30.
_CLOCK = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b|\b(\d{1,2}):(\d{2})\b",
    re.I,
)


#: Dash characters people paste in from documents, all meaning "to". Written as
#: escapes because they are visually indistinguishable from a hyphen in source.
_DASHES = str.maketrans(dict.fromkeys([0x2013, 0x2014, 0x2212], "-"))


def _normalise(text: str) -> str:
    return " ".join(text.lower().translate(_DASHES).split())


def _amount(match: re.Match[str]) -> float | None:
    """The number a quantity match carries, digits or words."""
    digits = match.group("num")
    if digits:
        return float(digits)
    word = match.group("word")
    return WORD_NUMBERS.get(word) if word else None


def parse_duration(text: str) -> int | None:
    """A stated length of time, in minutes. None when it says no such thing.

    A range gives its upper bound: "4-6 hours" is six hours of exposure, and
    planning against the four is how a window turns out to be too short.
    """
    lowered = _normalise(text)
    if not lowered:
        return None
    if _NO_TIME.match(lowered):
        return 0

    for pattern, minutes in _HALVES:
        if pattern.search(lowered):
            return round(minutes)

    ranged = _RANGE.search(lowered)
    if ranged:
        upper = _amount(ranged)
        if upper is not None:
            return round(upper * _UNITS[ranged.group("unit")])

    total = 0.0
    matched = False
    for match in _QUANTITY.finditer(lowered):
        amount = _amount(match)
        if amount is None:
            continue
        total += amount * _UNITS[match.group("unit")]
        matched = True
    if matched:
        return round(total)

    for pattern, minutes in _PHRASES:
        if pattern.search(lowered):
            return round(minutes)
    return None


def _clock_minutes(text: str) -> list[int]:
    """Every clock time in the text, as minutes past midnight."""
    found: list[int] = []
    for match in _CLOCK.finditer(text):
        if match.group(3):  # 12-hour
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            if hour > 12 or minute > 59:
                continue
            if match.group(3).lower() == "a":
                hour = 0 if hour == 12 else hour
            elif hour != 12:
                hour += 12
        else:
            hour, minute = int(match.group(4)), int(match.group(5))
            if hour > 23 or minute > 59:
                continue
        found.append(hour * 60 + minute)
    return found


def parse_window(text: str) -> int | None:
    """The length of a stated time range, in minutes.

    Two clock times are enough. A range that ends before it starts has crossed
    midnight, which is what a maintenance window usually does.
    """
    times = _clock_minutes(text)
    if len(times) < 2:
        return None
    span = (times[1] - times[0]) % 1440
    # Identical times say nothing usable: a zero-length window and a
    # round-the-clock one look the same from here.
    return span or None


def span_minutes(text: str) -> int | None:
    """How long the text describes, however it describes it.

    A stated length wins over a stated range, because "a 4 hour window starting
    at 22:00" means four hours and there is only one clock time to argue with.
    """
    if not text or not text.strip():
        return None
    return parse_duration(text) if parse_duration(text) is not None else parse_window(text)


def render_minutes(minutes: int) -> str:
    """Minutes as a person would say them, for quoting back in a question."""
    if minutes <= 0:
        return "none"
    parts: list[str] = []
    for label, size in (("day", 1440), ("hour", 60), ("minute", 1)):
        whole, minutes = divmod(minutes, size)
        if whole:
            parts.append(f"{whole} {label}{'s' if whole > 1 else ''}")
    return " ".join(parts)


__all__ = [
    "parse_duration",
    "parse_window",
    "render_minutes",
    "span_minutes",
]
