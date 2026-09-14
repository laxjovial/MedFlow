"""Exchange service: move a patient record between MedFlow facilities.

Two facilities running MedFlow — a clinic and a hospital, two branches of
the same group — can transfer a complete record without a shared database
or an internet-connected vendor cloud. The sender produces a self-contained
``.medflow.json`` bundle; the receiver imports it as either a *new* patient
or a *merge* into an existing record, keeping every conflicting value
visible in the returned report so a human confirms the outcome.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.errors import ExchangeError, NotFoundError
from app.models import AuditEvent, Patient
from app.models.audit import (
    EVENT_TRANSFER_IN,
    EVENT_TRANSFER_OUT,
)
from app.services.patients import PatientService
from app.utils.dates import to_iso, utcnow
from app.utils.json_utils import dumps

BUNDLE_FORMAT = "medflow-exchange"
BUNDLE_VERSION = 1


@dataclass
class TransferReport:
    """What happened when a bundle was imported."""

    mode: str                                    # new | merged
    patient_number: str
    patient_id: int | None
    merged_fields: list[str] = field(default_factory=list)
    kept_local_fields: list[str] = field(default_factory=list)
    new_history_events: int = 0

    def summary(self) -> str:
        if self.mode == "new":
            return f"Imported as new patient {self.patient_number}."
        return (
            f"Merged into {self.patient_number}: "
            f"{len(self.merged_fields)} field(s) updated from the transfer, "
            f"{len(self.kept_local_fields)} kept local."
        )


# ---------------------------------------------------------------------------
# export


class ExchangeService:
    """Build and import inter-facility transfer bundles."""

    def __init__(self, patient_service: PatientService, facility_name: str,
                 actor: str = "system", device_id: str = "workstation-01"):
        self.patients = patient_service
        self.facility_name = facility_name
        self.actor = actor
        self.device_id = device_id

    # ------------------------------------------------------------------ #
    # bundle creation

    def build_bundle(self, patient_id: int) -> dict:
        """Assemble the transfer payload for one patient."""
        chart = self.patients.chart(patient_id)
        patient = chart["patient"]
        payload = {
            "format": BUNDLE_FORMAT,
            "version": BUNDLE_VERSION,
            "created_at": to_iso(utcnow()),
            "origin_facility": self.facility_name,
            "origin_device": self.device_id,
            "patient": patient.to_row(),
            "chart": {
                key: [item.to_row() for item in chart.get(key, [])]
                for key in ("vitals", "diagnoses", "medications", "allergies",
                            "lab_results", "notes", "timeline")
            },
        }
        payload["checksum"] = self._checksum(payload)
        self.patients._audit(
            EVENT_TRANSFER_OUT, "patient", patient.patient_number,
            f"Transfer bundle created for {self.facility_name}",
        )
        return payload

    def export_file(self, patient_id: int, directory: str | Path) -> Path:
        """Write a ``.medflow.json`` transfer file and return its path."""
        bundle = self.build_bundle(patient_id)
        number = bundle["patient"]["patient_number"].replace("MF-", "")
        stamp = to_iso(utcnow()).replace(":", "").replace("-", "")[:13]
        name = f"medflow_transfer_{number}_{stamp}.medflow.json"
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(dumps(bundle), encoding="utf-8")
        return path

    # ------------------------------------------------------------------ #
    # import

    def import_bundle(self, bundle: dict, target_patient_id: int | None = None,
                      overwrite: bool = False) -> TransferReport:
        """Import a bundle as a new record, or merge into ``target_patient_id``.

        ``overwrite`` controls who wins a conflicting field during a merge:
        False (default) keeps the local value and lists the field as kept;
        True accepts the incoming transfer value.
        """
        self._verify(bundle)

        incoming = Patient.from_row(bundle["patient"])
        existing = self.patients.repos["patients"].get_by_number(
            incoming.patient_number
        )

        if target_patient_id is None and existing is None:
            return self._import_new(bundle, incoming)

        target_id = target_patient_id or existing.patient_id
        if target_patient_id and not self.patients.repos["patients"].get(target_id):
            raise NotFoundError(f"Patient #{target_id} does not exist.")
        return self._import_merge(bundle, incoming, target_id, overwrite)

    # ------------------------------------------------------------------ #
    # internals

    def _import_new(self, bundle: dict, incoming: Patient) -> TransferReport:
        created = self.patients.register(dict(
            name=incoming.name,
            age=incoming.age,
            sex=incoming.sex,
            date_of_birth=incoming.date_of_birth.isoformat()
            if incoming.date_of_birth else None,
            phone=incoming.phone,
            email=incoming.email,
            address=incoming.address,
            blood_pressure=incoming.blood_pressure,
            heart_rate=incoming.heart_rate,
            weight=incoming.weight,
            medical_history=incoming.medical_history,
            diagnosis=incoming.diagnosis,
            notes=incoming.notes,
        ))
        events = self._import_chart(bundle, created.patient_id)
        self.patients._audit(
            EVENT_TRANSFER_IN, "patient", created.patient_number,
            f"Record received from {bundle.get('origin_facility', 'unknown')}",
        )
        return TransferReport(
            mode="new", patient_number=created.patient_number,
            patient_id=created.patient_id, new_history_events=events,
        )

    def _import_merge(self, bundle: dict, incoming: Patient, target_id: int,
                      overwrite: bool) -> TransferReport:
        target = self.patients.repos["patients"].get(
            target_id, include_deleted=True
        )
        if not target:
            raise NotFoundError(f"Patient #{target_id} does not exist.")

        fields = ("age", "sex", "date_of_birth", "phone", "email", "address",
                  "blood_pressure", "heart_rate", "weight",
                  "medical_history", "diagnosis", "notes")
        merged: list[str] = []
        kept: list[str] = []
        payload: dict = {}
        for f in fields:
            incoming_value = getattr(incoming, f, None)
            local_value = getattr(target, f, None)
            if incoming_value in (None, "") or incoming_value == local_value:
                continue
            if local_value in (None, "") or overwrite:
                payload[f] = (incoming_value.isoformat()
                              if hasattr(incoming_value, "isoformat")
                              else incoming_value)
                merged.append(f)
            else:
                kept.append(f)

        if payload:
            self.patients.update(target_id, payload, changed_fields=merged)

        events = self._import_chart(bundle, target_id)
        self.patients._history(
            target_id, EVENT_TRANSFER_IN,
            f"Record merged from {bundle.get('origin_facility', 'unknown')} "
            f"({len(merged)} field(s) updated, {len(kept)} kept local).",
        )
        self.patients._audit(
            EVENT_TRANSFER_IN, "patient", target.patient_number,
            f"Merged from {bundle.get('origin_facility', 'unknown')}",
        )
        return TransferReport(
            mode="merged", patient_number=target.patient_number,
            patient_id=target_id, merged_fields=merged,
            kept_local_fields=kept, new_history_events=events,
        )

    def _import_chart(self, bundle: dict, patient_id: int) -> int:
        """Append incoming chart rows that the local chart does not have yet.

        Both sides are fingerprinted through the domain model (``from_row``
        then ``to_row``) so datetime formatting and column sets match exactly.
        """
        repos = self.patients.repos
        count = 0
        for key in ("vitals", "diagnoses", "medications", "allergies",
                    "lab_results", "notes"):
            repo = repos[key]
            model = repo.model
            pk = repo._pk()

            def fingerprint(record) -> str:
                row = record.to_row()
                row.pop(pk, None)
                row.pop("device_id", None)
                return json.dumps(row, sort_keys=True, default=str)

            seen = {fingerprint(r) for r in repo.list_for_patient(patient_id)}
            for row in bundle.get("chart", {}).get(key, []):
                record = model.from_row(dict(row))
                fp = fingerprint(record)
                if fp in seen:
                    continue
                row = record.to_row()
                row["patient_id"] = patient_id
                repo.insert(model.from_row(row))
                seen.add(fp)
                count += 1
        return count

    # ------------------------------------------------------------------ #
    # integrity

    @staticmethod
    def _checksum(payload: dict) -> str:
        body = {k: v for k, v in payload.items() if k != "checksum"}
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def _verify(self, bundle: dict) -> None:
        if not isinstance(bundle, dict):
            raise ExchangeError("Transfer file is not a valid bundle.")
        if bundle.get("format") != BUNDLE_FORMAT:
            raise ExchangeError(
                f"Not a MedFlow transfer bundle (format={bundle.get('format')!r})."
            )
        if int(bundle.get("version", 0)) > BUNDLE_VERSION:
            raise ExchangeError(
                "Transfer bundle was produced by a newer MedFlow; update first."
            )
        expected = bundle.get("checksum")
        if expected and expected != self._checksum(bundle):
            raise ExchangeError(
                "Checksum mismatch — the transfer file was modified or corrupted."
            )
        if "patient" not in bundle or not bundle["patient"].get("name"):
            raise ExchangeError("Bundle is missing the patient payload.")
