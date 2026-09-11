"""SQLite connection handling.

Every connection MedFlow opens is configured identically: row access by column
name, foreign keys enforced, and a busy timeout so a concurrent read does not
fail immediately.

Connections are short-lived — opened for one unit of work and closed — which
keeps the application free of long-held locks and makes the repository methods
safe to call from anywhere. SQLite's own file locking handles the rest.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.exceptions import PersistenceError

#: How long to wait for a lock before giving up.
DEFAULT_TIMEOUT_SECONDS = 5.0


class Database:
    """Owns the database file and hands out configured connections."""

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        foreign_keys: bool = True,
    ) -> None:
        self._path = str(path)
        self._timeout = timeout
        self._foreign_keys = foreign_keys
        # An in-memory database exists only for the life of a single connection,
        # so one is created here and kept. Tests mostly use a temporary file, but
        # :memory: is useful for throwaway checks.
        self._shared_memory_connection: sqlite3.Connection | None = None

    @property
    def path(self) -> str:
        return self._path

    @property
    def is_memory(self) -> bool:
        return self._path == ":memory:" or self._path.startswith("file::memory:")

    # ---------- connections ----------

    def connect(self) -> sqlite3.Connection:
        """Open a configured connection. The caller owns closing it."""
        if self.is_memory and self._shared_memory_connection is not None:
            return self._shared_memory_connection

        try:
            if not self.is_memory:
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)

            connection = sqlite3.connect(
                self._path,
                timeout=self._timeout,
                isolation_level=None,  # explicit transaction control
            )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not open database '{self._path}': {exc}") from exc

        connection.row_factory = sqlite3.Row

        if self._foreign_keys:
            connection.execute("PRAGMA foreign_keys = ON")

        if not self.is_memory:
            # Write-ahead logging keeps readers from blocking the writer. It is
            # skipped in memory, where it does not apply.
            try:
                connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.Error:
                # Some filesystems (certain network mounts) do not support WAL.
                # Rollback journalling still works, so this is not fatal.
                pass

        if self.is_memory:
            self._shared_memory_connection = connection

        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """A connection that is closed on exit, whatever happens."""
        connection = self.connect()
        try:
            yield connection
        finally:
            self._release(connection)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A connection wrapped in a transaction.

        Commits on success, rolls back on any exception. Used for operations that
        must be all-or-nothing — a patient insert together with its history and
        audit entries, or a legacy migration.
        """
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            self._release(connection)

    def _release(self, connection: sqlite3.Connection) -> None:
        if self.is_memory and connection is self._shared_memory_connection:
            return
        try:
            connection.close()
        except sqlite3.Error:
            pass

    # ---------- maintenance ----------

    def close(self) -> None:
        """Release the held connection, if any.

        Only an in-memory database holds a connection open between calls; for a
        file database there is nothing to release and this is a no-op. It exists so
        a caller replacing the database file underneath the application can state
        its intent without knowing which kind it holds.
        """
        connection = self._shared_memory_connection
        self._shared_memory_connection = None
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass

    def backup_to(self, destination: str | Path) -> Path:
        """Write a consistent snapshot to ``destination``.

        Uses SQLite's online backup API rather than copying the file, so the
        snapshot is valid even while the application is running and writing.
        """
        target = Path(destination)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as source:
                with sqlite3.connect(str(target)) as destination_connection:
                    source.backup(destination_connection)
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not back up to '{target}': {exc}") from exc
        return target
