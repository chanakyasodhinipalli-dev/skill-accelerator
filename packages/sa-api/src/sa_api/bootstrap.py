"""Application composition root.

The single place where discovery, registration, and connector wiring happen, so
the API service, the CLI, and tests all start from an identical platform state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sa_connectors.registry import connector_registry
from sa_orchestrator.registry import workflow_registry
from sa_platform.config import Settings, get_settings
from sa_platform.context import Principal, new_context
from sa_platform.health import health_registry
from sa_platform.logging import configure_logging, get_logger
from sa_skills.registry import skill_registry
from sa_tools.builtin import SAFE_BUILTINS, register_builtins
from sa_tools.registry import tool_registry

logger = get_logger(__name__)


@dataclass
class BootstrapReport:
    """What the bootstrap actually managed to wire up."""

    skills: int = 0
    tools: int = 0
    workflows: int = 0
    forms: int = 0
    connectors: dict[str, bool] = field(default_factory=dict)
    mcp_servers: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "skills": self.skills,
            "tools": self.tools,
            "workflows": self.workflows,
            "forms": self.forms,
            "connectors": self.connectors,
            "mcp_servers": self.mcp_servers,
            "warnings": self.warnings,
        }


async def bootstrap(
    settings: Settings | None = None,
    *,
    builtin_tools: tuple[str, ...] = SAFE_BUILTINS,
    workflow_dir: str = "examples/workflows",
    form_dir: str = "examples/forms",
    **builtin_kwargs: Any,
) -> BootstrapReport:
    """Discover skills, register tools, load workflows, and connect integrations.

    Runs under a system principal so discovery is not blocked by the
    permissions of whichever request happened to trigger startup.
    """
    settings = settings or get_settings()
    configure_logging()
    report = BootstrapReport()

    with new_context(principal=Principal.system()):
        # 1. Skills first — tools bridge from them.
        report.skills = await skill_registry.discover()

        # 2. Tools: decorated, built-in, then skill bridges.
        tool_registry.register_decorated(replace=True)
        register_builtins(tool_registry, include=builtin_tools, **builtin_kwargs)
        tool_registry.register_skills(skill_registry, replace=True)
        await tool_registry.load()
        report.tools = len(tool_registry)

        # 3. MCP servers. A server that is down must not block startup.
        if settings.mcp_servers:
            from sa_connectors.mcp import register_mcp_servers

            connectors = await register_mcp_servers(settings.mcp_servers, tool_registry)
            for config in settings.mcp_servers:
                connected = config.name in connectors
                report.mcp_servers[config.name] = connected
                if not connected and config.enabled:
                    report.warnings.append(f"MCP server '{config.name}' is unavailable")
            for connector in connectors.values():
                connector_registry.register(connector, replace=True)
            report.tools = len(tool_registry)

        # 4. Other registered connectors.
        if connector_registry.names():
            report.connectors = await connector_registry.connect_all()

        # 5. Workflow definitions.
        report.workflows = len(workflow_registry.load_directory(workflow_dir, replace=True))

        # 6. Form definitions, and the tools that drive them. Registered after
        #    the tool registry is populated so forms tools sit alongside the
        #    rest and inherit the same policy and audit path.
        from sa_forms.registry import form_registry
        from sa_forms.tools import register_form_tools

        report.forms = len(form_registry.load_directory(form_dir))
        register_form_tools(tool_registry, replace=True)
        report.tools = len(tool_registry)

        # 7. Health probes for the capability registries themselves.
        _register_health_checks()

    logger.info("bootstrap complete", extra=report.summary())
    return report


def _register_health_checks() -> None:
    from sa_platform.health import CheckResult

    def skills_check() -> CheckResult:
        count = len(skill_registry)
        if count == 0:
            return CheckResult.degraded("no skills are registered")
        return CheckResult.healthy(f"{count} skill version(s) registered", count=count)

    def tools_check() -> CheckResult:
        count = len(tool_registry)
        if count == 0:
            return CheckResult.degraded("no tools are registered")
        return CheckResult.healthy(f"{count} tool(s) registered", count=count)

    health_registry.register("skills", skills_check, critical=False)
    health_registry.register("tools", tools_check, critical=False)


async def shutdown() -> None:
    """Release everything the bootstrap acquired, in reverse order."""
    from sa_platform.events import event_bus

    await event_bus.drain()
    await connector_registry.close_all()
    await tool_registry.shutdown()
    await skill_registry.shutdown()
    logger.info("shutdown complete")


__all__ = ["BootstrapReport", "bootstrap", "shutdown"]
