"""Operator CLI.

    sa skills list                       # browse the catalogue
    sa skills run summarize -p '{"text":"..."}'
    sa tools list --max-danger low
    sa workflows run incident_triage -i '{"alert_id":"A-1"}'
    sa doctor                            # verify the deployment
    sa serve
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from sa_platform.config import get_settings
from sa_platform.context import Principal, new_context
from sa_platform.logging import configure_logging

app = typer.Typer(
    name="sa",
    help="Skill Accelerator — operator CLI",
    no_args_is_help=True,
    add_completion=False,
)
skills_app = typer.Typer(name="skills", help="Inspect and invoke skills", no_args_is_help=True)
tools_app = typer.Typer(name="tools", help="Inspect and invoke tools", no_args_is_help=True)
workflows_app = typer.Typer(name="workflows", help="Manage workflows", no_args_is_help=True)

app.add_typer(skills_app)
app.add_typer(tools_app)
app.add_typer(workflows_app)

console = Console()
error_console = Console(stderr=True, style="bold red")


def _parse_json(raw: str | None, label: str) -> dict[str, Any]:
    """Parse a JSON argument, accepting ``@path`` to read from a file."""
    if not raw:
        return {}
    if raw.startswith("@"):
        path = Path(raw[1:])
        if not path.is_file():
            error_console.print(f"{label} file not found: {path}")
            raise typer.Exit(2)
        raw = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        error_console.print(f"{label} is not valid JSON: {exc}")
        raise typer.Exit(2) from exc
    if not isinstance(parsed, dict):
        error_console.print(f"{label} must be a JSON object")
        raise typer.Exit(2)
    return parsed


async def _bootstrap() -> Any:
    from sa_api.bootstrap import bootstrap

    configure_logging()
    return await bootstrap()


def _run(coro: Any) -> Any:
    """Run an async command under a system principal."""

    async def wrapped() -> Any:
        with new_context(principal=Principal.system()):
            return await coro()

    return asyncio.run(wrapped())


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------


@skills_app.command("list")
def skills_list(
    query: str = typer.Option(None, "--query", "-q", help="Substring filter"),
    category: str = typer.Option(None, "--category", "-c"),
) -> None:
    """List registered skills."""

    async def command() -> None:
        await _bootstrap()
        from sa_skills.registry import skill_registry

        found = skill_registry.search(query=query, category=category)
        table = Table(title=f"Skills ({len(found)})", header_style="bold cyan")
        for column in ("Name", "Version", "Category", "Stability", "Owner", "Description"):
            table.add_column(column, overflow="fold")
        for instance in found:
            m = instance.manifest
            table.add_row(
                m.name,
                m.version,
                m.category.value,
                m.stability.value,
                m.owner or "-",
                m.description[:70],
            )
        console.print(table)

    _run(command)


@skills_app.command("show")
def skills_show(name: str) -> None:
    """Print a skill's full manifest."""

    async def command() -> None:
        await _bootstrap()
        from sa_skills.registry import skill_registry

        manifest = skill_registry.require(name).manifest
        console.print(JSON(manifest.model_dump_json(indent=2)))

    _run(command)


@skills_app.command("run")
def skills_run(
    name: str,
    payload: str = typer.Option(None, "--payload", "-p", help="JSON object, or @file.json"),
    version: str = typer.Option(None, "--version"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without side effects"),
) -> None:
    """Invoke a skill."""
    parsed = _parse_json(payload, "payload")

    async def command() -> None:
        await _bootstrap()
        from sa_platform.context import current_context
        from sa_skills.runtime import skill_runtime

        ctx = current_context().child(dry_run=dry_run)
        result = await skill_runtime.invoke(name, parsed, ctx=ctx, version=version)
        console.print(JSON(result.model_dump_json(indent=2)))
        if not result.ok:
            raise typer.Exit(1)

    _run(command)


@skills_app.command("verify")
def skills_verify(
    name: str = typer.Argument(None, help="Skill to verify; omit to verify all"),
) -> None:
    """Run the skill contract checks. Suitable for CI."""

    async def command() -> None:
        await _bootstrap()
        from sa_skills.registry import skill_registry
        from sa_skills.testing import assert_contract

        targets = [skill_registry.require(name)] if name else skill_registry.all()
        failed = 0
        for instance in targets:
            report = await assert_contract(instance)
            if report.ok:
                console.print(f"[green]PASS[/green] {instance.manifest.name}")
            else:
                failed += 1
                console.print(f"[red]FAIL[/red] {instance.manifest.name}")
                for failure in report.failures:
                    console.print(f"       {failure}")
        console.print(f"\n{len(targets) - failed}/{len(targets)} skills passed")
        if failed:
            raise typer.Exit(1)

    _run(command)


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


@tools_app.command("list")
def tools_list(
    query: str = typer.Option(None, "--query", "-q"),
    kind: str = typer.Option(None, "--kind", help="native | skill | mcp | openapi"),
    max_danger: str = typer.Option(None, "--max-danger", help="safe | low | medium | high"),
) -> None:
    """List registered tools."""

    async def command() -> None:
        await _bootstrap()
        from sa_tools.registry import tool_registry

        found = tool_registry.search(query=query, kind=kind, max_danger=max_danger)
        table = Table(title=f"Tools ({len(found)})", header_style="bold cyan")
        for column in ("Name", "Kind", "Danger", "Source", "Description"):
            table.add_column(column, overflow="fold")
        for instance in found:
            s = instance.spec
            colour = {"safe": "green", "low": "cyan", "medium": "yellow", "high": "red"}[
                s.danger.value
            ]
            table.add_row(
                s.name,
                s.kind.value,
                f"[{colour}]{s.danger.value}[/{colour}]",
                s.source or "-",
                s.description[:60],
            )
        console.print(table)

    _run(command)


@tools_app.command("run")
def tools_run(
    name: str,
    arguments: str = typer.Option(None, "--args", "-a", help="JSON object, or @file.json"),
    approve: bool = typer.Option(
        False, "--approve", help="Pre-approve a tool that is gated behind approval"
    ),
) -> None:
    """Invoke a tool."""
    parsed = _parse_json(arguments, "arguments")

    async def command() -> None:
        await _bootstrap()
        from sa_tools.executor import tool_executor

        result = await tool_executor.invoke(name, parsed, approved=approve or None)
        console.print(JSON(result.model_dump_json(indent=2)))
        if not result.ok:
            raise typer.Exit(1)

    _run(command)


@tools_app.command("definitions")
def tools_definitions(
    max_danger: str = typer.Option(None, "--max-danger"),
    output: Path = typer.Option(None, "--output", "-o", help="Write JSON to this path"),
) -> None:
    """Emit the Anthropic tool-definitions array for the catalogue."""

    async def command() -> None:
        await _bootstrap()
        from sa_tools.registry import tool_registry

        definitions = tool_registry.to_anthropic_tools(max_danger=max_danger)
        rendered = json.dumps(definitions, indent=2)
        if output:
            output.write_text(rendered, encoding="utf-8")
            console.print(f"[green]wrote {len(definitions)} definitions to {output}[/green]")
        else:
            console.print(JSON(rendered))

    _run(command)


# ---------------------------------------------------------------------------
# workflows
# ---------------------------------------------------------------------------


@workflows_app.command("list")
def workflows_list() -> None:
    """List registered workflows."""

    async def command() -> None:
        await _bootstrap()
        from sa_orchestrator.registry import workflow_registry

        found = workflow_registry.all()
        table = Table(title=f"Workflows ({len(found)})", header_style="bold cyan")
        for column in ("Name", "Version", "Steps", "Owner", "Description"):
            table.add_column(column, overflow="fold")
        for spec in found:
            table.add_row(
                spec.name,
                spec.version,
                str(len(spec.steps)),
                spec.owner or "-",
                spec.description[:60],
            )
        console.print(table)

    _run(command)


@workflows_app.command("graph")
def workflows_graph(name: str) -> None:
    """Show a workflow's execution levels — what runs in parallel."""

    async def command() -> None:
        await _bootstrap()
        from sa_orchestrator.graph import build_graph
        from sa_orchestrator.registry import workflow_registry

        spec = workflow_registry.require(name)
        graph = build_graph(spec)
        console.print(f"[bold]{spec.qualified_name}[/bold] — {graph.size} steps")
        for index, level in enumerate(graph.levels):
            marker = "parallel" if len(level) > 1 else "sequential"
            console.print(f"  level {index} ({marker}): {', '.join(level)}")
        console.print(f"\nmax parallelism: {graph.max_width}")

    _run(command)


@workflows_app.command("run")
def workflows_run(
    name: str,
    inputs: str = typer.Option(None, "--inputs", "-i", help="JSON object, or @file.json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Execute a workflow."""
    parsed = _parse_json(inputs, "inputs")

    async def command() -> None:
        await _bootstrap()
        from sa_orchestrator.engine import engine
        from sa_orchestrator.registry import workflow_registry
        from sa_platform.context import current_context

        spec = workflow_registry.require(name)
        ctx = current_context().child(dry_run=dry_run)
        state = await engine.run(spec, parsed, ctx=ctx)

        colour = {"succeeded": "green", "failed": "red"}.get(state.status.value, "yellow")
        console.print(
            f"[{colour}]{state.status.value}[/{colour}] "
            f"run {state.run_id} in {state.duration_ms:.0f}ms"
        )

        table = Table(title="Steps", header_style="bold cyan")
        for column in ("Step", "Status", "Duration", "Detail"):
            table.add_column(column, overflow="fold")
        for step_id, result in state.steps.items():
            detail = result.skipped_reason or (result.error or {}).get("message", "")
            table.add_row(
                step_id, result.status.value, f"{result.duration_ms:.0f}ms", str(detail)[:60]
            )
        console.print(table)

        if state.outputs:
            console.print("\n[bold]Outputs[/bold]")
            console.print(JSON(json.dumps(state.outputs, default=str, indent=2)))
        if state.status.value not in ("succeeded", "awaiting_approval"):
            raise typer.Exit(1)

    _run(command)


@workflows_app.command("validate")
def workflows_validate(path: Path) -> None:
    """Validate a workflow YAML file without registering it."""

    async def command() -> None:
        from sa_orchestrator.registry import WorkflowRegistry

        registry = WorkflowRegistry()
        spec = registry.load_file(path)
        console.print(f"[green]valid[/green] {spec.qualified_name} — {len(spec.steps)} steps")

    _run(command)


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------


@app.command("doctor")
def doctor() -> None:
    """Check that the deployment is wired up correctly."""

    async def command() -> None:
        settings = get_settings()
        report = await _bootstrap()

        console.print(f"[bold]{settings.service_name}[/bold] v{settings.version}")
        console.print(f"environment : {settings.environment}")
        # Report the profile that will actually serve a call, not the top-level
        # model setting — with profiles configured those can differ, and the
        # setting is the more believable of the two.
        from sa_connectors.llm import get_router

        router = get_router()
        active = router.profile(router.active)
        route = f"{active.vendor} · {active.model}"
        if active.vendor == "gateway":
            route += f" via gateway ({active.dialect} dialect)"
        # Square brackets would be swallowed as rich markup.
        console.print(f"model       : {route}  (profile: {router.active})")
        if len(router.names()) > 1:
            console.print(f"profiles    : {', '.join(router.names())}")
        console.print(f"skills      : {report.skills} discovered")
        console.print(f"tools       : {report.tools} registered")
        console.print(f"workflows   : {report.workflows} loaded")

        for warning in report.warnings:
            console.print(f"[yellow]warning[/yellow]  {warning}")

        from sa_platform.health import health_registry

        health = await health_registry.run()
        colour = {"healthy": "green", "degraded": "yellow"}.get(health["status"], "red")
        console.print(f"\nhealth      : [{colour}]{health['status']}[/{colour}]")
        for check, result in health["checks"].items():
            mark = "ok" if result["status"] == "healthy" else result["status"]
            console.print(f"  {check}: {mark} — {result.get('message', '')}")

        if health["status"] == "unhealthy":
            raise typer.Exit(1)

    _run(command)


@app.command("serve")
def serve(
    host: str = typer.Option(None, "--host"),
    port: int = typer.Option(None, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
) -> None:
    """Start the HTTP API."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "sa_api.app:app",
        host=host or settings.api.host,
        port=port or settings.api.port,
        reload=reload,
        log_config=None,  # the platform owns logging configuration
    )


@app.command("config")
def show_config(
    show_secrets: bool = typer.Option(False, "--show-secrets", help="Reveal secret values"),
) -> None:
    """Print the resolved configuration."""
    settings = get_settings()
    dumped = settings.model_dump(mode="json")
    if not show_secrets:
        # SecretStr already masks in model_dump, but api_keys are plain strings.
        api = dumped.get("api", {})
        if api.get("api_keys"):
            api["api_keys"] = {k: "***" for k in api["api_keys"]}
    console.print(JSON(json.dumps(dumped, indent=2, default=str)))


@app.command("version")
def version() -> None:
    """Print component versions."""
    import sa_connectors
    import sa_orchestrator
    import sa_platform
    import sa_skills
    import sa_tools

    for module in (sa_platform, sa_skills, sa_tools, sa_connectors, sa_orchestrator):
        console.print(f"{module.__name__:<18} {module.__version__}")


if __name__ == "__main__":  # pragma: no cover
    app()
