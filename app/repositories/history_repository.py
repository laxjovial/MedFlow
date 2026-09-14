"""The patient timeline repository interface.

Append-only by design: entries are written and read, never updated or removed.
A patient's history is a record of what happened, so editing it in place would
defeat its purpose.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.events import PatientEvent


class HistoryRepository(ABC):
    """Storage operations for per-patient timeline entries."""

    @abstractmethod
    def record(self, event: PatientEvent) -> PatientEvent:
        """Append an entry to a patient's timeline."""

    @abstractmethod
    def for_patient(self, patient_id: int, limit: int | None = None) -> list[PatientEvent]:
        """One patient's timeline, newest first."""

    @abstractmethod
    def recent(self, limit: int = 20) -> list[PatientEvent]:
        """The most recent entries across all patients."""
