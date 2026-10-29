"""Regression tests for sync conflict preservation."""

from datetime import datetime

from app.models import Patient
from app.services.sync import SyncEngine


class _FakeDatabase:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class _FakePatientRepository:
    def __init__(self, patient):
        self.patient = patient
        self.db = _FakeDatabase()
        self.upserted = []

    def get_by_number(self, patient_number):
        if self.patient.patient_number == patient_number:
            return self.patient
        return None

    def upsert_from_remote(self, patient):
        self.upserted.append(patient)
        self.patient = patient


def test_sync_conflict_preserves_local_clinical_values():
    local = Patient(
        patient_number="MF-000123",
        name="Local patient name",
        diagnosis="Local diagnosis",
        notes="Local note",
        version=2,
        updated_at=datetime(2026, 10, 28, 10, 0, 0),
        device_id="device-A",
    )
    remote = Patient(
        patient_number="MF-000123",
        name="Remote patient name",
        diagnosis="Remote diagnosis",
        notes="Remote note",
        version=3,
        updated_at=datetime(2026, 10, 29, 10, 0, 0),
        device_id="server",
    )
    patients = _FakePatientRepository(local)
    engine = SyncEngine({"patients": patients}, device_id="device-A")

    report = engine.apply_pull_payload({"patients": [remote.to_row()]})

    assert {conflict.field for conflict in report.conflicts} >= {
        "name", "diagnosis", "notes"
    }
    assert report.pulled == 0
    assert patients.patient.name == "Local patient name"
    assert patients.patient.diagnosis == "Local diagnosis"
    assert patients.patient.notes == "Local note"
    assert patients.patient.updated_at == local.updated_at
    assert patients.upserted == []
    assert patients.db.commits == 1


def test_sync_applies_remote_update_when_no_clinical_fields_conflict():
    local = Patient(
        patient_number="MF-000124",
        name="Same patient",
        diagnosis="Same diagnosis",
        version=2,
        updated_at=datetime(2026, 10, 28, 10, 0, 0),
        device_id="device-A",
    )
    remote = Patient(
        patient_number="MF-000124",
        name="Same patient",
        diagnosis="Same diagnosis",
        version=3,
        updated_at=datetime(2026, 10, 29, 10, 0, 0),
        device_id="server",
    )
    patients = _FakePatientRepository(local)
    engine = SyncEngine({"patients": patients}, device_id="device-A")

    report = engine.apply_pull_payload({"patients": [remote.to_row()]})

    assert report.conflicts == []
    assert report.pulled == 1
    assert patients.patient.version == 3
    assert len(patients.upserted) == 1
