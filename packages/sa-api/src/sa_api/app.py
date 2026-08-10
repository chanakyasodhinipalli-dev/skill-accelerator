"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sa_platform.config import Settings, get_settings
from sa_platform.logging import configure_logging, get_logger

from .bootstrap import bootstrap, shutdown
from .dependencies import bind_llm_profile
from .errors import register_error_handlers
from .middleware import AccessLogMiddleware, CorrelationMiddleware
from .routers import connectors, forms, health, providers, skills, tools, workflows

logger = get_logger(__name__)

DESCRIPTION = """\
Enterprise skill, tool, and orchestration platform.

* **Skills** — versioned business capabilities with declared contracts
* **Tools** — the governed action surface (native, skill-bridged, MCP, OpenAPI)
* **Workflows** — declarative DAGs coordinating the above
* **Forms** — conversational intake: gather form data from chat, JIRA, and email
  threads, then render, review, and baseline the artifact
* **Providers** — switchable model routes: Anthropic, OpenAI, Gemini, or an
  enterprise gateway, selected per call, per request, or per process
* **Connectors** — outbound integrations and model providers

Send `X-LLM-Profile: <name>` on any request to pin the model that serves it.

Every invocation passes through policy, permission, deadline, retry, and audit
handling, and carries a correlation id end to end.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application."""
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        report = await bootstrap(settings)
        app.state.bootstrap = report
        logger.info("api ready", extra=report.summary())
        try:
            yield
        finally:
            await shutdown()

    app = FastAPI(
        title=settings.service_name,
        description=DESCRIPTION,
        version=settings.version,
        lifespan=lifespan,
        root_path=settings.api.root_path,
        # Applied globally so every endpoint that reaches a model honours
        # `X-LLM-Profile`, not only the ones that thought to ask for it.
        dependencies=[Depends(bind_llm_profile)],
        # Interactive docs are useful in lower environments and an unnecessary
        # surface in production.
        docs_url="/docs" if settings.api.docs_enabled else None,
        redoc_url="/redoc" if settings.api.docs_enabled else None,
        openapi_url="/openapi.json" if settings.api.docs_enabled else None,
    )

    # Middleware runs bottom-up, so correlation is added last to make it
    # outermost — the access log then already has the id available.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationMiddleware)

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Correlation-Id", "X-Request-Id"],
        )

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(skills.router)
    app.include_router(tools.router)
    app.include_router(workflows.router)
    app.include_router(forms.router)
    app.include_router(providers.router)
    app.include_router(connectors.router)

    @app.get("/", tags=["health"], summary="Service root")
    async def root() -> dict[str, str]:
        return {
            "service": settings.service_name,
            "version": settings.version,
            "docs": "/docs" if settings.api.docs_enabled else "disabled",
        }

    return app


#: Module-level app for `uvicorn sa_api.app:app`.
app = create_app()

__all__ = ["app", "create_app"]
