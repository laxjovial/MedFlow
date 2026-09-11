"""The patient timeline service.

Where :mod:`app.services.audit_service` records *who used the application*, this
records *what happened to one patient* — the clinical story of a record, read by a
clinician rather than an auditor. The two are separate tables for that reason, and
the same action normally writes to both.
"""

from __future__ import annotations

from app.core.clock import Clock
from app.core.exceptions import ValidationError
from app.domain.enums import EventType
from app.domain.events import PatientEvent
from app.repositories.history_repository import HistoryRepository


class HistoryService:
    """Writes and reads per-patient timeline entries."""

    def __init__(self, repository: HistoryRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def record(
        self,
        patient_id: int | None,
        event_type: EventType | str,
        description: str = "",
        *,
        actor: str,
    ) -> PatientEvent:
        """Append a timeline entry for a patient.

        A patient without an identifier has not been persisted yet, so there is
        nothing to attach a timeline to — that is a programming error rather than
        something to store quietly.
        """
        if patient_id is None:
            raise ValidationError(
                "A timeline entry needs a saved patient to attach to"
            )

        return self._repository.record(
            PatientEvent(
                patient_id=patient_id,
                event_type=str(event_type),
                description=description,
                actor=actor,
                created_at=self._clock.timestamp(),
            )
        )

    def for_patient(self, patient_id: int, limit: int | None = None) -> list[PatientEvent]:
        return self._repository.for_patient(patient_id, limit=limit)

    def recent(self, limit: int = 20) -> list[PatientEvent]:
        return self._repository.recent(limit=limit)
