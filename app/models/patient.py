"""Patient aggregate root."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any

from app.models._serial import serializable
from app.utils.dates import to_iso, from_iso


def format_patient_number(number: int) -> str:
    """Stable, sortable patient identifier: ``MF-000042``."""
    return f"MF-{number:06d}"


@serializable("created_at", "updated_at")
@dataclass
class Patient:
    """A patient's demographics plus their current clinical baseline.

    Versioned for the sync engine: ``version`` increments on every service
    write, and ``device_id``/``updated_by`` record who made the last change
    so conflicts can be reconciled per-field instead of whole-record.
    """

    patient_number: str
    name: str
    age: int | None = None
    sex: str | None = None
    date_of_birth: date | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    blood_pressure: str | None = None
    heart_rate: int | None = None
    weight: float | None = None
    medical_history: str | None = None
    diagnosis: str | None = None
    notes: str | None = None
    patient_id: int | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None
    device_id: str | None = None
    origin_unit_id: int | None = None
    deleted: bool = False
    change_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("patient_id", None)
        data["date_of_birth"] = self.date_of_birth.isoformat() if self.date_of_birth else None
        data["created_at"] = to_iso(self.created_at)
        data["updated_at"] = to_iso(self.updated_at)
        return data

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Patient":
        row = dict(row)
        dob = row.get("date_of_birth")
        row["date_of_birth"] = date.fromisoformat(dob) if isinstance(dob, str) else dob
        for key in ("created_at", "updated_at"):
            row[key] = from_iso(row.get(key))
        known = {f for f in cls.__dataclass_fields__ if f != "patient_id"}
        return cls(**{k: v for k, v in row.items() if k in known})

    @property
    def display_id(self) -> str:
        return self.patient_number

    def summary_line(self) -> str:
        bits = []
        if self.age is not None:
            bits.append(f"{self.age}y")
        if self.sex:
            bits.append(self.sex)
        if self.diagnosis:
            bits.append(self.diagnosis[:40])
        return " | ".join(bits) or "No clinical summary yet"


@serializable(None)
@dataclass
class PatientSummary:
    """Lightweight listing row for searches and directories."""

    patient_id: int
    patient_number: str
    name: str
    age: int | None
    diagnosis: str | None
    updated_at: str | None
    version: int = 1
