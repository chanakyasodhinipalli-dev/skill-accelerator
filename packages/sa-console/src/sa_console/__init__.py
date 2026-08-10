"""Operator console: a browser UI over the platform API.

Built to be *used*, not just demonstrated: every screen drives the real
endpoints, so anything that works here works from a client, and anything that
breaks here is broken for everyone.
"""

from __future__ import annotations

from .config import ConsoleSettings

__version__ = "0.1.0"

__all__ = ["ConsoleSettings", "__version__"]
