"""Safe expression resolution for workflow bindings.

Workflow definitions are data, not code. Expressions are therefore restricted
to path lookups plus a small set of comparison and boolean operators — there is
no ``eval``, no attribute access on Python objects, and no way for a workflow
author (or an LLM that generated one) to execute arbitrary code.

Supported syntax::

    ${inputs.customer_id}
    ${steps.fetch_profile.output.email}
    ${item.name}                       # inside a map step
    ${steps.score.output.value > 0.8}  # comparison
    ${inputs.mode == "strict" and steps.a.output.ok}
    ${(inputs.tier == "gold" or inputs.tier == "platinum") and inputs.active}

Boolean composition binds ``or`` loosest, then ``and``, then ``not``.
Parentheses group, and are honoured inside quotes and at any depth — splitting
blindly would tear a grouped clause into fragments with unbalanced brackets,
each of which resolves to ``None`` and reads as false.

Literal strings pass through untouched; a whole-string expression preserves the
resolved value's type, while an interpolated one renders to text.
"""

from __future__ import annotations

import re
from typing import Any

from sa_platform.errors import ValidationError

# ${ ... } with no nesting.
_EXPRESSION = re.compile(r"\$\{([^{}]+)\}")
# A whole string that is exactly one expression.
_WHOLE = re.compile(r"^\s*\$\{([^{}]+)\}\s*$")

_COMPARISONS = ("==", "!=", ">=", "<=", ">", "<")


def _lookup(path: str, scope: dict[str, Any]) -> Any:
    """Resolve a dotted path, supporting numeric list indices.

    A missing segment resolves to ``None`` rather than raising: an optional
    upstream output should not abort the whole run.
    """
    current: Any = scope
    for segment in path.split("."):
        segment = segment.strip()
        if not segment:
            continue
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, (list, tuple)) and segment.lstrip("-").isdigit():
            index = int(segment)
            current = current[index] if -len(current) <= index < len(current) else None
        else:
            # Deliberately not getattr(): workflow data is plain JSON, and
            # attribute access would open a path to Python internals.
            return None
        if current is None:
            return None
    return current


def _parse_literal(token: str) -> tuple[bool, Any]:
    """Try to read a token as a literal. Returns ``(matched, value)``."""
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return True, token[1:-1]
    lowered = token.lower()
    if lowered in ("true", "false"):
        return True, lowered == "true"
    if lowered in ("null", "none"):
        return True, None
    try:
        return True, int(token)
    except ValueError:
        pass
    try:
        return True, float(token)
    except ValueError:
        pass
    return False, None


def _resolve_operand(token: str, scope: dict[str, Any]) -> Any:
    matched, value = _parse_literal(token)
    return value if matched else _lookup(token.strip(), scope)


def _compare(left: Any, operator: str, right: Any) -> bool:
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    try:
        if operator == ">":
            return left > right
        if operator == "<":
            return left < right
        if operator == ">=":
            return left >= right
        if operator == "<=":
            return left <= right
    except TypeError as exc:
        raise ValidationError(
            f"cannot compare {type(left).__name__} with {type(right).__name__} using '{operator}'",
            cause=exc,
        ) from exc
    raise ValidationError(f"unsupported operator '{operator}'")


def _split_top_level(body: str, keyword: str) -> list[str]:
    """Split on ``keyword`` where it appears outside parentheses and quotes.

    Depth-awareness is what makes grouping mean anything. Splitting blindly
    tears ``(a == 1 or b == 2) and c`` apart at the ``or``, leaving two
    fragments with unbalanced brackets — both of which resolve to ``None`` and
    read as false. The rule then never fires, and a check that silently never
    fires is worse than no check at all.
    """
    parts: list[str] = []
    depth = 0
    quote = ""
    start = 0
    index = 0
    token = f" {keyword} "

    while index < len(body):
        char = body[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in ("'", '"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValidationError(f"unbalanced ')' in expression: {body!r}")
        elif depth == 0 and body.startswith(token, index):
            parts.append(body[start:index])
            index += len(token)
            start = index
            continue
        index += 1

    if depth != 0:
        raise ValidationError(f"unbalanced '(' in expression: {body!r}")
    parts.append(body[start:])
    return parts


def _strip_grouping(body: str) -> str:
    """Remove one fully-enclosing pair of parentheses, if present."""
    while body.startswith("(") and body.endswith(")"):
        # Only strip when the opening bracket is the one that closes at the end;
        # `(a) and (b)` must survive intact.
        depth = 0
        for index, char in enumerate(body):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    if index != len(body) - 1:
                        return body
                    break
        body = body[1:-1].strip()
    return body


def _evaluate(expression: str, scope: dict[str, Any]) -> Any:
    """Evaluate one expression body (the text inside ``${...}``)."""
    body = _strip_grouping(expression.strip())
    if not body:
        return None

    # Boolean composition binds loosest: split on ` or ` first, then ` and `.
    for keyword, combine in (("or", any), ("and", all)):
        parts = _split_top_level(body, keyword)
        if len(parts) > 1:
            return combine(bool(_evaluate(part, scope)) for part in parts)

    if body.startswith("not "):
        return not bool(_evaluate(body[4:], scope))

    for operator in _COMPARISONS:
        # Split on the first occurrence only, so `a == b == c` is a clear error
        # rather than silently mis-parsed.
        index = body.find(operator)
        if index > 0:
            left = _resolve_operand(body[:index], scope)
            right = _resolve_operand(body[index + len(operator) :], scope)
            return _compare(left, operator, right)

    return _resolve_operand(body, scope)


def resolve(value: Any, scope: dict[str, Any]) -> Any:
    """Recursively resolve expressions in a value of any shape.

    A string that is *entirely* one expression keeps the resolved type (a dict
    stays a dict); a string with embedded expressions is rendered to text.
    """
    if isinstance(value, str):
        whole = _WHOLE.match(value)
        if whole:
            return _evaluate(whole.group(1), scope)

        def replace(match: re.Match[str]) -> str:
            resolved = _evaluate(match.group(1), scope)
            return "" if resolved is None else str(resolved)

        return _EXPRESSION.sub(replace, value)

    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in value]
    return value


def evaluate_condition(expression: str | None, scope: dict[str, Any]) -> bool:
    """Evaluate a ``when:`` guard. ``None`` means "always run"."""
    if expression is None:
        return True
    body = expression.strip()
    whole = _WHOLE.match(body)
    result = _evaluate(whole.group(1) if whole else body, scope)
    return bool(result)


def build_scope(
    inputs: dict[str, Any],
    step_outputs: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the scope expressions resolve against."""
    scope: dict[str, Any] = {
        "inputs": inputs,
        "steps": {sid: {"output": out} for sid, out in step_outputs.items()},
    }
    if extra:
        scope.update(extra)
    return scope


def referenced_steps(value: Any) -> set[str]:
    """Extract the step ids an expression tree references.

    Used to validate that a workflow's bindings match its declared
    dependencies, catching a missing ``depends_on`` before the run starts.
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for match in _EXPRESSION.finditer(node):
                for reference in re.finditer(r"steps\.([A-Za-z0-9_-]+)", match.group(1)):
                    found.add(reference.group(1))
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return found


__all__ = [
    "build_scope",
    "evaluate_condition",
    "referenced_steps",
    "resolve",
]
