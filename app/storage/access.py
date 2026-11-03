"""Notifications, staff invites, and multi-department membership.

Notifications are per-user notes the workspace surfaces in the bell:
appointment assignments, invite approvals, and anything else worth
flagging. Invites are one-time codes an administrator hands a new hire;
the account they create stays *pending* until an administrator approves
it — every step stamped in the audit trail.

These live beside (not inside) repositories.py to keep the file readable;
they follow the same conventions: repositories speak SQL only and return
plain dicts/models, services build on top of them.
"""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any, Sequence

from app.utils.dates import to_iso, utcnow


class NotificationRepository:
    """Per-user notification feed backing the bell."""

    table = "notifications"

    def __init__(self, db):
        self.db = db

    def _exec(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        return self.db.execute(sql, params)

    def insert(self, *, user_id: int, title: str, body: str = "",
               kind: str = "general", link: str | None = None,
               created_by: str | None = None) -> dict:
        cur = self._exec(
            f"INSERT INTO {self.table} "
            "(user_id, kind, title, body, link, read, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (user_id, kind, title, body or "", link, to_iso(utcnow()), created_by),
        )
        return self.get(cur.lastrowid)

    def get(self, notification_id: int) -> dict | None:
        row = self._exec(
            f"SELECT * FROM {self.table} WHERE notification_id = ?",
            (notification_id,)).fetchone()
        return dict(row) if row else None

    def list_for_user(self, user_id: int, limit: int = 50,
                      unread_only: bool = False) -> list[dict]:
        sql = (f"SELECT * FROM {self.table} WHERE user_id = ?"
               + (" AND read = 0" if unread_only else "")
               + " ORDER BY notification_id DESC LIMIT ?")
        return [dict(r) for r in self._exec(sql, (user_id, limit)).fetchall()]

    def unread_count(self, user_id: int) -> int:
        return int(self._exec(
            f"SELECT COUNT(*) AS c FROM {self.table} "
            "WHERE user_id = ? AND read = 0", (user_id,)).fetchone()["c"])

    def mark_read(self, notification_id: int, user_id: int,
                  read: bool = True) -> dict | None:
        self._exec(
            f"UPDATE {self.table} SET read = ?, read_at = ? "
            "WHERE notification_id = ? AND user_id = ?",
            (1 if read else 0, to_iso(utcnow()) if read else None,
             notification_id, user_id))
        return self.get(notification_id)

    def mark_all_read(self, user_id: int) -> int:
        cur = self._exec(
            f"UPDATE {self.table} SET read = 1, read_at = ? "
            "WHERE user_id = ? AND read = 0", (to_iso(utcnow()), user_id))
        return cur.rowcount

    def notify_role(self, role: str, *, title: str, body: str = "",
                    kind: str = "general", link: str | None = None,
                    created_by: str | None = None) -> int:
        """Send one notification to every active account holding a role."""
        rows = self._exec(
            "SELECT user_id FROM users WHERE role = ? AND active = 1 "
            "AND expires_at IS NULL", (role,)).fetchall()
        for row in rows:
            self.insert(user_id=row["user_id"], title=title, body=body,
                        kind=kind, link=link, created_by=created_by)
        return len(rows)


class InviteRepository:
    """One-time staff invite codes; accounts made with them start pending."""

    table = "invites"

    def __init__(self, db):
        self.db = db

    def _exec(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        return self.db.execute(sql, params)

    def insert(self, *, role: str, unit_id: int | None, label: str | None,
               created_by: str, expires_at: str, max_uses: int = 1) -> dict:
        code = secrets.token_urlsafe(9)
        while self.get_by_code(code):
            code = secrets.token_urlsafe(9)
        self._exec(
            f"INSERT INTO {self.table} "
            "(code, role, unit_id, label, created_by, created_at, expires_at, max_uses) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (code, role, unit_id, label, created_by, to_iso(utcnow()),
             expires_at, max_uses))
        return self.get_by_code(code)

    def get_by_code(self, code: str) -> dict | None:
        row = self._exec(f"SELECT * FROM {self.table} WHERE code = ?",
                         (code,)).fetchone()
        return dict(row) if row else None

    def list_all(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self._exec(
            f"SELECT * FROM {self.table} "
            "ORDER BY invite_id DESC LIMIT ?", (limit,)).fetchall()]

    def consume(self, code: str) -> dict | None:
        """Mark one use of a live invite; returns it or None when spent."""
        invite = self.get_by_code(code)
        if not invite or invite["revoked"]:
            return None
        now = to_iso(utcnow())
        if invite["expires_at"] <= now or \
                invite["used_count"] >= invite["max_uses"]:
            return None
        self._exec(f"UPDATE {self.table} SET used_count = used_count + 1 "
                   "WHERE invite_id = ?",
                   (invite["invite_id"],))
        return invite

    def revoke(self, invite_id: int) -> bool:
        cur = self._exec(f"UPDATE {self.table} SET revoked = 1 "
                         "WHERE invite_id = ?", (invite_id,))
        return cur.rowcount > 0


class PatientDepartmentRepository:
    """Which departments a patient belongs to (many-to-many)."""

    table = "patient_departments"

    def __init__(self, db):
        self.db = db

    def _exec(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        return self.db.execute(sql, params)

    def departments_for(self, patient_id: int) -> list[int]:
        rows = self._exec(
            "SELECT unit_id FROM patient_departments WHERE patient_id = ?",
            (patient_id,)).fetchall()
        return [r["unit_id"] for r in rows]

    def patients_for(self, unit_id: int) -> list[int]:
        rows = self._exec(
            "SELECT patient_id FROM patient_departments WHERE unit_id = ?",
            (unit_id,)).fetchall()
        return [r["patient_id"] for r in rows]

    def assign(self, patient_id: int, unit_id: int, by: str | None = None) -> None:
        self._exec(
            "INSERT INTO patient_departments (patient_id, unit_id, assigned_at, "
            "assigned_by) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(patient_id, unit_id) DO NOTHING",
            (patient_id, unit_id, to_iso(utcnow()), by))

    def unassign(self, patient_id: int, unit_id: int) -> None:
        self._exec("DELETE FROM patient_departments "
                   "WHERE patient_id = ? AND unit_id = ?",
                   (patient_id, unit_id))

    def set_departments(self, patient_id: int, unit_ids: list[int],
                        by: str | None = None) -> None:
        current = set(self.departments_for(patient_id))
        wanted = set(int(u) for u in unit_ids)
        for uid in wanted - current:
            self.assign(patient_id, uid, by)
        for uid in current - wanted:
            self.unassign(patient_id, uid)
        if current - wanted:
            p = self.db.execute("SELECT patient_number FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
            if p:
                emit_patient_descope_events(self.db, patient_id, p["patient_number"])

    def count_for_unit(self, unit_id: int) -> int:
        return int(self._exec(
            "SELECT COUNT(*) AS c FROM patient_departments pd "
            "JOIN patients p ON p.patient_id = pd.patient_id "
            "WHERE pd.unit_id = ? AND p.deleted = 0",
            (unit_id,)).fetchone()["c"])


def extend_repositories(repos: dict[str, Any]) -> dict[str, Any]:
    """Wire the access repositories into the shared repository map."""
    db = repos["patients"].db
    repos.setdefault("notifications", NotificationRepository(db))
    repos.setdefault("invites", InviteRepository(db))
    repos.setdefault("patient_departments", PatientDepartmentRepository(db))
    return repos


def emit_patient_descope_events(db, patient_id: int, patient_number: str) -> None:
    """Emit device-specific removal events for active workstations that lost access."""
    p = db.execute("SELECT origin_unit_id FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
    if not p:
        return
    origin_unit_id = p["origin_unit_id"]
    dept_rows = db.execute("SELECT unit_id FROM patient_departments WHERE patient_id = ?", (patient_id,)).fetchall()
    patient_units = {r["unit_id"] for r in dept_rows}
    if origin_unit_id is not None:
        patient_units.add(origin_unit_id)

    # Active, assigned workstations
    devices = db.execute(
        "SELECT device_id, unit_id FROM devices WHERE unit_id IS NOT NULL AND revoked_at IS NULL"
    ).fetchall()
    now = to_iso(utcnow())

    for dev in devices:
        dev_id = dev["device_id"]
        dev_unit = dev["unit_id"]
        # Workstation is authorized if dev_unit or any of its descendants matches patient_units
        allowed = db.execute(
            """
            WITH RECURSIVE allowed(unit_id) AS (
                SELECT unit_id FROM units WHERE unit_id = ?
                UNION ALL
                SELECT u.unit_id FROM units u JOIN allowed a ON u.parent_id = a.unit_id
            ) SELECT 1 FROM allowed WHERE unit_id IN (%s) LIMIT 1
            """ % (",".join("?" for _ in patient_units) if patient_units else "NULL"),
            (dev_unit, *patient_units) if patient_units else (dev_unit,),
        ).fetchone()

        if not allowed:
            # Check if this device previously had access / received a change for this patient
            had_access = db.execute(
                """
                SELECT 1 FROM sync_change_log
                WHERE patient_id = ? AND seq <= (
                    SELECT COALESCE(MAX(seq), 0) FROM sync_change_log
                ) LIMIT 1
                """,
                (patient_id,),
            ).fetchone()
            if had_access:
                # Insert de-scope event if not already recorded pending after latest change
                already_queued = db.execute(
                    "SELECT 1 FROM sync_scope_events WHERE device_id = ? AND patient_number = ? AND action = 'de_scoped'",
                    (dev_id, patient_number),
                ).fetchone()
                if not already_queued:
                    db.execute(
                        "INSERT INTO sync_scope_events (device_id, patient_id, patient_number, action, created_at) "
                        "VALUES (?, ?, ?, 'de_scoped', ?)",
                        (dev_id, patient_id, patient_number, now),
                    )
