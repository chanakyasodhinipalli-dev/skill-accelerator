"""Value coercion and validation.

The extractor returns every value as text, because asking a model for a
polymorphic JSON value across a dozen field types produces brittle output and
schema-union headaches. Coercion back to the declared type happens here, in
deterministic code, where it can be tested exhaustively.

That split matters: the model does language, this module does types.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sa_platform.errors import ValidationError

from .dates import resolve as resolve_date_expression
from .models import FieldType, FormField

# Words people actually use for yes/no in chat and ticket comments.
_TRUE_TOKENS = frozenset(
    {"true", "yes", "y", "1", "on", "enabled", "required", "approved", "affirmative"}
)
_FALSE_TOKENS = frozenset(
    {"false", "no", "n", "0", "off", "disabled", "not required", "none", "negative"}
)

# Values that mean "the speaker addressed this and there is nothing to record".
_NULL_TOKENS = frozenset({"", "n/a", "na", "none", "null", "unknown", "tbd", "not applicable", "-"})

# A bare yes/no is an answer to *some* question, but never the value of a
# free-text field. Storing it produces records like "Tracking ticket: yes",
# which read as answered and are worth nothing to the approver who has to act
# on them — worse than an empty field, which at least becomes an action item.
_BARE_ACKNOWLEDGEMENT = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "ya",
        "sure",
        "ok",
        "okay",
        "correct",
        "right",
        "affirmative",
        "confirmed",
        "done",
        "no",
        "nope",
        "nah",
        "negative",
    }
)

# First-person references. "Change owner: myself" names nobody: the artifact
# outlives the conversation, and whoever reads it at 2am cannot resolve it back
# to a person. Extraction substitutes the speaker's identity where it knows one;
# this is the backstop for when it does not.
_SELF_REFERENCE = frozenset(
    {
        "me",
        "myself",
        "i",
        "my self",
        "self",
        "mine",
        "us",
        "we",
        "our team",
        "my team",
        "same",
        "same as above",
        "same as me",
        "as above",
        "ditto",
    }
)

_GROUP_NOUNS = r"team|squad|group|crew|pod|guild|chapter|tribe|desk|unit|folks|people|side"

# "My team", "our scrum team" — a group identified only by its relationship to
# whoever is typing. Perfectly clear in the conversation and unresolvable the
# moment it ends, which is exactly when the artifact starts being read.
_POSSESSIVE_GROUP = re.compile("^(my|our)\\s+(\\w+\\s+)*(" + _GROUP_NOUNS + ")s?$", re.I)

# "The team", "this group" — a group noun with nothing naming it. A *named*
# team is a different thing entirely and is accepted: plenty of responsibilities
# genuinely sit with "Platform Support" rather than with any one person.
_UNNAMED_GROUP = re.compile(rf"^(the|this|that|a|an)\s+({_GROUP_NOUNS})s?$", re.I)

# Job titles standing in for a person. "The DBA" is a rota, not someone you can
# call, and by the time anyone reads the record they cannot tell which one.
_ROLE_ONLY = re.compile(
    r"^(the|a|an)?\s*(dba|sre|devops|admin|architect|manager|lead|owner|on.?call|"
    r"support|ops|platform|security|qa|tester|developer|engineer|analyst|scrum master)s?"
    # "The developer of iDocs" names a post, not a person. The qualifier makes
    # it sound specific and changes nothing: posts are held by whoever is in
    # them this quarter.
    r"(\s+(of|for|from|in|on|at)\s+.+)?$",
    re.I,
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y/%m/%d",
)
_DATETIME_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL_RE = re.compile(r"https?://\S+")
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")

#: A clock time in any of the shapes people type.
_CLOCK_TIME = re.compile(r"\b(\d{1,2}:\d{2}|\d{1,2}\s*[ap]\.?m\.?)\b", re.I)

#: Zone designators worth recognising: the abbreviations operations teams
#: actually write, an explicit offset, or an IANA name.
_TIMEZONE = re.compile(
    r"\b(utc|gmt|z|ist|bst|cet|cest|eet|eest|wet|"
    r"est|edt|cst|cdt|mst|mdt|pst|pdt|akst|hst|"
    r"jst|kst|sgt|hkt|awst|acst|aest|aedt|nzst|nzdt|msk|sast|brt|art)\b"
    r"|\b(?:utc|gmt)\s*[+-]\s*\d{1,2}(?::?\d{2})?\b"
    r"|(?<!\d)[+-]\d{2}:?\d{2}\b"
    r"|\b[A-Za-z]+/[A-Za-z_]+\b",
    re.I,
)


def states_a_time(text: str) -> bool:
    return bool(_CLOCK_TIME.search(text))


def states_a_timezone(text: str) -> bool:
    return bool(_TIMEZONE.search(text))


class CoercionError(ValidationError):
    """The stated value cannot be represented as the field's declared type."""


def is_null_token(raw: str | None) -> bool:
    return raw is None or raw.strip().lower() in _NULL_TOKENS


def coerce(field: FormField, raw: Any) -> Any:
    """Convert a stated value into the field's declared type.

    Raises :class:`CoercionError` when the text cannot represent the type — the
    caller turns that into a clarifying question rather than storing garbage.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        # Already structured (an import, or a model that returned real JSON).
        return _validate_structured(field, raw)

    text = raw.strip()
    if is_null_token(text):
        return None

    handler = {
        FieldType.STRING: _coerce_string,
        FieldType.TEXT: _coerce_string,
        FieldType.PERSON: _coerce_person,
        FieldType.DURATION: _coerce_string,
        FieldType.INTEGER: _coerce_integer,
        FieldType.NUMBER: _coerce_number,
        FieldType.CURRENCY: _coerce_number,
        FieldType.BOOLEAN: _coerce_boolean,
        FieldType.DATE: _coerce_date,
        FieldType.DATETIME: _coerce_datetime,
        FieldType.ENUM: _coerce_enum,
        FieldType.MULTI_ENUM: _coerce_multi_enum,
        FieldType.LIST: _coerce_list,
        FieldType.OBJECT: _coerce_object,
        FieldType.EMAIL: _coerce_email,
        FieldType.URL: _coerce_url,
    }[field.type]

    return handler(field, text)


# ---------------------------------------------------------------------------
# Per-type handlers
# ---------------------------------------------------------------------------


def _bare_token(text: str) -> str:
    return text.lower().strip(" .!,;:'\"")


def _coerce_string(field: FormField, text: str) -> str:
    if _bare_token(text) in _BARE_ACKNOWLEDGEMENT:
        raise CoercionError(
            f"'{field.label}' needs an actual value rather than a yes or no"
            + (f" — for example {field.examples[0]!r}." if field.examples else "."),
            details={"field": field.id, "raw": text, "reason": "bare_acknowledgement"},
        )
    if field.requires_timezone and states_a_time(text) and not states_a_timezone(text):
        raise CoercionError(
            f"'{field.label}' states a time but no timezone — which zone is "
            f"'{text}' in? Anyone reading this in another region has to guess, and "
            "the guess is wrong by hours.",
            details={"field": field.id, "raw": text, "reason": "timezone_missing"},
        )
    return text


def _coerce_person(field: FormField, text: str) -> str:
    """A person field must end up holding a name somebody can be paged by."""
    token = _bare_token(text)
    if token in _BARE_ACKNOWLEDGEMENT:
        return _coerce_string(field, text)
    if token in _SELF_REFERENCE:
        raise CoercionError(
            f"'{field.label}' needs a name — '{text}' doesn't identify anyone to "
            "whoever reads this later.",
            details={"field": field.id, "raw": text, "reason": "self_reference"},
        )
    # A responsibility may sit with a person or with a team — but either way it
    # has to be *named*. What is refused is anything that identifies nobody once
    # the conversation is over: a group known only as "mine", or a post that
    # will be held by someone else next quarter.
    if field.requires_named_party:
        if _POSSESSIVE_GROUP.match(token) or _UNNAMED_GROUP.match(token):
            raise CoercionError(
                f"'{field.label}' needs a name — either a person or the team's actual "
                f"name. '{text}' identifies nobody once this conversation is over.",
                details={"field": field.id, "raw": text, "reason": "unnamed_group"},
            )
        if _ROLE_ONLY.match(token):
            raise CoercionError(
                f"'{field.label}' needs a name rather than a role — '{text}' will be a "
                "different person by the time anyone reads this.",
                details={"field": field.id, "raw": text, "reason": "role_not_named"},
            )
    return text


def _coerce_integer(field: FormField, text: str) -> int:
    match = _NUMBER_RE.search(text)
    if not match:
        raise CoercionError(
            f"'{field.label}' expects a whole number but got {text!r}",
            details={"field": field.id, "raw": text},
        )
    cleaned = match.group().replace(",", "")
    try:
        return int(float(cleaned))
    except ValueError as exc:
        raise CoercionError(
            f"'{field.label}' expects a whole number but got {text!r}",
            details={"field": field.id, "raw": text},
            cause=exc,
        ) from exc


def _coerce_number(field: FormField, text: str) -> float:
    match = _NUMBER_RE.search(text)
    if not match:
        raise CoercionError(
            f"'{field.label}' expects a number but got {text!r}",
            details={"field": field.id, "raw": text},
        )
    try:
        return float(match.group().replace(",", ""))
    except ValueError as exc:
        raise CoercionError(
            f"'{field.label}' expects a number but got {text!r}",
            details={"field": field.id, "raw": text},
            cause=exc,
        ) from exc


def _coerce_boolean(field: FormField, text: str) -> bool:
    lowered = text.lower().strip(" .!")
    if lowered in _TRUE_TOKENS:
        return True
    if lowered in _FALSE_TOKENS:
        return False
    # Fall back to a leading-token check so "yes, definitely" still resolves.
    head = lowered.split(",")[0].split()[0] if lowered.split() else ""
    if head in _TRUE_TOKENS:
        return True
    if head in _FALSE_TOKENS:
        return False
    raise CoercionError(
        f"'{field.label}' expects yes or no but got {text!r}",
        details={"field": field.id, "raw": text},
    )


def _parse_date(text: str, formats: tuple[str, ...]) -> datetime | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _coerce_date(field: FormField, text: str) -> str:
    # Prefer an embedded ISO date; speakers often wrap it in prose.
    iso = re.search(r"\d{4}-\d{2}-\d{2}", text)
    candidate = iso.group() if iso else text
    parsed = _parse_date(candidate, _DATE_FORMATS)
    if parsed is None:
        parsed = _parse_date(candidate, _DATETIME_FORMATS)
    if parsed is not None:
        return parsed.date().isoformat()

    # Nothing fully written. Before rejecting, try the phrasings people
    # actually use — "next Friday", "Aug 15", "end of the month". Refusing
    # these is how a conversation turns into a form.
    resolved = resolve_date_expression(text)
    if resolved is not None:
        return resolved.iso

    raise CoercionError(
        f"'{field.label}' expects a date but got {text!r}. "
        "Give a concrete date such as 2026-03-15.",
        details={"field": field.id, "raw": text},
    )


def date_is_inferred(field: FormField, raw: Any) -> bool:
    """True when coercing ``raw`` would resolve a date the speaker didn't fully state.

    "Next Friday" and "Aug 15" are answers, so they are accepted — but the year
    or the reference point came from here, not from the speaker. The caller
    lowers confidence on that basis, which routes the value through
    confirmation instead of straight into the record.
    """
    if field.type not in (FieldType.DATE, FieldType.DATETIME) or not isinstance(raw, str):
        return False
    text = raw.strip()
    if not text or is_null_token(text):
        return False
    if re.search(r"\d{4}-\d{2}-\d{2}", text):
        return False
    if _parse_date(text, _DATE_FORMATS) or _parse_date(text, _DATETIME_FORMATS):
        return False
    resolved = resolve_date_expression(text)
    return resolved is not None and resolved.inferred


def _coerce_datetime(field: FormField, text: str) -> str:
    parsed = _parse_date(text, _DATETIME_FORMATS) or _parse_date(text, _DATE_FORMATS)
    if parsed is None:
        raise CoercionError(
            f"'{field.label}' expects a date and time but got {text!r}",
            details={"field": field.id, "raw": text},
        )
    return parsed.isoformat()


def _match_option(field: FormField, text: str) -> str | None:
    """Resolve free text to a declared option, tolerating case and spacing."""
    normalised = re.sub(r"[\s_-]+", " ", text.strip().lower())
    for option in field.options:
        if re.sub(r"[\s_-]+", " ", option.lower()) == normalised:
            return option
    # Substring match, but only when unambiguous — a partial match against two
    # options is worse than admitting we do not know.
    partial = [
        o
        for o in field.options
        if re.sub(r"[\s_-]+", " ", o.lower()) in normalised
        or normalised in re.sub(r"[\s_-]+", " ", o.lower())
    ]
    return partial[0] if len(partial) == 1 else None


def _coerce_enum(field: FormField, text: str) -> str:
    matched = _match_option(field, text)
    if matched is None:
        raise CoercionError(
            f"'{field.label}' must be one of: {', '.join(field.options)}. Got {text!r}.",
            details={"field": field.id, "raw": text, "options": field.options},
        )
    return matched


def _split_list(text: str) -> list[str]:
    """Split a stated list on the separators people actually use."""
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except json.JSONDecodeError:
            pass
    parts = re.split(r"[,;\n]|\band\b|\|", stripped)
    return [p.strip(" .-•\t") for p in parts if p.strip(" .-•\t")]


def _coerce_multi_enum(field: FormField, text: str) -> list[str]:
    resolved: list[str] = []
    unmatched: list[str] = []
    for token in _split_list(text):
        matched = _match_option(field, token)
        if matched is None:
            unmatched.append(token)
        elif matched not in resolved:
            resolved.append(matched)
    if unmatched:
        raise CoercionError(
            f"'{field.label}' does not allow: {', '.join(unmatched)}. "
            f"Allowed values: {', '.join(field.options)}.",
            details={"field": field.id, "unmatched": unmatched, "options": field.options},
        )
    return resolved


def _coerce_list(field: FormField, text: str) -> list[str]:
    items = _split_list(text)
    if not items:
        raise CoercionError(
            f"'{field.label}' expects one or more items but got {text!r}",
            details={"field": field.id, "raw": text},
        )
    return items


def _coerce_object(field: FormField, text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CoercionError(
            f"'{field.label}' expects structured JSON but got {text!r}",
            details={"field": field.id, "raw": text},
            cause=exc,
        ) from exc
    if not isinstance(parsed, dict):
        raise CoercionError(f"'{field.label}' expects a JSON object", details={"field": field.id})
    return parsed


def _coerce_email(field: FormField, text: str) -> str:
    match = _EMAIL_RE.search(text)
    if not match:
        raise CoercionError(
            f"'{field.label}' expects an email address but got {text!r}",
            details={"field": field.id, "raw": text},
        )
    return match.group().lower()


def _coerce_url(field: FormField, text: str) -> str:
    match = _URL_RE.search(text)
    if not match:
        raise CoercionError(
            f"'{field.label}' expects a URL but got {text!r}",
            details={"field": field.id, "raw": text},
        )
    return match.group().rstrip(".,);")


def _validate_structured(field: FormField, value: Any) -> Any:
    """Light checking for values that arrived already typed (imports)."""
    if field.type in (FieldType.LIST, FieldType.MULTI_ENUM) and not isinstance(value, list):
        return [value]
    if field.type is FieldType.OBJECT and not isinstance(value, dict):
        raise CoercionError(f"'{field.label}' expects an object", details={"field": field.id})
    return value


# ---------------------------------------------------------------------------
# Post-coercion validation
# ---------------------------------------------------------------------------


def validate_value(field: FormField, value: Any) -> None:
    """Apply the field's declared constraints. Raises on violation."""
    rules = field.validation
    if rules is None or value is None:
        return

    if isinstance(value, str):
        if rules.min_length is not None and len(value) < rules.min_length:
            raise CoercionError(
                f"'{field.label}' must be at least {rules.min_length} characters",
                details={"field": field.id},
            )
        if rules.max_length is not None and len(value) > rules.max_length:
            raise CoercionError(
                f"'{field.label}' must be at most {rules.max_length} characters",
                details={"field": field.id},
            )
        if rules.pattern and not re.search(rules.pattern, value):
            raise CoercionError(
                f"'{field.label}' is not in the expected format",
                details={"field": field.id, "pattern": rules.pattern},
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if rules.minimum is not None and value < rules.minimum:
            raise CoercionError(
                f"'{field.label}' must be at least {rules.minimum}", details={"field": field.id}
            )
        if rules.maximum is not None and value > rules.maximum:
            raise CoercionError(
                f"'{field.label}' must be at most {rules.maximum}", details={"field": field.id}
            )

    if isinstance(value, list):
        if rules.min_items is not None and len(value) < rules.min_items:
            raise CoercionError(
                f"'{field.label}' needs at least {rules.min_items} item(s)",
                details={"field": field.id},
            )
        if rules.max_items is not None and len(value) > rules.max_items:
            raise CoercionError(
                f"'{field.label}' accepts at most {rules.max_items} item(s)",
                details={"field": field.id},
            )


def coerce_and_validate(field: FormField, raw: Any) -> Any:
    """Coerce then validate. The single entry point callers should use."""
    value = coerce(field, raw)
    validate_value(field, value)
    return value


def render_value(field: FormField, value: Any) -> str:
    """Human-readable rendering for artifacts and confirmation prompts."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float) and field.type is FieldType.CURRENCY:
        return f"{value:,.2f} {field.unit}".strip()
    if field.unit and field.type in (FieldType.NUMBER, FieldType.INTEGER, FieldType.DURATION):
        return f"{value} {field.unit}"
    return str(value)


__all__ = [
    "CoercionError",
    "coerce",
    "coerce_and_validate",
    "date_is_inferred",
    "is_null_token",
    "render_value",
    "states_a_time",
    "states_a_timezone",
    "validate_value",
]
