"""sa-tools — the action surface.

Tools are how skills, workflows, and models *do* things. Every invocation
passes through policy, an approval gate, deadlines, retries, and audit.

Author a tool::

    from sa_tools import tool

    @tool(danger="medium", required_permissions=["crm:write"])
    async def create_ticket(subject: str, priority: str = "normal") -> dict:
        '''File a support ticket. Call this when the user asks to open or
        escalate an issue that needs tracking.

        Args:
            subject: One-line summary of the problem.
            priority: One of low, normal, high.
        '''
        ...

Render the catalogue for a model, then execute what it asks for::

    tools = tool_registry.to_anthropic_tools(max_danger="low")
    results = await tool_executor.execute_tool_use_blocks(response.content)
"""

from __future__ import annotations

from .base import FunctionTool, SkillTool, Tool
from .decorators import drain_pending, tool
from .executor import ToolExecutor, tool_executor
from .models import (
    DangerLevel,
    ToolInvocation,
    ToolKind,
    ToolResult,
    ToolSpec,
    ToolStatus,
)
from .policy import ApprovalDecision, ApprovalHandler, ToolPolicy, allow_all, deny_by_default
from .registry import ToolRegistry, tool_registry

__version__ = "0.1.0"

__all__ = [
    "ApprovalDecision",
    "ApprovalHandler",
    "DangerLevel",
    "FunctionTool",
    "SkillTool",
    "Tool",
    "ToolExecutor",
    "ToolInvocation",
    "ToolKind",
    "ToolPolicy",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolStatus",
    "__version__",
    "allow_all",
    "deny_by_default",
    "drain_pending",
    "tool",
    "tool_executor",
    "tool_registry",
]
