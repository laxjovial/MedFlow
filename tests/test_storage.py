"""Storage layer behavior: numbering, soft delete, deltas, chart CRUD."""

from __future__ import annotations

from app.models import Patient, Vitals
from app.models.patient import format_patient_number


def test_schema_migrates_from_zero(db):
    conn = db.connection()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 1
    tables = {r["name"] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"patients", "vitals", "appointments", "audit_events"} <= tables


def test_patient_numbers_monotonic_never_reused(repos, patient):
    assert patient.patient_number == format_patient_number(1)
    patient_repo = repos["patients"]

    second = patient_repo.insert(Patient(patient_number="", name="Second"))
    assert second.patient_number == format_patient_number(2)

    patient_repo.soft_delete(second.patient_id)
    third = patient_repo.insert(Patient(patient_number="", name="Third"))
    assert third.patient_number == format_patient_number(3)      # no ID reuse


def test_soft_delete_hides_and_restore_returns(repos, patient):
    repo = repos["patients"]
    assert repo.get(patient.patient_id) is not None

    assert repo.soft_delete(patient.patient_id) is True
    assert repo.get(patient.patient_id) is None
    assert repo.count() == 0
    assert repo.count(include_deleted=True) == 1

    deleted = repo.deleted_summaries()
    assert [s.patient_number for s in deleted] == [patient.patient_number]

    assert repo.restore(patient.patient_id) is True
    assert repo.get(patient.patient_id) is not None


def test_changes_since_returns_updated_rows(repos, patient):
    repo = repos["patients"]
    assert len(repo.changes_since(None)) == 1
    assert repo.changes_since("2999-01-01T00:00:00") == []


def test_search_matches_number_name_phone_diagnosis(repos, patient):
    repo = repos["patients"]
    numbers = [s.patient_number for s in repo.search(patient.patient_number)]
    names = [s.patient_number for s in repo.search("Test Pat")]
    phones = [s.patient_number for s in repo.search("555 0101")]
    diagnoses = [s.patient_number for s in repo.search("hyperten")]
    assert patient.patient_number in numbers
    assert patient.patient_number in names
    assert patient.patient_number in phones
    assert patient.patient_number in diagnoses


def test_clinical_record_crud(repos, patient):
    repo = repos["vitals"]
    record = repo.insert(Vitals(patient_id=patient.patient_id,
                                blood_pressure="118/76", heart_rate=70))
    fetched = repo.get(record.vitals_id)
    assert fetched.heart_rate == 70

    fetched.temperature_c = 36.9
    repo.update(fetched, ["temperature_c"])
    assert repo.get(record.vitals_id).temperature_c == 36.9

    assert repo.delete(record.vitals_id) is True
    assert repo.get(record.vitals_id) is None


def test_appointment_lifecycle(repos, patient):
    appts = repos["appointments"]
    appt = appts.insert({
        "patient_id": patient.patient_id,
        "scheduled_at": "2026-09-20T10:30",
        "status": "scheduled",
    })
    assert appts.upcoming()[0]["appointment_id"] == appt["appointment_id"]
    updated = appts.update_status(appt["appointment_id"], "completed")
    assert updated["status"] == "completed"

    import pytest
    from app.errors import ValidationError
    with pytest.raises(ValueError):
        appts.update_status(appt["appointment_id"], "bogus")


def test_dashboard_aggregate(repos, patient):
    stats = repos["stats"].dashboard()
    assert stats["total_patients"] == 1
    assert stats["deleted_patients"] == 0
    assert stats["database_bytes"] > 0
