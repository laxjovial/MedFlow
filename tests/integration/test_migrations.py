"""Migration behaviour, including conversion of the pre-refactor database.

The legacy tests build a genuine old-format database rather than mocking one, so
the conversion is proven against the real thing: a file with the old ``patients``
table, written by the old schema, at version 0. Whether a ``medflow.db`` happens to
exist on the machine running the tests is irrelevant.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config.settings import PatientIdSettings
from app.core.clock import FixedClock
from app.domain.enums import AuditAction, EventType
from app.repositories.sqlite.connection import Database
from app.repositories.sqlite.legacy import (
    LEGACY_TABLE,
    extract_ordinal,
    has_legacy_schema,
    split_name,
)
from app.repositories.sqlite.migrations import MigrationRunner
from app.repositories.sqlite.schema import SCHEMA_VERSION

LEGACY_DDL = """
CREATE TABLE patients (
    patient_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    age        TEXT,
    bp         TEXT,
    hr         TEXT,
    history    TEXT,
    diag       TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

#: Rows in the shape the previous version wrote them, including its ``--``
#: placeholders for values that were never recorded.
LEGACY_ROWS = (
    ("Patient 001", "John Doe", "45", "120/80", "72", "Hypertension since 2019", "Hypertension"),
    ("Patient 002", "Mary Jane Watson", "32", "--", "--", "--", "--"),
    ("Patient 007", "Victor K.", "58", "142/90", "82", "Diabetes", "Type 2 Diabetes"),
)


def _write_legacy_database(path: Path, rows=LEGACY_ROWS) -> None:
    """Create a database in the pre-refactor format, exactly as v1 left it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(LEGACY_DDL)
        connection.executemany(
            """
            INSERT INTO patients (patient_id, name, age, bp, hr, history, diag)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def legacy_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "medflow.db"
    _write_legacy_database(path)
    return path


@pytest.fixture
def legacy_runner(legacy_path: Path, fixed_clock: FixedClock) -> MigrationRunner:
    return MigrationRunner(
        Database(legacy_path),
        clock=fixed_clock,
        patient_ids=PatientIdSettings(),
        actor="migration-test",
    )


# ---------- fresh databases ----------


class TestFreshDatabase:
    def test_migration_records_the_schema_version(self, database: Database) -> None:
        runner = MigrationRunner(database)

        assert runner.current_version() == SCHEMA_VERSION
        assert runner.is_up_to_date()
        assert runner.pending() == []

    def test_migration_is_idempotent(self, app_settings) -> None:
        handle = Database(app_settings.database_path)
        runner = MigrationRunner(handle)

        first = runner.migrate()
        second = runner.migrate()

        assert first == [SCHEMA_VERSION]
        # Nothing to do the second time, and no attempt to re-run the DDL.
        assert second == []
        assert runner.current_version() == SCHEMA_VERSION

    def test_expected_tables_exist(self, database: Database) -> None:
        with database.connection() as connection:
            names = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        assert {
            "patients",
            "patient_records",
            "diagnoses",
            "patient_events",
            "audit_log",
            "sequences",
            "schema_migrations",
        } <= names

    def test_applied_history_records_the_migration(self, database: Database) -> None:
        history = MigrationRunner(database).applied_history()

        assert [entry["version"] for entry in history] == [SCHEMA_VERSION]

    def test_a_newer_database_is_refused(self, app_settings) -> None:
        handle = Database(app_settings.database_path)
        with handle.transaction() as connection:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")

        from app.core.exceptions import MigrationError

        with pytest.raises(MigrationError, match="newer"):
            MigrationRunner(handle).migrate()


# ---------- detection ----------


class TestLegacyDetection:
    def test_legacy_database_is_recognised(self, legacy_path: Path) -> None:
        with Database(legacy_path).connection() as connection:
            assert has_legacy_schema(connection)

    def test_migrated_database_is_not_mistaken_for_legacy(self, database: Database) -> None:
        with database.connection() as connection:
            # The table is called "patients" in both schemas, which is exactly why
            # detection checks the columns and not just the name.
            assert not has_legacy_schema(connection)


# ---------- the conversion ----------


class TestLegacyConversion:
    def test_every_row_is_converted(self, legacy_runner: MigrationRunner) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            total = connection.execute("SELECT COUNT(*) AS n FROM patients").fetchone()["n"]

        assert total == len(LEGACY_ROWS)

    def test_patient_numbers_follow_the_configured_format(
        self, legacy_runner: MigrationRunner
    ) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            numbers = [
                row["patient_number"]
                for row in connection.execute(
                    "SELECT patient_number FROM patients ORDER BY id"
                ).fetchall()
            ]

        # The ordinal from "Patient 007" is preserved, not renumbered to 3.
        assert numbers == ["MF-000001", "MF-000002", "MF-000007"]

    def test_names_are_split_on_the_final_space(
        self, legacy_runner: MigrationRunner
    ) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            row = connection.execute(
                "SELECT first_name, last_name FROM patients WHERE patient_number = ?",
                ("MF-000002",),
            ).fetchone()

        assert (row["first_name"], row["last_name"]) == ("Mary Jane", "Watson")

    def test_clinical_values_move_to_the_record(self, legacy_runner: MigrationRunner) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            row = connection.execute(
                """
                SELECT r.blood_pressure, r.heart_rate, r.medical_history, p.age_years
                FROM patient_records r
                JOIN patients p ON p.id = r.patient_id
                WHERE p.patient_number = ?
                """,
                ("MF-000001",),
            ).fetchone()

        assert row["blood_pressure"] == "120/80"
        assert row["heart_rate"] == "72"
        assert row["medical_history"] == "Hypertension since 2019"
        # Age is carried across as text, because that is how it was recorded and
        # no date of birth was ever captured to convert it into.
        assert row["age_years"] == "45"

    def test_placeholders_become_empty_not_dashes(
        self, legacy_runner: MigrationRunner
    ) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            row = connection.execute(
                """
                SELECT r.blood_pressure, r.heart_rate, r.medical_history
                FROM patient_records r
                JOIN patients p ON p.id = r.patient_id
                WHERE p.patient_number = ?
                """,
                ("MF-000002",),
            ).fetchone()

        assert (row["blood_pressure"], row["heart_rate"], row["medical_history"]) == ("", "", "")

    def test_diagnoses_become_rows(self, legacy_runner: MigrationRunner) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT d.diagnosis, d.status
                FROM diagnoses d
                JOIN patients p ON p.id = d.patient_id
                ORDER BY d.id
                """
            ).fetchall()

        # "--" was the old placeholder for "no diagnosis", so it does not become one.
        assert [(row["diagnosis"], row["status"]) for row in rows] == [
            ("Hypertension", "active"),
            ("Type 2 Diabetes", "active"),
        ]

    def test_conversion_is_recorded_in_history_and_audit(
        self, legacy_runner: MigrationRunner
    ) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            events = connection.execute(
                "SELECT event_type, description FROM patient_events"
            ).fetchall()
            audits = connection.execute(
                "SELECT action, actor FROM audit_log"
            ).fetchall()

        assert len(events) == len(LEGACY_ROWS)
        assert {row["event_type"] for row in events} == {EventType.MIGRATED.value}
        assert "Patient 001" in events[0]["description"]

        assert len(audits) == len(LEGACY_ROWS)
        assert {row["action"] for row in audits} == {AuditAction.MIGRATE.value}

    def test_numbering_continues_after_the_conversion(
        self, legacy_runner: MigrationRunner
    ) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            row = connection.execute(
                "SELECT value FROM sequences WHERE name = ?", ("patient_number",)
            ).fetchone()

        # The highest migrated ordinal was 7, so the counter must be past it —
        # otherwise the next new patient would be handed MF-000007 again.
        assert row["value"] == 7

    def test_the_legacy_table_is_removed(self, legacy_runner: MigrationRunner) -> None:
        legacy_runner.migrate()

        with legacy_runner.database.connection() as connection:
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE ?",
                ("%legacy%",),
            ).fetchall()

        assert remaining == []
        with legacy_runner.database.connection() as connection:
            assert not has_legacy_schema(connection)

    def test_an_empty_legacy_table_migrates_cleanly(self, tmp_path: Path) -> None:
        path = tmp_path / "data" / "medflow.db"
        _write_legacy_database(path, rows=())

        runner = MigrationRunner(Database(path), patient_ids=PatientIdSettings())
        runner.migrate()

        assert runner.current_version() == SCHEMA_VERSION
        with runner.database.connection() as connection:
            total = connection.execute("SELECT COUNT(*) AS n FROM patients").fetchone()["n"]
        assert total == 0


# ---------- conversion rules ----------


class TestConversionRules:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("John Doe", ("John", "Doe")),
            ("Mary Jane Watson", ("Mary Jane", "Watson")),
            ("Cher", ("Cher", "")),
            ("", ("", "")),
            ("   ", ("", "")),
            ("  Victor   K.  ", ("Victor", "K.")),
            ("--", ("", "")),
        ],
    )
    def test_split_name(self, raw: str, expected: tuple[str, str]) -> None:
        assert split_name(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Patient 001", 1),
            ("Patient 007", 7),
            ("PAT-1234", 1234),
            ("42", 42),
            ("", None),
            ("Patient", None),
        ],
    )
    def test_extract_ordinal(self, raw: str, expected: int | None) -> None:
        assert extract_ordinal(raw) == expected

    def test_legacy_table_name_is_stable(self) -> None:
        # The detection logic depends on the old table being called "patients";
        # asserting it here means a rename cannot pass unnoticed.
        assert LEGACY_TABLE == "patients"
