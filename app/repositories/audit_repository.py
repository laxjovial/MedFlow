"""The audit trail repository interface.

Append-only, and deliberately broader than the patient timeline: exports,
imports, backups and migrations are auditable too, which is why entries carry
free-form entity type and identifier rather than a foreign key to ``patients``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.audit import AuditEntry


class AuditRepository(ABC):
    """Storage operations for the application audit trail."""

    @abstractmethod
    def record(self, entry: AuditEntry) -> AuditEntry:
        """Append an entry."""

    @abstractmethod
    def recent(self, limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        """The most recent entries, newest first."""

    @abstractmethod
    def for_entity(
        self, entity_type: str, entity_id: str, limit: int | None = None
    ) -> list[AuditEntry]:
        """Every entry recorded against one entity."""

    @abstractmethod
    def count(self) -> int:
        """How many entries exist."""
