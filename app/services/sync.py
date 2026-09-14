"""Sync engine: local-first change tracking with push/pull to a MedFlow server.

The desktop app stays fully usable offline. Every patient row carries
``version``, ``updated_at``, ``device_id``, and ``change_id``. Push sends
dirty rows; pull merges remote rows; conflicts (same version, both
changed) are reported, never silently overwritten.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.models import AuditEvent, Patient
from app.models.audit import EVENT_SYNCED
from app.models.patient import format_patient_number
from app.utils.dates import to_iso, utcnow


@dataclass
class SyncConflict:
    """A row changed on both sides since the last sync."""

    patient_number: str
    field: str
    local_value: object
    remote_value: object

    def describe(self) -> str:
        return (f"{self.patient_number}.{self.field}: "
                f"local={self.local_value!r} remote={self.remote_value!r}")


@dataclass
class SyncReport:
    """What one sync run did — shown verbatim in the UI."""

    pushed: int = 0
    pulled: int = 0
    conflicts: list[SyncConflict] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: to_iso(utcnow()))
    finished_at: str | None = None
    mode: str = "manual"
    error: str | None = None

    def summary(self) -> str:
        if self.error:
            return f"Sync failed: {self.error}"
        text = f"Pushed {self.pushed}, pulled {self.pulled}"
        if self.conflicts:
            text += f", {len(self.conflicts)} conflict(s) to review"
        return text


class SyncEngine:
    """Change tracking and merge logic; transport is injected."""

    def __init__(self, repos, device_id: str = "workstation-01",
                 transport=None):
        self.repos = repos
        self.device_id = device_id
        self.transport = transport          # callable(payload) -> response
        self.last_sync_at: str | None = None
        self.auto_mode: str = "manual"      # manual | automatic | auto_plus_manual

    # ------------------------------------------------------------------ #
    # change tracking

    def pending_changes(self, since: str | None = None) -> list[Patient]:
        """Patients changed locally since the last successful sync."""
        return self.repos["patients"].changes_since(since or self.last_sync_at)

    def pending_count(self) -> int:
        return len(self.pending_changes())

    # ------------------------------------------------------------------ #
    # payloads

    def build_push_payload(self) -> dict:
        changes = self.pending_changes()
        return {
            "device_id": self.device_id,
            "change_id": uuid.uuid4().hex,
            "sent_at": to_iso(utcnow()),
            "patients": [p.to_row() for p in changes],
        }

    def apply_pull_payload(self, payload: dict) -> SyncReport:
        """Merge remote patients using last-writer-wins per field band."""
        report = SyncReport(mode="pull")
        for row in payload.get("patients", []):
            remote = Patient.from_row(row)
            local = self.repos["patients"].get_by_number(remote.patient_number)

            if local is None:
                self.repos["patients"].upsert_from_remote(remote)
                report.pulled += 1
                continue

            if (remote.updated_at or "") > (local.updated_at or ""):
                conflicts = self._detect_conflicts(local, remote)
                if conflicts and local.device_id == self.device_id:
                    # I changed it here after their change: keep both, flag it
                    report.conflicts.extend(conflicts)
                self.repos["patients"].upsert_from_remote(remote)
                report.pulled += 1
            elif (remote.updated_at or "") == (local.updated_at or ""):
                if remote.version > local.version:
                    self.repos["patients"].upsert_from_remote(remote)
                    report.pulled += 1

        self.repos["patients"].db.commit()
        report.finished_at = to_iso(utcnow())
        return report

    def _detect_conflicts(self, local: Patient, remote: Patient) -> list[SyncConflict]:
        fields = ("name", "age", "sex", "phone", "email", "address",
                  "blood_pressure", "heart_rate", "weight",
                  "medical_history", "diagnosis", "notes")
        out = []
        for f in fields:
            lv, rv = getattr(local, f, None), getattr(remote, f, None)
            if lv != rv:
                out.append(SyncConflict(local.patient_number, f, lv, rv))
        return out

    # ------------------------------------------------------------------ #
    # runs

    def sync_now(self, mode: str = "manual") -> SyncReport:
        """Push local changes, then pull remote changes.

        ``transport`` is a callable: payload dict in, response dict out.
        In local-only mode (no transport configured) the engine validates
        the payloads it *would* send — useful as a dry run and for tests.
        """
        report = SyncReport(mode=mode)

        if self.transport is None:
            payload = self.build_push_payload()
            report.pushed = len(payload["patients"])
            report.summary_note = "dry run (no server configured)"
            report.finished_at = to_iso(utcnow())
            return report

        try:
            push_payload = self.build_push_payload()
            response = self.transport({"op": "push", **push_payload})
            report.pushed = int(response.get("accepted", len(push_payload["patients"])))

            pull_payload = self.transport({"op": "pull", "device_id": self.device_id})
            pull_report = self.apply_pull_payload(pull_payload)
            report.pulled = pull_report.pulled
            report.conflicts = pull_report.conflicts
        except Exception as exc:
            report.error = str(exc)
        finally:
            report.finished_at = to_iso(utcnow())
            if report.error is None:
                self.last_sync_at = report.finished_at
                self.record_sync_event(report)

        return report

    # ------------------------------------------------------------------ #
    # history

    def record_sync_event(self, report: SyncReport) -> None:
        self.repos["audit"].record(
            AuditEvent(
                action=EVENT_SYNCED, entity_type="database",
                entity_id=self.device_id, details=report.summary(),
                actor=self.device_id,
            )
        )
