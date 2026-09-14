"""SQLite schema: one place defines every table.

The schema is versioned and migrated by :mod:`app.storage.migrations`.
Local mode and the FastAPI server share it byte-for-byte, so a database
file can move between a desktop install and a hosted server without
translation.
"""

SCHEMA_VERSION = 2

TABLES: tuple[str, ...] = (
    # --- identity / organization ---
    """
    CREATE TABLE IF NOT EXISTS units (
        unit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'department',
        parent_id INTEGER REFERENCES units(unit_id),
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        unit_id INTEGER REFERENCES units(unit_id),
        password_hash TEXT,
        email TEXT,
        auth_provider TEXT NOT NULL DEFAULT 'password',
        expires_at TEXT,
        scope_patient_ids TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY,
        label TEXT,
        unit_id INTEGER REFERENCES units(unit_id),
        last_seen_at TEXT,
        registered_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shift_assignments (
        shift_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(user_id),
        unit_id INTEGER REFERENCES units(unit_id),
        starts_at TEXT,
        ends_at TEXT
    )
    """,
    # --- patients ---
    """
    CREATE TABLE IF NOT EXISTS patients (
        patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_number TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        age INTEGER,
        sex TEXT,
        date_of_birth TEXT,
        phone TEXT,
        email TEXT,
        address TEXT,
        blood_pressure TEXT,
        heart_rate INTEGER,
        weight REAL,
        medical_history TEXT,
        diagnosis TEXT,
        notes TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT,
        updated_at TEXT,
        created_by TEXT,
        updated_by TEXT,
        device_id TEXT,
        origin_unit_id INTEGER REFERENCES units(unit_id),
        deleted INTEGER NOT NULL DEFAULT 0,
        change_id TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_patients_number ON patients(patient_number)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_patients_name ON patients(name)
    """,
    # --- clinical chart ---
    """
    CREATE TABLE IF NOT EXISTS vitals (
        vitals_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        blood_pressure TEXT,
        heart_rate INTEGER,
        temperature_c REAL,
        respiratory_rate INTEGER,
        oxygen_saturation REAL,
        recorded_at TEXT,
        recorded_by TEXT,
        device_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS diagnoses (
        diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        code TEXT,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        diagnosed_at TEXT,
        resolved_at TEXT,
        diagnosed_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS medications (
        medication_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        dose TEXT,
        route TEXT,
        frequency TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        started_at TEXT,
        ended_at TEXT,
        prescribed_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS allergies (
        allergy_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        substance TEXT NOT NULL,
        reaction TEXT,
        severity TEXT NOT NULL DEFAULT 'unknown',
        noted_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lab_results (
        lab_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        panel TEXT NOT NULL,
        analyte TEXT NOT NULL,
        value TEXT,
        unit TEXT,
        reference_range TEXT,
        flag TEXT NOT NULL DEFAULT 'normal',
        collected_at TEXT,
        resulted_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notes (
        note_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        author TEXT,
        unit_id INTEGER REFERENCES units(unit_id),
        category TEXT NOT NULL DEFAULT 'progress',
        body TEXT NOT NULL DEFAULT '',
        created_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_vitals_patient ON vitals(patient_id, recorded_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_diagnoses_patient ON diagnoses(patient_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_medications_patient ON medications(patient_id)
    """,
    # --- appointments / schedule ---
    """
    CREATE TABLE IF NOT EXISTS appointments (
        appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        unit_id INTEGER REFERENCES units(unit_id),
        scheduled_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL DEFAULT 30,
        provider TEXT,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'scheduled',
        created_at TEXT,
        created_by TEXT,
        device_id TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_appointments_when ON appointments(scheduled_at)
    """,
    # --- audit / history ---
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        details TEXT,
        actor TEXT,
        device_id TEXT,
        unit_id INTEGER,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS patient_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        description TEXT NOT NULL,
        actor TEXT,
        unit_id INTEGER,
        created_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
)


def iter_tables():
    """Yield DDL statements in dependency-safe order."""
    yield from TABLES
