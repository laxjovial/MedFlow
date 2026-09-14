"""Composition root.

Everything is wired together here and nowhere else. Each object receives what it
needs as constructor arguments and builds none of its own dependencies, so a test
can assemble the same graph against a temporary database or with a frozen clock —
and swapping the SQLite repositories for networked ones is a change to this file
alone.

That property is the whole point of the refactor. ``Container.build`` is the one
place in the codebase that knows storage is SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import AppSettings
from app.core.clock import Clock, SystemClock
from app.repositories.sqlite.audit_repository import SqliteAuditRepository
from app.repositories.sqlite.connection import Database
from app.repositories.sqlite.history_repository import SqliteHistoryRepository
from app.repositories.sqlite.patient_repository import SqlitePatientRepository
from app.services.audit_service import AuditService
from app.services.backup_service import BackupService
from app.services.dashboard_service import DashboardService
from app.services.history_service import HistoryService
from app.services.patient_service import PatientService
from app.services.transfer_service import TransferService


@dataclass
class Container:
    """The application's object graph."""

    settings: AppSettings
    clock: Clock
    database: Database

    patients: PatientService
    history: HistoryService
    audit: AuditService
    dashboard: DashboardService
    backups: BackupService
    transfer: TransferService

    @classmethod
    def build(cls, settings: AppSettings, *, clock: Clock | None = None) -> "Container":
        """Assemble the graph for a set of settings.

        The clock is injectable so that tests can freeze time; in the running
        application it is the system clock.
        """
        active_clock: Clock = clock or SystemClock()
        database = Database(settings.database_path)

        patient_repository = SqlitePatientRepository(database, settings.patient_ids)
        history_repository = SqliteHistoryRepository(database)
        audit_repository = SqliteAuditRepository(database, settings.patient_ids)

        # Services first: they own validation, change tracking and audit emission,
        # so nothing below them has to remember to do it.
        audit = AuditService(audit_repository, active_clock)
        history = HistoryService(history_repository, active_clock)
        patients = PatientService(
            patient_repository,
            history,
            audit,
            settings.validation,
            active_clock,
        )

        return cls(
            settings=settings,
            clock=active_clock,
            database=database,
            patients=patients,
            history=history,
            audit=audit,
            dashboard=DashboardService(patients, history, settings),
            backups=BackupService(database, settings, audit, active_clock),
            transfer=TransferService(patients, history, audit, active_clock),
        )

    def close(self) -> None:
        """Release the database handle, if one is held."""
        self.database.close()
