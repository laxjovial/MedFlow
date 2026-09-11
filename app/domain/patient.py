"""The patient aggregate.

Plain data: no database access, no Tk imports, no I/O. That is what allows the
same objects to travel through a SQLite repository today and an HTTP client
later without either side changing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.domain.diagnosis import Diagnosis
from app.domain.enums import DiagnosisStatus, PatientStatus


@dataclass
class PatientRecord:
    """The current clinical snapshot for a patient.

    Kept separate from demographics because it is edited at a different cadence
    and, later, may be visible to different roles.
    """

    blood_pressure: str = ""
    heart_rate: str = ""
    weight: str = ""
    height: str = ""
    medical_history: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def has_content(self) -> bool:
        """Whether any clinical value has been recorded."""
        return any(
            (
                self.blood_pressure,
                self.heart_rate,
                self.weight,
                self.height,
                self.medical_history,
                self.notes,
            )
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PatientRecord:
        return cls(
            blood_pressure=str(data.get("blood_pressure", "") or ""),
            heart_rate=str(data.get("heart_rate", "") or ""),
            weight=str(data.get("weight", "") or ""),
            height=str(data.get("height", "") or ""),
            medical_history=str(data.get("medical_history", "") or ""),
            notes=str(data.get("notes", "") or ""),
        )


@dataclass
class Patient:
    """A patient, with their current clinical record and diagnosis history."""

    patient_number: str = ""
    first_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""
    #: Legacy support. The pre-refactor application captured age as free text
    #: ("32", or "--" when unrecorded) and had no notion of a date of birth.
    #: Keeping both means migrated records stay honest instead of implying a
    #: birth date that was never recorded.
    age_years: str = ""
    sex: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    status: str = PatientStatus.ACTIVE.value
    record_version: int = 1
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""
    updated_by: str = ""
    deleted_at: str = ""
    id: int | None = None

    record: PatientRecord = field(default_factory=PatientRecord)
    diagnoses: list[Diagnosis] = field(default_factory=list)

    # ---------- derived ----------

    @property
    def full_name(self) -> str:
        parts = [part for part in (self.first_name, self.last_name) if part]
        if parts:
            return " ".join(parts)
        # A migrated record could have had a blank name; the number is the
        # only reliable way to refer to it.
        return self.patient_number or "Unnamed patient"

    @property
    def display_name(self) -> str:
        """A short label for lists and headers."""
        return self.full_name

    @property
    def is_deleted(self) -> bool:
        return bool(self.deleted_at)

    @property
    def is_active(self) -> bool:
        return self.status == PatientStatus.ACTIVE.value and not self.is_deleted

    @property
    def active_diagnoses(self) -> list[Diagnosis]:
        return [d for d in self.diagnoses if d.status == DiagnosisStatus.ACTIVE.value]

    # ---------- conversion ----------

    def to_dict(self) -> dict[str, Any]:
        """Flatten to a plain mapping, used by export and by the audit trail."""
        return {
            "patient_number": self.patient_number,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "date_of_birth": self.date_of_birth,
            "age_years": self.age_years,
            "sex": self.sex,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "status": self.status,
            "record_version": self.record_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "blood_pressure": self.record.blood_pressure,
            "heart_rate": self.record.heart_rate,
            "weight": self.record.weight,
            "height": self.record.height,
            "medical_history": self.record.medical_history,
            "notes": self.record.notes,
        }

    def to_form_data(self) -> dict[str, str]:
        """The editable values, shaped to match the patient form's field keys."""
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth,
            "age_years": self.age_years,
            "sex": self.sex,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "blood_pressure": self.record.blood_pressure,
            "heart_rate": self.record.heart_rate,
            "weight": self.record.weight,
            "height": self.record.height,
            "medical_history": self.record.medical_history,
            "notes": self.record.notes,
        }
