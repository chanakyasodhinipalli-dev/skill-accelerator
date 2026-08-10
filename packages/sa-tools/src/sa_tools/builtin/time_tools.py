"""Clock tool.

Small but load-bearing: a model has no reliable sense of "now", and hard-coding
a timestamp into the system prompt would invalidate the prompt cache on every
request. Exposing the clock as a tool solves both problems.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sa_platform.context import ExecutionContext
from sa_platform.errors import ValidationError

from ..base import Tool
from ..models import DangerLevel, ToolSpec


class CurrentTimeTool(Tool):
    """Return the current date and time."""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                name="current_time",
                description=(
                    "Get the current date and time. Call this whenever the answer depends "
                    "on what 'today', 'now', or a relative date resolves to — do not assume "
                    "the current date from memory."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "timezone": {
                            "type": "string",
                            "description": "IANA timezone name, e.g. 'America/New_York'. Defaults to UTC.",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                danger=DangerLevel.SAFE,
                tags=["utility", "time"],
            )
        )

    async def invoke(self, ctx: ExecutionContext, arguments: dict[str, Any]) -> Any:
        tz_name = arguments.get("timezone") or "UTC"
        try:
            tz = UTC if tz_name.upper() == "UTC" else ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError(
                f"unknown timezone '{tz_name}'", details={"timezone": tz_name}, cause=exc
            ) from exc

        now = datetime.now(tz)
        return {
            "iso8601": now.isoformat(),
            "date": now.date().isoformat(),
            "time": now.time().replace(microsecond=0).isoformat(),
            "timezone": tz_name,
            "unix_timestamp": now.timestamp(),
            "weekday": now.strftime("%A"),
        }


__all__ = ["CurrentTimeTool"]
