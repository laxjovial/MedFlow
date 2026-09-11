"""Audit and history models.

Two distinct concepts:
- PatientHistoryEvent: clinical narrative, shown on the patient timeline.
- AuditEvent: security/operational trail, shown in Activity and exportable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models._serial import serializable

EVENT_CREATED = "created"
EVENT_UPDATED = "updated"
EVENT_DELETED = "deleted"
EVENT_VIEWED = "viewed"
EVENT_EXPORTED = "exported"
EVENT_IMPORTED = "imported"
EVENT_SYNCED = "synced"
EVENT_TRANSFER_IN = "transfer_in"
EVENT_TRANSFER_OUT = "transfer_out"
EVENT_DELIVERY_QUEUED = "delivery_queued"
EVENT_DELIVERY_SENT = "delivery_sent"


@serializable("created_at")
@dataclass
class AuditEvent:
    """One operational action: who, what, where, when."""

    action: str
    entity_type: str
    entity_id: str | None
    details: str | None = None
    actor: str | None = None
    device_id: str | None = None
    unit_id: int | None = None
    created_at: datetime | None = None
    event_id: int | None = None


@serializable("created_at")
@dataclass
class PatientHistoryEvent:
    """Clinical timeline entry attached to one patient."""

    patient_id: int
    event_type: str
    description: str
    actor: str | None = None
    unit_id: int | None = None
    created_at: datetime | None = None
    history_id: int | None = None
