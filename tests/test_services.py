"""Service-layer behavior: validation, records, security, exchange."""

from __future__ import annotations

import pytest

from app.errors import AuthenticationError, ValidationError
from app.validation import PatientValidator


# --------------------------------------------------------------------------- #
# validation


def test_validator_rejects_bad_age_and_phone():
    validator = PatientValidator()
    with pytest.raises(ValidationError) as exc:
        validator.validate({"name": "A", "age": 500, "phone": "123"})
    assert "age" in exc.value.errors and "phone" in exc.value.errors


def test_validator_cross_checks_age_against_dob():
    validator = PatientValidator()
    with pytest.raises(ValidationError):
        validator.validate({"name": "A", "age": 20, "date_of_birth": "1990-01-01"})
    clean = validator.validate({"name": "A", "age": 35,
                                "date_of_birth": "1991-06-15"})
    assert clean["age"] == 35


def test_validator_accepts_minimal_patient():
    clean = PatientValidator().validate({"name": "Only Name"})
    assert clean["name"] == "Only Name"
    assert clean["age"] is None


# --------------------------------------------------------------------------- #
# patient service


def test_register_writes_timeline_and_audit(repos, admin_user):
    from app.services.patients import PatientService
    service = PatientService(repos, actor="admin", device_id="t01")
    patient = service.register({"name": "Timeline Patient"})
    timeline = repos["audit"].history_for_patient(patient.patient_id)
    assert any("Registered" in e.description for e in timeline)
    actions = [e.action for e in repos["audit"].recent(limit=10)]
    assert "created" in actions


def test_update_rejects_invalid_payload(repos, admin_user, patient):
    from app.services.patients import PatientService
    service = PatientService(repos, actor="admin")
    with pytest.raises(ValidationError):
        service.update(patient.patient_id, {"age": 999})


def test_delete_then_recycle_bin_then_restore(repos, admin_user, patient):
    from app.services.patients import PatientService
    service = PatientService(repos, actor="admin")
    service.delete(patient.patient_id)
    deleted = service.deleted_patients()
    assert [s.patient_id for s in deleted] == [patient.patient_id]
    assert service.restore(patient.patient_id) is True
    assert service.deleted_patients() == []


def test_chart_assembles_every_section(repos, admin_user, patient):
    from app.services.patients import PatientService
    from app.services.records import RecordsService
    patients = PatientService(repos, actor="admin")
    records = RecordsService(repos, actor="admin")
    records.add_vitals(patient.patient_id, {"heart_rate": "80"})
    records.add_diagnosis(patient.patient_id, "Malaria")
    chart = patients.chart(patient.patient_id)
    assert chart["patient"].name == "Test Patient"
    assert len(chart["vitals"]) == 1
    assert len(chart["diagnoses"]) == 1
    assert chart["timeline"]


# --------------------------------------------------------------------------- #
# records service


def test_vitals_range_guard(repos, admin_user, patient):
    from app.services.records import RecordsService
    service = RecordsService(repos, actor="admin")
    with pytest.raises(ValidationError) as exc:
        service.add_vitals(patient.patient_id, {"heart_rate": "9999"})
    assert "heart_rate" in exc.value.errors


def test_medication_discontinue_flow(repos, admin_user, patient):
    from app.services.records import RecordsService
    service = RecordsService(repos, actor="admin")
    med = service.add_medication(patient.patient_id, "Paracetamol", dose="500mg")
    assert med.status == "active"
    done = service.discontinue_medication(med.medication_id)
    assert done.status == "discontinued"
    assert done.ended_at is not None


def test_critical_lab_raises_audit(repos, admin_user, patient):
    from app.services.records import RecordsService
    service = RecordsService(repos, actor="admin")
    service.add_lab_result(patient.patient_id, "CMP", "Potassium",
                           value="6.8", unit="mmol/L", flag="critical")
    actions = [e.action for e in repos["audit"].recent(limit=20)]
    assert "critical_lab" in actions


# --------------------------------------------------------------------------- #
# security


def test_password_hashing_and_login(repos, admin_user):
    from app.services.security import SecurityService
    security = SecurityService(repos["users"])
    assert security.authenticate("admin", "password123").user_id == 1
    with pytest.raises(AuthenticationError):
        security.authenticate("admin", "wrong")
    with pytest.raises(AuthenticationError):
        security.authenticate("ghost", "password123")


def test_permissions_differ_by_role():
    from app.services.security import permissions_for
    from app.models.org import ROLE_ADMIN, ROLE_VIEWER, ROLE_PHYSICIAN
    assert "users.manage" in permissions_for(ROLE_ADMIN)
    assert "users.manage" not in permissions_for(ROLE_PHYSICIAN)
    assert "patients.view" in permissions_for(ROLE_VIEWER)
    assert "patients.delete" not in permissions_for(ROLE_VIEWER)


def test_short_password_rejected(repos, admin_user):
    from app.services.security import SecurityService
    with pytest.raises(AuthenticationError):
        SecurityService(repos["users"]).create_user(
            "weak", "Weak User", "short", "nurse")


# --------------------------------------------------------------------------- #
# exchange


def test_exchange_round_trip_new_and_merge(repos, admin_user, patient):
    from app.services.exchange import ExchangeService
    from app.services.patients import PatientService
    from app.services.records import RecordsService

    sender = PatientService(repos, actor="drlee", device_id="ws-a")
    records = RecordsService(repos, actor="drlee", device_id="ws-a")
    records.add_vitals(patient.patient_id, {"blood_pressure": "110/70",
                                            "heart_rate": "64"})

    exchange = ExchangeService(sender, facility_name="Clinic A",
                               actor="drlee", device_id="ws-a")
    bundle = exchange.build_bundle(patient.patient_id)

    # tamper must be rejected
    bad = dict(bundle)
    bad["patient"] = dict(bundle["patient"], name="Evil")
    with pytest.raises(Exception):
        exchange.import_bundle(bad)

    # merge into the same record: no duplicate rows, phone logic intact
    sender.update(patient.patient_id, {"phone": "+234 802 222 2222"})
    report = exchange.import_bundle(bundle, target_patient_id=patient.patient_id,
                                    overwrite=False)
    assert report.mode == "merged"
    assert len(repos["vitals"].list_for_patient(patient.patient_id)) == 1
    assert repos["patients"].get(patient.patient_id).phone == "+234 802 222 2222"


# --------------------------------------------------------------------------- #
# automation + backup


def test_automation_rule_fires_backup(repos, admin_user, patient, tmp_path):
    from app.services.automation import AutomationEngine
    from app.services.backup import BackupService

    db_path = repos["patients"].db.db_path
    backup = BackupService(db_path, tmp_path / "backups")
    engine = AutomationEngine(repos, backup_service=backup)
    engine.add_rule("Auto backup", "patients_total", ">=", 1, "backup")
    report = engine.run_once()
    assert report[0]["fired"] is True
    assert "backup created" in report[0]["result"]
    assert len(backup.list_backups()) == 1


def test_backup_restore_round_trip(repos, admin_user, patient, tmp_path):
    from app.services.backup import BackupService
    from app.models import Patient

    db_path = repos["patients"].db.db_path
    service = BackupService(db_path, tmp_path / "backups")
    snapshot = service.create_backup(label="test")

    repos["patients"].insert(Patient(patient_number="", name="After Snapshot"))
    assert repos["patients"].count() == 2

    service.restore_backup(snapshot)
    assert repos["patients"].count() == 1


def test_sync_dry_run_reports_pending(repos, admin_user, patient):
    from app.services.sync import SyncEngine
    engine = SyncEngine(repos, device_id="ws-01")
    report = engine.sync_now()
    assert report.pushed == 1
    assert report.error is None
