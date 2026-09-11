"""Clinical record models — the sections of a patient chart.

Each model maps 1:1 to a table and serializes through ``to_row``/``from_row``
so repositories stay dumb and the sync engine can diff any record type.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models._serial import serializable


@serializable("recorded_at")
@dataclass
class Vitals:
    """One vitals observation. Heart rate/blood pressure snapshots live here."""

    patient_id: int
    blood_pressure: str | None = None
    heart_rate: int | None = None
    temperature_c: float | None = None
    respiratory_rate: int | None = None
    oxygen_saturation: float | None = None
    recorded_at: datetime | None = None
    recorded_by: str | None = None
    vitals_id: int | None = None
    device_id: str | None = None


@serializable("diagnosed_at", "resolved_at")
@dataclass
class Diagnosis:
    patient_id: int
    code: str | None = None
    description: str = ""
    status: str = "active"          # active | resolved | chronic | suspected
    diagnosed_at: datetime | None = None
    resolved_at: datetime | None = None
    diagnosed_by: str | None = None
    diagnosis_id: int | None = None


@serializable("started_at", "ended_at")
@dataclass
class Medication:
    patient_id: int
    name: str
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    status: str = "active"          # active | completed | discontinued
    started_at: datetime | None = None
    ended_at: datetime | None = None
    prescribed_by: str | None = None
    medication_id: int | None = None


@serializable(None)
@dataclass
class Allergy:
    patient_id: int
    substance: str
    reaction: str | None = None
    severity: str = "unknown"       # mild | moderate | severe | unknown
    noted_by: str | None = None
    allergy_id: int | None = None


@serializable("collected_at")
@dataclass
class LabResult:
    patient_id: int
    panel: str                      # e.g. "CBC", "LFT"
    analyte: str                    # e.g. "Hemoglobin"
    value: str | None = None
    unit: str | None = None
    reference_range: str | None = None
    flag: str = "normal"            # normal | abnormal | critical
    collected_at: datetime | None = None
    resulted_by: str | None = None
    lab_id: int | None = None


@serializable("created_at")
@dataclass
class ClinicalNote:
    patient_id: int
    author: str | None = None
    unit_id: int | None = None
    category: str = "progress"      # progress | radiology | pharmacy | discharge
    body: str = ""
    created_at: datetime | None = None
    note_id: int | None = None


CLINICAL_MODELS = {
    "vitals": Vitals,
    "diagnoses": Diagnosis,
    "medications": Medication,
    "allergies": Allergy,
    "lab_results": LabResult,
    "notes": ClinicalNote,
}
