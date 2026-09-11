"""The per-patient timeline.

``patient_events`` answers "what is this patient's story?" — the question a
clinician asks when opening a record. Compare :mod:`app.domain.audit`, which
answers "who touched this record and when?".

Recorded as an append-only log: a patient's timeline never loses an entry, even
when the underlying value is later changed again.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import EventType

#: Display labels for each event type.
EVENT_LABELS: dict[str, str] = {
    EventType.CREATED.value: "Record created",
    EventType.UPDATED.value: "Record updated",
    EventType.DELETED.value: "Record deleted",
    EventType.RESTORED.value: "Record restored",
    EventType.MIGRATED.value: "Migrated from the previous version",
    EventType.DIAGNOSIS_ADDED.value: "Diagnosis added",
    EventType.DIAGNOSIS_UPDATED.value: "Diagnosis updated",
    EventType.DIAGNOSIS_RESOLVED.value: "Diagnosis resolved",
}


@dataclass
class PatientEvent:
    """One entry in a patient's timeline."""

    patient_id: int | None = None
    event_type: str = ""
    description: str = ""
    actor: str = ""
    created_at: str = ""
    id: int | None = None

    @property
    def label(self) -> str:
        """Human-readable name for the event type."""
        return EVENT_LABELS.get(self.event_type, str(self.event_type).replace("_", " ").title())
