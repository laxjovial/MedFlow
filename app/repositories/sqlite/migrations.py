"""Versioned, forward-only schema migrations.

The authoritative version is SQLite's ``user_version`` pragma; the
``schema_migrations`` table is a human-readable ledger so an operator can see
what was applied and when without running a pragma.

Each migration runs inside its own transaction, together with the bookkeeping
that records it. A migration that fails leaves the database exactly as it was.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Sequence

from app.config.constants import SYSTEM_ACTOR
from app.config.settings import PatientIdSettings
from app.core.clock import Clock, SystemClock, format_timestamp
from app.core.exceptions import MigrationError
from app.core.logging import get_logger
from app.repositories.sqlite import legacy
from app.repositories.sqlite.connection import Database
from app.repositories.sqlite.schema import SCHEMA_V1, SCHEMA_VERSION

logger = get_logger("migrations")


@dataclass(frozen=True)
class MigrationContext:
    """Everything a migration needs that is not the connection itself."""

    clock: Clock
    patient_ids: PatientIdSettings
    actor: str


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection, MigrationContext], None]


def _apply_v1(connection: sqlite3.Connection, context: MigrationContext) -> None:
    """Create schema v1, converting a pre-refactor database if one is present.

    Order matters. The legacy table is renamed *before* the new schema is
    created, because the new schema wants to claim the name ``patients`` for
    itself. Conversion then reads from the parked table.
    """
    converting = legacy.has_legacy_schema(connection)

    if converting:
        logger.info("Pre-refactor schema detected; converting to schema v1")
        legacy.rename_legacy_table(connection)

    execute_script(connection, SCHEMA_V1)

    if converting:
        result = legacy.migrate_rows(
            connection,
            clock=context.clock,
            patient_ids=context.patient_ids,
            actor=context.actor,
        )
        logger.info(
            "Converted %d patient(s), %d record(s), %d diagnosis(es)",
            result.patients_converted,
            result.records_converted,
            result.diagnoses_converted,
        )


#: Every migration, in order. Append to this list; never edit an applied entry.
MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "Initial relational schema", _apply_v1),
)


def execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Run a multi-statement DDL script inside the caller's transaction.

    ``sqlite3.executescript`` commits any open transaction before running, which
    would defeat the atomicity a migration depends on. Splitting the script and
    executing statement by statement keeps the whole migration in one
    transaction. The DDL contains no semicolons inside string literals or
    triggers, so splitting on ``;`` is safe here.
    """
    for statement in _split_statements(script):
        connection.execute(statement)


def _split_statements(script: str) -> list[str]:
    without_comments = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("--")
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


class MigrationRunner:
    """Brings a database up to the current schema version."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Clock | None = None,
        patient_ids: PatientIdSettings | None = None,
        actor: str = SYSTEM_ACTOR,
        migrations: Sequence[Migration] | None = None,
    ) -> None:
        self.database = database
        self.migrations: tuple[Migration, ...] = tuple(migrations or MIGRATIONS)
        self.context = MigrationContext(
            clock=clock or SystemClock(),
            patient_ids=patient_ids or PatientIdSettings(),
            actor=actor,
        )

    # ---------- inspection ----------

    def current_version(self) -> int:
        """The version recorded in the database."""
        with self.database.connection() as connection:
            return self._read_user_version(connection)

    def pending(self) -> list[Migration]:
        """Migrations that have not been applied yet."""
        current = self.current_version()
        return [m for m in self.migrations if m.version > current]

    def is_up_to_date(self) -> bool:
        return not self.pending()

    # ---------- execution ----------

    def migrate(self) -> list[int]:
        """Apply every pending migration. Returns the versions applied."""
        applied: list[int] = []

        with self.database.transaction() as connection:
            current = self._read_user_version(connection)

            if current > SCHEMA_VERSION:
                raise MigrationError(
                    f"This database is at schema version {current}, but this build of "
                    f"MedFlow only understands version {SCHEMA_VERSION}. "
                    "It was probably written by a newer version of the application."
                )

            for migration in self.migrations:
                if migration.version <= current:
                    continue

                logger.info(
                    "Applying migration %d: %s", migration.version, migration.description
                )
                try:
                    migration.apply(connection, self.context)
                except MigrationError:
                    raise
                except Exception as exc:
                    raise MigrationError(
                        f"Migration {migration.version} "
                        f"('{migration.description}') failed: {exc}"
                    ) from exc

                # The version, the ledger row and the migration itself commit
                # together, so a database can never claim a version it does not
                # actually have.
                connection.execute(f"PRAGMA user_version = {int(migration.version)}")
                self._record(connection, migration)
                applied.append(migration.version)

        if applied:
            logger.info("Schema is now at version %d", applied[-1])
        return applied

    # ---------- internals ----------

    @staticmethod
    def _read_user_version(connection: sqlite3.Connection) -> int:
        row = connection.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row is not None else 0

    @staticmethod
    def _record(connection: sqlite3.Connection, migration: Migration) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                applied_at  TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO schema_migrations (version, description, applied_at)
            VALUES (?, ?, ?)
            ON CONFLICT (version) DO UPDATE SET
                description = excluded.description,
                applied_at  = excluded.applied_at
            """,
            (
                migration.version,
                migration.description,
                format_timestamp(SystemClock().now()),
            ),
        )

    def applied_history(self) -> list[sqlite3.Row]:
        """Rows from the migration ledger, newest first."""
        with self.database.connection() as connection:
            try:
                return connection.execute(
                    "SELECT version, description, applied_at "
                    "FROM schema_migrations ORDER BY version DESC"
                ).fetchall()
            except sqlite3.Error:
                return []
