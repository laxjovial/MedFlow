"""Patient service: registration, editing, search, deletion, chart access.

This is the layer the UI binds to. Every mutation is validated, permission
checked, versioned, audited, and reflected in the patient's clinical
timeline. The UI never writes to a repository directly.
"""

from __future__ import annotations

from datetime import date

from app.errors import DuplicatePatientError, NotFoundError
from app.models import (
    AuditEvent,
    Patient,
    PatientHistoryEvent,
    PatientSummary,
)
from app.models.audit import (
    EVENT_CREATED,
    EVENT_DELETED,
    EVENT_UPDATED,
    EVENT_VIEWED,
)
from app.validation import PatientValidator
from app.utils.dates import humanize, utcnow


class PatientService:
    """All patient workflows in one permission-checked place."""

    def __init__(self, repos, validator: PatientValidator | None = None,
                 actor: str = "system", device_id: str = "workstation-01"):
        self.repos = repos
        self.validator = validator or PatientValidator()
        self.actor = actor
        self.device_id = device_id

    # ------------------------------------------------------------------ #
    # helpers

    def _audit(self, action: str, entity_type: str, entity_id, details: str = "") -> None:
        self.repos["audit"].record(AuditEvent(
            action=action, entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details or None, actor=self.actor, device_id=self.device_id,
        ))

    def _history(self, patient_id: int, event_type: str, description: str) -> None:
        self.repos["audit"].add_history(PatientHistoryEvent(
            patient_id=patient_id, event_type=event_type, description=description,
            actor=self.actor,
        ))

    # ------------------------------------------------------------------ #
    # queries

    def search(self, query: str = "", limit: int = 200) -> list[PatientSummary]:
        return self.repos["patients"].search(query, limit=limit)

    def get(self, patient_id: int) -> Patient:
        patient = self.repos["patients"].get(patient_id)
        if not patient:
            raise NotFoundError(f"Patient #{patient_id} does not exist.")
        self._audit(EVENT_VIEWED, "patient", patient.patient_number)
        return patient

    def get_by_number(self, patient_number: str) -> Patient:
        patient = self.repos["patients"].get_by_number(patient_number)
        if not patient:
            raise NotFoundError(f"Patient {patient_number} does not exist.")
        return patient

    def count(self) -> int:
        return self.repos["patients"].count()

    def chart(self, patient_id: int) -> dict:
        """The full clinical chart for one patient, every section at once."""
        patient = self.get(patient_id)
        section_keys = ("vitals", "diagnoses", "medications", "allergies",
                        "lab_results", "notes")
        chart = {"patient": patient}
        for key in section_keys:
            chart[key] = self.repos[key].list_for_patient(patient_id)
        chart["appointments"] = self.repos["appointments"].for_patient(patient_id)
        chart["timeline"] = self.repos["audit"].history_for_patient(patient_id)
        return chart

    # ------------------------------------------------------------------ #
    # mutations

    def register(self, data: dict) -> Patient:
        """Validate and create a patient; returns the persisted model."""
        clean = self.validator.validate(data)

        if clean.get("email"):
            dup = self.repos["patients"].search(clean["email"], limit=1)
            # soft duplicate hint only; email is not a hard unique key
            self._audit("duplicate_check", "patient", None,
                        f"email {clean['email']} matched {len(dup)} record(s)")

        patient = Patient(
            patient_number="",            # assigned by the repository
            name=clean["name"],
            age=clean.get("age"),
            sex=clean.get("sex"),
            date_of_birth=clean.get("date_of_birth"),
            phone=clean.get("phone"),
            email=clean.get("email"),
            address=clean.get("address"),
            blood_pressure=clean.get("blood_pressure"),
            heart_rate=clean.get("heart_rate"),
            weight=clean.get("weight"),
            medical_history=clean.get("medical_history"),
            diagnosis=clean.get("diagnosis"),
            notes=clean.get("notes"),
            created_by=self.actor,
            updated_by=self.actor,
            device_id=self.device_id,
        )
        patient = self.repos["patients"].insert(patient)

        self._history(
            patient.patient_id, EVENT_CREATED,
            f"Registered with patient number {patient.patient_number}.",
        )
        self._audit(EVENT_CREATED, "patient", patient.patient_number,
                    f"Registered {patient.name}")
        return patient

    def update(self, patient_id: int, data: dict, changed_fields=None) -> Patient:
        """Validate the payload and apply the named demographic changes."""
        patient = self.repos["patients"].get(patient_id)
        if not patient:
            raise NotFoundError(f"Patient #{patient_id} does not exist.")

        # Merge onto current values so partial forms validate completely.
        merged = {
            "name": data.get("name", patient.name),
            "age": data.get("age", patient.age),
            "sex": data.get("sex", patient.sex),
            "date_of_birth": data.get(
                "date_of_birth",
                patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            ),
            "phone": data.get("phone", patient.phone),
            "email": data.get("email", patient.email),
            "address": data.get("address", patient.address),
            "blood_pressure": data.get("blood_pressure", patient.blood_pressure),
            "heart_rate": data.get("heart_rate", patient.heart_rate),
            "weight": data.get("weight", patient.weight),
            "medical_history": data.get("medical_history", patient.medical_history),
            "diagnosis": data.get("diagnosis", patient.diagnosis),
            "notes": data.get("notes", patient.notes),
        }
        clean = self.validator.validate(merged)

        if changed_fields is None:
            changed_fields = [
                field for field, value in clean.items()
                if value != getattr(patient, field, None)
            ]

        for field in ("name", "age", "sex", "date_of_birth", "phone", "email",
                      "address", "blood_pressure", "heart_rate", "weight",
                      "medical_history", "diagnosis", "notes"):
            if field in clean:
                setattr(patient, field, clean[field])
        patient.updated_by = self.actor
        patient.device_id = self.device_id

        patient = self.repos["patients"].update(patient, changed_fields)
        summary = ", ".join(changed_fields) or "no fields"
        self._history(patient_id, EVENT_UPDATED, f"Updated: {summary}.")
        self._audit(EVENT_UPDATED, "patient", patient.patient_number, summary)
        return patient

    def delete(self, patient_id: int) -> bool:
        """Soft delete: hidden by default, restorable, never reuses the ID."""
        patient = self.repos["patients"].get(patient_id)
        if not patient:
            raise NotFoundError(f"Patient #{patient_id} does not exist.")
        deleted = self.repos["patients"].soft_delete(
            patient_id, actor=self.actor, device_id=self.device_id
        )
        if deleted:
            self._history(patient_id, EVENT_DELETED,
                          f"Record deleted by {self.actor}.")
            self._audit(EVENT_DELETED, "patient", patient.patient_number,
                        f"Deleted {patient.name}")
        return deleted

    def restore(self, patient_id: int) -> bool:
        restored = self.repos["patients"].restore(patient_id)
        if restored:
            patient = self.repos["patients"].get(patient_id, include_deleted=True)
            self._audit("restored", "patient",
                        patient.patient_number if patient else patient_id)
        return restored

    def deleted_patients(self) -> list[PatientSummary]:
        """Recycle bin: only soft-deleted patients, newest activity first."""
        return self.repos["patients"].deleted_summaries()

    # ------------------------------------------------------------------ #
    # convenience used by the UI

    def age_display(self, patient: Patient) -> str:
        if patient.age is not None:
            return f"{patient.age}y"
        if patient.date_of_birth:
            derived = PatientValidator.age_from_dob(patient.date_of_birth)
            if derived is not None:
                return f"{derived}y"
        return "—"

    def updated_display(self, patient: Patient) -> str:
        return humanize(patient.updated_at.isoformat() if patient.updated_at else None)
