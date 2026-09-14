"""Export, import and backup.

The theme running through these tests is that no file is ever trusted. An import is
parsed and validated before anything is written, a bad row is skipped rather than
stopping the file, and a backup is taken through SQLite rather than by copying the
database file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.container import Container
from app.core.exceptions import DataImportError, ExportError, ValidationError
from app.domain.enums import AuditAction

ACTOR = "dr-owino"


@pytest.fixture
def populated(container: Container, sample_patient_data) -> Container:
    container.patients.create(sample_patient_data, actor=ACTOR)
    container.patients.create(
        {**sample_patient_data, "first_name": "Alice", "last_name": "Smith",
         "diagnosis": "Asthma"},
        actor=ACTOR,
    )
    return container


# ---------- export ----------


class TestCsvExport:
    def test_writes_a_header_and_a_row_per_patient(
        self, populated: Container, tmp_path: Path
    ) -> None:
        path = populated.transfer.export_patients(tmp_path / "out.csv", actor=ACTOR)
        lines = path.read_text(encoding="utf-8").splitlines()

        assert lines[0].startswith("patient_number,first_name,last_name")
        assert len(lines) == 3

    def test_records_the_export_in_the_audit_trail(
        self, populated: Container, tmp_path: Path
    ) -> None:
        populated.transfer.export_patients(tmp_path / "out.csv", actor=ACTOR)

        latest = populated.audit.recent()[0]
        assert latest.action == AuditAction.EXPORT.value
        assert latest.details["patients"] == 2

    def test_the_extension_is_applied_when_it_is_missing(
        self, populated: Container, tmp_path: Path
    ) -> None:
        path = populated.transfer.export_patients(tmp_path / "out", actor=ACTOR)

        assert path.suffix == ".csv"
        assert path.exists()

    def test_deleted_patients_are_excluded_by_default(
        self, populated: Container, tmp_path: Path
    ) -> None:
        victim = populated.patients.search("Smith")[0]
        populated.patients.delete(victim.patient_number, actor=ACTOR)

        path = populated.transfer.export_patients(tmp_path / "out.csv", actor=ACTOR)
        assert len(path.read_text(encoding="utf-8").splitlines()) == 2

        path = populated.transfer.export_patients(
            tmp_path / "all.csv", actor=ACTOR, include_deleted=True
        )
        assert len(path.read_text(encoding="utf-8").splitlines()) == 3

    def test_an_unsupported_format_is_refused(
        self, populated: Container, tmp_path: Path
    ) -> None:
        with pytest.raises(ExportError, match="Unsupported export format"):
            populated.transfer.export_patients(tmp_path / "out.pdf", actor=ACTOR, fmt="pdf")

    def test_the_export_directory_is_created(
        self, populated: Container, tmp_path: Path
    ) -> None:
        path = populated.transfer.export_patients(
            tmp_path / "nested" / "deeper" / "out.csv", actor=ACTOR
        )

        assert path.exists()


class TestJsonExport:
    def test_writes_a_document_with_metadata(
        self, populated: Container, tmp_path: Path
    ) -> None:
        path = populated.transfer.export_patients(
            tmp_path / "out.json", actor=ACTOR, fmt="json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert payload["application"] == "medflow"
        assert payload["patient_count"] == 2
        assert len(payload["patients"]) == 2
        assert payload["patients"][0]["patient_number"] == "MF-000001"


# ---------- import ----------


class TestImportPreview:
    def test_preview_writes_nothing(self, container: Container, tmp_path: Path) -> None:
        source = tmp_path / "in.csv"
        source.write_text(
            "first_name,last_name,blood_pressure\n"
            "Grace,Wanjiru,118/76\n",
            encoding="utf-8",
        )

        preview = container.transfer.preview_import(source)

        assert preview.total_rows == 1
        assert preview.can_import
        # Nothing has been created by looking.
        assert container.patients.count(include_deleted=True) == 0

    def test_invalid_rows_are_collected_not_raised(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text(
            "first_name,email,heart_rate\n"
            "Good,good@example.com,72\n"
            ",bad@example.com,72\n"
            "Bad,,not-a-number\n",
            encoding="utf-8",
        )

        preview = container.transfer.preview_import(source)

        assert preview.total_rows == 3
        assert len(preview.valid_rows) == 1
        assert len(preview.invalid_rows) == 2
        assert "First name is required." in preview.invalid_rows[0].error_summary

    def test_the_summary_explains_the_outcome(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text("first_name\nGood\n\n", encoding="utf-8")

        preview = container.transfer.preview_import(source)

        assert "1 of 1 rows ready to import" in preview.summary

    def test_an_empty_file_reports_no_rows(self, container: Container, tmp_path: Path) -> None:
        source = tmp_path / "in.csv"
        source.write_text("first_name,last_name\n", encoding="utf-8")

        preview = container.transfer.preview_import(source)

        assert preview.total_rows == 0
        assert not preview.can_import
        assert preview.summary == "No rows found in that file."

    def test_a_missing_file_is_reported(self, container: Container, tmp_path: Path) -> None:
        with pytest.raises(DataImportError, match="No file found"):
            container.transfer.preview_import(tmp_path / "absent.csv")

    def test_malformed_json_is_reported(self, container: Container, tmp_path: Path) -> None:
        source = tmp_path / "in.json"
        source.write_text("{not json", encoding="utf-8")

        with pytest.raises(DataImportError, match="could not be read as JSON"):
            container.transfer.preview_import(source)

    def test_json_without_a_patient_list_is_reported(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.json"
        source.write_text('{"patients": "nope"}', encoding="utf-8")

        with pytest.raises(DataImportError, match="does not contain a list"):
            container.transfer.preview_import(source)


class TestImport:
    def test_creates_the_valid_rows(self, container: Container, tmp_path: Path) -> None:
        source = tmp_path / "in.csv"
        source.write_text(
            "first_name,last_name,email\n"
            "Grace,Wanjiru,grace@example.com\n"
            ",Ndeda,bad@example.com\n",
            encoding="utf-8",
        )

        result = container.transfer.import_patients(source, actor=ACTOR)

        assert result.created == 1
        assert result.skipped == 1
        assert container.patients.search("Wanjiru")

    def test_patient_numbers_are_allocated_locally(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text(
            "patient_number,first_name,last_name\n"
            "OTHER-000042,Grace,Wanjiru\n",
            encoding="utf-8",
        )

        container.transfer.import_patients(source, actor=ACTOR)

        imported = container.patients.search("Wanjiru")[0]
        # A number from another system is a reference, not an identity here.
        assert imported.patient_number == "MF-000001"

    def test_the_source_identifier_is_preserved_in_the_timeline(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text(
            "patient_number,first_name,last_name\n"
            "OTHER-000042,Grace,Wanjiru\n",
            encoding="utf-8",
        )

        container.transfer.import_patients(source, actor=ACTOR)
        imported = container.patients.search("Wanjiru")[0]

        descriptions = [
            event.description for event in container.patients.timeline(imported.patient_number)
        ]
        assert any("OTHER-000042" in text for text in descriptions)

    def test_the_import_is_recorded_in_the_audit_trail(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text("first_name,last_name\nGrace,Wanjiru\n", encoding="utf-8")

        container.transfer.import_patients(source, actor=ACTOR)

        actions = [entry.action for entry in container.audit.recent()]
        assert AuditAction.IMPORT.value in actions
        assert AuditAction.CREATE.value in actions
        assert actions[0] == AuditAction.IMPORT.value

    def test_every_valid_row_in_the_file_is_created(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text(
            "first_name,last_name\nGrace,Wanjiru\nBetter,Too\n", encoding="utf-8"
        )

        result = container.transfer.import_patients(source, actor=ACTOR)

        assert result.created == 2
        assert result.failures == []

    def test_an_empty_file_is_a_no_op(self, container: Container, tmp_path: Path) -> None:
        source = tmp_path / "in.csv"
        source.write_text("first_name,last_name\n", encoding="utf-8")

        result = container.transfer.import_patients(source, actor=ACTOR)

        assert result.created == 0
        assert container.patients.count(include_deleted=True) == 0

    def test_a_preview_can_be_reused_so_parsing_happens_once(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text("first_name,last_name\nGrace,Wanjiru\n", encoding="utf-8")
        preview = container.transfer.preview_import(source)

        result = container.transfer.import_patients(source, actor=ACTOR, preview=preview)

        assert result.created == 1


class TestImportShapes:
    """The file shapes a real import actually arrives in."""

    def test_a_single_name_column_is_split(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text("name\nMary Jane Watson\n", encoding="utf-8")

        container.transfer.import_patients(source, actor=ACTOR)

        imported = container.patients.search("Watson")[0]
        assert (imported.first_name, imported.last_name) == ("Mary Jane", "Watson")

    def test_a_single_word_name_is_kept_whole(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text("name\nCher\n", encoding="utf-8")

        container.transfer.import_patients(source, actor=ACTOR)

        imported = container.patients.search("Cher")[0]
        assert (imported.first_name, imported.last_name) == ("Cher", "")

    def test_legacy_column_names_are_understood(
        self, container: Container, tmp_path: Path
    ) -> None:
        # A file exported from the pre-refactor application, straight in.
        source = tmp_path / "legacy.csv"
        source.write_text(
            "name,age,bp,hr,history,diag\n"
            "John Doe,45,120/80,72,Hypertension,Hypertension\n",
            encoding="utf-8",
        )

        container.transfer.import_patients(source, actor=ACTOR)

        imported = container.patients.search("Doe")[0]
        assert imported.record.blood_pressure == "120/80"
        assert imported.record.heart_rate == "72"
        assert imported.diagnoses[0].diagnosis == "Hypertension"

    def test_a_bare_json_array_is_accepted(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.json"
        source.write_text(
            json.dumps([{"first_name": "Grace", "last_name": "Wanjiru"}]),
            encoding="utf-8",
        )

        result = container.transfer.import_patients(source, actor=ACTOR)

        assert result.created == 1

    def test_unknown_columns_are_ignored(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text(
            "first_name,last_name,insurance_provider\nGrace,Wanjiru,NHIF\n",
            encoding="utf-8",
        )

        result = container.transfer.import_patients(source, actor=ACTOR)

        assert result.created == 1


# ---------- round trip ----------


class TestRoundTrip:
    def test_export_then_import_into_an_empty_database(
        self, populated: Container, tmp_path: Path
    ) -> None:
        path = populated.transfer.export_patients(tmp_path / "snapshot.csv", actor=ACTOR)
        original = {
            patient.patient_number: patient for patient in populated.patients.list_all()
        }

        # A fresh installation, with its own database and counter.
        from app.config.settings import AppSettings
        from app.container import Container as OtherContainer

        target = OtherContainer.build(AppSettings.default(base_directory=tmp_path / "second"))
        from app.repositories.sqlite.migrations import MigrationRunner

        MigrationRunner(target.database, patient_ids=target.settings.patient_ids).migrate()

        try:
            result = target.transfer.import_patients(path, actor=ACTOR)

            assert result.created == 2
            for patient in target.patients.list_all():
                source = original[patient.patient_number]
                assert patient.first_name == source.first_name
                assert patient.last_name == source.last_name
                assert patient.record.blood_pressure == source.record.blood_pressure
                assert patient.record.medical_history == source.record.medical_history
        finally:
            target.close()

    def test_a_round_trip_through_json_preserves_clinical_values(
        self, populated: Container, tmp_path: Path
    ) -> None:
        path = populated.transfer.export_patients(
            tmp_path / "snapshot.json", actor=ACTOR, fmt="json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))

        record = next(
            item for item in payload["patients"] if item["first_name"] == "Victor"
        )
        assert record["blood_pressure"] == "118/75"
        assert record["heart_rate"] == "90"
        assert record["notes"] == "Pre-op fasting from midnight."


# ---------- backups ----------


class TestBackups:
    def test_a_backup_is_written_and_listed(
        self, populated: Container, tmp_path: Path
    ) -> None:
        info = populated.backups.create_backup(actor=ACTOR)

        assert info.path.exists()
        assert info.size_bytes > 0
        assert info.name.endswith(".db")
        assert [backup.name for backup in populated.backups.list_backups()] == [info.name]

    def test_a_backup_records_an_audit_entry(
        self, populated: Container
    ) -> None:
        populated.backups.create_backup(actor=ACTOR)

        assert populated.audit.recent()[0].action == AuditAction.BACKUP.value

    def test_backups_do_not_collide_within_the_same_second(
        self, populated: Container
    ) -> None:
        first = populated.backups.create_backup(actor=ACTOR, label="manual")
        second = populated.backups.create_backup(actor=ACTOR, label="manual")

        assert first.path != second.path
        assert len(populated.backups.list_backups()) == 2

    def test_a_label_is_made_safe_for_a_filename(self, populated: Container) -> None:
        info = populated.backups.create_backup(actor=ACTOR, label="before / after: review")

        assert "/" not in info.name
        assert ":" not in info.name

    def test_listing_is_empty_before_any_backup(self, container: Container) -> None:
        assert container.backups.list_backups() == []

    def test_the_backup_can_be_reopened_as_a_database(
        self, populated: Container
    ) -> None:
        import sqlite3

        info = populated.backups.create_backup(actor=ACTOR)

        # The snapshot is a valid database, taken while the application was
        # running, which copying the file would not guarantee under WAL.
        connection = sqlite3.connect(str(info.path))
        try:
            total = connection.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        finally:
            connection.close()

        assert total == 2

    def test_restoring_a_backup_keeps_a_safety_copy(
        self, populated: Container
    ) -> None:
        info = populated.backups.create_backup(actor=ACTOR)

        safety = populated.backups.restore_backup(info.path, actor=ACTOR)

        assert safety.path.exists()
        assert "pre-restore" in safety.name
        assert populated.audit.recent()[0].action == AuditAction.RESTORE_BACKUP.value

    def test_restoring_a_missing_backup_is_reported(
        self, populated: Container, tmp_path: Path
    ) -> None:
        from app.core.exceptions import BackupError

        with pytest.raises(BackupError, match="No backup found"):
            populated.backups.restore_backup(tmp_path / "absent.db", actor=ACTOR)


# ---------- the service contract ----------


class TestTransferGuardrails:
    def test_validation_rules_apply_to_imported_rows(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text("first_name,email\nGrace,not-an-email\n", encoding="utf-8")

        # The same validator the form uses, so a file cannot smuggle in a record
        # the form would have refused.
        preview = container.transfer.preview_import(source)
        assert preview.invalid_rows[0].errors["email"]

    def test_importing_does_not_need_a_preview_first(
        self, container: Container, tmp_path: Path
    ) -> None:
        source = tmp_path / "in.csv"
        source.write_text("first_name,last_name\nGrace,Wanjiru\n", encoding="utf-8")

        # The service parses for itself when no preview is supplied, so a caller
        # cannot accidentally skip validation by forgetting to build one.
        result = container.transfer.import_patients(source, actor=ACTOR)

        assert result.created == 1

    def test_patient_service_validation_is_public(self, container: Container) -> None:
        with pytest.raises(ValidationError):
            container.patients.validate({"first_name": ""})
