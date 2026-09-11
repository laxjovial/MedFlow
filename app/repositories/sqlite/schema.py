"""Schema definition.

The pre-refactor application stored everything in one flat ``patients`` table
(``patient_id, name, age, bp, hr, history, diag``). That shape cannot express a
patient with a history of diagnoses, cannot record who changed what, and cannot
distinguish a deleted record from a missing one.

Schema v1 splits those concerns across related tables. See docs/ARCHITECTURE.md
for the reasoning behind each.
"""

from __future__ import annotations

#: Current schema version. Bump this when adding a migration.
SCHEMA_VERSION = 1

#: Applied as one unit by the version 1 migration.
SCHEMA_V1 = """
-- Identity and demographics.
CREATE TABLE IF NOT EXISTS patients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_number  TEXT    NOT NULL UNIQUE,
    first_name      TEXT    NOT NULL DEFAULT '',
    last_name       TEXT    NOT NULL DEFAULT '',
    date_of_birth   TEXT,
    age_years       TEXT,
    sex             TEXT,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',
    record_version  INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    created_by      TEXT    NOT NULL DEFAULT '',
    updated_by      TEXT    NOT NULL DEFAULT '',
    deleted_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_patients_name
    ON patients (last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_patients_updated_at
    ON patients (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_patients_deleted_at
    ON patients (deleted_at);

-- Current clinical snapshot, one row per patient.
CREATE TABLE IF NOT EXISTS patient_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL UNIQUE
                    REFERENCES patients (id) ON DELETE CASCADE,
    blood_pressure  TEXT,
    heart_rate      TEXT,
    weight          TEXT,
    height          TEXT,
    medical_history TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- One row per diagnosis. A patient accumulates these over time, so the history
-- survives rather than being overwritten by the latest entry.
CREATE TABLE IF NOT EXISTS diagnoses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL
                 REFERENCES patients (id) ON DELETE CASCADE,
    diagnosis    TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'active',
    notes        TEXT,
    diagnosed_at TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_diagnoses_patient
    ON diagnoses (patient_id, status);
CREATE INDEX IF NOT EXISTS idx_diagnoses_text
    ON diagnoses (diagnosis);

-- The patient's own timeline: "what is this patient's story?"
CREATE TABLE IF NOT EXISTS patient_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER NOT NULL
                REFERENCES patients (id) ON DELETE CASCADE,
    event_type  TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    actor       TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_patient_events_patient
    ON patient_events (patient_id, created_at DESC);

-- The application's audit trail: "who touched this record, and when?"
-- Deliberately distinct from patient_events. Covers non-patient actions too
-- (exports, imports, backups, migrations), hence the free-form entity columns.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL DEFAULT '',
    actor       TEXT NOT NULL DEFAULT '',
    details     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created
    ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity
    ON audit_log (entity_type, entity_id);

-- Monotonic counters. Patient numbers are allocated from here rather than from
-- MAX(patient_number) + 1, so a deleted record can never have its number reused
-- by a later patient.
CREATE TABLE IF NOT EXISTS sequences (
    name  TEXT    PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

-- Human-readable ledger of applied migrations. The authoritative version is
-- SQLite's user_version pragma; this table exists so an operator can see what
-- happened without running a pragma.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    applied_at  TEXT NOT NULL
);
"""

#: Sequence name backing patient numbering.
PATIENT_NUMBER_SEQUENCE = "patient_number"
