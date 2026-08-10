"""sa-api — HTTP surface for the platform.

Run it::

    uvicorn sa_api.app:app --reload
    # or
    sa serve
"""

from __future__ import annotations

from .app import create_app
from .bootstrap import BootstrapReport, bootstrap, shutdown

__version__ = "0.1.0"

__all__ = ["BootstrapReport", "__version__", "bootstrap", "create_app", "shutdown"]
