"""``sa-console`` entry point."""

from __future__ import annotations

import argparse

from .config import ConsoleSettings


def main() -> None:
    """Serve the console."""
    settings = ConsoleSettings()
    parser = argparse.ArgumentParser(
        prog="sa-console",
        description="Operator console for the Skill Accelerator platform.",
    )
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument(
        "--api",
        default=settings.api_base_url,
        metavar="URL",
        help="Proxy to a remote platform API instead of mounting it in this process",
    )
    parser.add_argument("--reload", action="store_true", help="Reload on source changes")
    args = parser.parse_args()

    if args.api:
        # Set before the app is imported so the factory sees remote mode.
        import os

        os.environ["SA_CONSOLE_API_BASE_URL"] = args.api

    import uvicorn

    mode = "remote" if args.api else "embedded"
    print(f"console  http://{args.host}:{args.port}  ({mode} api)")
    uvicorn.run(
        "sa_console.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,  # the platform configures structured logging itself
    )


if __name__ == "__main__":  # pragma: no cover
    main()
