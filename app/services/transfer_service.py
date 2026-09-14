"""Export and import.

The transfer format is a file, not a second database. CSV and JSON are ways of
*leaving* MedFlow — a spreadsheet for a colleague, a snapshot for an archive, a
handover to another system. They are never read at runtime to serve a patient
record, because a flat file has no transactions, no constraints and no audit trail,
and treating one as storage is how clinical data quietly diverges.

Import follows three rules:

1. **Nothing is written until a preview has been shown.** The same parsing and
   validation runs in both passes; only the write is conditional.
2. **A bad row never blocks a good one.** Failures are collected per row and
   reported, rather than aborting the whole file on the first problem.
3. **Patient numbers are allocated locally.** A number from another system is not
   an identity here — it is recorded as a source reference in the patient's
   timeline. That avoids collisions and keeps the no-reuse guarantee intact.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.config.constants import EXPORT_FORMATS
from app.core.clock import Clock
from app.core.exceptions import (
    DataImportError,
    ExportError,
    PersistenceError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.validators import clean_text
from app.domain.enums import AuditAction, EntityType, EventType
from app.services.audit_service import AuditService
from app.services.history_service import HistoryService
from app.services.patient_service import PatientService

logger = get_logger(__name__)

#: Columns written on export, in order. Kept stable so a spreadsheet opened last
#: year still lines up with one exported today.
EXPORT_COLUMNS: tuple[str, ...] = (
    "patient_number",
    "first_name",
    "last_name",
    "date_of_birth",
    "age_years",
    "sex",
    "phone",
    "email",
    "address",
    "status",
    "blood_pressure",
    "heart_rate",
    "weight",
    "height",
    "medical_history",
    "notes",
    "created_at",
    "updated_at",
)

#: Columns an imported file may use to identify the source record.
_SOURCE_NUMBER_KEYS = ("patient_number", "patient_id", "id", "source_id")


@dataclass
class ImportRow:
    """One line of an import file, with the outcome of validating it."""

    line: int
    data: dict[str, Any]
    source_identifier: str = ""
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def label(self) -> str:
        name = " ".join(
            part for part in (self.data.get("first_name"), self.data.get("last_name")) if part
        )
        return name or self.source_identifier or f"row {self.line}"

    @property
    def error_summary(self) -> str:
        return "; ".join(self.errors.values())


@dataclass
class ImportPreview:
    """What an import *would* do, produced without writing anything."""

    source: Path
    rows: list[ImportRow] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def valid_rows(self) -> list[ImportRow]:
        return [row for row in self.rows if row.is_valid]

    @property
    def invalid_rows(self) -> list[ImportRow]:
        return [row for row in self.rows if not row.is_valid]

    @property
    def can_import(self) -> bool:
        return bool(self.valid_rows)

    @property
    def summary(self) -> str:
        if not self.rows:
            return "No rows found in that file."
        parts = [f"{len(self.valid_rows)} of {self.total_rows} rows ready to import"]
        if self.invalid_rows:
            parts.append(f"{len(self.invalid_rows)} need attention")
        return ". ".join(parts) + "."


@dataclass
class ImportResult:
    """What an import actually did."""

    created: int = 0
    skipped: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"Imported {self.created} patient(s)"]
        if self.skipped:
            parts.append(f"skipped {self.skipped}")
        if self.failures:
            parts.append(f"{len(self.failures)} failed")
        return ". ".join(parts) + "."


class TransferService:
    """Exports patients to a file and imports them back."""

    def __init__(
        self,
        patients: PatientService,
        history: HistoryService,
        audit: AuditService,
        clock: Clock,
    ) -> None:
        self._patients = patients
        self._history = history
        self._audit = audit
        self._clock = clock

    # ---------- export ----------

    def export_patients(
        self,
        path: Path | str,
        *,
        actor: str,
        fmt: str = "csv",
        include_deleted: bool = False,
    ) -> Path:
        """Write every patient to ``path``, returning the file written."""
        normalised = fmt.strip().lower()
        if normalised not in EXPORT_FORMATS:
            raise ExportError(
                f"Unsupported export format {fmt!r}. "
                f"Choose one of: {', '.join(sorted(EXPORT_FORMATS))}."
            )

        destination = Path(path)
        if destination.suffix.lower() != EXPORT_FORMATS[normalised]:
            destination = destination.with_suffix(EXPORT_FORMATS[normalised])

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportError(f"Could not create the export directory: {exc}") from exc

        records = [
            patient.to_dict()
            for patient in self._patients.list_all(include_deleted=include_deleted)
        ]

        try:
            if normalised == "csv":
                _write_csv(destination, records)
            else:
                _write_json(destination, records)
        except OSError as exc:
            raise ExportError(f"Could not write the export file: {exc}") from exc

        self._audit.record(
            AuditAction.EXPORT,
            entity_type=EntityType.DATABASE,
            entity_id=destination.name,
            actor=actor,
            details={"patients": len(records), "format": normalised},
        )
        logger.info("Exported %d patients to %s", len(records), destination)

        return destination

    # ---------- import ----------

    def preview_import(self, path: Path | str) -> ImportPreview:
        """Parse and validate a file without writing anything.

        Deliberately doing the whole job and discarding it: a preview that used
        different parsing from the real import would be worse than none.
        """
        source = Path(path)
        rows = list(_read_rows(source))
        preview = ImportPreview(source=source)

        for line, raw in rows:
            normalised = _normalise_row(raw)
            source_identifier = _first_present(raw, _SOURCE_NUMBER_KEYS)

            row = ImportRow(
                line=line,
                data=normalised,
                source_identifier=source_identifier,
            )

            if not normalised.get("first_name") and not normalised.get("last_name"):
                row.errors["first_name"] = "First name is required."

            try:
                self._patients.validate(normalised, require_name=True)
            except ValidationError as exc:
                # Per-field messages from the same validator the form uses, so an
                # imported record is held to exactly the rules a typed one is.
                row.errors.update(exc.errors)

            preview.rows.append(row)

        return preview

    def import_patients(
        self,
        path: Path | str,
        *,
        actor: str,
        preview: ImportPreview | None = None,
    ) -> ImportResult:
        """Create patients from a file, skipping rows that fail validation."""
        checked = preview or self.preview_import(path)
        result = ImportResult(skipped=len(checked.invalid_rows))

        for row in checked.valid_rows:
            try:
                patient = self._patients.create(row.data, actor=actor)
            except ValidationError as exc:
                result.failures.append((row.label, exc.summary()))
                continue
            except PersistenceError as exc:
                result.failures.append((row.label, str(exc)))
                continue

            details: dict[str, Any] = {"source_file": checked.source.name}
            if row.source_identifier:
                details["source_identifier"] = row.source_identifier

            self._audit.record(
                AuditAction.IMPORT,
                entity_type=EntityType.PATIENT,
                entity_id=patient.patient_number,
                actor=actor,
                details=details,
            )

            # The identifier the record carried in its source system is preserved
            # as how the record is traced back, not as the patient's number here.
            if row.source_identifier and patient.id is not None:
                self._history.record(
                    patient.id,
                    EventType.MIGRATED,
                    f"Imported from {checked.source.name} "
                    f"(source identifier {row.source_identifier}).",
                    actor=actor,
                )

            result.created += 1

        logger.info(
            "Import from %s: %d created, %d skipped, %d failed",
            checked.source,
            result.created,
            result.skipped,
            len(result.failures),
        )

        return result


# ---------- reading and writing ----------


def _write_csv(destination: Path, records: list[Mapping[str, Any]]) -> None:
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPORT_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _write_json(destination: Path, records: list[Mapping[str, Any]]) -> None:
    payload = {
        "application": "medflow",
        "patient_count": len(records),
        "patients": records,
    }
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def _read_rows(source: Path) -> Iterable[tuple[int, Mapping[str, Any]]]:
    """Yield ``(line_number, row)`` from a CSV or JSON file.

    Line numbers are carried through so a reported problem points at something the
    user can actually find in their file.
    """
    if not source.is_file():
        raise DataImportError(f"No file found at {source}")

    if source.suffix.lower() == ".json":
        yield from _read_json(source)
    else:
        yield from _read_csv(source)


def _read_csv(source: Path) -> Iterable[tuple[int, Mapping[str, Any]]]:
    try:
        with source.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise DataImportError("That file appears to be empty.")
            for offset, row in enumerate(reader, start=2):  # line 1 is the header
                yield offset, {key: value for key, value in row.items() if key}
    except UnicodeDecodeError as exc:
        raise DataImportError(
            "That file is not readable as text. Export as CSV or JSON and try again."
        ) from exc
    except csv.Error as exc:
        raise DataImportError(f"That file could not be read as CSV: {exc}") from exc


def _read_json(source: Path) -> Iterable[tuple[int, Mapping[str, Any]]]:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataImportError(f"That file could not be read as JSON: {exc}") from exc

    # Accept both the wrapper written by export and a bare list, so a file
    # produced by another tool does not need editing first.
    if isinstance(payload, Mapping):
        records = payload.get("patients", [])
    else:
        records = payload

    if not isinstance(records, list):
        raise DataImportError("That JSON file does not contain a list of patients.")

    for offset, record in enumerate(records, start=1):
        if isinstance(record, Mapping):
            yield offset, record


def _normalise_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Map an input row onto the fields the patient form understands.

    Handles the two shapes a real file arrives in: MedFlow's own columns, and a
    single ``name`` column. The name is split on the last space — the same rule the
    legacy migration uses — so "Mary Jane Watson" becomes "Mary Jane" / "Watson"
    rather than losing the surname.
    """
    data: dict[str, Any] = {
        key: value for key, value in raw.items() if key in EXPORT_COLUMNS and key not in {"patient_number"}
    }

    if not data.get("first_name") and not data.get("last_name"):
        full_name = clean_text(raw.get("name") or raw.get("full_name") or "")
        if full_name:
            head, _, tail = full_name.rpartition(" ")
            if head:
                data["first_name"], data["last_name"] = head, tail
            else:
                data["first_name"] = full_name

    # Legacy field names, so a file exported from the pre-refactor application
    # imports without being edited by hand.
    aliases = {"bp": "blood_pressure", "hr": "heart_rate", "diag": "diagnosis", "history": "medical_history"}
    for old, new in aliases.items():
        if not data.get(new) and raw.get(old):
            data[new] = raw[old]

    return data


def _first_present(row: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return str(value).strip()
    return ""
