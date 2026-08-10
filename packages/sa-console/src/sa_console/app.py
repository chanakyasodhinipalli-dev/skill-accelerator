"""The console web application.

Runs in one of two modes, and the difference is one setting:

* **embedded** (default) — the platform API is mounted in this process at
  ``/api``. One command, one port, no CORS, nothing to keep in sync. This is
  what makes the console usable as a live test harness.
* **remote** — requests to ``/api`` are proxied to ``SA_CONSOLE_API_BASE_URL``.
  The console becomes a thin front end for an API deployed and scaled
  separately, and the upstream credential stays server-side rather than being
  handed to the browser.

Either way the browser only ever talks to this origin, so there is no CORS
configuration and no second base URL baked into the front end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sa_platform.config import get_settings
from sa_platform.logging import configure_logging, get_logger

from .config import ConsoleSettings

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

#: Headers a proxy must not copy through: they describe the *hop*, not the
#: message, and forwarding them corrupts the response framing.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
        "host",
    }
)


def create_console(settings: ConsoleSettings | None = None) -> FastAPI:
    """Build the console application."""
    settings = settings or ConsoleSettings()
    configure_logging()

    upstream: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal upstream
        if settings.mode == "embedded":
            # Starlette does not forward lifespan events to a mounted
            # sub-application, so the platform's composition root is run here
            # explicitly. Without this the API would serve requests against an
            # empty registry — no skills, no tools, no forms.
            from sa_api.bootstrap import bootstrap, shutdown

            report = await bootstrap(get_settings())
            app.state.bootstrap = report
            logger.info("console ready (embedded api)", extra=report.summary())
            try:
                yield
            finally:
                await shutdown()
        else:
            upstream = httpx.AsyncClient(
                base_url=str(settings.api_base_url).rstrip("/"),
                timeout=settings.request_timeout_seconds,
                follow_redirects=False,
            )
            logger.info("console ready (remote api)", extra={"upstream": settings.api_base_url})
            try:
                yield
            finally:
                await upstream.aclose()

    app = FastAPI(
        title=settings.title,
        description="Operator console for the Skill Accelerator platform.",
        version="0.1.0",
        lifespan=lifespan,
        # The console's own API surface is tiny; the platform's docs live at
        # /api/docs in embedded mode.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.console_settings = settings

    @app.get("/console/config")
    async def console_config() -> dict[str, Any]:
        """Bootstrap data for the front end. No credentials, ever."""
        return settings.public_config()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode}

    if settings.mode == "embedded":
        from sa_api.app import create_app

        # Mounted rather than re-declared: the console must exercise the same
        # routes, the same validation, and the same error handling that a real
        # client hits, or testing through it proves nothing.
        app.mount("/api", create_app(get_settings()))
    else:

        @app.api_route(
            "/api/{path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        )
        async def proxy(path: str, request: Request) -> Response:
            if upstream is None:  # pragma: no cover - lifespan sets it
                return JSONResponse({"error": "upstream client is not ready"}, status_code=503)

            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower() not in _HOP_BY_HOP
            }
            if settings.api_key is not None:
                # Attached here so the browser never holds the platform
                # credential; the console is the trust boundary.
                headers["x-api-key"] = settings.api_key.get_secret_value()

            try:
                response = await upstream.request(
                    request.method,
                    f"/{path}",
                    params=request.query_params,
                    content=await request.body(),
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                logger.warning("upstream request failed", extra={"path": path, "error": str(exc)})
                return JSONResponse(
                    {
                        "error": {
                            "code": "dependency_error",
                            "message": f"could not reach the platform API: {exc}",
                        }
                    },
                    status_code=502,
                )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in _HOP_BY_HOP
                },
                media_type=response.headers.get("content-type"),
            )

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


#: Module-level app for `uvicorn sa_console.app:app`.
app = create_console()

__all__ = ["STATIC_DIR", "app", "create_console"]
