"""MedFlow — native desktop patient management system.

The application is layered so the user interface never talks to a database
directly:

    ui -> services -> repositories -> storage

``repositories`` defines abstract interfaces; ``repositories.sqlite`` provides the
local implementation. A networked implementation (for example one backed by a
FastAPI service) can be substituted without changing the UI or the services.
"""

__version__ = "2.0.0"
