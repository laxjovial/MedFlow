"""SQLite implementation of the audit trail repository."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.exceptions import PersistenceError
from app.domain.audit import AuditEntry
from app.repositories.audit_repository import AuditRepository
from app.repositories.sqlite.connection import Database


class SqliteAuditRepository(AuditRepository):
    """Stores audit entries in the ``audit_log`` table.

    ``details`` is persisted as JSON text, which keeps the domain object a plain
    mapping and means a new action type never requires a schema change.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, entry: AuditEntry) -> AuditEntry:
        try:
            payload = json.dumps(entry.details or {}, default=str)
        except (TypeError, ValueError) as exc:
            raise PersistenceError(f"Audit details are not serialisable: {exc}") from exc

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO audit_log
                        (action, entity_type, entity_id, actor, details, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.action,
                        entry.entity_type,
                        entry.entity_id,
                        entry.actor,
                        payload,
                        entry.created_at,
                    ),
                )
                entry.id = cursor.lastrowid
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not record audit entry: {exc}") from exc

        return entry

    def recent(self, limit: int = 100, offset: int = 0) -> list[AuditEntry]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, action, entity_type, entity_id, actor, details, created_at
                FROM audit_log
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [_to_entry(row) for row in rows]

    def for_entity(
        self, entity_type: str, entity_id: str, limit: int | None = None
    ) -> list[AuditEntry]:
        sql = """
            SELECT id, action, entity_type, entity_id, actor, details, created_at
            FROM audit_log
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY id DESC
        """
        parameters: list[object] = [entity_type, entity_id]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)

        with self._database.connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        return [_to_entry(row) for row in rows]

    def count(self) -> int:
        with self._database.connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM audit_log").fetchone()
        return int(row["total"]) if row else 0


def _to_entry(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(
        id=row["id"],
        action=row["action"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"] or "",
        actor=row["actor"] or "",
        details=_decode_details(row["details"]),
        created_at=row["created_at"] or "",
    )


def _decode_details(raw: Any) -> dict[str, Any]:
    """Parse stored details, tolerating anything unreadable.

    An entry written by an older or newer version must not make the Activity
    view unloadable; an unreadable payload degrades to an empty mapping.
    """
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}
