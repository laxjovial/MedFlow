"""The patient repository interface.

**This is the seam that makes network mode possible.** Services depend on this
class, never on SQLite. Adding a networked MedFlow means writing one more
implementation of these methods — ``ApiPatientRepository`` — and changing which
object the application constructs at startup. No service, view or dialog changes.

    ui -> PatientService -> PatientRepository
                                ├── SqlitePatientRepository  (this release)
                                └── ApiPatientRepository     (FastAPI, later)

Implementations are expected to be storage-shaped, not rule-shaped: validation,
change tracking and audit logging belong to the service layer, so they cannot be
forgotten by a second implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.diagnosis import Diagnosis
from app.domain.enums import DEFAULT_SORT
from app.domain.patient import Patient
from app.domain.summary import DiagnosisCount, RepositoryStatistics


class PatientRepository(ABC):
    """Storage operations for patients, their record and their diagnoses."""

    # ---------- numbering ----------

    @abstractmethod
    def allocate_patient_number(self) -> str:
        """Reserve and return the next patient number.

        Allocation is monotonic and independent of the rows currently present,
        so deleting a patient never frees their number for reuse.
        """

    # ---------- writes ----------

    @abstractmethod
    def insert(self, patient: Patient) -> Patient:
        """Persist a new patient, returning it with its identifier populated.

        Diagnoses are written separately, through :meth:`add_diagnosis`.
        """

    @abstractmethod
    def save(self, patient: Patient) -> Patient:
        """Persist changes to an existing patient and their clinical record."""

    @abstractmethod
    def mark_deleted(self, patient_number: str, *, deleted_at: str, actor: str) -> bool:
        """Soft-delete a patient. Returns whether a row was affected."""

    @abstractmethod
    def restore(self, patient_number: str) -> bool:
        """Undo a soft delete. Returns whether a row was affected."""

    # ---------- reads ----------

    @abstractmethod
    def fetch(self, patient_number: str, *, include_deleted: bool = False) -> Patient | None:
        """Load one patient, by number, with their record and diagnoses."""

    @abstractmethod
    def search(
        self,
        query: str = "",
        *,
        sort_by: str = DEFAULT_SORT,
        descending: bool = True,
        include_deleted: bool = False,
        limit: int | None = None,
    ) -> list[Patient]:
        """Find patients by number, name or diagnosis.

        An unknown ``sort_by`` must fall back to the default rather than being
        interpolated into a query.
        """

    @abstractmethod
    def list_all(self, *, include_deleted: bool = False) -> list[Patient]:
        """Every patient, for export."""

    @abstractmethod
    def count(self, *, include_deleted: bool = False) -> int:
        """How many patients exist."""

    @abstractmethod
    def statistics(self, *, today: str) -> RepositoryStatistics:
        """Counts for the dashboard, gathered in one pass.

        ``today`` is a ``YYYY-MM-DD`` date supplied by the caller rather than
        read from the system clock, so "created today" is both testable and
        unaffected by when the query happens to run.
        """

    @abstractmethod
    def diagnosis_distribution(self, limit: int = 5) -> list[DiagnosisCount]:
        """Most frequent diagnoses across all patients."""

    # ---------- diagnoses ----------

    @abstractmethod
    def list_diagnoses(self, patient_id: int) -> list[Diagnosis]:
        """Every diagnosis recorded against a patient, newest first."""

    @abstractmethod
    def add_diagnosis(self, patient_id: int, diagnosis: Diagnosis) -> Diagnosis:
        """Record a new diagnosis."""

    @abstractmethod
    def update_diagnosis(self, diagnosis: Diagnosis) -> Diagnosis:
        """Change an existing diagnosis — its text, status or notes."""
