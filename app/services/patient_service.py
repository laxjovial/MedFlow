"""The patient service.

This is where the application's rules live: validation, change tracking, timeline
entries and audit records. It sits between the views and the repository, and it is
the only layer that writes to both at once.

The placement is deliberate. If validation lived in the dialog and audit logging
lived in the repository, a second repository implementation could forget them. Here
they are unavoidable: ``create`` cannot insert without also recording who did it.

The service never learns which repository it holds. That is the property that lets
a networked ``ApiPatientRepository`` replace the SQLite one without a single change
above this line.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.config.settings import ValidationSettings
from app.core.clock import Clock
from app.core.exceptions import NotFoundError, ValidationError
from app.core.validators import PatientValidator, label_for
from app.domain.audit import AuditEntry
from app.domain.diagnosis import Diagnosis
from app.domain.enums import (
    DEFAULT_SORT,
    TRACKED_PATIENT_FIELDS,
    AuditAction,
    DiagnosisStatus,
    EntityType,
    EventType,
    PatientStatus,
)
from app.domain.events import PatientEvent
from app.domain.patient import Patient, PatientRecord
from app.domain.summary import DiagnosisCount, RepositoryStatistics
from app.repositories.patient_repository import PatientRepository
from app.services.audit_service import AuditService
from app.services.history_service import HistoryService

#: Patient fields that live on the clinical record rather than the demographic row.
#: Used to decide where a cleaned value is written.
_RECORD_FIELDS = frozenset(
    {"blood_pressure", "heart_rate", "weight", "height", "medical_history", "notes"}
)

#: Demographics the form may submit.
_DEMOGRAPHIC_FIELDS = frozenset(
    {"first_name", "last_name", "date_of_birth", "age_years", "sex", "phone", "email", "address"}
)


class PatientService:
    """Create, read, update and delete patients, with validation and tracking."""

    def __init__(
        self,
        repository: PatientRepository,
        history: HistoryService,
        audit: AuditService,
        validation: ValidationSettings,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._history = history
        self._audit = audit
        self._validation = validation
        self._clock = clock
        self._validator = PatientValidator(validation)

    # ---------- reads ----------

    def get(self, patient_number: str, *, include_deleted: bool = False) -> Patient | None:
        """Load a patient, or ``None`` if there is no such record."""
        return self._repository.fetch(patient_number, include_deleted=include_deleted)

    def require(self, patient_number: str, *, include_deleted: bool = False) -> Patient:
        """Load a patient, raising if they do not exist.

        Used by every operation that needs the patient to be there before it can
        proceed, so the "is it missing?" check is written once.
        """
        patient = self.get(patient_number, include_deleted=include_deleted)
        if patient is None:
            raise NotFoundError(f"No patient found with number {patient_number}.")
        return patient

    def search(
        self,
        query: str = "",
        *,
        sort_by: str = DEFAULT_SORT,
        descending: bool = True,
        include_deleted: bool = False,
        limit: int | None = None,
    ) -> list[Patient]:
        return self._repository.search(
            query,
            sort_by=sort_by,
            descending=descending,
            include_deleted=include_deleted,
            limit=limit,
        )

    def list_all(self, *, include_deleted: bool = False) -> list[Patient]:
        return self._repository.list_all(include_deleted=include_deleted)

    def count(self, *, include_deleted: bool = False) -> int:
        return self._repository.count(include_deleted=include_deleted)

    def statistics(self) -> RepositoryStatistics:
        """Dashboard counts, with "today" resolved once, here."""
        return self._repository.statistics(today=self._clock.today())

    def diagnosis_distribution(self, limit: int = 5) -> list[DiagnosisCount]:
        return self._repository.diagnosis_distribution(limit=limit)

    def timeline(self, patient_number: str, limit: int | None = None) -> list[PatientEvent]:
        """What happened to this patient's record, newest first."""
        patient = self.require(patient_number, include_deleted=True)
        assert patient.id is not None
        return self._history.for_patient(patient.id, limit=limit)

    def audit_trail(self, patient_number: str, limit: int | None = None) -> list[AuditEntry]:
        """Who touched this patient's record, newest first."""
        return self._audit.for_patient(patient_number, limit=limit)

    # ---------- writes ----------

    def create(self, form_data: Mapping[str, Any], *, actor: str) -> Patient:
        """Validate and store a new patient.

        Raises :class:`ValidationError` carrying per-field messages if anything is
        wrong; nothing is written in that case.
        """
        cleaned = self._validate(form_data, require_name=True)

        timestamp = self._clock.timestamp()
        patient = Patient(
            first_name=cleaned["first_name"],
            last_name=cleaned["last_name"],
            date_of_birth=cleaned["date_of_birth"],
            age_years=cleaned["age_years"],
            sex=cleaned["sex"],
            phone=cleaned["phone"],
            email=cleaned["email"],
            address=cleaned["address"],
            status=PatientStatus.ACTIVE.value,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=actor,
            updated_by=actor,
            record=PatientRecord(
                blood_pressure=cleaned["blood_pressure"],
                heart_rate=cleaned["heart_rate"],
                weight=cleaned["weight"],
                height=cleaned["height"],
                medical_history=cleaned["medical_history"],
                notes=cleaned["notes"],
                created_at=timestamp,
                updated_at=timestamp,
            ),
        )

        self._repository.insert(patient)
        assert patient.id is not None

        # An opening diagnosis is common enough at registration to accept it in
        # the same submission, but it is stored as a diagnosis row — not as a
        # field that a later edit would silently overwrite.
        opening_diagnosis = cleaned.get("diagnosis", "")
        if opening_diagnosis:
            self._repository.add_diagnosis(
                patient.id,
                Diagnosis(
                    diagnosis=opening_diagnosis,
                    diagnosed_at=timestamp,
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
            )

        self._history.record(
            patient.id,
            EventType.CREATED,
            f"Patient {patient.patient_number} registered.",
            actor=actor,
        )
        self._audit.record(
            AuditAction.CREATE,
            entity_type=EntityType.PATIENT,
            entity_id=patient.patient_number,
            actor=actor,
            details={"name": patient.full_name},
        )

        return self.require(patient.patient_number)

    def update(
        self, patient_number: str, form_data: Mapping[str, Any], *, actor: str
    ) -> Patient:
        """Validate and apply changes to an existing patient.

        Only fields present in ``form_data`` are considered, so a partial update
        cannot blank out values it never mentioned. When nothing actually differs
        the record is left untouched — no write, no version bump, no timeline entry
        — which keeps the history free of noise from a dialog opened and saved
        without changes.
        """
        patient = self.require(patient_number)

        present = {key for key in form_data if key in _DEMOGRAPHIC_FIELDS | _RECORD_FIELDS}
        cleaned = self._validate(
            {key: value for key, value in form_data.items() if key in present},
            require_name="first_name" in present,
        )

        changes = self._diff(patient, cleaned, present)
        if not changes:
            return patient

        timestamp = self._clock.timestamp()
        for field_name, (_before, after) in changes.items():
            if field_name in _RECORD_FIELDS:
                setattr(patient.record, field_name, after)
            else:
                setattr(patient, field_name, after)

        patient.updated_at = timestamp
        patient.updated_by = actor
        patient.record.updated_at = timestamp

        self._repository.save(patient)

        self._history.record(
            patient.id,
            EventType.UPDATED,
            _describe_changes(changes),
            actor=actor,
        )
        self._audit.record(
            AuditAction.UPDATE,
            entity_type=EntityType.PATIENT,
            entity_id=patient.patient_number,
            actor=actor,
            details={"changed": sorted(changes)},
        )

        return self.require(patient_number)

    def delete(self, patient_number: str, *, actor: str) -> bool:
        """Soft-delete a patient, preserving the record and its history.

        The row is never removed: a clinical record that vanishes without trace is
        worse than one marked as no longer in use, and the patient number must never
        be handed to someone else.
        """
        patient = self.require(patient_number, include_deleted=True)
        if patient.is_deleted:
            return False
        timestamp = self._clock.timestamp()

        if not self._repository.mark_deleted(
            patient.patient_number, deleted_at=timestamp, actor=actor
        ):
            return False

        self._history.record(
            patient.id,
            EventType.DELETED,
            f"Patient {patient.patient_number} marked as deleted.",
            actor=actor,
        )
        self._audit.record(
            AuditAction.DELETE,
            entity_type=EntityType.PATIENT,
            entity_id=patient.patient_number,
            actor=actor,
            details={"name": patient.full_name},
        )
        return True

    def restore(self, patient_number: str, *, actor: str) -> bool:
        """Undo a soft delete."""
        patient = self.require(patient_number, include_deleted=True)

        if not self._repository.restore(patient.patient_number):
            return False

        self._history.record(
            patient.id,
            EventType.RESTORED,
            f"Patient {patient.patient_number} restored.",
            actor=actor,
        )
        self._audit.record(
            AuditAction.RESTORE,
            entity_type=EntityType.PATIENT,
            entity_id=patient.patient_number,
            actor=actor,
            details={"name": patient.full_name},
        )
        return True

    # ---------- diagnoses ----------

    def add_diagnosis(self, patient_number: str, text: str, *, actor: str) -> Diagnosis:
        """Record a new diagnosis against a patient."""
        cleaned = self._validate({"diagnosis": text}, require_name=False)["diagnosis"]
        if not cleaned:
            raise ValidationError({"diagnosis": "Diagnosis is required."})

        patient = self.require(patient_number)
        assert patient.id is not None
        timestamp = self._clock.timestamp()

        diagnosis = self._repository.add_diagnosis(
            patient.id,
            Diagnosis(
                diagnosis=cleaned,
                diagnosed_at=timestamp,
                created_at=timestamp,
                updated_at=timestamp,
            ),
        )

        self._history.record(
            patient.id,
            EventType.DIAGNOSIS_ADDED,
            f"Diagnosis recorded: {cleaned}",
            actor=actor,
        )
        self._audit.record(
            AuditAction.UPDATE,
            entity_type=EntityType.DIAGNOSIS,
            entity_id=patient.patient_number,
            actor=actor,
            details={"added": cleaned},
        )
        return diagnosis

    def resolve_diagnosis(
        self,
        patient_number: str,
        diagnosis_id: int,
        *,
        actor: str,
        status: DiagnosisStatus | str = DiagnosisStatus.RESOLVED,
    ) -> Diagnosis:
        """Move a diagnosis to resolved (or back to active).

        The row is updated rather than removed, so the fact that the patient was
        once treated for it stays visible.
        """
        patient = self.require(patient_number, include_deleted=True)
        target = next(
            (item for item in patient.diagnoses if item.id == diagnosis_id), None
        )
        if target is None:
            raise NotFoundError("That diagnosis is no longer on this patient's record.")

        target.status = str(status)
        target.updated_at = self._clock.timestamp()
        self._repository.update_diagnosis(target)

        event = (
            EventType.DIAGNOSIS_RESOLVED
            if target.status == DiagnosisStatus.RESOLVED.value
            else EventType.DIAGNOSIS_UPDATED
        )
        self._history.record(
            patient.id,
            event,
            f"Diagnosis {target.status_label.lower()}: {target.diagnosis}",
            actor=actor,
        )
        self._audit.record(
            AuditAction.UPDATE,
            entity_type=EntityType.DIAGNOSIS,
            entity_id=patient.patient_number,
            actor=actor,
            details={"diagnosis": target.diagnosis, "status": target.status},
        )
        return target

    # ---------- validation ----------

    def validate(
        self, form_data: Mapping[str, Any], *, require_name: bool = True
    ) -> dict[str, str]:
        """Check a submission and return the cleaned values, writing nothing.

        Public so that import previews and any future form can ask "would this be
        accepted?" without creating a record to find out.
        """
        return self._validate(form_data, require_name=require_name)

    def _validate(
        self, data: Mapping[str, Any], *, require_name: bool
    ) -> dict[str, str]:
        return self._validator.validate(
            data, require_name=require_name, today=self._clock.today()
        )

    @staticmethod
    def _diff(
        patient: Patient, cleaned: Mapping[str, str], present: set[str]
    ) -> dict[str, tuple[str, str]]:
        """Compare a cleaned submission against the stored record.

        Returns only the fields that genuinely changed, as ``field -> (before,
        after)``, which is what the timeline entry is built from.
        """
        current = patient.to_form_data()
        changes: dict[str, tuple[str, str]] = {}

        for field_name in present:
            if field_name not in current and field_name not in _RECORD_FIELDS:
                continue
            before = current.get(field_name, "")
            after = cleaned.get(field_name, "")
            if before != after:
                changes[field_name] = (before, after)
                # Keep the working copy in step so a field compared twice in the
                # same pass cannot report a stale "before" value.
                current[field_name] = after

        return changes


def _describe_changes(changes: Mapping[str, tuple[str, str]]) -> str:
    """Summarise an edit for the patient timeline.

    Names the fields rather than dumping values: a timeline is read at a glance,
    and repeating medical history verbatim in a log line helps nobody.
    """
    labels = [label_for(field_name) for field_name in TRACKED_PATIENT_FIELDS if field_name in changes]
    unlabelled = [name for name in changes if name not in TRACKED_PATIENT_FIELDS]
    labels.extend(label_for(name) for name in unlabelled)

    if not labels:
        return "Record updated."
    if len(labels) == 1:
        return f"Updated {labels[0].lower()}."
    return f"Updated {len(labels)} fields: {', '.join(labels)}."
