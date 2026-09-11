"""Domain models — plain dataclasses, the vocabulary of MedFlow.

Repositories produce these, services validate and mutate them, the UI
displays them. Nothing in this package imports tkinter, sqlite3, or the web
framework: models are the stable contract between every layer.
"""

from app.models.patient import Patient, PatientSummary, format_patient_number
from app.models.records import (
    Allergy,
    CLINICAL_MODELS,
    ClinicalNote,
    Diagnosis,
    LabResult,
    Medication,
    Vitals,
)
from app.models.audit import AuditEvent, PatientHistoryEvent
from app.models.org import Device, ShiftAssignment, User, Unit

__all__ = [
    "Patient",
    "PatientSummary",
    "format_patient_number",
    "Vitals",
    "Diagnosis",
    "Medication",
    "Allergy",
    "LabResult",
    "ClinicalNote",
    "CLINICAL_MODELS",
    "AuditEvent",
    "PatientHistoryEvent",
    "User",
    "Unit",
    "Device",
    "ShiftAssignment",
]
