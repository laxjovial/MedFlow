"""Repositories: the only code that talks SQL.

Each repository returns domain models. Services above this layer never see
SQL; the sync engine below it can diff anything a repository can produce.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Sequence

from app.models import (
    Allergy,
    AuditEvent,
    ClinicalNote,
    CLINICAL_MODELS,
    Diagnosis,
    Device,
    LabResult,
    Medication,
    Patient,
    PatientHistoryEvent,
    PatientSummary,
    ShiftAssignment,
    Unit,
    User,
    Vitals,
    format_patient_number,
)
from app.models._serial import serializable  # noqa: F401  (re-exported convenience)
from app.utils.dates import from_iso, to_iso, utcnow

# Clinical record tables share identical CRUD shape; one generic class
# serves them all (keyed like CLINICAL_MODELS: table name -> model).
APPOINTMENT_STATUSES = ("scheduled", "checked_in", "in_progress", "completed",
                        "cancelled", "no_show")


class _Repository:
    """Base: owns the Database and standard row conversion."""

    table: str = ""

    def __init__(self, db):
        self.db = db

    def _exec(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        return self.db.execute(sql, params)

    def _query_all(self, sql: str, params: Sequence = ()) -> list[dict]:
        return [dict(r) for r in self._exec(sql, params).fetchall()]

    def _query_one(self, sql: str, params: Sequence = ()) -> dict | None:
        row = self._exec(sql, params).fetchone()
        return dict(row) if row else None


class PatientRepository(_Repository):
    table = "patients"

    # ------------------------------------------------------------------ #
    # queries

    def get(self, patient_id: int, include_deleted: bool = False) -> Patient | None:
        row = self._query_one(
            f"SELECT * FROM {self.table} WHERE patient_id = ?", (patient_id,)
        )
        if not row:
            return None
        if row.get("deleted") and not include_deleted:
            return None
        return Patient.from_row(row)

    def get_by_number(self, patient_number: str) -> Patient | None:
        row = self._query_one(
            f"SELECT * FROM {self.table} WHERE patient_number = ?",
            (patient_number,),
        )
        return Patient.from_row(row) if row else None

    def search(self, query: str = "", limit: int = 200,
               include_deleted: bool = False) -> list[PatientSummary]:
        query = (query or "").strip()
        sql = f"SELECT patient_id, patient_number, name, age, diagnosis, updated_at, version FROM {self.table}"
        conditions: list[str] = []
        params: list[Any] = []
        if not include_deleted:
            conditions.append("deleted = 0")
        if query:
            conditions.append(
                "(patient_number LIKE ? OR name LIKE ? OR phone LIKE ? OR COALESCE(diagnosis, '') LIKE ?)"
            )
            like = f"%{query}%"
            params += [like, like, like, like]
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY name COLLATE NOCASE LIMIT ?"
        params.append(limit)
        return [PatientSummary.from_row(r) for r in self._query_all(sql, params)]

    def count(self, include_deleted: bool = False) -> int:
        sql = f"SELECT COUNT(*) AS c FROM {self.table}"
        if not include_deleted:
            sql += " WHERE deleted = 0"
        return self._query_one(sql)["c"]

    def changes_since(self, since_iso: str | None) -> list[Patient]:
        """Rows changed after a timestamp, for delta sync."""
        if since_iso:
            rows = self._query_all(
                f"SELECT * FROM {self.table} WHERE updated_at > ?", (since_iso,)
            )
        else:
            rows = self._query_all(f"SELECT * FROM {self.table}")
        return [Patient.from_row(r) for r in rows]

    # ------------------------------------------------------------------ #
    # writes

    def next_patient_number(self) -> str:
        row = self._query_one(
            "SELECT MAX(CAST(SUBSTR(patient_number, 4) AS INTEGER)) AS m "
            "FROM patients WHERE patient_number LIKE 'MF-%'"
        )
        return format_patient_number((row["m"] or 0) + 1)

    def insert(self, patient: Patient) -> Patient:
        row = patient.to_row()
        row.pop("patient_id", None)
        if not patient.patient_number:
            row["patient_number"] = self.next_patient_number()
            patient.patient_number = row["patient_number"]
        row["created_at"] = row.get("created_at") or to_iso(utcnow())
        row["updated_at"] = row["created_at"]
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self._exec(f"INSERT INTO {self.table} ({cols}) VALUES ({marks})",
                         tuple(row.values()))
        patient.patient_id = cur.lastrowid
        patient.created_at = from_iso(row["created_at"])
        patient.updated_at = patient.created_at
        return patient

    def update(self, patient: Patient, fields: Iterable[str],
               bump_version: bool = True) -> Patient:
        """Persist the named fields of a patient; bumps version + updated_at."""
        row = patient.to_row()
        updates = [f for f in fields if f in row]
        if not updates:
            return patient
        assignments = ", ".join(f"{f} = ?" for f in updates)
        params = [row[f] for f in updates]
        if bump_version:
            patient.version = int(patient.version or 1) + 1
            assignments += ", version = ?"
            params.append(patient.version)
        patient.updated_at = utcnow()
        assignments += ", updated_at = ?"
        params.append(to_iso(patient.updated_at))
        params.append(patient.patient_id)
        self._exec(
            f"UPDATE {self.table} SET {assignments} WHERE patient_id = ?",
            tuple(params),
        )
        return patient

    def soft_delete(self, patient_id: int, actor: str | None = None,
                    device_id: str | None = None) -> bool:
        now = to_iso(utcnow())
        cur = self._exec(
            "UPDATE patients SET deleted = 1, updated_at = ?, updated_by = ?, "
            "device_id = ?, version = version + 1 WHERE patient_id = ? AND deleted = 0",
            (now, actor, device_id, patient_id),
        )
        return cur.rowcount > 0

    def restore(self, patient_id: int) -> bool:
        cur = self._exec(
            "UPDATE patients SET deleted = 0, version = version + 1, "
            "updated_at = ? WHERE patient_id = ?",
            (to_iso(utcnow()), patient_id),
        )
        return cur.rowcount > 0

    def upsert_from_remote(self, patient: Patient) -> Patient:
        """Insert or update from a sync payload without bumping version."""
        row = patient.to_row()
        existing = self.get_by_number(patient.patient_number)
        if existing:
            row["patient_id"] = existing.patient_id
            updates = [k for k in row if k != "patient_id"]
            assignments = ", ".join(f"{k} = ?" for k in updates)
            params = [row[k] for k in updates] + [existing.patient_id]
            self._exec(
                f"UPDATE patients SET {assignments} WHERE patient_id = ?",
                tuple(params),
            )
            patient.patient_id = existing.patient_id
        else:
            row.pop("patient_id", None)
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            cur = self._exec(
                f"INSERT INTO patients ({cols}) VALUES ({marks})",
                tuple(row.values()),
            )
            patient.patient_id = cur.lastrowid
        return patient


class ClinicalRecordRepository(_Repository):
    """Generic CRUD for the six chart tables sharing one shape."""

    def __init__(self, db, table: str, model: type):
        super().__init__(db)
        self.table = table
        self.model = model

    def list_for_patient(self, patient_id: int) -> list:
        rows = self._query_all(
            f"SELECT * FROM {self.table} WHERE patient_id = ? "
            f"ORDER BY 1 DESC",
            (patient_id,),
        )
        return [self.model.from_row(r) for r in rows]

    def get(self, record_id: int):
        row = self._query_one(
            f"SELECT * FROM {self.table} WHERE {self._pk()} = ?", (record_id,)
        )
        return self.model.from_row(row) if row else None

    def insert(self, record) -> Any:
        row = record.to_row()
        row.pop(self._pk(), None)
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self._exec(
            f"INSERT INTO {self.table} ({cols}) VALUES ({marks})",
            tuple(row.values()),
        )
        setattr(record, self._pk(), cur.lastrowid)
        return record

    def update(self, record, fields: Iterable[str]) -> Any:
        row = record.to_row()
        updates = [f for f in fields if f in row]
        if not updates:
            return record
        assignments = ", ".join(f"{f} = ?" for f in updates)
        params = [row[f] for f in updates] + [getattr(record, self._pk())]
        self._exec(
            f"UPDATE {self.table} SET {assignments} WHERE {self._pk()} = ?",
            tuple(params),
        )
        return record

    def delete(self, record_id: int) -> bool:
        cur = self._exec(
            f"DELETE FROM {self.table} WHERE {self._pk()} = ?", (record_id,)
        )
        return cur.rowcount > 0

    def delete_for_patient(self, patient_id: int) -> int:
        cur = self._exec(
            f"DELETE FROM {self.table} WHERE patient_id = ?", (patient_id,)
        )
        return cur.rowcount

    def _pk(self) -> str:
        return {
            "vitals": "vitals_id",
            "diagnoses": "diagnosis_id",
            "medications": "medication_id",
            "allergies": "allergy_id",
            "lab_results": "lab_id",
            "notes": "note_id",
        }[self.table]


class AppointmentRepository(_Repository):
    table = "appointments"

    def get(self, appointment_id: int) -> dict | None:
        return self._query_one(
            f"SELECT * FROM {self.table} WHERE appointment_id = ?",
            (appointment_id,),
        )

    def upcoming(self, limit: int = 50) -> list[dict]:
        now = to_iso(utcnow())
        return self._query_all(
            f"SELECT a.*, p.name AS patient_name, p.patient_number "
            f"FROM {self.table} a JOIN patients p USING (patient_id) "
            f"WHERE a.scheduled_at >= ? AND a.status IN ('scheduled', 'checked_in') "
            f"ORDER BY a.scheduled_at LIMIT ?",
            (now, limit),
        )

    def on_date(self, day_iso: str) -> list[dict]:
        return self._query_all(
            f"SELECT a.*, p.name AS patient_name, p.patient_number "
            f"FROM {self.table} a JOIN patients p USING (patient_id) "
            f"WHERE SUBSTR(a.scheduled_at, 1, 10) = ? "
            f"ORDER BY a.scheduled_at",
            (day_iso,),
        )

    def for_patient(self, patient_id: int) -> list[dict]:
        return self._query_all(
            f"SELECT * FROM {self.table} WHERE patient_id = ? "
            f"ORDER BY scheduled_at DESC",
            (patient_id,),
        )

    def insert(self, data: dict) -> dict:
        data.setdefault("created_at", to_iso(utcnow()))
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        cur = self._exec(
            f"INSERT INTO {self.table} ({cols}) VALUES ({marks})",
            tuple(data.values()),
        )
        return self.get(cur.lastrowid)

    def update_status(self, appointment_id: int, status: str) -> dict | None:
        if status not in APPOINTMENT_STATUSES:
            raise ValueError(f"Unknown appointment status: {status}")
        self._exec(
            f"UPDATE {self.table} SET status = ? WHERE appointment_id = ?",
            (status, appointment_id),
        )
        return self.get(appointment_id)


class UserRepository(_Repository):
    table = "users"

    def get(self, user_id: int) -> User | None:
        row = self._query_one(f"SELECT * FROM {self.table} WHERE user_id = ?",
                              (user_id,))
        return User.from_row(row) if row else None

    def get_by_username(self, username: str) -> User | None:
        row = self._query_one(
            f"SELECT * FROM {self.table} WHERE username = ? COLLATE NOCASE",
            (username,),
        )
        return User.from_row(row) if row else None

    def list(self, active_only: bool = True) -> list[User]:
        sql = f"SELECT * FROM {self.table}"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY display_name COLLATE NOCASE"
        return [User.from_row(r) for r in self._query_all(sql)]

    def insert(self, user: User) -> User:
        row = user.to_row()
        row.pop("user_id", None)
        row.setdefault("created_at", to_iso(utcnow()))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self._exec(f"INSERT INTO {self.table} ({cols}) VALUES ({marks})",
                         tuple(row.values()))
        user.user_id = cur.lastrowid
        return user

    def update(self, user: User, fields: Iterable[str]) -> User:
        row = user.to_row()
        updates = [f for f in fields if f in row]
        if not updates:
            return user
        assignments = ", ".join(f"{f} = ?" for f in updates)
        params = [row[f] for f in updates] + [user.user_id]
        self._exec(
            f"UPDATE {self.table} SET {assignments} WHERE user_id = ?",
            tuple(params),
        )
        return user


class UnitRepository(_Repository):
    table = "units"

    def get(self, unit_id: int) -> Unit | None:
        row = self._query_one(f"SELECT * FROM {self.table} WHERE unit_id = ?",
                              (unit_id,))
        return Unit.from_row(row) if row else None

    def list(self) -> list[Unit]:
        rows = self._query_all(
            f"SELECT * FROM {self.table} ORDER BY kind, name COLLATE NOCASE"
        )
        return [Unit.from_row(r) for r in rows]

    def insert(self, unit: Unit) -> Unit:
        row = unit.to_row()
        row.pop("unit_id", None)
        row.setdefault("created_at", to_iso(utcnow()))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self._exec(f"INSERT INTO {self.table} ({cols}) VALUES ({marks})",
                         tuple(row.values()))
        unit.unit_id = cur.lastrowid
        return unit

    def ensure_root(self, name: str = "Main Facility") -> Unit:
        """Guarantee an organization root exists; returns it."""
        row = self._query_one(
            f"SELECT * FROM {self.table} WHERE parent_id IS NULL LIMIT 1"
        )
        if row:
            return Unit.from_row(row)
        return self.insert(Unit(name=name, kind="organization"))


class DeviceRepository(_Repository):
    table = "devices"

    def get(self, device_id: str) -> Device | None:
        row = self._query_one(
            f"SELECT * FROM {self.table} WHERE device_id = ?", (device_id,)
        )
        return Device.from_row(row) if row else None

    def list(self) -> list[Device]:
        rows = self._query_all(
            f"SELECT * FROM {self.table} ORDER BY registered_at DESC"
        )
        return [Device.from_row(r) for r in rows]

    def register(self, device: Device) -> Device:
        row = device.to_row()
        existing = self.get(device.device_id)
        if existing:
            updates = [k for k in row if k != "device_id"]
            assignments = ", ".join(f"{k} = ?" for k in updates)
            params = [row[k] for k in updates] + [device.device_id]
            self._exec(
                f"UPDATE {self.table} SET {assignments} WHERE device_id = ?",
                tuple(params),
            )
        else:
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            self._exec(
                f"INSERT INTO {self.table} ({cols}) VALUES ({marks})",
                tuple(row.values()),
            )
        return device


class AuditRepository(_Repository):
    """Audit trail (operational) and patient history (clinical timeline)."""

    def record(self, event: AuditEvent) -> AuditEvent:
        row = event.to_row()
        row.pop("event_id", None)
        row.setdefault("created_at", to_iso(utcnow()))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self._exec(
            f"INSERT INTO audit_events ({cols}) VALUES ({marks})",
            tuple(row.values()),
        )
        event.event_id = cur.lastrowid
        event.created_at = from_iso(row["created_at"])
        return event

    def recent(self, limit: int = 100) -> list[AuditEvent]:
        rows = self._query_all(
            "SELECT * FROM audit_events ORDER BY event_id DESC LIMIT ?",
            (limit,),
        )
        return [AuditEvent.from_row(r) for r in rows]

    def add_history(self, event: PatientHistoryEvent) -> PatientHistoryEvent:
        row = event.to_row()
        row.pop("history_id", None)
        row.setdefault("created_at", to_iso(utcnow()))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self._exec(
            f"INSERT INTO patient_history ({cols}) VALUES ({marks})",
            tuple(row.values()),
        )
        event.history_id = cur.lastrowid
        event.created_at = from_iso(row["created_at"])
        return event

    def history_for_patient(self, patient_id: int, limit: int = 200) -> list[PatientHistoryEvent]:
        rows = self._query_all(
            "SELECT * FROM patient_history WHERE patient_id = ? "
            "ORDER BY history_id DESC LIMIT ?",
            (patient_id, limit),
        )
        return [PatientHistoryEvent.from_row(r) for r in rows]


class StatsRepository(_Repository):
    """Dashboard aggregates in a single round trip."""

    def dashboard(self) -> dict:
        q = self._query_one
        total = q("SELECT COUNT(*) AS c FROM patients WHERE deleted = 0")["c"]
        week = self._exec(
            "SELECT COUNT(*) AS c FROM patients WHERE created_at >= ? AND deleted = 0",
            (to_iso(utcnow().replace(microsecond=0)),),
        ).fetchone()["c"]
        active_dx = q(
            "SELECT COUNT(*) AS c FROM diagnoses WHERE status = 'active'"
        )["c"]
        appts_today = q(
            "SELECT COUNT(*) AS c FROM appointments WHERE "
            "SUBSTR(scheduled_at, 1, 10) = SUBSTR(?, 1, 10) AND status = 'scheduled'",
            (to_iso(utcnow()),),
        )["c"]
        critical_labs = q(
            "SELECT COUNT(*) AS c FROM lab_results WHERE flag = 'critical'"
        )["c"]
        deleted = q("SELECT COUNT(*) AS c FROM patients WHERE deleted = 1")["c"]
        db_size = 0
        try:
            db_size = self.db.connection().execute("PRAGMA page_count").fetchone()[0] \
                * self.db.connection().execute("PRAGMA page_size").fetchone()[0]
        except sqlite3.Error:
            pass
        return {
            "total_patients": total,
            "new_this_week_placeholder": week,  # refined by service layer
            "active_diagnoses": active_dx,
            "appointments_today": appts_today,
            "critical_labs": critical_labs,
            "deleted_patients": deleted,
            "database_bytes": db_size,
        }


def build_repositories(db) -> dict[str, Any]:
    """Construct every repository over one Database, keyed for services."""
    repos: dict[str, Any] = {
        "patients": PatientRepository(db),
        "appointments": AppointmentRepository(db),
        "users": UserRepository(db),
        "units": UnitRepository(db),
        "devices": DeviceRepository(db),
        "audit": AuditRepository(db),
        "stats": StatsRepository(db),
    }
    for table, model in CLINICAL_MODELS.items():
        repos[table] = ClinicalRecordRepository(db, table, model)
    return repos
