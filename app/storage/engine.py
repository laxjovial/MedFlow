"""Database connection management.

One small engine shared by desktop mode and the API server. WAL mode keeps
reads fast while a writer works; foreign keys are always on; the busy
timeout absorbs the brief lock contention typical of a clinic desk.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.migrations import migrate
from app.utils.logging_utils import get_logger

log = get_logger("storage.engine")

_BUSY_TIMEOUT_MS = 5_000


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) a MedFlow database, migrated and ready."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")

    version = migrate(conn)
    log.info("database ready at %s (schema v%d)", path, version)
    return conn


class Database:
    """Thin holder for a process-wide connection.

    SQLite in WAL mode happily serves the concurrent readers a desktop UI
    and an API server generate. Writes are short transactions.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect(self.db_path)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # Convenience passthroughs used by small repositories and tests.

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.connection().execute(sql, params)

    def commit(self) -> None:
        self.connection().commit()
