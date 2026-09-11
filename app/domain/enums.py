"""Enumerations shared across the domain.

These are stored in the database as their string values, so the members are
vocabulary rather than magic strings — and adding a member never requires a
schema change.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """A string enum whose value is used for storage and comparison."""

    def __str__(self) -> str:
        return str(self.value)


class PatientStatus(StrEnum):
    """Lifecycle state of a patient record."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class DiagnosisStatus(StrEnum):
    """Where a diagnosis sits in the clinical process."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    RULED_OUT = "ruled_out"


class EventType(StrEnum):
    """Per-patient timeline entries.

    This is the patient's clinical story — what happened to *this* record. It is
    deliberately distinct from :class:`AuditAction`, which records who used the
    application.
    """

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"
    RESTORED = "RESTORED"
    MIGRATED = "MIGRATED"
    DIAGNOSIS_ADDED = "DIAGNOSIS_ADDED"
    DIAGNOSIS_UPDATED = "DIAGNOSIS_UPDATED"
    DIAGNOSIS_RESOLVED = "DIAGNOSIS_RESOLVED"


class AuditAction(StrEnum):
    """Application-level actions, recorded against whatever they affected."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    RESTORE = "RESTORE"
    MIGRATE = "MIGRATE"
    EXPORT = "EXPORT"
    IMPORT = "IMPORT"
    BACKUP = "BACKUP"
    RESTORE_BACKUP = "RESTORE_BACKUP"


class EntityType(StrEnum):
    """What an audit entry refers to."""

    PATIENT = "patient"
    PATIENT_RECORD = "patient_record"
    DIAGNOSIS = "diagnosis"
    DATABASE = "database"
    APPLICATION = "application"


#: Display labels for audit actions, used by the Activity view and its filter.
AUDIT_ACTION_LABELS: dict[str, str] = {
    AuditAction.CREATE.value: "Created a patient",
    AuditAction.UPDATE.value: "Changed a record",
    AuditAction.DELETE.value: "Deleted a patient",
    AuditAction.RESTORE.value: "Restored a patient",
    AuditAction.MIGRATE.value: "Migrated legacy data",
    AuditAction.EXPORT.value: "Exported data",
    AuditAction.IMPORT.value: "Imported data",
    AuditAction.BACKUP.value: "Took a backup",
    AuditAction.RESTORE_BACKUP.value: "Restored a backup",
}


#: Fields a patient edit may change, mapped to their human-readable labels. The
#: service layer diffs against these to describe *what* changed in the patient
#: timeline, rather than logging an uninformative "record updated".
TRACKED_PATIENT_FIELDS: dict[str, str] = {
    "first_name": "First name",
    "last_name": "Last name",
    "date_of_birth": "Date of birth",
    "age_years": "Age",
    "sex": "Sex",
    "phone": "Phone",
    "email": "Email",
    "address": "Address",
    "status": "Status",
    "blood_pressure": "Blood pressure",
    "heart_rate": "Heart rate",
    "weight": "Weight",
    "height": "Height",
    "medical_history": "Medical history",
    "notes": "Notes",
}

#: Sort orders offered for the patient list. These keys are the contract shared
#: between the UI and the repositories; the SQL that implements each one is
#: whitelisted inside the SQLite repository, never built from user input.
SORT_OPTIONS: dict[str, str] = {
    "patient_number": "Patient number",
    "name": "Name",
    "created_at": "Date created",
    "updated_at": "Last updated",
}

#: Applied when no sort is chosen. Most recently touched first is the most
#: useful default on a clinical worklist.
DEFAULT_SORT = "updated_at"
