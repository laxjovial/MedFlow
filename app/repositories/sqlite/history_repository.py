"""SQLite implementation of the patient timeline repository."""

from __future__ import annotations

import sqlite3

from app.core.exceptions import PersistenceError
from app.domain.events import PatientEvent
from app.repositories.history_repository import HistoryRepository
from app.repositories.sqlite.connection import Database


class SqliteHistoryRepository(HistoryRepository):
    """Stores timeline entries in the ``patient_events`` table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, event: PatientEvent) -> PatientEvent:
        if event.patient_id is None:
            raise PersistenceError("A timeline entry must reference a patient")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO patient_events
                        (patient_id, event_type, description, actor, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event.patient_id,
                        event.event_type,
                        event.description,
                        event.actor,
                        event.created_at,
                    ),
                )
                event.id = cursor.lastrowid
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not record timeline entry: {exc}") from exc

        return event

    def for_patient(self, patient_id: int, limit: int | None = None) -> list[PatientEvent]:
        sql = """
            SELECT id, patient_id, event_type, description, actor, created_at
            FROM patient_events
            WHERE patient_id = ?
            ORDER BY id DESC
        """
        parameters: list[object] = [patient_id]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)

        with self._database.connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        return [_to_event(row) for row in rows]

    def recent(self, limit: int = 20) -> list[PatientEvent]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, patient_id, event_type, description, actor, created_at
                FROM patient_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [_to_event(row) for row in rows]


def _to_event(row: sqlite3.Row) -> PatientEvent:
    return PatientEvent(
        id=row["id"],
        patient_id=row["patient_id"],
        event_type=row["event_type"],
        description=row["description"] or "",
        actor=row["actor"] or "",
        created_at=row["created_at"] or "",
    )
