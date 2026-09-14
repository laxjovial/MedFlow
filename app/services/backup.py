"""Backup service: one-click snapshots, restore, rotation, and integrity.

Backups are plain SQLite files — no proprietary format — so a snapshot can
be copied to a USB stick, emailed to a colleague, or dropped into a cloud
folder and restored anywhere MedFlow runs.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from app.errors import RepositoryError
from app.utils.dates import to_iso, utcnow


class BackupService:
    """Snapshot, restore, list, and prune database backups."""

    def __init__(self, db_path: str | Path, backup_dir: str | Path,
                 keep: int = 10):
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.keep = max(1, int(keep))

    # ------------------------------------------------------------------ #
    # snapshot

    def create_backup(self, label: str | None = None) -> Path:
        """Consistent snapshot via the SQLite backup API (safe while open)."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = to_iso(utcnow()).replace(":", "").replace("-", "")[:15]
        suffix = f"_{label}" if label else ""
        target = self.backup_dir / f"medflow_{stamp}{suffix}.db"

        try:
            source = sqlite3.connect(str(self.db_path))
            destination = sqlite3.connect(str(target))
            with destination:
                source.backup(destination)
            destination.close()
            source.close()
        except sqlite3.Error as exc:
            raise RepositoryError(f"Backup failed: {exc}") from exc
        return target

    # ------------------------------------------------------------------ #
    # restore

    def restore_backup(self, backup_path: str | Path) -> None:
        """Replace the live database with a snapshot (overwrites the .db-wal)."""
        source = Path(backup_path)
        if not source.exists():
            raise RepositoryError(f"Backup not found: {source}")

        check = sqlite3.connect(str(source))
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        check.close()
        if result != "ok":
            raise RepositoryError(f"Backup file is corrupt: {result}")

        try:
            destination = sqlite3.connect(str(self.db_path))
            with destination:
                source_conn = sqlite3.connect(str(source))
                source_conn.backup(destination)
                source_conn.close()
            destination.close()
            # stale WAL/SHM would confuse the next open
            for stale in ("medflow.db-wal", "medflow.db-shm"):
                p = self.db_path.parent / stale
                if p.exists():
                    p.unlink()
        except sqlite3.Error as exc:
            raise RepositoryError(f"Restore failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # management

    def list_backups(self) -> list[dict]:
        """Snapshot inventory, newest first."""
        if not self.backup_dir.exists():
            return []
        items = []
        for path in sorted(self.backup_dir.glob("medflow_*.db"), reverse=True):
            stat = path.stat()
            items.append({
                "path": str(path),
                "name": path.name,
                "size_bytes": stat.st_size,
                "size_display": _human_size(stat.st_size),
            })
        return items

    def prune(self, keep: int | None = None) -> int:
        """Delete the oldest snapshots beyond the retention count."""
        keep = keep or self.keep
        backups = sorted(self.backup_dir.glob("medflow_*.db"))
        removed = 0
        for path in backups[:-keep] if len(backups) > keep else []:
            path.unlink()
            removed += 1
        return removed

    def verify(self, backup_path: str | Path) -> bool:
        check = sqlite3.connect(str(backup_path))
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        check.close()
        return result == "ok"


def _human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"
