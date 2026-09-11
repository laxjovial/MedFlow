"""Conversion of the pre-refactor flat schema into schema v1.

The old application kept everything in one table::

    patients (patient_id, name, age, bp, hr, history, diag, created_at)

Schema v1 splits that across ``patients``, ``patient_records`` and ``diagnoses``.
This module detects the old shape, moves it aside, and converts every row.

Two properties matter here:

* **Nothing is lost.** Every legacy column is carried into a column that means
  the same thing. Where the old schema had no equivalent (a date of birth was
  never recorded), the new column is left empty rather than guessed at.
* **Nothing is half-done.** The whole conversion runs in the migration's
  transaction. If any row fails, the original table is left untouched.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from app.config.settings import PatientIdSettings
from app.core.clock import Clock, format_timestamp
from app.core.validators import clean_text
from app.domain.enums import AuditAction, DiagnosisStatus, EntityType, EventType
from app.repositories.sqlite.schema import PATIENT_NUMBER_SEQUENCE

#: The table the previous version of MedFlow used.
LEGACY_TABLE = "patients"

#: Where the legacy table is parked while it is converted.
LEGACY_BACKUP_TABLE = "patients_legacy"

#: Columns that identify the old schema. Their presence is the detection signal.
LEGACY_SIGNATURE_COLUMNS = frozenset(
    {"patient_id", "name", "age", "bp", "hr", "history", "diag"}
)

_DIGITS = re.compile(r"(\d+)")


@dataclass
class LegacyConversionResult:
    """Outcome of a legacy conversion, for logging and for tests to assert on."""

    patients_converted: int = 0
    records_converted: int = 0
    diagnoses_converted: int = 0
    highest_ordinal: int = 0

    @property
    def is_empty(self) -> bool:
        return self.patients_converted == 0


# ---------- detection ----------


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {row["name"] for row in rows}


def has_legacy_schema(connection: sqlite3.Connection) -> bool:
    """Whether this database predates the refactor.

    Requires the legacy table to carry the old column set *and* to lack the new
    ``patient_number`` column, so a database already on schema v1 is never
    mistaken for a legacy one.
    """
    if not table_exists(connection, LEGACY_TABLE):
        return False

    columns = table_columns(connection, LEGACY_TABLE)
    if "patient_number" in columns:
        return False

    return LEGACY_SIGNATURE_COLUMNS.issubset(columns)


def rename_legacy_table(connection: sqlite3.Connection) -> None:
    """Park the legacy table so the new schema can claim the ``patients`` name."""
    if table_exists(connection, LEGACY_BACKUP_TABLE):
        connection.execute(f'DROP TABLE "{LEGACY_BACKUP_TABLE}"')
    connection.execute(f'ALTER TABLE "{LEGACY_TABLE}" RENAME TO "{LEGACY_BACKUP_TABLE}"')


# ---------- value conversion ----------


def split_name(name: str) -> tuple[str, str]:
    """Split a single stored name into first and last parts.

    The old application captured one free-text name. Splitting on the final
    space keeps multi-part given names intact — "Mary Jane Watson" becomes
    "Mary Jane" and "Watson", not "Mary" and "Jane Watson".
    """
    cleaned = clean_text(name)
    if not cleaned:
        return "", ""

    parts = cleaned.split()
    if len(parts) == 1:
        return parts[0], ""

    return " ".join(parts[:-1]), parts[-1]


def extract_ordinal(legacy_id: str) -> int | None:
    """Pull the numeric part out of an identifier such as ``Patient 001``."""
    match = _DIGITS.search(str(legacy_id or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - the regex guarantees digits
        return None


def format_patient_number(ordinal: int, settings: PatientIdSettings) -> str:
    """Render an ordinal in the configured patient-number format."""
    return f"{settings.prefix}-{ordinal:0{settings.padding}d}"


# ---------- conversion ----------


def migrate_rows(
    connection: sqlite3.Connection,
    *,
    clock: Clock,
    patient_ids: PatientIdSettings,
    actor: str,
) -> LegacyConversionResult:
    """Convert every row from the parked legacy table into schema v1.

    Must be called with the legacy table already renamed and the new schema
    created. Runs inside the caller's transaction.
    """
    result = LegacyConversionResult()

    rows = connection.execute(
        f'SELECT * FROM "{LEGACY_BACKUP_TABLE}" ORDER BY rowid'
    ).fetchall()

    if not rows:
        connection.execute(f'DROP TABLE "{LEGACY_BACKUP_TABLE}"')
        return result

    moment = format_timestamp(clock.now())
    used_numbers: set[str] = set()
    # Ordinals taken from the legacy identifiers, so numbering continues from
    # where the previous version left off rather than restarting at one.
    highest = 0
    fallback_ordinal = 0

    for row in rows:
        legacy_id = str(row["patient_id"] or "")

        ordinal = extract_ordinal(legacy_id)
        if ordinal is None or ordinal < 1:
            fallback_ordinal += 1
            ordinal = highest + fallback_ordinal

        while True:
            candidate = format_patient_number(ordinal, patient_ids)
            if candidate not in used_numbers:
                break
            ordinal += 1

        used_numbers.add(candidate)
        highest = max(highest, ordinal)

        first_name, last_name = split_name(str(row["name"] or ""))
        created_at = str(row["created_at"] or moment)

        cursor = connection.execute(
            """
            INSERT INTO patients (
                patient_number, first_name, last_name, age_years,
                status, record_version, created_at, updated_at,
                created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                candidate,
                first_name,
                last_name,
                clean_text(row["age"]),
                "active",
                created_at,
                created_at,
                actor,
                actor,
            ),
        )
        patient_id = cursor.lastrowid
        result.patients_converted += 1

        # Clinical snapshot. "--" placeholders become empty rather than being
        # carried forward as literal dashes.
        connection.execute(
            """
            INSERT INTO patient_records (
                patient_id, blood_pressure, heart_rate,
                medical_history, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                clean_text(row["bp"]),
                clean_text(row["hr"]),
                clean_text(row["history"]),
                created_at,
                created_at,
            ),
        )
        result.records_converted += 1

        diagnosis_text = clean_text(row["diag"])
        if diagnosis_text:
            connection.execute(
                """
                INSERT INTO diagnoses (
                    patient_id, diagnosis, status, diagnosed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    patient_id,
                    diagnosis_text,
                    DiagnosisStatus.ACTIVE.value,
                    created_at,
                    created_at,
                    created_at,
                ),
            )
            result.diagnoses_converted += 1

        connection.execute(
            """
            INSERT INTO patient_events (patient_id, event_type, description, actor, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                EventType.MIGRATED.value,
                f"Converted from the previous version (was {legacy_id}).",
                actor,
                moment,
            ),
        )

        connection.execute(
            """
            INSERT INTO audit_log (action, entity_type, entity_id, actor, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                AuditAction.MIGRATE.value,
                EntityType.PATIENT.value,
                candidate,
                actor,
                f'{{"legacy_id": "{legacy_id}", "patient_number": "{candidate}"}}',
                moment,
            ),
        )

    result.highest_ordinal = highest

    # Point the sequence past everything that was migrated, so the next new
    # patient continues the numbering instead of colliding with it.
    if highest > 0:
        connection.execute(
            """
            INSERT INTO sequences (name, value) VALUES (?, ?)
            ON CONFLICT (name) DO UPDATE SET value = MAX(value, excluded.value)
            """,
            (PATIENT_NUMBER_SEQUENCE, highest),
        )

    connection.execute(f'DROP TABLE "{LEGACY_BACKUP_TABLE}"')
    return result
