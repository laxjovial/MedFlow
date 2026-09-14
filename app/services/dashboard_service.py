"""The dashboard service.

Assembles the view model the dashboard renders. The view itself performs no
counting: everything it displays arrives in one :class:`DashboardSummary`, which is
also the shape a future networked build could return from a single API call.
"""

from __future__ import annotations

from app.config.settings import AppSettings
from app.domain.summary import DashboardSummary
from app.services.history_service import HistoryService
from app.services.patient_service import PatientService

#: How many recent timeline entries the dashboard shows. Small on purpose — the
#: Activity view is where the full log lives.
DEFAULT_RECENT_LIMIT = 8

#: How many diagnoses the distribution chart shows.
DEFAULT_DIAGNOSIS_LIMIT = 5


class DashboardService:
    """Builds the dashboard summary."""

    def __init__(
        self,
        patients: PatientService,
        history: HistoryService,
        settings: AppSettings,
    ) -> None:
        self._patients = patients
        self._history = history
        self._settings = settings

    def summary(
        self,
        *,
        recent_limit: int = DEFAULT_RECENT_LIMIT,
        diagnosis_limit: int = DEFAULT_DIAGNOSIS_LIMIT,
    ) -> DashboardSummary:
        stats = self._patients.statistics()

        return DashboardSummary(
            total_patients=stats.total_patients,
            active_patients=stats.active_patients,
            archived_patients=stats.archived_patients,
            deleted_patients=stats.deleted_patients,
            created_today=stats.created_today,
            updated_today=stats.updated_today,
            active_diagnoses=stats.active_diagnoses,
            storage_mode=self._settings.storage.mode,
            # The dashboard shows where the data is, so a user can tell at a
            # glance whether they are looking at a local file or a shared store.
            database_location=str(self._settings.database_path),
            top_diagnoses=self._patients.diagnosis_distribution(limit=diagnosis_limit),
            recent_events=self._history.recent(limit=recent_limit),
        )
