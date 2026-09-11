"""Aggregate values for the dashboard.

Produced by the service layer so the view only has to render what it is given —
the dashboard does no counting of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.events import PatientEvent


@dataclass
class DiagnosisCount:
    """How many patients carry a given diagnosis. Drives the dashboard chart."""

    diagnosis: str
    count: int

    @property
    def label(self) -> str:
        return self.diagnosis


@dataclass
class RepositoryStatistics:
    """Raw counts gathered in one pass by the repository.

    Distinct from :class:`DashboardSummary`, which is the assembled view model.
    Keeping the raw counts separate means the dashboard service can decide how to
    present them, and a future networked repository can return the same shape
    from a single API call.
    """

    total_patients: int = 0
    active_patients: int = 0
    archived_patients: int = 0
    deleted_patients: int = 0
    created_today: int = 0
    updated_today: int = 0
    active_diagnoses: int = 0


@dataclass
class DashboardSummary:
    """Everything the dashboard needs, in one object."""

    total_patients: int = 0
    active_patients: int = 0
    archived_patients: int = 0
    deleted_patients: int = 0
    created_today: int = 0
    updated_today: int = 0
    active_diagnoses: int = 0

    #: Where the data actually lives, shown so the user can tell local from
    #: networked storage at a glance once network mode exists.
    storage_mode: str = "local"
    database_location: str = ""

    top_diagnoses: list[DiagnosisCount] = field(default_factory=list)
    recent_events: list[PatientEvent] = field(default_factory=list)

    @property
    def max_diagnosis_count(self) -> int:
        """Largest bar value, so a chart can scale relative to the data."""
        return max((entry.count for entry in self.top_diagnoses), default=0)

    @property
    def has_diagnoses(self) -> bool:
        return bool(self.top_diagnoses)
