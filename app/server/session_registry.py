"""Persistent authentication-session lifecycle backed by MedFlow SQLite.

Only opaque token identifiers are stored; bearer/cookie token material is
never persisted. Expired records are inert and can be pruned independently.
"""
from __future__ import annotations

import time


class SessionRegistry:
    def __init__(self, database):
        self.database = database

    def register(self, jti: str, user_id: int, expires_at: int,
                 client_type: str = "api", device_id: str | None = None) -> None:
        now = int(time.time())
        self.database.execute(
            """
            INSERT INTO auth_sessions
                (jti, user_id, client_type, issued_at, expires_at, revoked_at, device_id)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (jti, int(user_id), client_type, now, int(expires_at), device_id),
        )

    def get(self, jti: str) -> dict | None:
        row = self.database.execute(
            "SELECT jti, user_id, client_type, device_id, expires_at, revoked_at "
            "FROM auth_sessions WHERE jti = ?", (jti,),
        ).fetchone()
        return dict(row) if row else None

    def is_active(self, jti: str, now: int | None = None) -> bool:
        if not jti:
            return False
        now = int(time.time()) if now is None else int(now)
        row = self.database.execute(
            "SELECT expires_at, revoked_at FROM auth_sessions WHERE jti = ?",
            (jti,),
        ).fetchone()
        return bool(row and row["revoked_at"] is None and int(row["expires_at"]) >= now)

    def revoke(self, jti: str, now: int | None = None) -> bool:
        if not jti:
            return False
        now = int(time.time()) if now is None else int(now)
        cursor = self.database.execute(
            "UPDATE auth_sessions SET revoked_at = ? "
            "WHERE jti = ? AND revoked_at IS NULL",
            (now, jti),
        )
        return cursor.rowcount == 1

    def revoke_user(self, user_id: int, now: int | None = None) -> int:
        now = int(time.time()) if now is None else int(now)
        cursor = self.database.execute(
            "UPDATE auth_sessions SET revoked_at = ? "
            "WHERE user_id = ? AND revoked_at IS NULL AND expires_at >= ?",
            (now, int(user_id), now),
        )
        return cursor.rowcount

    def revoke_device(self, device_id: str, now: int | None = None) -> int:
        """Revoke every active desktop session bound to one workstation."""
        now = int(time.time()) if now is None else int(now)
        cursor = self.database.execute(
            "UPDATE auth_sessions SET revoked_at = ? "
            "WHERE device_id = ? AND client_type = 'desktop' "
            "AND revoked_at IS NULL AND expires_at >= ?",
            (now, device_id, now),
        )
        return cursor.rowcount

    def prune_expired(self, now: int | None = None) -> int:
        now = int(time.time()) if now is None else int(now)
        cursor = self.database.execute(
            "DELETE FROM auth_sessions WHERE expires_at < ?",
            (now,),
        )
        return cursor.rowcount
