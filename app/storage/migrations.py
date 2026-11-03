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

def _migrate_sync_change_log(conn: sqlite3.Connection) -> None:
    """Install the monotonic patient change log on current and legacy DBs."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(patients)").fetchall()}
    for name, declaration in (
        ("version", "INTEGER NOT NULL DEFAULT 1"),
        ("updated_at", "TEXT"),
        ("device_id", "TEXT"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE patients ADD COLUMN {name} {declaration}")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_change_log (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        version INTEGER NOT NULL,
        device_id TEXT,
        changed_at TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_change_log_patient ON sync_change_log(patient_id, seq)")
    conn.execute("""
        INSERT INTO sync_change_log(patient_id, version, device_id, changed_at)
        SELECT patient_id, version, device_id, updated_at FROM patients
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_patients_sync_insert
        AFTER INSERT ON patients BEGIN
            INSERT INTO sync_change_log(patient_id, version, device_id, changed_at)
            VALUES (NEW.patient_id, NEW.version, NEW.device_id, NEW.updated_at);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_patients_sync_update
        AFTER UPDATE ON patients BEGIN
            INSERT INTO sync_change_log(patient_id, version, device_id, changed_at)
            VALUES (NEW.patient_id, NEW.version, NEW.device_id, NEW.updated_at);
        END
    """)


def _migrate_sync_hardening(conn: sqlite3.Connection) -> None:
    """Add immutable revision snapshots, device-bound sessions and batch receipts."""
    patient_cols = {row[1] for row in conn.execute("PRAGMA table_info(patients)")}
    for name, declaration in (
        ("created_by", "TEXT"), ("updated_by", "TEXT"),
        ("origin_unit_id", "INTEGER"), ("deleted", "INTEGER NOT NULL DEFAULT 0"),
        ("change_id", "TEXT"),
    ):
        if name not in patient_cols:
            conn.execute(f"ALTER TABLE patients ADD COLUMN {name} {declaration}")
    session_cols = {row[1] for row in conn.execute("PRAGMA table_info(auth_sessions)")}
    if "device_id" not in session_cols:
        conn.execute("ALTER TABLE auth_sessions ADD COLUMN device_id TEXT")
    log_cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_change_log)")}
    if "snapshot" not in log_cols:
        conn.execute("ALTER TABLE sync_change_log ADD COLUMN snapshot TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_batches (
            device_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            response_json TEXT NOT NULL,
            payload_hash TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY(device_id, batch_id)
        )
    """)
    batch_cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_batches)")}
    if "payload_hash" not in batch_cols:
        conn.execute("ALTER TABLE sync_batches ADD COLUMN payload_hash TEXT")
    conn.execute("DROP TRIGGER IF EXISTS trg_patients_sync_insert")
    conn.execute("DROP TRIGGER IF EXISTS trg_patients_sync_update")
    snapshot = """json_object(
        'patient_id', NEW.patient_id, 'patient_number', NEW.patient_number,
        'name', NEW.name, 'age', NEW.age, 'sex', NEW.sex,
        'date_of_birth', NEW.date_of_birth, 'phone', NEW.phone,
        'email', NEW.email, 'address', NEW.address,
        'blood_pressure', NEW.blood_pressure, 'heart_rate', NEW.heart_rate,
        'weight', NEW.weight, 'medical_history', NEW.medical_history,
        'diagnosis', NEW.diagnosis, 'notes', NEW.notes,
        'version', NEW.version, 'created_at', NEW.created_at,
        'updated_at', NEW.updated_at, 'created_by', NEW.created_by,
        'updated_by', NEW.updated_by, 'device_id', NEW.device_id,
        'origin_unit_id', NEW.origin_unit_id, 'deleted', NEW.deleted,
        'change_id', NEW.change_id
    )"""
    for operation in ("INSERT", "UPDATE"):
        suffix = "insert" if operation == "INSERT" else "update"
        conn.execute(f"""
            CREATE TRIGGER trg_patients_sync_{suffix}
            AFTER {operation} ON patients BEGIN
                INSERT INTO sync_change_log
                    (patient_id, version, device_id, changed_at, snapshot)
                VALUES (NEW.patient_id, NEW.version, NEW.device_id,
                        NEW.updated_at, {snapshot});
            END
        """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_patient_department_sync_insert
        AFTER INSERT ON patient_departments BEGIN
            UPDATE patients SET version = version + 1, updated_at = datetime('now')
            WHERE patient_id = NEW.patient_id;
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_patient_department_sync_delete
        AFTER DELETE ON patient_departments BEGIN
            UPDATE patients SET version = version + 1, updated_at = datetime('now')
            WHERE patient_id = OLD.patient_id;
        END
    """)
    conn.execute("""
        UPDATE sync_change_log
        SET snapshot = (
            SELECT json_object(
                'patient_id', p.patient_id, 'patient_number', p.patient_number,
                'name', p.name, 'age', p.age, 'sex', p.sex,
                'date_of_birth', p.date_of_birth, 'phone', p.phone,
                'email', p.email, 'address', p.address,
                'blood_pressure', p.blood_pressure, 'heart_rate', p.heart_rate,
                'weight', p.weight, 'medical_history', p.medical_history,
                'diagnosis', p.diagnosis, 'notes', p.notes,
                'version', p.version, 'created_at', p.created_at,
                'updated_at', p.updated_at, 'created_by', p.created_by,
                'updated_by', p.updated_by, 'device_id', p.device_id,
                'origin_unit_id', p.origin_unit_id, 'deleted', p.deleted,
                'change_id', p.change_id
            ) FROM patients p WHERE p.patient_id = sync_change_log.patient_id
        )
        WHERE snapshot IS NULL
    """)



def _migrate_device_scope(conn: sqlite3.Connection) -> None:
    """Add workstation ownership, scope assignment and revocation state."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY, label TEXT,
            unit_id INTEGER REFERENCES units(unit_id),
            last_seen_at TEXT, registered_at TEXT
        )
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}
    for name, declaration in (
        ("owner_user_id", "INTEGER REFERENCES users(user_id)"),
        ("revoked_at", "TEXT"),
        ("scope_version", "INTEGER NOT NULL DEFAULT 1"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE devices ADD COLUMN {name} {declaration}")
    conn.execute("DROP TRIGGER IF EXISTS trg_patients_sync_insert")
    conn.execute("DROP TRIGGER IF EXISTS trg_patients_sync_update")
    snapshot = """json_object(
        'patient_id', NEW.patient_id, 'patient_number', NEW.patient_number,
        'name', NEW.name, 'age', NEW.age, 'sex', NEW.sex,
        'date_of_birth', NEW.date_of_birth, 'phone', NEW.phone,
        'email', NEW.email, 'address', NEW.address,
        'blood_pressure', NEW.blood_pressure, 'heart_rate', NEW.heart_rate,
        'weight', NEW.weight, 'medical_history', NEW.medical_history,
        'diagnosis', NEW.diagnosis, 'notes', NEW.notes,
        'version', NEW.version, 'created_at', NEW.created_at,
        'updated_at', NEW.updated_at, 'created_by', NEW.created_by,
        'updated_by', NEW.updated_by, 'device_id', NEW.device_id,
        'origin_unit_id', NEW.origin_unit_id, 'deleted', NEW.deleted,
        'department_ids', (SELECT json_group_array(unit_id)
                           FROM patient_departments
                           WHERE patient_id = NEW.patient_id),
        'change_id', NEW.change_id
    )"""
    for operation in ("INSERT", "UPDATE"):
        suffix = "insert" if operation == "INSERT" else "update"
        conn.execute(f"""
            CREATE TRIGGER trg_patients_sync_{suffix}
            AFTER {operation} ON patients BEGIN
                INSERT INTO sync_change_log
                    (patient_id, version, device_id, changed_at, snapshot)
                VALUES (NEW.patient_id, NEW.version, NEW.device_id,
                        NEW.updated_at, {snapshot});
            END
        """)
    conn.execute("""
        UPDATE sync_change_log
        SET snapshot = (
            SELECT json_set(snapshot, '$.department_ids',
                COALESCE((SELECT json_group_array(unit_id)
                          FROM patient_departments pd
                          WHERE pd.patient_id = sync_change_log.patient_id), json('[]')))
            FROM sync_change_log l
            WHERE l.seq = sync_change_log.seq
        )
        WHERE snapshot IS NOT NULL
    """)

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
    # v5 -> v6: persisted auth sessions for revocation and session lifecycle.
    (6, lambda conn: (
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                jti TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                client_type TEXT NOT NULL DEFAULT 'api',
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER
            )
        """),
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_active "
            "ON auth_sessions(user_id, revoked_at, expires_at)"
        ),
    )),
    # v6 -> v7: durable, idempotent sync conflict review queue.
    (7, lambda conn: (
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_conflicts (
                conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                local_version INTEGER NOT NULL,
                remote_version INTEGER NOT NULL,
                local_snapshot TEXT NOT NULL,
                remote_snapshot TEXT NOT NULL,
                conflicting_fields TEXT NOT NULL,
                source_device_id TEXT,
                detected_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'resolved', 'rejected')),
                resolved_by TEXT,
                resolved_at TEXT,
                resolution_choice TEXT,
                resolution_snapshot TEXT
            )
        """),
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sync_conflicts_status_detected "
            "ON sync_conflicts(status, detected_at)"
        ),
    )),
    # v7 -> v8: monotonic patient change sequence for incremental sync.
    (8, _migrate_sync_change_log),
    # v8 -> v9: immutable patient snapshots, device-bound sessions and batch receipts.
    (9, _migrate_sync_hardening),
    # v9 -> v10: device ownership/revocation and department-aware snapshots.
    (10, _migrate_device_scope),
    # v10 -> v11: durable scope removal events for de-scoped patients.
    (11, lambda conn: (
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_scope_events (
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                patient_id INTEGER,
                patient_number TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'de_scoped',
                created_at TEXT NOT NULL
            )
        """),
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sync_scope_events_device_seq "
            "ON sync_scope_events(device_id, event_seq)"
        ),
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
