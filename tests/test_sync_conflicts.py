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



def test_conflict_is_persisted_and_duplicate_pull_is_idempotent(repos, admin_user, patient):
    from app.services.sync import SyncEngine
    local = repos["patients"].get(patient.patient_id)
    local.device_id = "device-A"
    local.version = 2
    local.updated_at = datetime(2026, 10, 28, 10, 0, 0)
    repos["patients"].update(local, ["device_id", "version", "updated_at"], bump_version=False)
    # Repository.update intentionally stamps wall-clock updated_at. Restore the
    # simulated prior revision timestamp directly so this test is deterministic.
    repos["patients"].db.connection().execute(
        "UPDATE patients SET updated_at = ? WHERE patient_id = ?",
        ("2026-10-28T10:00:00", patient.patient_id),
    )
    repos["patients"].db.connection().commit()
    local = repos["patients"].get(patient.patient_id)
    remote = Patient.from_row(local.to_row())
    remote.name = "Remote changed name"
    remote.version = 3
    remote.updated_at = datetime(2026, 10, 29, 10, 0, 0)
    remote.device_id = "server"

    engine = SyncEngine(repos, device_id="device-A")
    payload = {"patients": [remote.to_row()]}
    first = engine.apply_pull_payload(payload)
    second = engine.apply_pull_payload(payload)

    assert first.conflicts and second.conflicts
    pending = repos["sync_conflicts"].list_pending()
    assert len(pending) == 1
    detail = repos["sync_conflicts"].get_conflict(pending[0]["conflict_id"])
    assert detail["local_snapshot"]["name"] == local.name
    assert detail["remote_snapshot"]["name"] == "Remote changed name"
    assert detail["conflicting_fields"]


def _make_persisted_conflict(repos, patient, *, field="notes", remote_value="Remote notes"):
    local = repos["patients"].get(patient.patient_id)
    local.device_id = "device-A"
    local.version = 2
    repos["patients"].update(local, ["device_id", "version"], bump_version=False)
    repos["patients"].db.connection().execute(
        "UPDATE patients SET updated_at = ? WHERE patient_id = ?",
        ("2026-10-28T10:00:00", patient.patient_id),
    )
    repos["patients"].db.connection().commit()
    local = repos["patients"].get(patient.patient_id)
    remote = Patient.from_row(local.to_row())
    setattr(remote, field, remote_value)
    remote.version = 3
    remote.updated_at = datetime(2026, 10, 29, 10, 0, 0)
    remote.device_id = "server"
    SyncEngine(repos, device_id="device-A").apply_pull_payload(
        {"patients": [remote.to_row()]}
    )
    return repos["sync_conflicts"].list_pending()[0], local, remote


def test_conflict_resolution_is_one_way_and_audited(repos, admin_user, patient):
    conflict, local, remote = _make_persisted_conflict(repos, patient)
    repo = repos["sync_conflicts"]
    status = repo.resolve_patient_conflict_atomic(
        conflict["conflict_id"], actor="admin", choice="keep_local",
        patients=repos["patients"], audit=repos["audit"],
    )
    assert status == "resolved"
    assert repo.resolve_patient_conflict_atomic(
        conflict["conflict_id"], actor="admin", choice="keep_local",
        patients=repos["patients"], audit=repos["audit"],
    ) == "already_resolved"
    assert repo.get_conflict(conflict["conflict_id"])["status"] == "resolved"
    events = repos["audit"].history_for_entity("sync_conflict", str(conflict["conflict_id"]))
    assert len(events) == 1 and events[0].actor == "admin"


def test_apply_remote_and_audit_are_atomic_on_audit_failure(repos, admin_user, patient, monkeypatch):
    conflict, local, remote = _make_persisted_conflict(repos, patient, field="notes")
    conflict_id = conflict["conflict_id"]
    before = repos["patients"].get(patient.patient_id)
    def fail_audit(event):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(repos["audit"], "record", fail_audit)
    import pytest
    with pytest.raises(RuntimeError, match="injected audit failure"):
        repos["sync_conflicts"].resolve_patient_conflict_atomic(
            conflict_id, actor="admin", choice="apply_remote",
            patients=repos["patients"], audit=repos["audit"],
        )
    after = repos["patients"].get(patient.patient_id)
    assert after.notes == before.notes
    assert after.version == before.version
    assert repos["sync_conflicts"].get_conflict(conflict_id)["status"] == "pending"


def test_apply_remote_resolves_patient_and_conflict_together(repos, admin_user, patient):
    conflict, local, remote = _make_persisted_conflict(repos, patient, field="notes")
    result = repos["sync_conflicts"].resolve_patient_conflict_atomic(
        conflict["conflict_id"], actor="admin", choice="apply_remote",
        patients=repos["patients"], audit=repos["audit"],
    )
    assert result == "resolved"
    assert repos["patients"].get(patient.patient_id).notes == "Remote notes"
    assert repos["sync_conflicts"].get_conflict(conflict["conflict_id"])["status"] == "resolved"


def test_field_merge_only_accepts_stored_conflicting_values(repos, admin_user, patient):
    conflict, local, remote = _make_persisted_conflict(repos, patient, field="notes")
    repo = repos["sync_conflicts"]
    import pytest
    with pytest.raises(ValueError, match="must match stored local or remote"):
        repo.resolve_patient_conflict_atomic(
            conflict["conflict_id"], actor="admin", choice="field_merge",
            merged_fields={"notes": "invented third value"},
            patients=repos["patients"], audit=repos["audit"],
        )
    assert repo.get_conflict(conflict["conflict_id"])["status"] == "pending"
    result = repo.resolve_patient_conflict_atomic(
        conflict["conflict_id"], actor="admin", choice="field_merge",
        merged_fields={"notes": "Remote notes"},
        patients=repos["patients"], audit=repos["audit"],
    )
    assert result == "resolved"
    assert repos["patients"].get(patient.patient_id).notes == "Remote notes"


def test_field_merge_rejects_non_conflicting_fields(repos, admin_user, patient):
    conflict, local, remote = _make_persisted_conflict(repos, patient, field="notes")
    import pytest
    with pytest.raises(ValueError, match="recorded conflicting fields"):
        repos["sync_conflicts"].resolve_patient_conflict_atomic(
            conflict["conflict_id"], actor="admin", choice="field_merge",
            merged_fields={"name": local.name},
            patients=repos["patients"], audit=repos["audit"],
        )
