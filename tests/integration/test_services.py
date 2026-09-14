"""Service behaviour: validation, change tracking, and what gets recorded.

The service layer is where the application's rules live, so these tests are about
*policy* rather than storage: that an invalid submission writes nothing, that an
unchanged submission writes nothing, and that every real change leaves both a
timeline entry and an audit entry behind.
"""

from __future__ import annotations

import pytest

from app.container import Container
from app.core.clock import FixedClock
from app.core.exceptions import NotFoundError, ValidationError
from app.domain.enums import AuditAction, DiagnosisStatus, EntityType, EventType
from app.services.patient_service import PatientService

ACTOR = "dr-owino"


@pytest.fixture
def service(container: Container) -> PatientService:
    return container.patients


# ---------- create ----------


class TestCreatePatient:
    def test_registers_a_patient(self, service: PatientService, sample_patient_data) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        assert patient.patient_number == "MF-000001"
        assert patient.id is not None
        assert patient.full_name == "Victor Kamau"
        assert patient.record.blood_pressure == "118/75"
        assert patient.record_version == 1

    def test_stamps_who_created_it_and_when(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        assert patient.created_at == "2026-03-04 10:30:00"
        assert patient.updated_at == patient.created_at
        assert patient.created_by == ACTOR
        assert patient.updated_by == ACTOR

    def test_records_an_opening_diagnosis(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        # The pre-refactor application had a single "diag" field. Here it becomes
        # a diagnosis row, so a later edit cannot silently overwrite it.
        assert [d.diagnosis for d in patient.diagnoses] == ["Acute Appendicitis"]
        assert patient.active_diagnoses[0].status == DiagnosisStatus.ACTIVE.value

    def test_writes_a_timeline_entry(self, service: PatientService, sample_patient_data) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        events = service.timeline(patient.patient_number)
        assert [event.event_type for event in events] == [EventType.CREATED.value]
        assert events[0].actor == ACTOR

    def test_writes_an_audit_entry(self, service: PatientService, sample_patient_data) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        entries = service.audit_trail(patient.patient_number)
        assert [entry.action for entry in entries] == [AuditAction.CREATE.value]
        assert entries[0].entity_type == EntityType.PATIENT.value
        assert entries[0].details["name"] == "Victor Kamau"

    def test_patient_numbers_increment(self, service: PatientService,
                                       sample_patient_data) -> None:
        first = service.create(sample_patient_data, actor=ACTOR)
        second = service.create(sample_patient_data, actor=ACTOR)

        assert (first.patient_number, second.patient_number) == ("MF-000001", "MF-000002")


class TestCreateRejectsInvalidInput:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("first_name", ""),
            ("first_name", "   "),
            ("email", "not-an-email"),
            ("heart_rate", "fast"),
            ("blood_pressure", "high"),
            ("age_years", "-4"),
            ("age_years", "999"),
            ("date_of_birth", "12/04/1979"),
            ("date_of_birth", "2099-01-01"),
        ],
    )
    def test_invalid_values_are_rejected(
        self, service: PatientService, sample_patient_data, field: str, value: str
    ) -> None:
        sample_patient_data[field] = value

        with pytest.raises(ValidationError) as caught:
            service.create(sample_patient_data, actor=ACTOR)

        assert field in caught.value.errors

    def test_nothing_is_written_when_validation_fails(
        self, service: PatientService, sample_patient_data
    ) -> None:
        sample_patient_data["email"] = "bad"

        with pytest.raises(ValidationError):
            service.create(sample_patient_data, actor=ACTOR)

        assert service.count(include_deleted=True) == 0
        assert service.diagnosis_distribution() == []

    def test_every_problem_is_reported_at_once(
        self, service: PatientService, sample_patient_data
    ) -> None:
        sample_patient_data.update({"first_name": "", "email": "bad", "heart_rate": "x"})

        with pytest.raises(ValidationError) as caught:
            service.create(sample_patient_data, actor=ACTOR)

        # One submission, one round of feedback — not three attempts.
        assert set(caught.value.errors) == {"first_name", "email", "heart_rate"}

    def test_placeholder_values_are_treated_as_not_recorded(
        self, service: PatientService, sample_patient_data
    ) -> None:
        # The previous version wrote "--" into empty fields; re-entering it must
        # mean "no value", not a literal pair of dashes.
        sample_patient_data.update({"blood_pressure": "--", "heart_rate": "--", "notes": "--"})

        patient = service.create(sample_patient_data, actor=ACTOR)

        assert patient.record.blood_pressure == ""
        assert patient.record.heart_rate == ""
        assert patient.record.notes == ""


# ---------- update ----------


class TestUpdatePatient:
    def test_applies_changes_and_bumps_the_version(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        updated = service.update(
            patient.patient_number,
            {"first_name": "Victoria", "blood_pressure": "124/82"},
            actor=ACTOR,
        )

        assert updated.first_name == "Victoria"
        assert updated.record.blood_pressure == "124/82"
        assert updated.record_version == patient.record_version + 1

    def test_an_update_with_no_changes_writes_nothing(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        unchanged = service.update(
            patient.patient_number, patient.to_form_data(), actor=ACTOR
        )

        # Opening a record and saving it again must not fill the timeline with
        # entries that say nothing happened.
        assert unchanged.record_version == patient.record_version
        assert len(service.timeline(patient.patient_number)) == 1

    def test_only_the_supplied_fields_are_touched(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        service.update(patient.patient_number, {"phone": "+254700999888"}, actor=ACTOR)

        reloaded = service.require(patient.patient_number)
        assert reloaded.phone == "+254700999888"
        assert reloaded.email == "victor@example.com"
        assert reloaded.record.blood_pressure == "118/75"

    def test_the_timeline_names_what_changed(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        service.update(
            patient.patient_number,
            {"blood_pressure": "124/82", "phone": "+254700999888"},
            actor=ACTOR,
        )

        events = service.timeline(patient.patient_number)
        latest = events[0]
        assert latest.event_type == EventType.UPDATED.value
        assert "2 fields" in latest.description
        assert "Blood pressure" in latest.description
        assert "Phone" in latest.description

    def test_a_single_change_is_described_in_the_singular(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)
        service.update(patient.patient_number, {"phone": "+254700999888"}, actor=ACTOR)

        description = service.timeline(patient.patient_number)[0].description
        assert description == "Updated phone."

    def test_the_audit_entry_lists_the_changed_fields(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)
        service.update(patient.patient_number, {"phone": "+254700999888"}, actor=ACTOR)

        entry = service.audit_trail(patient.patient_number)[0]
        assert entry.action == AuditAction.UPDATE.value
        assert entry.details["changed"] == ["phone"]

    def test_an_invalid_update_changes_nothing(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        with pytest.raises(ValidationError):
            service.update(patient.patient_number, {"email": "bad"}, actor=ACTOR)

        reloaded = service.require(patient.patient_number)
        assert reloaded.email == "victor@example.com"
        assert reloaded.record_version == patient.record_version

    def test_updating_a_patient_that_does_not_exist_is_reported(
        self, service: PatientService
    ) -> None:
        with pytest.raises(NotFoundError):
            service.update("MF-999999", {"phone": "+254700999888"}, actor=ACTOR)

    def test_the_form_round_trips(self, service: PatientService, sample_patient_data) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        # Everything the form can edit is present in what it is given to populate
        # itself, so an edit never silently drops a field.
        assert set(patient.to_form_data()) == {
            "first_name", "last_name", "date_of_birth", "age_years", "sex",
            "phone", "email", "address", "blood_pressure", "heart_rate",
            "weight", "height", "medical_history", "notes",
        }


# ---------- delete and restore ----------


class TestDeleteAndRestore:
    def test_delete_is_soft(self, service: PatientService, sample_patient_data) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        assert service.delete(patient.patient_number, actor=ACTOR)

        assert service.get(patient.patient_number) is None
        retained = service.get(patient.patient_number, include_deleted=True)
        assert retained is not None and retained.is_deleted

    def test_delete_keeps_the_clinical_record(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)
        service.delete(patient.patient_number, actor=ACTOR)

        retained = service.get(patient.patient_number, include_deleted=True)
        assert retained is not None
        assert retained.record.blood_pressure == "118/75"
        assert retained.diagnoses  # the diagnosis survives too

    def test_delete_records_a_timeline_entry_and_audit(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)
        service.delete(patient.patient_number, actor=ACTOR)

        events = service.timeline(patient.patient_number)
        assert events[0].event_type == EventType.DELETED.value
        assert service.audit_trail(patient.patient_number)[0].action == AuditAction.DELETE.value

    def test_restore_undoes_a_delete(self, service: PatientService, sample_patient_data) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)
        service.delete(patient.patient_number, actor=ACTOR)

        assert service.restore(patient.patient_number, actor=ACTOR)

        restored = service.require(patient.patient_number)
        assert not restored.is_deleted
        assert service.timeline(patient.patient_number)[0].event_type == EventType.RESTORED.value

    def test_a_patient_number_is_never_reissued(
        self, service: PatientService, sample_patient_data
    ) -> None:
        first = service.create(sample_patient_data, actor=ACTOR)
        service.delete(first.patient_number, actor=ACTOR)

        second = service.create(sample_patient_data, actor=ACTOR)

        assert second.patient_number != first.patient_number

    def test_deleting_twice_is_reported_as_no_change(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        assert service.delete(patient.patient_number, actor=ACTOR)
        assert not service.delete(patient.patient_number, actor=ACTOR)


# ---------- diagnoses ----------


class TestDiagnoses:
    def test_adding_a_diagnosis_is_recorded(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        service.add_diagnosis(patient.patient_number, "Hypertension", actor=ACTOR)

        reloaded = service.require(patient.patient_number)
        assert "Hypertension" in {d.diagnosis for d in reloaded.diagnoses}
        assert service.timeline(patient.patient_number)[0].event_type == (
            EventType.DIAGNOSIS_ADDED.value
        )

    def test_a_blank_diagnosis_is_rejected(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        with pytest.raises(ValidationError):
            service.add_diagnosis(patient.patient_number, "   ", actor=ACTOR)

    def test_resolving_keeps_the_row(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)
        diagnosis = patient.diagnoses[0]

        resolved = service.resolve_diagnosis(
            patient.patient_number, diagnosis.id, actor=ACTOR
        )

        assert resolved.status == DiagnosisStatus.RESOLVED.value
        reloaded = service.require(patient.patient_number)
        # Still on the record — the fact that the patient was treated for it does
        # not stop being true when it resolves.
        assert len(reloaded.diagnoses) == 1
        assert reloaded.active_diagnoses == []

    def test_resolving_records_the_event(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)
        service.resolve_diagnosis(
            patient.patient_number, patient.diagnoses[0].id, actor=ACTOR
        )

        assert service.timeline(patient.patient_number)[0].event_type == (
            EventType.DIAGNOSIS_RESOLVED.value
        )

    def test_an_unknown_diagnosis_is_reported(
        self, service: PatientService, sample_patient_data
    ) -> None:
        patient = service.create(sample_patient_data, actor=ACTOR)

        with pytest.raises(NotFoundError):
            service.resolve_diagnosis(patient.patient_number, 999_999, actor=ACTOR)


# ---------- reads ----------


class TestReads:
    def test_search_and_sort_are_passed_through(
        self, service: PatientService, sample_patient_data
    ) -> None:
        service.create(sample_patient_data, actor=ACTOR)
        service.create({**sample_patient_data, "first_name": "Alice",
                        "last_name": "Smith"}, actor=ACTOR)

        assert len(service.search("")) == 2
        assert len(service.search("alice")) == 1
        assert [p.last_name for p in service.search("", sort_by="name",
                                                    descending=False)] == [
            "Kamau",
            "Smith",
        ]

    def test_timeline_of_an_unknown_patient_is_reported(
        self, service: PatientService
    ) -> None:
        with pytest.raises(NotFoundError):
            service.timeline("MF-999999")

    def test_statistics_take_today_from_the_clock(
        self, service: PatientService, sample_patient_data
    ) -> None:
        service.create(sample_patient_data, actor=ACTOR)

        stats = service.statistics()

        # The fixture clock is pinned to 2026-03-04, so "today" is that date and
        # not the date the suite happens to run on.
        assert stats.created_today == 1
        assert stats.total_patients == 1


# ---------- the clock ----------


class TestClockIsUsedEverywhere:
    def test_a_frozen_clock_produces_identical_timestamps(
        self, container: Container, sample_patient_data
    ) -> None:
        clock = container.clock
        assert isinstance(clock, FixedClock)

        first = container.patients.create(sample_patient_data, actor=ACTOR)
        clock.advance(seconds=120)
        second = container.patients.create(sample_patient_data, actor=ACTOR)

        assert first.created_at == "2026-03-04 10:30:00"
        assert second.created_at == "2026-03-04 10:32:00"


# ---------- dashboard ----------


class TestDashboard:
    def test_summary_reports_the_register(
        self, container: Container, sample_patient_data
    ) -> None:
        container.patients.create(sample_patient_data, actor=ACTOR)

        summary = container.dashboard.summary()

        assert summary.total_patients == 1
        assert summary.created_today == 1
        assert summary.active_diagnoses == 1
        assert summary.storage_mode == "local"
        assert summary.database_location.endswith("medflow.db")

    def test_summary_includes_the_diagnosis_distribution(
        self, container: Container, sample_patient_data
    ) -> None:
        container.patients.create(sample_patient_data, actor=ACTOR)
        container.patients.create(sample_patient_data, actor=ACTOR)

        summary = container.dashboard.summary()

        assert summary.has_diagnoses
        assert summary.top_diagnoses[0].diagnosis == "Acute Appendicitis"
        assert summary.top_diagnoses[0].count == 2
        assert summary.max_diagnosis_count == 2

    def test_summary_is_empty_but_valid_on_a_fresh_database(
        self, container: Container
    ) -> None:
        summary = container.dashboard.summary()

        assert summary.total_patients == 0
        assert summary.top_diagnoses == []
        assert summary.recent_events == []
        assert not summary.has_diagnoses
        assert summary.max_diagnosis_count == 0

    def test_summary_includes_recent_activity(
        self, container: Container, sample_patient_data
    ) -> None:
        container.patients.create(sample_patient_data, actor=ACTOR)

        summary = container.dashboard.summary()

        assert [event.event_type for event in summary.recent_events] == [
            EventType.CREATED.value
        ]


# ---------- seeding ----------


class TestSeeding:
    def test_demo_data_is_created_once(self, container: Container) -> None:
        from app.services.seed import seed

        assert seed(container.patients, actor="system") == 3
        assert seed(container.patients, actor="system") == 0
        assert container.patients.count() == 3

    def test_seeded_patients_have_full_history(self, container: Container) -> None:
        from app.services.seed import seed

        seed(container.patients, actor="system")

        # Seeding goes through the service, so a demo record is a normal record:
        # it has a timeline and an audit trail like any other.
        patient = container.patients.search("Kamau")[0]
        assert len(patient.diagnoses) == 2
        assert container.patients.timeline(patient.patient_number)
        assert container.patients.audit_trail(patient.patient_number)

    def test_seeding_is_skipped_when_a_deleted_patient_exists(
        self, container: Container
    ) -> None:
        from app.services.seed import seed

        seed(container.patients, actor="system")
        for patient in container.patients.search("", include_deleted=True):
            container.patients.delete(patient.patient_number, actor="system")

        assert container.patients.count() == 0
        assert container.patients.count(include_deleted=True) == 3

        # A register emptied by deletion is not a new installation, so the demo
        # data must not come back.
        assert seed(container.patients, actor="system") == 0


# ---------- audit service ----------


class TestAuditService:
    def test_records_and_reads_back(self, container: Container) -> None:
        entry = container.audit.record(
            AuditAction.EXPORT,
            entity_type=EntityType.DATABASE,
            entity_id="patients.csv",
            actor=ACTOR,
            details={"patients": 12},
        )

        assert entry.id is not None
        assert container.audit.count() == 1
        assert container.audit.recent()[0].details == {"patients": 12}

    def test_timestamps_come_from_the_clock(self, container: Container) -> None:
        entry = container.audit.record(
            AuditAction.BACKUP, entity_type=EntityType.DATABASE, actor=ACTOR
        )

        assert entry.created_at == "2026-03-04 10:30:00"


# ---------- history service ----------


class TestHistoryService:
    def test_recording_without_a_patient_is_reported(self, container: Container) -> None:
        with pytest.raises(ValidationError):
            container.history.record(None, EventType.CREATED, "no patient", actor=ACTOR)
