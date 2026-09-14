"""SQLite implementation of the patient repository.

All SQL in the application lives behind this module. Services depend on
:class:`~app.repositories.patient_repository.PatientRepository`, so nothing above
this file knows that storage happens to be SQLite — which is what makes the
networked implementation a drop-in later.

Two safety rules are enforced here:

* Sorting is resolved through a whitelist. A ``sort_by`` value that is not
  recognised falls back to the default instead of reaching the query, so the
  parameter can never become a SQL injection point.
* Every value is passed as a bound parameter. The only strings ever interpolated
  into SQL are the whitelisted sort columns and generated placeholder lists.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from app.config.settings import PatientIdSettings
from app.core.exceptions import PersistenceError
from app.domain.diagnosis import Diagnosis
from app.domain.enums import DEFAULT_SORT, PatientStatus
from app.domain.patient import Patient, PatientRecord
from app.domain.summary import DiagnosisCount, RepositoryStatistics
from app.repositories.patient_repository import PatientRepository
from app.repositories.sqlite.connection import Database
from app.repositories.sqlite.schema import PATIENT_NUMBER_SEQUENCE

#: Whitelisted sort keys and the columns each one orders by. Splitting "name"
#: into two columns is why these are tuples rather than a single expression.
SORT_COLUMNS: dict[str, tuple[str, ...]] = {
    "patient_number": ("p.patient_number",),
    "name": ("p.last_name", "p.first_name"),
    "created_at": ("p.created_at",),
    "updated_at": ("p.updated_at",),
}

_SELECT_PATIENTS = """
    SELECT
        p.id, p.patient_number, p.first_name, p.last_name,
        p.date_of_birth, p.age_years, p.sex, p.phone, p.email, p.address,
        p.status, p.record_version, p.created_at, p.updated_at,
        p.created_by, p.updated_by, p.deleted_at,
        r.blood_pressure      AS r_blood_pressure,
        r.heart_rate          AS r_heart_rate,
        r.weight              AS r_weight,
        r.height              AS r_height,
        r.medical_history     AS r_medical_history,
        r.notes               AS r_notes,
        r.created_at          AS r_created_at,
        r.updated_at          AS r_updated_at
    FROM patients p
    LEFT JOIN patient_records r ON r.patient_id = p.id
"""


class SqlitePatientRepository(PatientRepository):
    """Patient storage backed by SQLite."""

    def __init__(self, database: Database, patient_ids: PatientIdSettings) -> None:
        self._database = database
        self._patient_ids = patient_ids

    # ---------- numbering ----------

    def allocate_patient_number(self) -> str:
        """Reserve the next patient number.

        The counter is stored independently of the rows, so deleting a patient
        never makes their number available again.
        """
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO sequences (name, value) VALUES (?, 1)
                    ON CONFLICT (name) DO UPDATE SET value = value + 1
                    """,
                    (PATIENT_NUMBER_SEQUENCE,),
                )
                row = connection.execute(
                    "SELECT value FROM sequences WHERE name = ?",
                    (PATIENT_NUMBER_SEQUENCE,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not allocate a patient number: {exc}") from exc

        ordinal = int(row["value"]) if row else 1
        return f"{self._patient_ids.prefix}-{ordinal:0{self._patient_ids.padding}d}"

    # ---------- writes ----------

    def insert(self, patient: Patient) -> Patient:
        """Persist a new patient and their clinical record.

        Diagnoses are *not* written here; they go through
        :meth:`add_diagnosis`, so there is exactly one code path that creates a
        diagnosis row and every one of them is a deliberate act with its own
        timeline entry.
        """
        if not patient.patient_number:
            patient.patient_number = self.allocate_patient_number()

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO patients (
                        patient_number, first_name, last_name, date_of_birth,
                        age_years, sex, phone, email, address, status,
                        record_version, created_at, updated_at, created_by, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        patient.patient_number,
                        patient.first_name,
                        patient.last_name,
                        patient.date_of_birth,
                        patient.age_years,
                        patient.sex,
                        patient.phone,
                        patient.email,
                        patient.address,
                        patient.status,
                        patient.record_version,
                        patient.created_at,
                        patient.updated_at,
                        patient.created_by,
                        patient.updated_by,
                    ),
                )
                patient.id = cursor.lastrowid

                connection.execute(
                    """
                    INSERT INTO patient_records (
                        patient_id, blood_pressure, heart_rate, weight, height,
                        medical_history, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        patient.id,
                        patient.record.blood_pressure,
                        patient.record.heart_rate,
                        patient.record.weight,
                        patient.record.height,
                        patient.record.medical_history,
                        patient.record.notes,
                        patient.created_at,
                        patient.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(
                f"Patient {patient.patient_number} already exists: {exc}"
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not create patient: {exc}") from exc

        return patient

    def save(self, patient: Patient) -> Patient:
        if patient.id is None:
            raise PersistenceError("Cannot save a patient that has no identifier")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE patients SET
                        first_name = ?, last_name = ?, date_of_birth = ?,
                        age_years = ?, sex = ?, phone = ?, email = ?, address = ?,
                        status = ?, record_version = record_version + 1,
                        updated_at = ?, updated_by = ?
                    WHERE id = ?
                    """,
                    (
                        patient.first_name,
                        patient.last_name,
                        patient.date_of_birth,
                        patient.age_years,
                        patient.sex,
                        patient.phone,
                        patient.email,
                        patient.address,
                        patient.status,
                        patient.updated_at,
                        patient.updated_by,
                        patient.id,
                    ),
                )

                if cursor.rowcount == 0:
                    raise PersistenceError(
                        f"Patient {patient.patient_number} no longer exists"
                    )

                # A record row is created with the patient, but an upsert keeps
                # this correct even for data migrated or imported another way.
                connection.execute(
                    """
                    INSERT INTO patient_records (
                        patient_id, blood_pressure, heart_rate, weight, height,
                        medical_history, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (patient_id) DO UPDATE SET
                        blood_pressure  = excluded.blood_pressure,
                        heart_rate      = excluded.heart_rate,
                        weight          = excluded.weight,
                        height          = excluded.height,
                        medical_history = excluded.medical_history,
                        notes           = excluded.notes,
                        updated_at      = excluded.updated_at
                    """,
                    (
                        patient.id,
                        patient.record.blood_pressure,
                        patient.record.heart_rate,
                        patient.record.weight,
                        patient.record.height,
                        patient.record.medical_history,
                        patient.record.notes,
                        patient.created_at,
                        patient.updated_at,
                    ),
                )

                patient.record_version += 1
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not update patient: {exc}") from exc

        return patient

    def mark_deleted(self, patient_number: str, *, deleted_at: str, actor: str) -> bool:
        """Soft-delete a patient.

        The row is retained so the record and its history survive, and so the
        patient number is never handed to someone else.
        """
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE patients SET deleted_at = ?, updated_at = ?, updated_by = ?
                    WHERE patient_number = ? AND deleted_at IS NULL
                    """,
                    (deleted_at, deleted_at, actor, patient_number),
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not delete patient: {exc}") from exc

        return cursor.rowcount > 0

    def restore(self, patient_number: str) -> bool:
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE patients SET deleted_at = NULL
                    WHERE patient_number = ? AND deleted_at IS NOT NULL
                    """,
                    (patient_number,),
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not restore patient: {exc}") from exc

        return cursor.rowcount > 0

    # ---------- reads ----------

    def fetch(self, patient_number: str, *, include_deleted: bool = False) -> Patient | None:
        sql = _SELECT_PATIENTS + " WHERE p.patient_number = ?"
        if not include_deleted:
            sql += " AND p.deleted_at IS NULL"

        with self._database.connection() as connection:
            row = connection.execute(sql, (patient_number,)).fetchone()
            if row is None:
                return None
            patient = _to_patient(row)
            self._attach_diagnoses(connection, [patient])

        return patient

    def search(
        self,
        query: str = "",
        *,
        sort_by: str = DEFAULT_SORT,
        descending: bool = True,
        include_deleted: bool = False,
        limit: int | None = None,
    ) -> list[Patient]:
        conditions: list[str] = []
        parameters: list[object] = []

        if not include_deleted:
            conditions.append("p.deleted_at IS NULL")

        search_text = (query or "").strip()
        if search_text:
            pattern = _like_pattern(search_text)
            conditions.append(
                """(
                    p.patient_number LIKE ? ESCAPE '\\'
                    OR p.first_name LIKE ? ESCAPE '\\'
                    OR p.last_name LIKE ? ESCAPE '\\'
                    OR (p.first_name || ' ' || p.last_name) LIKE ? ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1 FROM diagnoses d
                        WHERE d.patient_id = p.id
                          AND d.diagnosis LIKE ? ESCAPE '\\'
                    )
                )"""
            )
            parameters.extend([pattern] * 5)

        sql = _SELECT_PATIENTS
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY " + _order_clause(sort_by, descending)
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)

        with self._database.connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            patients = [_to_patient(row) for row in rows]
            self._attach_diagnoses(connection, patients)

        return patients

    def list_all(self, *, include_deleted: bool = False) -> list[Patient]:
        return self.search(
            "",
            sort_by="patient_number",
            descending=False,
            include_deleted=include_deleted,
        )

    def count(self, *, include_deleted: bool = False) -> int:
        sql = "SELECT COUNT(*) AS total FROM patients"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"

        with self._database.connection() as connection:
            row = connection.execute(sql).fetchone()

        return int(row["total"]) if row else 0

    def statistics(self, *, today: str) -> RepositoryStatistics:
        prefix = f"{today}%"

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM patients WHERE deleted_at IS NULL)
                        AS total_patients,
                    (SELECT COUNT(*) FROM patients
                     WHERE deleted_at IS NULL AND status = ?)
                        AS active_patients,
                    (SELECT COUNT(*) FROM patients
                     WHERE deleted_at IS NULL AND status = ?)
                        AS archived_patients,
                    (SELECT COUNT(*) FROM patients WHERE deleted_at IS NOT NULL)
                        AS deleted_patients,
                    (SELECT COUNT(*) FROM patients
                     WHERE deleted_at IS NULL AND created_at LIKE ?)
                        AS created_today,
                    (SELECT COUNT(*) FROM patients
                     WHERE deleted_at IS NULL AND updated_at LIKE ?)
                        AS updated_today,
                    (SELECT COUNT(*) FROM diagnoses d
                     JOIN patients p ON p.id = d.patient_id
                     WHERE d.status = ? AND p.deleted_at IS NULL)
                        AS active_diagnoses
                """,
                (
                    PatientStatus.ACTIVE.value,
                    PatientStatus.ARCHIVED.value,
                    prefix,
                    prefix,
                    "active",
                ),
            ).fetchone()

        if row is None:  # pragma: no cover - an aggregate always returns one row
            return RepositoryStatistics()

        return RepositoryStatistics(
            total_patients=int(row["total_patients"]),
            active_patients=int(row["active_patients"]),
            archived_patients=int(row["archived_patients"]),
            deleted_patients=int(row["deleted_patients"]),
            created_today=int(row["created_today"]),
            updated_today=int(row["updated_today"]),
            active_diagnoses=int(row["active_diagnoses"]),
        )

    def diagnosis_distribution(self, limit: int = 5) -> list[DiagnosisCount]:
        # Grouping is case-insensitive so "Hypertension" and "hypertension" are
        # one entry; MIN() picks a stable spelling to display.
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT MIN(d.diagnosis) AS diagnosis,
                       COUNT(DISTINCT d.patient_id) AS total
                FROM diagnoses d
                JOIN patients p ON p.id = d.patient_id
                WHERE p.deleted_at IS NULL
                  AND d.diagnosis IS NOT NULL
                  AND TRIM(d.diagnosis) <> ''
                GROUP BY LOWER(TRIM(d.diagnosis))
                ORDER BY total DESC, diagnosis ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            DiagnosisCount(diagnosis=row["diagnosis"], count=int(row["total"]))
            for row in rows
        ]

    # ---------- diagnoses ----------

    def list_diagnoses(self, patient_id: int) -> list[Diagnosis]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, patient_id, diagnosis, status, notes,
                       diagnosed_at, created_at, updated_at
                FROM diagnoses
                WHERE patient_id = ?
                ORDER BY id DESC
                """,
                (patient_id,),
            ).fetchall()

        return [_to_diagnosis(row) for row in rows]

    def add_diagnosis(self, patient_id: int, diagnosis: Diagnosis) -> Diagnosis:
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO diagnoses (
                        patient_id, diagnosis, status, notes,
                        diagnosed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        patient_id,
                        diagnosis.diagnosis,
                        diagnosis.status,
                        diagnosis.notes,
                        diagnosis.diagnosed_at,
                        diagnosis.created_at,
                        diagnosis.updated_at,
                    ),
                )
                diagnosis.id = cursor.lastrowid
                diagnosis.patient_id = patient_id
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not record diagnosis: {exc}") from exc

        return diagnosis

    def update_diagnosis(self, diagnosis: Diagnosis) -> Diagnosis:
        if diagnosis.id is None:
            raise PersistenceError("Cannot update a diagnosis that has no identifier")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE diagnoses SET
                        diagnosis = ?, status = ?, notes = ?,
                        diagnosed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        diagnosis.diagnosis,
                        diagnosis.status,
                        diagnosis.notes,
                        diagnosis.diagnosed_at,
                        diagnosis.updated_at,
                        diagnosis.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise PersistenceError("Diagnosis no longer exists")
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not update diagnosis: {exc}") from exc

        return diagnosis

    # ---------- internals ----------

    @staticmethod
    def _attach_diagnoses(connection: sqlite3.Connection, patients: list[Patient]) -> None:
        """Load diagnoses for many patients in one query.

        Fetching per patient would be an N+1 query pattern, which shows up
        immediately once the patient list grows.
        """
        identifiers = [patient.id for patient in patients if patient.id is not None]
        if not identifiers:
            return

        placeholders = ", ".join("?" for _ in identifiers)
        rows = connection.execute(
            f"""
            SELECT id, patient_id, diagnosis, status, notes,
                   diagnosed_at, created_at, updated_at
            FROM diagnoses
            WHERE patient_id IN ({placeholders})
            ORDER BY id DESC
            """,
            identifiers,
        ).fetchall()

        grouped: dict[int, list[Diagnosis]] = defaultdict(list)
        for row in rows:
            grouped[row["patient_id"]].append(_to_diagnosis(row))

        for patient in patients:
            patient.diagnoses = grouped.get(patient.id or -1, [])


# ---------- mapping ----------


def _order_clause(sort_by: str, descending: bool) -> str:
    """Build the ORDER BY clause from a whitelisted key.

    An unrecognised key falls back to the default rather than being used, so a
    caller can never inject SQL through the sort parameter.

    ``p.id`` is appended as a final tie-break in the *same* direction, so patients
    that share a sort value — everyone registered in the same second, say — keep a
    stable, predictable order instead of one that depends on the query planner.
    """
    columns = SORT_COLUMNS.get(sort_by) or SORT_COLUMNS[DEFAULT_SORT]
    direction = "DESC" if descending else "ASC"
    parts = [f"{column} {direction}" for column in columns]
    parts.append(f"p.id {direction}")
    return ", ".join(parts)


def _like_pattern(text: str) -> str:
    """Build a LIKE pattern, escaping wildcards the user typed.

    Without this, searching for ``50%`` would match almost everything.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _to_patient(row: sqlite3.Row) -> Patient:
    return Patient(
        id=row["id"],
        patient_number=_text(row["patient_number"]),
        first_name=_text(row["first_name"]),
        last_name=_text(row["last_name"]),
        date_of_birth=_text(row["date_of_birth"]),
        age_years=_text(row["age_years"]),
        sex=_text(row["sex"]),
        phone=_text(row["phone"]),
        email=_text(row["email"]),
        address=_text(row["address"]),
        status=_text(row["status"]) or PatientStatus.ACTIVE.value,
        record_version=int(row["record_version"] or 1),
        created_at=_text(row["created_at"]),
        updated_at=_text(row["updated_at"]),
        created_by=_text(row["created_by"]),
        updated_by=_text(row["updated_by"]),
        deleted_at=_text(row["deleted_at"]),
        record=PatientRecord(
            blood_pressure=_text(row["r_blood_pressure"]),
            heart_rate=_text(row["r_heart_rate"]),
            weight=_text(row["r_weight"]),
            height=_text(row["r_height"]),
            medical_history=_text(row["r_medical_history"]),
            notes=_text(row["r_notes"]),
            created_at=_text(row["r_created_at"]),
            updated_at=_text(row["r_updated_at"]),
        ),
    )


def _to_diagnosis(row: sqlite3.Row) -> Diagnosis:
    return Diagnosis(
        id=row["id"],
        patient_id=row["patient_id"],
        diagnosis=_text(row["diagnosis"]),
        status=_text(row["status"]) or "active",
        notes=_text(row["notes"]),
        diagnosed_at=_text(row["diagnosed_at"]),
        created_at=_text(row["created_at"]),
        updated_at=_text(row["updated_at"]),
    )
