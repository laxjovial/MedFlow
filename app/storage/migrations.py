"""Schema versioning and migration runner.

``user_version`` in the SQLite header tracks the schema generation. Every
migration is a plain function taking a connection; they run in order and
each is idempotent. A brand-new database applies all migrations from zero.
"""

from __future__ import annotations

import sqlite3

from app.storage.schema import SCHEMA_VERSION, iter_tables
from app.utils.logging_utils import get_logger

log = get_logger("storage.migrations")

# Future migrations append here: (target_version, callable(conn)).
# Each entry must bring the database from target_version - 1 to target_version.
MIGRATIONS: list[tuple[int, "callable"]] = [
    # v1 -> v2: Google identities, self-service signup, temporary scoped users
    (2, lambda conn: (
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT"),
        conn.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT "
                     "NOT NULL DEFAULT 'password'"),
        conn.execute("ALTER TABLE users ADD COLUMN expires_at TEXT"),
        conn.execute("ALTER TABLE users ADD COLUMN scope_patient_ids TEXT"),
    )),
]


def get_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {int(version)}")


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create every table (idempotent) and stamp the schema version."""
    for ddl in iter_tables():
        conn.execute(ddl)
    set_user_version(conn, SCHEMA_VERSION)


def migrate(conn: sqlite3.Connection) -> int:
    """Bring an existing database up to SCHEMA_VERSION. Returns version."""
    current = get_user_version(conn)

    if current == 0:
        log.info("creating schema v%d", SCHEMA_VERSION)
        apply_schema(conn)
        return SCHEMA_VERSION

    if current == SCHEMA_VERSION:
        return current

    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema v{current} is newer than this MedFlow build "
            f"(v{SCHEMA_VERSION}). Update the application."
        )

    for target, step in MIGRATIONS:
        if current < target <= SCHEMA_VERSION:
            log.info("migrating schema v%d -> v%d", target - 1, target)
            step(conn)
            set_user_version(conn, target)

    return get_user_version(conn)
