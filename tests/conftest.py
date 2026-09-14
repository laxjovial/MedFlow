"""Shared fixtures: throwaway databases and a ready API client."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

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

    from app.config import Config
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
