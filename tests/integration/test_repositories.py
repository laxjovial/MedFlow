"""Repository behaviour: CRUD, search, sorting, numbering and soft delete.

These tests run against a real migrated SQLite database. That is deliberate — the
repository's job is to be correct about SQL, and an in-memory stub would prove
nothing about the queries that actually run.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.config.settings import PatientIdSettings
from app.core.exceptions import PersistenceError
from app.domain.audit import AuditEntry
from app.domain.diagnosis import Diagnosis
from app.domain.enums import AuditAction, EntityType, EventType
from app.domain.events import PatientEvent
from app.domain.patient import Patient, PatientRecord
from app.repositories.sqlite.audit_repository import SqliteAuditRepository
from app.repositories.sqlite.connection import Database
from app.repositories.sqlite.history_repository import SqliteHistoryRepository
from app.repositories.sqlite.patient_repository import (
    SORT_COLUMNS,
    SqlitePatientRepository,
    _like_pattern,
)

TODAY = "2026-03-04"
MOMENT = "2026-03-04 10:30:00"


@pytest.fixture
def repository(database: Database) -> SqlitePatientRepository:
    return SqlitePatientRepository(database, PatientIdSettings())


@pytest.fixture
def history(database: Database) -> SqliteHistoryRepository:
    return SqliteHistoryRepository(database)


@pytest.fixture
def audit(database: Database) -> SqliteAuditRepository:
    return SqliteAuditRepository(database)


def make_patient(
    *,
    first_name: str = "Victor",
    last_name: str = "Kamau",
    created_at: str = MOMENT,
    blood_pressure: str = "118/75",
    diagnosis: str = "",
) -> Patient:
    """A patient ready to insert, with sensible defaults for the fields under test."""
    return Patient(
        first_name=first_name,
        last_name=last_name,
        created_at=created_at,
        updated_at=created_at,
        created_by="tester",
        updated_by="tester",
        record=PatientRecord(blood_pressure=blood_pressure, created_at=created_at,
                             updated_at=created_at),
        diagnoses=(
            [Diagnosis(diagnosis=diagnosis, diagnosed_at=created_at)]
            if diagnosis
            else []
        ),
    )


# ---------- numbering ----------


class TestPatientNumbering:
    def test_numbers_are_formatted_from_configuration(
        self, database: Database
    ) -> None:
        repository = SqlitePatientRepository(
            database, PatientIdSettings(prefix="PAT", padding=3)
        )

        assert repository.allocate_patient_number() == "PAT-001"
        assert repository.allocate_patient_number() == "PAT-002"

    def test_numbers_are_never_reused_after_deletion(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())
        repository.mark_deleted(patient.patient_number, deleted_at=MOMENT, actor="tester")

        # The counter is independent of the rows, so the deleted number is not
        # handed out again — a patient number must never point at two people.
        assert repository.allocate_patient_number() == "MF-000002"
        assert repository.count(include_deleted=True) == 1

    def test_insert_allocates_a_number_when_none_is_given(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())

        assert patient.patient_number == "MF-000001"
        assert patient.id is not None


# ---------- create, read, update ----------


class TestPatientRepositoryCrud:
    def test_round_trip(self, repository: SqlitePatientRepository) -> None:
        stored = repository.insert(make_patient())
        loaded = repository.fetch(stored.patient_number)

        assert loaded is not None
        assert loaded.first_name == "Victor"
        assert loaded.last_name == "Kamau"
        assert loaded.record.blood_pressure == "118/75"

    def test_fetch_returns_none_for_an_unknown_number(
        self, repository: SqlitePatientRepository
    ) -> None:
        assert repository.fetch("MF-999999") is None

    def test_save_updates_and_bumps_the_version(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())
        original_version = patient.record_version

        patient.first_name = "Victoria"
        patient.record.blood_pressure = "120/80"
        repository.save(patient)

        reloaded = repository.fetch(patient.patient_number)
        assert reloaded is not None
        assert reloaded.first_name == "Victoria"
        assert reloaded.record.blood_pressure == "120/80"
        assert reloaded.record_version == original_version + 1

    def test_save_refuses_a_patient_that_was_never_stored(
        self, repository: SqlitePatientRepository
    ) -> None:
        with pytest.raises(PersistenceError, match="no identifier"):
            repository.save(make_patient())

    def test_save_reports_a_patient_that_no_longer_exists(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None
        patient.id = 999_999

        with pytest.raises(PersistenceError, match="no longer exists"):
            repository.save(patient)

    def test_duplicate_patient_numbers_are_rejected(
        self, repository: SqlitePatientRepository
    ) -> None:
        first = repository.insert(make_patient())
        clash = make_patient(first_name="Someone")
        clash.patient_number = first.patient_number

        with pytest.raises(PersistenceError, match="already exists"):
            repository.insert(clash)


# ---------- search ----------


class TestPatientSearch:
    @pytest.fixture(autouse=True)
    def _populate(self, repository: SqlitePatientRepository) -> None:
        repository.insert(make_patient(first_name="Victor", last_name="Kamau",
                                       diagnosis="Type 2 Diabetes"))
        repository.insert(make_patient(first_name="Alice", last_name="Smith"))
        repository.insert(make_patient(first_name="John", last_name="Doe",
                                       diagnosis="Hypertension"))

    def test_empty_query_returns_everyone(self, repository: SqlitePatientRepository) -> None:
        assert len(repository.search("")) == 3

    @pytest.mark.parametrize("query", ["victor", "KAMAU", "Victor Kamau", "MF-000001"])
    def test_search_matches_name_and_number(
        self, repository: SqlitePatientRepository, query: str
    ) -> None:
        results = repository.search(query)
        assert [patient.first_name for patient in results] == ["Victor"]

    def test_search_matches_a_diagnosis(self, repository: SqlitePatientRepository) -> None:
        results = repository.search("hypertension")

        assert [patient.first_name for patient in results] == ["John"]

    def test_search_ignores_deleted_patients_by_default(
        self, repository: SqlitePatientRepository
    ) -> None:
        repository.mark_deleted("MF-000002", deleted_at=MOMENT, actor="tester")

        # Default sort is most-recently-updated first, so the newest id leads.
        assert [p.patient_number for p in repository.search("")] == ["MF-000003", "MF-000001"]
        assert len(repository.search("", include_deleted=True)) == 3

    def test_limit_is_applied(self, repository: SqlitePatientRepository) -> None:
        assert len(repository.search("", limit=2)) == 2

    def test_wildcards_typed_by_the_user_are_escaped(
        self, repository: SqlitePatientRepository
    ) -> None:
        # Without escaping, "a%" would match almost every name.
        assert repository.search("a%") == []
        assert repository.search("%") == []
        assert repository.search("_") == []

    def test_like_pattern_escapes_the_escape_character_itself(self) -> None:
        assert _like_pattern("100%") == "%100\\%%"
        assert _like_pattern("a_b") == "%a\\_b%"
        assert _like_pattern("c\\d") == "%c\\\\d%"


# ---------- sorting ----------


class TestPatientSorting:
    @pytest.fixture(autouse=True)
    def _populate(self, repository: SqlitePatientRepository) -> None:
        repository.insert(make_patient(first_name="Zoe", last_name="Adams",
                                       created_at="2026-01-01 09:00:00"))
        repository.insert(make_patient(first_name="Adam", last_name="Zulu",
                                       created_at="2026-02-01 09:00:00"))

    def test_sort_by_name_ascending(self, repository: SqlitePatientRepository) -> None:
        results = repository.search("", sort_by="name", descending=False)

        assert [p.last_name for p in results] == ["Adams", "Zulu"]

    def test_sort_by_name_descending_reverses_both_columns(
        self, repository: SqlitePatientRepository
    ) -> None:
        results = repository.search("", sort_by="name", descending=True)

        assert [p.last_name for p in results] == ["Zulu", "Adams"]

    def test_sort_by_created_at(self, repository: SqlitePatientRepository) -> None:
        results = repository.search("", sort_by="created_at", descending=False)

        assert [p.last_name for p in results] == ["Adams", "Zulu"]

    def test_an_unknown_sort_key_falls_back_instead_of_reaching_the_query(
        self, repository: SqlitePatientRepository
    ) -> None:
        # The whitelist is the injection guard: an unrecognised key must not be
        # interpolated into the ORDER BY clause.
        results = repository.search("", sort_by="name; DROP TABLE patients")

        assert len(results) == 2
        assert repository.count() == 2

    def test_only_whitelisted_columns_are_sortable(self) -> None:
        assert set(SORT_COLUMNS) == {"patient_number", "name", "created_at", "updated_at"}


# ---------- soft delete ----------


class TestSoftDelete:
    def test_delete_is_reversible_and_keeps_the_record(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())

        assert repository.mark_deleted(patient.patient_number, deleted_at=MOMENT,
                                       actor="tester")
        assert repository.fetch(patient.patient_number) is None

        retained = repository.fetch(patient.patient_number, include_deleted=True)
        assert retained is not None
        assert retained.is_deleted
        assert retained.record.blood_pressure == "118/75"

        assert repository.restore(patient.patient_number)
        assert repository.fetch(patient.patient_number) is not None

    def test_deleting_twice_is_reported_as_no_change(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())

        assert repository.mark_deleted(patient.patient_number, deleted_at=MOMENT,
                                       actor="tester")
        assert not repository.mark_deleted(patient.patient_number, deleted_at=MOMENT,
                                           actor="tester")

    def test_deleting_something_that_does_not_exist_is_not_an_error(
        self, repository: SqlitePatientRepository
    ) -> None:
        assert not repository.mark_deleted("MF-999999", deleted_at=MOMENT, actor="tester")
        assert not repository.restore("MF-999999")

    def test_count_can_include_or_exclude_deleted(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())
        repository.mark_deleted(patient.patient_number, deleted_at=MOMENT, actor="tester")

        assert repository.count() == 0
        assert repository.count(include_deleted=True) == 1


# ---------- statistics and distributions ----------


class TestStatistics:
    def test_counts_are_gathered_in_one_pass(
        self, repository: SqlitePatientRepository
    ) -> None:
        active = repository.insert(make_patient(first_name="Active"))
        archived = repository.insert(make_patient(first_name="Archived"))
        archived.status = "archived"
        repository.save(archived)

        removed = repository.insert(make_patient(first_name="Removed"))
        repository.mark_deleted(removed.patient_number, deleted_at=MOMENT, actor="tester")

        assert active.id is not None
        repository.add_diagnosis(active.id, Diagnosis(diagnosis="Asthma", status="active"))

        stats = repository.statistics(today=TODAY)

        assert stats.total_patients == 2
        assert stats.active_patients == 1
        assert stats.archived_patients == 1
        assert stats.deleted_patients == 1
        assert stats.active_diagnoses == 1

    def test_today_is_supplied_by_the_caller(
        self, repository: SqlitePatientRepository
    ) -> None:
        repository.insert(make_patient(created_at="2026-03-04 08:00:00"))

        # "Created today" is relative to the date given, not to when the test ran.
        assert repository.statistics(today="2026-03-04").created_today == 1
        assert repository.statistics(today="2026-03-05").created_today == 0

    def test_statistics_on_an_empty_database_are_all_zero(
        self, repository: SqlitePatientRepository
    ) -> None:
        stats = repository.statistics(today=TODAY)

        assert stats.total_patients == 0
        assert stats.active_diagnoses == 0

    def test_diagnosis_distribution_counts_patients_not_rows(
        self, repository: SqlitePatientRepository
    ) -> None:
        first = repository.insert(make_patient(first_name="One"))
        second = repository.insert(make_patient(first_name="Two"))
        assert first.id is not None and second.id is not None

        repository.add_diagnosis(first.id, Diagnosis(diagnosis="Hypertension"))
        repository.add_diagnosis(first.id, Diagnosis(diagnosis="hypertension"))
        repository.add_diagnosis(second.id, Diagnosis(diagnosis="Asthma"))

        distribution = repository.diagnosis_distribution(limit=5)
        by_name = {entry.diagnosis: entry.count for entry in distribution}

        # Grouping is case-insensitive, so the two spellings are one entry.
        assert by_name == {"Asthma": 1, "Hypertension": 1}
        assert len(distribution) == 2

    def test_blank_diagnoses_are_left_out_of_the_distribution(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None
        repository.add_diagnosis(patient.id, Diagnosis(diagnosis="   "))

        assert repository.diagnosis_distribution() == []

    def test_distribution_respects_its_limit(
        self, repository: SqlitePatientRepository
    ) -> None:
        for index in range(4):
            patient = repository.insert(make_patient(first_name=f"P{index}"))
            assert patient.id is not None
            repository.add_diagnosis(patient.id, Diagnosis(diagnosis=f"Condition {index}"))

        assert len(repository.diagnosis_distribution(limit=2)) == 2


# ---------- diagnoses ----------


class TestDiagnoses:
    def test_add_and_list(self, repository: SqlitePatientRepository) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None

        repository.add_diagnosis(patient.id, Diagnosis(diagnosis="Asthma",
                                                       diagnosed_at=MOMENT))
        repository.add_diagnosis(patient.id, Diagnosis(diagnosis="Eczema",
                                                       diagnosed_at=MOMENT))

        listed = repository.list_diagnoses(patient.id)
        assert [item.diagnosis for item in listed] == ["Eczema", "Asthma"]  # newest first

    def test_update_changes_status_and_keeps_the_row(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None
        diagnosis = repository.add_diagnosis(
            patient.id, Diagnosis(diagnosis="Asthma", diagnosed_at=MOMENT)
        )

        diagnosis.status = "resolved"
        repository.update_diagnosis(diagnosis)

        listed = repository.list_diagnoses(patient.id)
        assert len(listed) == 1
        assert listed[0].status == "resolved"

    def test_fetch_attaches_diagnoses(self, repository: SqlitePatientRepository) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None
        repository.add_diagnosis(patient.id, Diagnosis(diagnosis="Hypertension"))
        repository.add_diagnosis(patient.id, Diagnosis(diagnosis="Asthma"))

        loaded = repository.fetch(patient.patient_number)
        assert loaded is not None
        assert len(loaded.diagnoses) == 2
        assert len(loaded.active_diagnoses) == 2

    def test_deleting_a_patient_leaves_their_diagnoses_intact(
        self, repository: SqlitePatientRepository
    ) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None
        repository.add_diagnosis(patient.id, Diagnosis(diagnosis="Hypertension"))

        repository.mark_deleted(patient.patient_number, deleted_at=MOMENT, actor="tester")

        # Soft delete is a flag, not a cascade: the clinical record survives.
        assert len(repository.list_diagnoses(patient.id)) == 1


# ---------- history ----------


class TestHistoryRepository:
    def test_round_trip(self, history: SqliteHistoryRepository,
                        repository: SqlitePatientRepository) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None

        history.record(PatientEvent(patient_id=patient.id, event_type=EventType.CREATED.value,
                                    description="Registered.", actor="tester",
                                    created_at=MOMENT))

        events = history.for_patient(patient.id)
        assert len(events) == 1
        assert events[0].label == "Record created"
        assert events[0].actor == "tester"

    def test_a_timeline_entry_needs_a_patient(
        self, history: SqliteHistoryRepository
    ) -> None:
        with pytest.raises(PersistenceError, match="must reference a patient"):
            history.record(PatientEvent(event_type=EventType.CREATED.value))

    def test_recent_is_newest_first(self, history: SqliteHistoryRepository,
                                    repository: SqlitePatientRepository) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None

        for count in range(3):
            history.record(PatientEvent(patient_id=patient.id,
                                        event_type=EventType.UPDATED.value,
                                        description=f"Change {count}",
                                        created_at=MOMENT))

        assert [e.description for e in history.recent(limit=2)] == ["Change 2", "Change 1"]

    def test_deleting_a_patient_removes_their_timeline(
        self, history: SqliteHistoryRepository, repository: SqlitePatientRepository,
        database: Database,
    ) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None
        history.record(PatientEvent(patient_id=patient.id, event_type=EventType.CREATED.value,
                                    created_at=MOMENT))

        # A hard delete is not something the application does, but the foreign key
        # is what guarantees a timeline can never outlive its patient.
        with database.transaction() as connection:
            connection.execute("DELETE FROM patients WHERE id = ?", (patient.id,))

        assert history.for_patient(patient.id) == []


# ---------- audit ----------


class TestAuditRepository:
    def test_round_trip_preserves_details(self, audit: SqliteAuditRepository) -> None:
        audit.record(AuditEntry(action=AuditAction.UPDATE.value,
                                entity_type=EntityType.PATIENT.value,
                                entity_id="MF-000001", actor="tester",
                                details={"changed": ["first_name", "phone"]},
                                created_at=MOMENT))

        entry = audit.recent()[0]
        assert entry.details == {"changed": ["first_name", "phone"]}
        assert entry.actor == "tester"
        assert entry.label == "Changed a record"
        assert "MF-000001" in entry.summary

    def test_entries_can_be_filtered_by_entity(self, audit: SqliteAuditRepository) -> None:
        for number in ("MF-000001", "MF-000002", "MF-000001"):
            audit.record(AuditEntry(action=AuditAction.UPDATE.value,
                                    entity_type=EntityType.PATIENT.value,
                                    entity_id=number, created_at=MOMENT))

        assert len(audit.for_entity(EntityType.PATIENT.value, "MF-000001")) == 2
        assert audit.for_entity(EntityType.PATIENT.value, "MF-000001", limit=1)

    def test_count(self, audit: SqliteAuditRepository) -> None:
        assert audit.count() == 0
        audit.record(AuditEntry(action=AuditAction.CREATE.value, created_at=MOMENT))
        assert audit.count() == 1

    def test_recent_honours_limit_and_offset(self, audit: SqliteAuditRepository) -> None:
        for index in range(5):
            audit.record(AuditEntry(action=AuditAction.UPDATE.value,
                                    entity_id=f"MF-{index}", created_at=MOMENT))

        page = audit.recent(limit=2, offset=1)
        assert [entry.entity_id for entry in page] == ["MF-000003", "MF-000002"]

    def test_unreadable_details_degrade_to_empty(
        self, audit: SqliteAuditRepository, database: Database
    ) -> None:
        # An entry written by another version must not make the Activity view
        # unloadable.
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (action, entity_type, entity_id, actor, details, created_at)
                VALUES ('UPDATE', 'patient', 'MF-000001', 'tester', 'not json', '2026-03-04 10:30:00')
                """
            )

        assert audit.recent()[0].details == {}

    def test_non_mapping_details_degrade_to_empty(
        self, audit: SqliteAuditRepository, database: Database
    ) -> None:
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (action, entity_type, entity_id, actor, details, created_at)
                VALUES ('UPDATE', 'patient', 'MF-000001', 'tester', '[1, 2, 3]', '2026-03-04 10:30:00')
                """
            )

        assert audit.recent()[0].details == {}

    def test_details_are_stored_as_json_text(self, audit: SqliteAuditRepository,
                                             database: Database) -> None:
        audit.record(AuditEntry(action=AuditAction.IMPORT.value,
                                details={"count": 3, "path": "/tmp/x.csv"},
                                created_at=MOMENT))

        with database.connection() as connection:
            raw = connection.execute("SELECT details FROM audit_log").fetchone()["details"]

        assert isinstance(raw, str)
        assert '"count": 3' in raw

    def test_details_that_cannot_be_encoded_are_reported(
        self, audit: SqliteAuditRepository
    ) -> None:
        # A self-referencing structure survives ``default=str`` but not encoding,
        # which is the case an audit write has to fail loudly on rather than
        # storing something that cannot be read back.
        circular: dict[str, object] = {}
        circular["self"] = circular

        with pytest.raises(PersistenceError, match="not serialisable"):
            audit.record(AuditEntry(action=AuditAction.UPDATE.value,
                                    details=circular,
                                    created_at=MOMENT))

    def test_audit_survives_the_patient_it_describes(
        self, audit: SqliteAuditRepository, repository: SqlitePatientRepository,
        database: Database,
    ) -> None:
        patient = repository.insert(make_patient())
        audit.record(AuditEntry(action=AuditAction.CREATE.value,
                                entity_type=EntityType.PATIENT.value,
                                entity_id=patient.patient_number, created_at=MOMENT))

        with database.transaction() as connection:
            connection.execute("DELETE FROM patients WHERE id = ?", (patient.id,))

        # entity_id is a plain string, not a foreign key, so the audit trail is
        # not erased along with the record it describes.
        assert audit.count() == 1


# ---------- schema guarantees ----------


class TestSchemaGuarantees:
    def test_patient_numbers_are_unique(self, database: Database) -> None:
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO patients (patient_number, created_at, updated_at) VALUES (?, ?, ?)",
                ("MF-000001", MOMENT, MOMENT),
            )

        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO patients (patient_number, created_at, updated_at) "
                    "VALUES (?, ?, ?)",
                    ("MF-000001", MOMENT, MOMENT),
                )

    def test_deleting_a_patient_cascades_across_a_foreign_key(
        self, repository: SqlitePatientRepository, database: Database
    ) -> None:
        patient = repository.insert(make_patient())
        assert patient.id is not None
        repository.add_diagnosis(patient.id, Diagnosis(diagnosis="Hypertension"))

        with database.transaction() as connection:
            connection.execute("DELETE FROM patients WHERE id = ?", (patient.id,))

        with database.connection() as connection:
            remaining = connection.execute(
                "SELECT COUNT(*) AS n FROM diagnoses"
            ).fetchone()["n"]

        assert remaining == 0
