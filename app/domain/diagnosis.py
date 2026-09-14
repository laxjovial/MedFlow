"""Diagnoses.

Modelled as one row per diagnosis rather than a single overwritable
``diagnosis`` column, because a patient accumulates diagnoses over time and the
history is clinically meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import DiagnosisStatus


@dataclass
class Diagnosis:
    """A single diagnosis recorded against a patient."""

    diagnosis: str = ""
    status: str = DiagnosisStatus.ACTIVE.value
    notes: str = ""
    diagnosed_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    patient_id: int | None = None
    id: int | None = None

    @property
    def is_active(self) -> bool:
        return self.status == DiagnosisStatus.ACTIVE.value

    @property
    def status_label(self) -> str:
        """Title-cased status, for display."""
        return str(self.status).replace("_", " ").capitalize()
