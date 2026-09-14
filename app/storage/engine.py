"""Database connection management.

One small engine shared by desktop mode and the API server. WAL mode keeps
reads fast while a writer works; foreign keys are always on; the busy
timeout absorbs the brief lock contention typical of a clinic desk.
"""

from __future__ import annotations

import sqlite3
import threading
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
    """Thread-safe holder for per-thread SQLite connections.

    The desktop UI and the API server both call services from worker
    threads, and a raw sqlite3 connection refuses cross-thread use. Each
    thread therefore gets its own connection (WAL mode serves concurrent
    readers happily; the busy timeout absorbs write contention), created
    lazily and reused for the thread's lifetime.
    """

    _DML_PREFIXES = ("INSERT", "UPDATE", "DELETE", "REPLACE")

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._write_lock = threading.RLock()

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.db_path)
            self._local.conn = conn
        return conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Run one statement; writes commit immediately and are serialized.

        Repositories never call COMMIT themselves, so durability lives here:
        every DML statement is committed before returning (WAL keeps this
        cheap) and a process-wide lock serializes writers so concurrent
        threads cannot interleave half-finished operations.
        """
        conn = self.connection()
        with self._write_lock:
            cur = conn.execute(sql, params)
            if sql.lstrip().upper().startswith(self._DML_PREFIXES):
                conn.commit()
            return cur

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def commit(self) -> None:
        """Explicit commit for multi-statement service transactions."""
        self.connection().commit()
