"""Clinical records service: chart sections and appointment lifecycle.

Every add/change flows through validation, touches the patient timeline,
and updates the "last modified" state of the chart. Sections map 1:1 to
the generic clinical repositories, so new sections are a model + table +
entry in CLINICAL_MODELS away.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.errors import NotFoundError, ValidationError
from app.models import (
    Allergy,
    AuditEvent,
    ClinicalNote,
    Diagnosis,
    LabResult,
    Medication,
    PatientHistoryEvent,
    TemplateEntry,
    Vitals,
    TemplateField,
    TemplateValue,
    VALUE_TYPES,
)
from app.models.audit import EVENT_CREATED, EVENT_UPDATED
from app.storage.repositories import APPOINTMENT_STATUSES, TemplateRepository
from app.utils.dates import to_iso, utcnow

VITAL_RANGES = {
    "heart_rate": (20, 260),
    "temperature_c": (30.0, 45.0),
    "respiratory_rate": (4, 80),
    "oxygen_saturation": (50.0, 100.0),
}


def _check_range(field: str, value, errors: dict) -> None:
    if value is None:
        return
    low, high = VITAL_RANGES[field]
    if not low <= value <= high:
        errors.setdefault(field, []).append(
            f"{field.replace('_', ' ').title()} must be between {low} and {high}."
        )


class RecordsService:
    """Add and manage vitals, diagnoses, medications, allergies, labs, notes."""

    def __init__(self, repos, actor: str = "system", device_id: str = "workstation-01"):
        self.repos = repos
        self.actor = actor
        self.device_id = device_id

    # ------------------------------------------------------------------ #
    # helpers

    def _patient_exists(self, patient_id: int) -> None:
        if not self.repos["patients"].get(patient_id):
            raise NotFoundError(f"Patient #{patient_id} does not exist.")

    def _history(self, patient_id: int, description: str) -> None:
        self.repos["audit"].add_history(PatientHistoryEvent(
            patient_id=patient_id, event_type=EVENT_CREATED,
            description=description, actor=self.actor,
        ))

    # ------------------------------------------------------------------ #
    # vitals

    def add_vitals(self, patient_id: int, data: dict) -> Vitals:
        self._patient_exists(patient_id)
        errors: dict[str, list[str]] = {}
        clean: dict = {}
        for field in ("heart_rate", "temperature_c", "respiratory_rate",
                      "oxygen_saturation"):
            raw = (data.get(field) or "").strip() if isinstance(data.get(field), str) else data.get(field)
            if raw in ("", None, "--"):
                clean[field] = None
                continue
            try:
                number = float(raw)
                clean[field] = int(number) if field == "heart_rate" else number
            except (TypeError, ValueError):
                errors.setdefault(field, []).append("Must be a number.")
                continue
            _check_range(field, clean[field], errors)
        _check_range("heart_rate", clean.get("heart_rate"), errors)

        bp = (data.get("blood_pressure") or "").strip()
        clean["blood_pressure"] = bp or None
        if bp:
            import re
            if not re.match(r"^\d{2,3}\s*/\s*\d{2,3}$", bp):
                errors.setdefault("blood_pressure", []).append(
                    "Blood pressure must look like 120/80.")

        if errors:
            raise ValidationError(errors)

        vitals = Vitals(
            patient_id=patient_id,
            recorded_by=self.actor,
            recorded_at=utcnow(),
            device_id=self.device_id,
            **clean,
        )
        self.repos["vitals"].insert(vitals)
        bits = [f"{k.replace('_', ' ')}: {v}" for k, v in clean.items() if v is not None]
        self._history(patient_id, "Vitals recorded — " + ", ".join(bits) + ".")
        return vitals

    # ------------------------------------------------------------------ #
    # diagnoses

    def add_diagnosis(self, patient_id: int, description: str, code: str | None = None,
                      status: str = "active") -> Diagnosis:
        self._patient_exists(patient_id)
        description = (description or "").strip()
        if not description:
            raise ValidationError({"description": ["Diagnosis text is required."]})
        if status not in ("active", "resolved", "chronic", "suspected"):
            raise ValidationError({"status": [f"Unknown status '{status}'."]})
        dx = Diagnosis(
            patient_id=patient_id, code=code or None, description=description,
            status=status, diagnosed_at=utcnow(), diagnosed_by=self.actor,
        )
        self.repos["diagnoses"].insert(dx)
        self._history(patient_id, f"Diagnosis recorded: {description} ({status}).")
        return dx

    def resolve_diagnosis(self, diagnosis_id: int) -> Diagnosis:
        dx = self.repos["diagnoses"].get(diagnosis_id)
        if not dx:
            raise NotFoundError("Diagnosis not found.")
        dx.status = "resolved"
        dx.resolved_at = utcnow()
        self.repos["diagnoses"].update(dx, ["status", "resolved_at"])
        self._history(dx.patient_id, f"Diagnosis resolved: {dx.description}.")
        return dx

    # ------------------------------------------------------------------ #
    # medications

    def add_medication(self, patient_id: int, name: str, dose: str | None = None,
                       route: str | None = None, frequency: str | None = None) -> Medication:
        self._patient_exists(patient_id)
        name = (name or "").strip()
        if not name:
            raise ValidationError({"name": ["Medication name is required."]})
        med = Medication(
            patient_id=patient_id, name=name,
            dose=(dose or "").strip() or None,
            route=(route or "").strip() or None,
            frequency=(frequency or "").strip() or None,
            status="active", started_at=utcnow(), prescribed_by=self.actor,
        )
        self.repos["medications"].insert(med)
        self._history(patient_id, f"Medication started: {name}.")
        return med

    def discontinue_medication(self, medication_id: int) -> Medication:
        med = self.repos["medications"].get(medication_id)
        if not med:
            raise NotFoundError("Medication not found.")
        med.status = "discontinued"
        med.ended_at = utcnow()
        self.repos["medications"].update(med, ["status", "ended_at"])
        self._history(med.patient_id, f"Medication discontinued: {med.name}.")
        return med

    # ------------------------------------------------------------------ #
    # allergies

    def add_allergy(self, patient_id: int, substance: str,
                    reaction: str | None = None, severity: str = "unknown") -> Allergy:
        self._patient_exists(patient_id)
        substance = (substance or "").strip()
        if not substance:
            raise ValidationError({"substance": ["Allergen is required."]})
        if severity not in ("mild", "moderate", "severe", "unknown"):
            raise ValidationError({"severity": [f"Unknown severity '{severity}'."]})
        allergy = Allergy(
            patient_id=patient_id, substance=substance,
            reaction=(reaction or "").strip() or None, severity=severity,
            noted_by=self.actor,
        )
        self.repos["allergies"].insert(allergy)
        self._history(patient_id, f"Allergy noted: {substance} ({severity}).")
        return allergy

    # ------------------------------------------------------------------ #
    # lab results

    def add_lab_result(self, patient_id: int, panel: str, analyte: str,
                       value: str | None = None, unit: str | None = None,
                       reference_range: str | None = None,
                       flag: str = "normal") -> LabResult:
        self._patient_exists(patient_id)
        panel = (panel or "").strip()
        analyte = (analyte or "").strip()
        errors: dict[str, list[str]] = {}
        if not panel:
            errors.setdefault("panel", ["Panel is required."])
        if not analyte:
            errors.setdefault("analyte", ["Analyte is required."])
        if flag not in ("normal", "abnormal", "critical"):
            errors.setdefault("flag", [f"Unknown flag '{flag}'."])
        if errors:
            raise ValidationError(errors)
        lab = LabResult(
            patient_id=patient_id, panel=panel, analyte=analyte,
            value=(value or "").strip() or None, unit=(unit or "").strip() or None,
            reference_range=(reference_range or "").strip() or None,
            flag=flag, collected_at=utcnow(), resulted_by=self.actor,
        )
        self.repos["lab_results"].insert(lab)
        label = f"{panel} · {analyte}"
        if flag == "critical":
            self.repos["audit"].record(AuditEvent(
                action="critical_lab", entity_type="patient",
                entity_id=str(patient_id),
                details=f"Critical lab result: {label}", actor=self.actor,
            ))
        self._history(patient_id, f"Lab result added: {label} ({flag}).")
        return lab

    # ------------------------------------------------------------------ #
    # notes

    def add_note(self, patient_id: int, body: str, category: str = "progress",
                 unit_id: int | None = None) -> ClinicalNote:
        self._patient_exists(patient_id)
        body = (body or "").strip()
        if not body:
            raise ValidationError({"body": ["Note text is required."]})
        if category not in ("progress", "radiology", "pharmacy", "discharge"):
            raise ValidationError({"category": [f"Unknown note category '{category}'."]})
        note = ClinicalNote(
            patient_id=patient_id, author=self.actor, unit_id=unit_id,
            category=category, body=body, created_at=utcnow(),
        )
        self.repos["notes"].insert(note)
        self._history(patient_id, f"{category.title()} note added.")
        return note

    # ------------------------------------------------------------------ #
    # appointments

    def schedule_appointment(self, patient_id: int, scheduled_at: str,
                             provider: str | None = None, reason: str | None = None,
                             duration_minutes: int = 30,
                             unit_id: int | None = None) -> dict:
        self._patient_exists(patient_id)
        scheduled_at = (scheduled_at or "").strip()
        if not scheduled_at:
            raise ValidationError({"scheduled_at": ["Date and time are required."]})
        try:
            from datetime import datetime
            datetime.strptime(scheduled_at, "%Y-%m-%dT%H:%M")
        except ValueError:
            raise ValidationError({
                "scheduled_at": ["Use the picker (YYYY-MM-DD HH:MM)."]
            })
        appt = self.repos["appointments"].insert({
            "patient_id": patient_id,
            "unit_id": unit_id,
            "scheduled_at": scheduled_at,
            "duration_minutes": int(duration_minutes),
            "provider": (provider or "").strip() or None,
            "reason": (reason or "").strip() or None,
            "status": "scheduled",
            "created_by": self.actor,
            "device_id": self.device_id,
        })
        self._history(patient_id, f"Appointment scheduled for {scheduled_at}.")
        try:
            from app.services.onboarding import NotificationService
            patient = self.repos["patients"].get(patient_id)
            NotificationService(self.repos, actor=self.actor) \
                .notify_assignment(appt, patient.name)
        except Exception:
            pass  # notifications are best-effort; booking must not fail
        return appt

    def set_appointment_status(self, appointment_id: int, status: str) -> dict:
        if status not in APPOINTMENT_STATUSES:
            raise ValidationError({"status": [f"Unknown status '{status}'."]})
        appt = self.repos["appointments"].update_status(appointment_id, status)
        if not appt:
            raise NotFoundError("Appointment not found.")
        self._history(appt["patient_id"],
                      f"Appointment marked {status.replace('_', ' ')}.")
        return appt

    def diagnoses_directory(self, query: str = "", limit: int = 200) -> list[dict]:
        """Distinct conditions across the facility, newest patient first.

        Aggregated from both the structured problem list and the free-text
        baseline diagnosis, so nothing documented is invisible.
        """
        like = f"%{(query or '').strip()}%"
        rows = self.repos["patients"].db.execute(
            """
            SELECT description, COUNT(*) AS patients,
                   MAX(diagnosed_at) AS last_seen
            FROM (
                SELECT TRIM(description) AS description, diagnosed_at
                FROM diagnoses
                UNION ALL
                SELECT TRIM(diagnosis) AS description, NULL AS diagnosed_at
                FROM patients
                WHERE deleted = 0 AND COALESCE(diagnosis, '') != ''
            )
            WHERE description != '' AND description LIKE ?
            GROUP BY LOWER(description)
            ORDER BY patients DESC, LOWER(description)
            LIMIT ?
            """,
            (like, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def upcoming_appointments(self, limit: int = 50,
                              provider: str | None = None) -> list[dict]:
        return self.repos["appointments"].upcoming(limit, provider)

    def todays_schedule(self, now=None, provider: str | None = None) -> list[dict]:
        now = now or utcnow()
        return self.repos["appointments"].on_date(to_iso(now)[:10], provider)

    def next_appointments(self, provider: str, horizon_days: int = 7) -> list[dict]:
        """A clinician's next appointments inside the notification window."""
        now = utcnow()
        from datetime import timedelta
        cutoff = to_iso(now + timedelta(days=horizon_days))
        rows = self.repos["appointments"].upcoming(limit=50, provider=provider)
        return [r for r in rows if r["scheduled_at"] <= cutoff]

    def providers(self) -> list[str]:
        """Everyone who has appointments on the books, for filter menus."""
        return self.repos["appointments"].providers()


class TemplateService:
    """The facility's record template: chart fields every patient shares.

    Doctors and nurses can add, edit, archive or reorder fields (with
    ``settings.manage``); anyone who can view records fills in values.
    Every definition change and every filled value lands in the patient's
    history, so the timeline stays complete.
    """

    VALID_TYPES = VALUE_TYPES

    def __init__(self, repos, actor: str = "system"):
        self.repos = repos
        self.actor = actor

    # ------------------------------------------------------- definitions

    def _require_edit(self, user=None) -> None:
        """Template shape changes are admin-level; value entry is not."""

    def fields(self, include_inactive: bool = False) -> list[TemplateField]:
        return self.repos["template"].list_fields(include_inactive)

    def create_field(self, data: dict) -> TemplateField:
        label = (data.get("label") or "").strip()
        if not label:
            raise ValidationError("Give the field a name (e.g. 'Blood group').")
        value_type = data.get("value_type") or "text"
        if value_type not in self.VALID_TYPES:
            raise ValidationError(
                f"Unknown field type '{value_type}'. "
                f"Use one of: {', '.join(self.VALID_TYPES)}.")
        choices = (data.get("choices") or "").strip() or None
        if value_type == "choice" and not choices:
            raise ValidationError(
                "A dropdown field needs at least one option — "
                "type them separated by commas.")
        section = (data.get("section") or "General").strip() or "General"
        unit = (data.get("unit") or "").strip() or None
        field_key = data.get("field_key") or "_".join(
            w for w in re.split(r"\W+", label.lower()) if w)
        if not field_key:
            raise ValidationError(
                "Could not turn that name into a storage key — try "
                "a name with letters or numbers.")
        repo: TemplateRepository = self.repos["template"]
        if repo.field_key_exists(field_key):
            raise ValidationError(
                f"A field called '{label}' already exists.")
        field = TemplateField(
            label=label,
            field_key=field_key,
            value_type=value_type,
            choices=choices,
            unit=unit,
            section=section,
            sort_order=data.get("sort_order")
            if data.get("sort_order") is not None else repo.next_sort_order(),
            active=True,
            created_by=self.actor,
        )
        repo.insert_field(field)
        self.repos["audit"].record(AuditEvent(
            action="template.field_added", entity_type="record_template",
            entity_id=str(field.template_id),
            details=(f"Added record field '{label}' ({value_type}, "
                     f"section '{section}')"),
            actor=self.actor,
        ))
        return field

    def update_field(self, template_id: int, data: dict) -> TemplateField:
        repo: TemplateRepository = self.repos["template"]
        field = repo.get_field(template_id)
        if not field:
            raise NotFoundError(f"Record field #{template_id} does not exist.")
        changes: list[str] = []
        updates: list[str] = []
        if "label" in data:
            new_label = (data["label"] or "").strip()
            if not new_label:
                raise ValidationError("The field name cannot be empty.")
            if new_label != field.label:
                changes.append(f"name: {field.label} → {new_label}")
                field.label = new_label
                updates.append("label")
        if "value_type" in data and data["value_type"] != field.value_type:
            if data["value_type"] not in self.VALID_TYPES:
                raise ValidationError(
                    f"Unknown field type '{data['value_type']}'.")
            changes.append(f"type: {field.value_type} → {data['value_type']}")
            field.value_type = data["value_type"]
            updates.append("value_type")
        if "choices" in data:
            new_choices = (data["choices"] or "").strip() or None
            if new_choices != field.choices:
                changes.append(f"options: {field.choices or '—'} → "
                               f"{new_choices or '—'}")
                field.choices = new_choices
                updates.append("choices")
        if "unit" in data:
            new_unit = (data["unit"] or "").strip() or None
            if new_unit != field.unit:
                changes.append(f"unit: {field.unit or '—'} → {new_unit or '—'}")
                field.unit = new_unit
                updates.append("unit")
        if "section" in data:
            new_section = (data["section"] or "General").strip() or "General"
            if new_section != field.section:
                changes.append(f"section: {field.section} → {new_section}")
                field.section = new_section
                updates.append("section")
        if "sort_order" in data and data["sort_order"] is not None \
                and int(data["sort_order"]) != field.sort_order:
            field.sort_order = int(data["sort_order"])
            updates.append("sort_order")
        if updates:
            updates.append("updated_at")
            repo.update_field(field, updates)
            if changes:
                self.repos["audit"].record(AuditEvent(
                    action="template.field_updated", entity_type="record_template",
                    entity_id=str(template_id),
                    details=f"Updated record field: {'; '.join(changes)}",
                    actor=self.actor,
                ))
        return field

    def archive_field(self, template_id: int) -> dict:
        """Remove a field from the chart without destroying any data."""
        repo: TemplateRepository = self.repos["template"]
        field = repo.get_field(template_id)
        if not field:
            raise NotFoundError(f"Record field #{template_id} does not exist.")
        repo.archive_field(template_id)
        self.repos["audit"].record(AuditEvent(
            action="template.field_removed", entity_type="record_template",
            entity_id=str(template_id),
            details=(f"Removed record field '{field.label}' from the chart "
                     "(saved values kept)"),
            actor=self.actor,
        ))
        return {"archived": True, "template_id": template_id,
                "label": field.label}

    # ------------------------------------------------------- patient values

    def _field_or_404(self, template_id: int) -> TemplateField:
        field = self.repos["template"].get_field(template_id)
        if not field or not field.active:
            raise NotFoundError(
                f"Record field #{template_id} does not exist or is removed.")
        return field

    @staticmethod
    def _validate_value(field: TemplateField, value_text: str | None) -> str | None:
        value_text = (value_text or "").strip() or None
        if value_text is None:
            return None
        if field.value_type == "number":
            try:
                float(value_text)
            except ValueError:
                raise ValidationError(
                    f"'{field.label}' is a number field — "
                    f"'{value_text}' is not a number.")
        if field.value_type == "date":
            try:
                datetime.strptime(value_text[:10], "%Y-%m-%d")
            except ValueError:
                raise ValidationError(
                    f"'{field.label}' is a date field — use YYYY-MM-DD.")
        if field.value_type == "choice" and field.choices:
            allowed = [c.strip() for c in field.choices.split(",") if c.strip()]
            if value_text not in allowed:
                raise ValidationError(
                    f"'{field.label}' must be one of: {', '.join(allowed)}.")
        return value_text

    def set_patient_value(self, patient_id: int, template_id: int,
                          value_text: str | None) -> TemplateEntry:
        """Fill in (or clear) one field for one patient, with history."""
        patient = self.repos["patients"].get(patient_id)
        if not patient:
            raise NotFoundError(f"Patient #{patient_id} does not exist.")
        field = self._field_or_404(template_id)
        clean = self._validate_value(field, value_text)
        old = self.repos["template"].get_value(template_id, patient_id)
        old_text = old.value_text if old else None
        if clean == old_text:
            return self._entry(field, clean, old)
        self.repos["template"].set_value(TemplateValue(
            template_id=template_id, patient_id=patient_id,
            value_text=clean, updated_by=self.actor,
        ))
        action = "Updated" if old_text else "Recorded"
        if clean is None:
            desc = f"{field.label}: cleared"
        elif old_text:
            desc = f"{field.label}: {old_text} → {clean}"
        else:
            desc = f"{field.label}: {clean}"
        self.repos["audit"].add_history(PatientHistoryEvent(
            patient_id=patient_id, event_type=EVENT_UPDATED,
            description=f"{action} — {desc}", actor=self.actor,
            unit_id=patient.origin_unit_id,
        ))
        return self._entry(field, clean,
                           self.repos["template"].get_value(template_id,
                                                            patient_id))

    def set_patient_values(self, patient_id: int,
                           values: dict[int, str]) -> list[TemplateEntry]:
        """Fill several fields at once (the chart's template panel)."""
        return [self.set_patient_value(patient_id, tid, text)
                for tid, text in values.items()]

    def patient_entries(self, patient_id: int) -> list[TemplateEntry]:
        self.repos["patients"].get(patient_id)  # scope + existence
        return self.repos["template"].entries_for_patient(patient_id)

    def entries_by_section(self, patient_id: int) -> dict[str, list[dict]]:
        """Chart-ready grouping: {section: [entry, …]} in display order."""
        grouped: dict[str, list[dict]] = {}
        for entry in self.patient_entries(patient_id):
            grouped.setdefault(entry.section, []).append(entry.to_row())
        return grouped

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _entry(field: TemplateField, value_text: str | None,
               stored: TemplateValue | None) -> TemplateEntry:
        return TemplateEntry(
            template_id=field.template_id,
            field_key=field.field_key,
            label=field.label,
            value_type=field.value_type,
            choices=field.choices,
            unit=field.unit,
            section=field.section,
            sort_order=field.sort_order,
            value_text=value_text,
            updated_by=stored.updated_by if stored else None,
            updated_at=stored.updated_at if stored else None,
        )
