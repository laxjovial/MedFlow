"""Application-wide audit entries.

Covers every entity, not just patients: exports, imports, backups and
migrations are auditable events too, and recording them in the same table means
the Activity view is a genuine account of what the application did.

``details`` holds a JSON-serialisable mapping — field-level differences on an
update, row counts on an import — so an entry explains itself without a schema
change for every new action type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import AUDIT_ACTION_LABELS


@dataclass
class AuditEntry:
    """A single auditable action."""

    action: str = ""
    entity_type: str = ""
    entity_id: str = ""
    actor: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    id: int | None = None

    @property
    def label(self) -> str:
        """Human-readable name for the action."""
        return AUDIT_ACTION_LABELS.get(
            self.action, str(self.action).replace("_", " ").title()
        )

    @property
    def target(self) -> str:
        """What the action was performed on, as ``entity_type entity_id``."""
        return f"{self.entity_type} {self.entity_id}".strip()

    @property
    def summary(self) -> str:
        """A one-line description, for the Activity view and log output.

        Names the record the action touched rather than only its entity type,
        because "Changed a record · patient MF-000012" is what someone scanning
        the log is actually looking for.
        """
        if self.target:
            return f"{self.label} · {self.target}"
        return self.label
