"""MedFlow API server — the web half of the local-first clinic platform.

``python -m app.server`` serves:

- the JSON API under ``/api/*`` (the same services the desktop UI calls)
- the built-in web client at ``/`` (no build step, no node_modules)

Both faces share one SQLite database and one permission model, so a clinic
can run desktop-only, web-only, or both at once.
"""

from app.server.app import create_app

__all__ = ["create_app"]
