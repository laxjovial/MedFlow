"""The audit service.

The audit trail answers "who did what, and when" across the whole application.
Every other service funnels its writes through here rather than touching the
repository directly, so the timestamp format and the actor attribution are decided
in exactly one place.
"""

from __future__ import annotations

from typing import Any

from app.core.clock import Clock
from app.domain.audit import AuditEntry
from app.domain.enums import AuditAction, EntityType
from app.repositories.audit_repository import AuditRepository


class AuditService:
    """Writes and reads application audit entries."""

    def __init__(self, repository: AuditRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    def record(
        self,
        action: AuditAction | str,
        *,
        entity_type: EntityType | str,
        entity_id: str = "",
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Append an entry, stamping it with the current time."""
        return self._repository.record(
            AuditEntry(
                action=str(action),
                entity_type=str(entity_type),
                entity_id=str(entity_id),
                actor=actor,
                details=dict(details or {}),
                created_at=self._clock.timestamp(),
            )
        )

    def recent(self, limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        return self._repository.recent(limit=limit, offset=offset)

    def for_patient(self, patient_number: str, limit: int | None = None) -> list[AuditEntry]:
        """Audit entries recorded against one patient."""
        return self._repository.for_entity(
            str(EntityType.PATIENT), patient_number, limit=limit
        )

    def count(self) -> int:
        return self._repository.count()
