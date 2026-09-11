"""Shared pytest fixtures.

Tests run against temporary directories and temporary databases — never the real
``medflow.db``. That is not only hygiene: several tests deliberately store the
legacy schema, drop tables and rewrite rows, all of which would be destructive
against a database holding real records.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import AppSettings, ValidationSettings
from app.container import Container
from app.core.clock import FixedClock
from app.repositories.sqlite.connection import Database
from app.repositories.sqlite.migrations import MigrationRunner
from app.services.patient_service import PatientService

#: A fixed moment used by tests that assert on stored timestamps.
TEST_MOMENT = "2026-03-04 10:30:00"

#: The date part of :data:`TEST_MOMENT`, for "created today" style assertions.
TEST_DATE = "2026-03-04"


@pytest.fixture
def validation_settings() -> ValidationSettings:
    """Default validation bounds."""
    return ValidationSettings()


@pytest.fixture
def fixed_clock() -> FixedClock:
    """A clock pinned to a known moment."""
    from datetime import datetime, timezone

    return FixedClock(datetime(2026, 3, 4, 10, 30, 0, tzinfo=timezone.utc))


@pytest.fixture
def app_settings(tmp_path: Path) -> AppSettings:
    """Settings rooted in a temporary directory, so nothing touches the repository."""
    return AppSettings.default(base_directory=tmp_path)


@pytest.fixture
def sample_patient_data() -> dict[str, str]:
    """A valid patient payload, as a form would submit it."""
    return {
        "first_name": "Victor",
        "last_name": "Kamau",
        "age_years": "29",
        "sex": "Male",
        "phone": "+254 700 123456",
        "email": "victor@example.com",
        "address": "12 Riverside Drive",
        "blood_pressure": "118/75",
        "heart_rate": "90",
        "weight": "72 kg",
        "height": "178 cm",
        "medical_history": "Appendectomy scheduled.",
        "notes": "Pre-op fasting from midnight.",
        "diagnosis": "Acute Appendicitis",
    }


@pytest.fixture
def database(app_settings: AppSettings) -> Database:
    """A migrated database in a temporary directory."""
    handle = Database(app_settings.database_path)
    MigrationRunner(
        handle,
        patient_ids=app_settings.patient_ids,
    ).migrate()
    return handle


@pytest.fixture
def container(
    app_settings: AppSettings, fixed_clock: FixedClock, database: Database
) -> Container:
    """A fully wired container, sharing the migrated temporary database.

    Built through ``Container.build`` rather than by hand so the tests exercise the
    same wiring the application uses — a service that is only constructed in tests
    is a service that is not really tested.
    """
    built = Container.build(app_settings, clock=fixed_clock)
    try:
        yield built
    finally:
        built.close()


@pytest.fixture
def patients(container: Container) -> PatientService:
    """The patient service from the wired container."""
    return container.patients
