"""Built-in tools shipped with the platform.

Nothing here is registered automatically — an application opts in by calling
:func:`register_builtins` with the set it wants. Filesystem and shell access in
particular should be enabled deliberately, not by default.
"""

from __future__ import annotations

from sa_platform.logging import get_logger

from ..registry import ToolRegistry, tool_registry
from .fs import ReadFileTool, WriteFileTool
from .http import HttpRequestTool
from .introspection import DescribeSkillTool, ListSkillsTool, ListToolsTool
from .time_tools import CurrentTimeTool

logger = get_logger(__name__)

#: Read-only, side-effect-free tools. Safe to enable everywhere.
SAFE_BUILTINS = ("current_time", "list_tools", "list_skills", "describe_skill")

#: Everything, including filesystem writes and outbound HTTP.
ALL_BUILTINS = (*SAFE_BUILTINS, "http_request", "read_file", "write_file")

_FACTORIES = {
    "current_time": CurrentTimeTool,
    "list_tools": ListToolsTool,
    "list_skills": ListSkillsTool,
    "describe_skill": DescribeSkillTool,
    "http_request": HttpRequestTool,
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
}


def register_builtins(
    registry: ToolRegistry | None = None,
    *,
    include: tuple[str, ...] = SAFE_BUILTINS,
    replace: bool = True,
    **factory_kwargs: object,
) -> list[str]:
    """Register the named built-in tools.

    ``factory_kwargs`` are forwarded to the tool constructors — for example
    ``root=Path("/data")`` to sandbox the filesystem tools.
    """
    target = registry if registry is not None else tool_registry
    registered: list[str] = []

    for name in include:
        factory = _FACTORIES.get(name)
        if factory is None:
            logger.warning("unknown builtin tool requested", extra={"tool": name})
            continue
        try:
            import inspect

            accepted = inspect.signature(factory).parameters
            kwargs = {k: v for k, v in factory_kwargs.items() if k in accepted}
            target.register(factory(**kwargs), replace=replace)  # type: ignore[arg-type]
            registered.append(name)
        except Exception as exc:  # noqa: BLE001 - a missing optional dep must not be fatal
            logger.warning("builtin tool unavailable", extra={"tool": name, "error": str(exc)})

    logger.info("registered builtin tools", extra={"tools": registered})
    return registered


__all__ = [
    "ALL_BUILTINS",
    "SAFE_BUILTINS",
    "CurrentTimeTool",
    "DescribeSkillTool",
    "HttpRequestTool",
    "ListSkillsTool",
    "ListToolsTool",
    "ReadFileTool",
    "WriteFileTool",
    "register_builtins",
]
