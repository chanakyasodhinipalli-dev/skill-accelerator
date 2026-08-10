"""Tabular data profiling.

Demonstrates a skill whose value is a structured, machine-consumable report
rather than prose — the shape most useful as an upstream step in a workflow.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from sa_skills import skill

#: Above this share of nulls, a column is probably not usable as-is.
_NULL_WARNING_THRESHOLD = 0.5
#: A column with one distinct value carries no information.
_CONSTANT_WARNING = 1


def _infer_type(values: list[Any]) -> str:
    """Infer a column's logical type from its non-null values."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "unknown"
    if all(isinstance(v, bool) for v in non_null):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "integer"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "number"
    if all(isinstance(v, str) for v in non_null):
        return "string"
    if all(isinstance(v, (list, tuple)) for v in non_null):
        return "array"
    if all(isinstance(v, dict) for v in non_null):
        return "object"
    return "mixed"


def _numeric_stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    count = len(ordered)
    mean = sum(ordered) / count
    variance = sum((v - mean) ** 2 for v in ordered) / count

    def percentile(fraction: float) -> float:
        return ordered[min(count - 1, int(count * fraction))]

    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": round(mean, 6),
        "stddev": round(math.sqrt(variance), 6),
        "p25": percentile(0.25),
        "median": percentile(0.5),
        "p75": percentile(0.75),
    }


@skill(
    name="data.profile",
    version="1.0.0",
    description="Profile a tabular dataset for structure and quality.",
    category="analysis",
    stability="stable",
    owner="data-platform",
    tags=["data", "quality"],
)
async def profile_dataset(rows: list[dict], max_distinct_examples: int = 5) -> dict:
    """Profile a tabular dataset given as a list of row objects.

    Call this before relying on an unfamiliar dataset — it reports types, null
    rates, cardinality, numeric distributions, and quality warnings.

    Args:
        rows: The dataset, one object per row. Keys are column names.
        max_distinct_examples: How many example values to include per column.
    """
    from sa_platform.errors import ValidationError

    if not isinstance(rows, list):
        raise ValidationError(f"rows must be a list, got {type(rows).__name__}")
    if not rows:
        return {"row_count": 0, "column_count": 0, "columns": {}, "warnings": ["dataset is empty"]}

    # Union of keys, not just the first row's — ragged data is common and
    # silently profiling only row 0's columns would hide the problem.
    column_names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("every row must be an object")
        for key in row:
            if key not in column_names:
                column_names.append(key)

    row_count = len(rows)
    columns: dict[str, Any] = {}
    warnings: list[str] = []

    for name in column_names:
        values = [row.get(name) for row in rows]
        non_null = [v for v in values if v is not None]
        null_count = row_count - len(non_null)
        inferred = _infer_type(values)

        # Unhashable values (dicts, lists) cannot go through Counter.
        try:
            distribution = Counter(non_null)
            distinct = len(distribution)
            examples = [v for v, _ in distribution.most_common(max_distinct_examples)]
        except TypeError:
            distinct = -1  # not computable
            examples = non_null[:max_distinct_examples]

        profile: dict[str, Any] = {
            "type": inferred,
            "null_count": null_count,
            "null_ratio": round(null_count / row_count, 4),
            "distinct_count": distinct,
            "examples": examples,
        }

        if inferred in ("integer", "number") and non_null:
            profile["stats"] = _numeric_stats([float(v) for v in non_null])

        columns[name] = profile

        # Ordered most-severe first, and mutually exclusive: an entirely-null
        # column should not also be reported as "80% null" and "constant".
        if null_count == row_count:
            warnings.append(f"column '{name}' is entirely null")
        elif profile["null_ratio"] > _NULL_WARNING_THRESHOLD:
            warnings.append(f"column '{name}' is {profile['null_ratio']:.0%} null")
        elif distinct == _CONSTANT_WARNING and row_count > 1:
            warnings.append(
                f"column '{name}' has a single distinct value and carries no information"
            )
        if inferred == "mixed":
            warnings.append(f"column '{name}' holds mixed types; downstream casts may fail")

    ragged = [name for name in column_names if any(name not in row for row in rows)]
    if ragged:
        warnings.append(f"dataset is ragged; column(s) missing from some rows: {', '.join(ragged)}")

    return {
        "row_count": row_count,
        "column_count": len(column_names),
        "columns": columns,
        "warnings": warnings,
    }
