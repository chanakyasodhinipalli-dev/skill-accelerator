"""Declarative policy evaluation.

Rules are data — a pattern plus metadata — so a compliance team can maintain
them without a code change, and so a rule set is reviewable and diffable.
"""

from __future__ import annotations

import re
from typing import Any

from sa_skills import skill

_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_BLOCKING_SEVERITIES = frozenset({"high", "critical"})

#: Guards against a catastrophically backtracking user-supplied pattern.
_MAX_PATTERN_LENGTH = 500


@skill(
    name="compliance.check_policy",
    version="0.2.0",
    description="Evaluate content against a declarative rule set.",
    category="validation",
    stability="beta",
    owner="compliance-engineering",
    tags=["compliance", "governance"],
    idempotent=True,
)
async def check_policy(
    content: str,
    rules: list[dict],
    fail_on: str = "high",
) -> dict:
    """Evaluate content against a set of policy rules and report findings.

    Call this as a gate before publishing content or committing a transaction
    that must satisfy compliance rules.

    Args:
        content: The text to evaluate.
        rules: Rule objects, each with id, pattern, severity, and message.
        fail_on: Minimum severity that causes an overall failure.
    """
    from sa_platform.errors import ValidationError

    if not isinstance(rules, list):
        raise ValidationError(f"rules must be a list, got {type(rules).__name__}")
    if fail_on not in _SEVERITY_ORDER:
        raise ValidationError(
            f"fail_on must be one of {sorted(_SEVERITY_ORDER)}",
            details={"fail_on": fail_on},
        )

    threshold = _SEVERITY_ORDER[fail_on]
    findings: list[dict[str, Any]] = []
    evaluated = 0

    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValidationError(f"rule at index {index} must be an object")

        rule_id = rule.get("id") or f"rule-{index}"
        pattern = rule.get("pattern")
        if not pattern:
            raise ValidationError(f"rule '{rule_id}' has no pattern", details={"rule": rule_id})
        if len(pattern) > _MAX_PATTERN_LENGTH:
            raise ValidationError(
                f"rule '{rule_id}' pattern exceeds {_MAX_PATTERN_LENGTH} characters",
                details={"rule": rule_id},
            )

        severity = str(rule.get("severity", "medium")).lower()
        if severity not in _SEVERITY_ORDER:
            raise ValidationError(
                f"rule '{rule_id}' has unknown severity '{severity}'",
                details={"rule": rule_id, "allowed": sorted(_SEVERITY_ORDER)},
            )

        flags = re.IGNORECASE if rule.get("ignore_case", True) else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            raise ValidationError(
                f"rule '{rule_id}' has an invalid regular expression: {exc}",
                details={"rule": rule_id, "pattern": pattern},
                cause=exc,
            ) from exc

        evaluated += 1
        matches = list(compiled.finditer(content))

        # `expect: present` inverts the rule — the finding is the *absence* of
        # a required disclosure rather than the presence of forbidden text.
        expect_present = str(rule.get("expect", "absent")).lower() == "present"
        violated = (not matches) if expect_present else bool(matches)
        if not violated:
            continue

        findings.append(
            {
                "rule_id": rule_id,
                "severity": severity,
                "message": rule.get("message", f"rule '{rule_id}' was violated"),
                "match_count": len(matches),
                # Report positions, not the matched text — echoing a matched
                # card number into logs would recreate the leak being detected.
                "positions": [[m.start(), m.end()] for m in matches[:20]],
                "blocking": _SEVERITY_ORDER[severity] >= threshold,
            }
        )

    highest = (
        max(findings, key=lambda f: _SEVERITY_ORDER[f["severity"]])["severity"]
        if findings
        else None
    )

    return {
        "passed": not any(f["blocking"] for f in findings),
        "findings": findings,
        "evaluated_rules": evaluated,
        "highest_severity": highest,
        "blocking_severities": sorted(_BLOCKING_SEVERITIES),
    }
