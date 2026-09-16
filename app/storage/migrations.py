"""Schema versioning and migration runner.

``user_version`` in the SQLite header tracks the schema generation. Every
migration is a plain function taking a connection; they run in order and
each is idempotent. A brand-new database applies all migrations from zero.
"""

from __future__ import annotations

import re
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
    # v2 -> v3: staff profiles — job title and contact number per account
    (3, lambda conn: (
        conn.execute("ALTER TABLE users ADD COLUMN job_title TEXT"),
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT"),
    )),
    # v3 -> v4: record template — facility-defined chart fields + per-patient values
    (4, lambda conn: (
        conn.execute("""
            CREATE TABLE IF NOT EXISTS record_templates (
                template_id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                value_type TEXT NOT NULL DEFAULT 'text',
                choices TEXT,
                unit TEXT,
                section TEXT NOT NULL DEFAULT 'General',
                sort_order INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                created_by TEXT,
                updated_at TEXT
            )
        """),
        conn.execute("""
            CREATE TABLE IF NOT EXISTS record_template_values (
                value_id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL REFERENCES record_templates(template_id) ON DELETE CASCADE,
                patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
                value_text TEXT,
                updated_at TEXT,
                updated_by TEXT,
                UNIQUE(template_id, patient_id)
            )
        """),
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rtv_patient "
                     "ON record_template_values(patient_id)"),
        seed_template_defaults(conn),
    )),
    # v4 -> v5: notifications, staff invites, multi-department patients
    (5, lambda conn: (
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_departments (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
                unit_id INTEGER NOT NULL REFERENCES units(unit_id) ON DELETE CASCADE,
                assigned_at TEXT,
                assigned_by TEXT,
                UNIQUE(patient_id, unit_id)
            )
        """),
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pdept_unit "
                     "ON patient_departments(unit_id)"),
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                kind TEXT NOT NULL DEFAULT 'general',
                title TEXT NOT NULL,
                body TEXT,
                link TEXT,
                read INTEGER NOT NULL DEFAULT 0,
                read_at TEXT,
                created_at TEXT,
                created_by TEXT
            )
        """),
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_user "
                     "ON notifications(user_id, read)"),
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                invite_id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'viewer',
                unit_id INTEGER REFERENCES units(unit_id),
                label TEXT,
                created_by TEXT,
                created_at TEXT,
                expires_at TEXT NOT NULL,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                revoked INTEGER NOT NULL DEFAULT 0
            )
        """),
        conn.execute("UPDATE users SET active = active WHERE 1"),
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
    seed_template_defaults(conn)
    conn.commit()


DEFAULT_TEMPLATE_FIELDS = (
    # label, value_type, choices, unit, section
    ("Blood group", "choice", "A+, A-, B+, B-, O+, O-, AB+, AB-", "", "Screening"),
    ("Genotype", "choice", "AA, AS, AC, SS, other", "", "Screening"),
    ("Next of kin", "text", "", "", "Social history"),
    ("Next of kin phone", "text", "", "", "Social history"),
    ("Referral source", "text", "", "", "Social history"),
)


def seed_template_defaults(conn: sqlite3.Connection) -> None:
    """Give a fresh facility a sensible starter template, exactly once.

    Guarded by a ``schema_meta`` flag so fields a clinic deliberately
    deleted are never resurrected on the next launch.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        "key TEXT PRIMARY KEY, value TEXT)")
    seeded = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'template_seeded'"
    ).fetchone()
    if seeded:
        return
    from app.utils.dates import to_iso, utcnow
    now = to_iso(utcnow())
    for order, (label, vtype, choices, unit, section) in enumerate(
            DEFAULT_TEMPLATE_FIELDS):
        key = "_".join(w for w in re.split(r"\W+", label.lower()) if w)
        conn.execute(
            "INSERT OR IGNORE INTO record_templates "
            "(field_key, label, value_type, choices, unit, section, "
            " sort_order, active, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 'system')",
            (key, label, vtype, choices or None, unit or None,
             section, order, now),
        )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) "
        "VALUES ('template_seeded', '1')"
    )


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
            # BEGIN IMMEDIATE serializes concurrent openers: whoever loses
            # the race re-checks inside the lock and skips if already done.
            conn.execute("BEGIN IMMEDIATE")
            try:
                if get_user_version(conn) < target:
                    log.info("migrating schema v%d -> v%d", target - 1, target)
                    step(conn)
                    set_user_version(conn, target)
                    conn.commit()
                else:
                    conn.execute("ROLLBACK")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            current = target

    return get_user_version(conn)
