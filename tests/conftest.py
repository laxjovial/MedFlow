"""Shared pytest fixtures — both architecture suites live here.

Two coexisting suites run against this conftest:

- the **platform suite** (``test_storage``, ``test_services``, ``test_server``,
  ``test_access``): throwaway databases, repositories, and an authenticated
  API client;
- the **modular suite** (``tests/unit``, ``tests/integration``, ``tests/ui``):
  the container-based desktop architecture with its own settings, clock,
  and migration fixtures.

Both use temporary directories and temporary databases — never the real
``medflow.db``. Several tests deliberately store legacy schemas, drop tables
and rewrite rows, which would be destructive against a database holding real
records.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# The desktop-UI tests import CustomTkinter, which needs a display and the
# ``tkinter`` system package. Headless environments (CI, sandboxes) skip them.
collect_ignore_glob = []
try:
    import tkinter  # noqa: F401
except ImportError:
    collect_ignore_glob.append("ui/*")

# ---------------------------------------------------------------- platform ---

from app.storage.engine import Database
from app.storage.repositories import build_repositories


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture()
def repos(db):
    return build_repositories(db)


@pytest.fixture()
def admin_user(repos):
    from app.services.security import SecurityService
    security = SecurityService(repos["users"])
    return security.create_user("admin", "Ada Admin", "password123",
                                "administrator")


@pytest.fixture()
def patient(repos, admin_user):
    from app.services.patients import PatientService
    service = PatientService(repos, actor="admin", device_id="test-01")
    return service.register({
        "name": "Test Patient",
        "age": 41,
        "phone": "+234 803 555 0101",
        "blood_pressure": "120/80",
        "heart_rate": 72,
        "weight": 70.5,
        "diagnosis": "Hypertension",
        "medical_history": "Smoker, occasional alcohol",
    })


@pytest.fixture()
def client(repos, admin_user):
    """TestClient with an authenticated default (``auth`` fixture not needed)."""
    from fastapi.testclient import TestClient

    from app.runtime_config import Config
    from app.server.app import create_app
    from app.server.tokens import load_or_create_secret

    tmp = Path(tempfile.mkdtemp())
    config = Config.load(tmp)
    app = create_app(config=config, db=None, repos=repos)
    app.state.token_secret = load_or_create_secret(tmp / ".token_secret")
    return TestClient(app)


@pytest.fixture()
def auth(client):
    """Login and return an Authorization header mapping."""
    response = client.post("/api/auth/login",
                           json={"username": "admin", "password": "password123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


# ----------------------------------------------------------- modular suite ---

from app.config.settings import AppSettings, ValidationSettings
from app.container import Container
from app.core.clock import FixedClock
from app.repositories.sqlite.connection import Database as ModularDatabase
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
def database(app_settings: AppSettings) -> ModularDatabase:
    """A migrated database in a temporary directory."""
    handle = ModularDatabase(app_settings.database_path)
    MigrationRunner(
        handle,
        patient_ids=app_settings.patient_ids,
    ).migrate()
    return handle


@pytest.fixture
def container(
    app_settings: AppSettings, fixed_clock: FixedClock, database: ModularDatabase
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
