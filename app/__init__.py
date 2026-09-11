"""MedFlow — clinical records management with an offline-first architecture.

MedFlow is a patient records platform built as a layered Python application:

    UI (CustomTkinter desktop / browser web client)
      -> Services (business rules, validation, audit)
        -> Repositories (local SQLite or remote API)
          -> SQLite / FastAPI -> PostgreSQL

The client never touches SQL in network mode; every read/write flows through
a service that validates, audits, and versions data. Local Mode uses the same
services against a local SQLite repository, so the storage backend is a
swappable detail rather than an architectural assumption.
"""

__version__ = "3.0.0"
APP_NAME = "MedFlow"
