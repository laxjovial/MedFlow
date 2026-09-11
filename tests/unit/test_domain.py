"""Domain models.

These are plain data with derived properties, so the tests are mostly about the
properties: they are the only logic in the layer, and everything above depends on
them being right.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.domain.audit import AuditEntry
from app.domain.diagnosis import Diagnosis
from app.domain.enums import (
    AUDIT_ACTION_LABELS,
    AuditAction,
    DiagnosisStatus,
    EntityType,
    EventType,
    PatientStatus,
)
from app.domain.events import EVENT_LABELS, PatientEvent
from app.domain.patient import Patient, PatientRecord


def make_patient(**overrides: object) -> Patient:
    defaults: dict[str, object] = {
        "patient_number": "MF-000001",
        "first_name": "Victor",
        "last_name": "Kamau",
        "id": 1,
    }
    return Patient(**{**defaults, **overrides})


class TestPatientName:
    def test_full_name_joins_the_two_halves(self) -> None:
        assert make_patient().full_name == "Victor Kamau"

    def test_a_missing_surname_leaves_no_trailing_space(self) -> None:
        assert make_patient(last_name="").full_name == "Victor"

    def test_a_missing_first_name_leaves_no_leading_space(self) -> None:
        assert make_patient(first_name="").full_name == "Kamau"

    def test_a_nameless_record_falls_back_to_its_number(self) -> None:
        # Migrated rows can have a blank name, and the number is the only
        # reliable way to refer to one.
        assert make_patient(first_name="", last_name="").full_name == "MF-000001"

    def test_a_nameless_record_with_no_number_still_reads(self) -> None:
        assert make_patient(first_name="", last_name="", patient_number="").full_name == (
            "Unnamed patient"
        )

    def test_display_name_matches_full_name(self) -> None:
        patient = make_patient()
        assert patient.display_name == patient.full_name


class TestPatientStatus:
    def test_a_new_patient_is_active(self) -> None:
        assert make_patient().is_active

    def test_a_deleted_patient_is_not_active(self) -> None:
        assert not make_patient(deleted_at="2026-03-04 10:30:00").is_active
        assert make_patient(deleted_at="2026-03-04 10:30:00").is_deleted

    def test_an_inactive_patient_is_not_deleted(self) -> None:
        patient = make_patient(status=PatientStatus.INACTIVE.value)
        assert not patient.is_active
        assert not patient.is_deleted

    def test_the_default_status_comes_from_the_enum(self) -> None:
        # If the default were a literal, renaming the enum member would silently
        # leave new patients in a status nothing recognises.
        assert make_patient().status == PatientStatus.ACTIVE.value


class TestActiveDiagnoses:
    def test_only_active_diagnoses_are_returned(self) -> None:
        patient = make_patient(
            diagnoses=[
                Diagnosis(diagnosis="Malaria", status=DiagnosisStatus.ACTIVE.value),
                Diagnosis(diagnosis="Flu", status=DiagnosisStatus.RESOLVED.value),
                Diagnosis(diagnosis="Anaemia", status=DiagnosisStatus.ACTIVE.value),
            ]
        )

        assert [d.diagnosis for d in patient.active_diagnoses] == ["Malaria", "Anaemia"]

    def test_a_patient_with_no_diagnoses_returns_an_empty_list(self) -> None:
        assert make_patient().active_diagnoses == []


class TestPatientRecord:
    def test_an_untouched_record_has_no_content(self) -> None:
        assert not PatientRecord().has_content

    @pytest.mark.parametrize(
        "field_name",
        ["blood_pressure", "heart_rate", "weight", "height", "medical_history", "notes"],
    )
    def test_any_single_clinical_value_counts_as_content(self, field_name: str) -> None:
        assert PatientRecord(**{field_name: "x"}).has_content

    def test_from_mapping_keeps_only_the_clinical_fields(self) -> None:
        record = PatientRecord.from_mapping(
            {
                "blood_pressure": "118/75",
                "notes": "Stable.",
                "first_name": "Victor",  # not a record field
                "heart_rate": None,  # explicitly absent
            }
        )

        assert record.blood_pressure == "118/75"
        assert record.notes == "Stable."
        assert record.heart_rate == ""
        assert not hasattr(record, "first_name")

    def test_from_mapping_tolerates_a_missing_mapping(self) -> None:
        assert not PatientRecord.from_mapping({}).has_content


class TestPatientConversion:
    def test_to_dict_flattens_the_record(self) -> None:
        patient = make_patient(record=PatientRecord(blood_pressure="118/75", notes="Stable."))
        flat = patient.to_dict()

        assert flat["blood_pressure"] == "118/75"
        assert flat["notes"] == "Stable."

    def test_to_dict_includes_the_derived_full_name(self) -> None:
        assert make_patient().to_dict()["full_name"] == "Victor Kamau"

    def test_to_dict_omits_diagnoses(self) -> None:
        # Diagnoses have their own table and their own export shape; flattening
        # them into the patient row would put a list inside a CSV cell.
        patient = make_patient(diagnoses=[Diagnosis(diagnosis="Malaria")])
        assert "diagnoses" not in patient.to_dict()

    def test_to_form_data_round_trips_the_editable_values(self) -> None:
        patient = make_patient(
            sex="Male",
            phone="+254 700 123456",
            record=PatientRecord(blood_pressure="118/75", heart_rate="90"),
        )
        data = patient.to_form_data()

        assert data["first_name"] == "Victor"
        assert data["sex"] == "Male"
        assert data["phone"] == "+254 700 123456"
        assert data["blood_pressure"] == "118/75"
        assert data["heart_rate"] == "90"

    def test_to_form_data_does_not_leak_the_patient_number(self) -> None:
        # The number is allocated by the system, so the form must not offer it as
        # an editable field — otherwise a save could try to change it.
        assert "patient_number" not in make_patient().to_form_data()

    def test_every_form_key_maps_onto_a_model_field(self) -> None:
        # The form's keys are the contract between the UI and the service. A key
        # that no model holds would silently drop whatever the user typed into
        # it, which is the kind of bug that is only noticed weeks later.
        form_keys = set(make_patient().to_form_data())
        editable = {f.name for f in dataclasses.fields(Patient)} | {
            f.name for f in dataclasses.fields(PatientRecord)
        }

        assert form_keys <= editable

    def test_a_patient_rebuilt_from_form_data_keeps_its_demographics(self) -> None:
        original = make_patient(
            date_of_birth="1994-02-17",
            sex="Male",
            address="12 Riverside Drive",
        )
        restored = make_patient(
            **{
                key: value
                for key, value in original.to_form_data().items()
                if key in {f.name for f in dataclasses.fields(Patient)}
            }
        )

        assert restored.first_name == original.first_name
        assert restored.date_of_birth == original.date_of_birth
        assert restored.address == original.address


class TestDiagnosis:
    def test_a_diagnosis_defaults_to_active(self) -> None:
        assert Diagnosis(diagnosis="Malaria").is_active

    def test_the_recorded_text_is_preserved_verbatim(self) -> None:
        # Case and spacing are the clinician's. Normalising at the model would
        # erase the difference between "Type 2 Diabetes" and "type 2 diabetes"
        # before anything had a chance to decide whether it matters.
        assert Diagnosis(diagnosis="Type 2 Diabetes").diagnosis == "Type 2 Diabetes"

    def test_the_status_label_is_readable(self) -> None:
        assert Diagnosis(status=DiagnosisStatus.RULED_OUT.value).status_label == "Ruled out"


class TestLabels:
    def test_every_event_type_has_a_label(self) -> None:
        missing = [event.value for event in EventType if event.value not in EVENT_LABELS]
        assert missing == []

    def test_every_audit_action_has_a_label(self) -> None:
        missing = [
            action.value for action in AuditAction if action.value not in AUDIT_ACTION_LABELS
        ]
        assert missing == []

    def test_event_labels_are_written_for_a_person_to_read(self) -> None:
        assert EVENT_LABELS[EventType.CREATED.value] == "Record created"
        assert "_" not in EVENT_LABELS[EventType.DIAGNOSIS_ADDED.value]


class TestTimelineEntries:
    def test_a_history_entry_carries_its_type(self) -> None:
        event = PatientEvent(
            patient_id=1,
            event_type=EventType.CREATED.value,
            description="Record created.",
            actor="dr-owino",
            created_at="2026-03-04 10:30:00",
        )

        assert event.event_type == EventType.CREATED.value
        assert event.actor == "dr-owino"
        assert event.label == EVENT_LABELS[EventType.CREATED.value]

    def test_an_unknown_event_type_still_gets_a_label(self) -> None:
        # A row written by a newer version, or by hand, must not blank the view.
        event = PatientEvent(event_type="SOMETHING_NEW")

        assert event.label == "Something New"


class TestAuditEntries:
    def test_an_entry_describes_its_target(self) -> None:
        entry = AuditEntry(
            actor="dr-owino",
            action=AuditAction.CREATE.value,
            entity_type=EntityType.PATIENT.value,
            entity_id="MF-000001",
            created_at="2026-03-04 10:30:00",
        )

        assert entry.target == "patient MF-000001"

    def test_an_entry_with_no_entity_id_still_has_a_target(self) -> None:
        entry = AuditEntry(
            actor="dr-owino",
            action=AuditAction.BACKUP.value,
            entity_type=EntityType.DATABASE.value,
            created_at="2026-03-04 10:30:00",
        )

        assert entry.target == "database"

    def test_an_entry_summarises_as_label_and_target(self) -> None:
        entry = AuditEntry(
            actor="dr-owino",
            action=AuditAction.CREATE.value,
            entity_type=EntityType.PATIENT.value,
            entity_id="MF-000001",
            created_at="2026-03-04 10:30:00",
        )

        assert entry.summary == f"{entry.label} · {entry.target}"
        assert entry.label == AUDIT_ACTION_LABELS[AuditAction.CREATE.value]

    def test_an_employee_facing_action_reads_as_a_sentence(self) -> None:
        entry = AuditEntry(action=AuditAction.CREATE.value)

        assert entry.summary == "Created a patient"

    def test_an_unknown_action_is_tidied_rather_than_shown_raw(self) -> None:
        assert AuditEntry(action="SOMETHING_NEW").label == "Something New"

    def test_details_default_to_an_empty_mapping(self) -> None:
        # Details are optional everywhere, so the default must not be a shared
        # mutable dict that one entry could write into for all of them.
        first = AuditEntry(actor="a", action="create", entity_type="patient")
        second = AuditEntry(actor="b", action="create", entity_type="patient")

        first.details["patients"] = 3
        assert second.details == {}
