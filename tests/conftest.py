"""Shared pytest fixtures.

Tests run against temporary directories and temporary databases - never the real
``medflow.db``. That is not only hygiene: several tests deliberately store the
legacy schema, drop tables and rewrite rows, all of which would be destructive
against a database holding real records.
"""

from __future__ import annotations

import pytest

from app.config.settings import ValidationSettings


@pytest.fixture
def validation_settings() -> ValidationSettings:
    """Default validation bounds."""
    return ValidationSettings()


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
