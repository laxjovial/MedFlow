"""Backup and restore.

A backup is a consistent snapshot of the SQLite file taken while the application is
running. Copying the file with the operating system is not safe for a database in
WAL mode — a copy taken mid-write can be torn — so the snapshot is produced through
SQLite's own online backup API, which is what :meth:`Database.backup_to` wraps.

Restoring replaces the live database, so it takes a safety copy of the current file
first. That way "restore the wrong backup" is itself recoverable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config.settings import AppSettings
from app.core.clock import Clock
from app.core.exceptions import BackupError
from app.core.logging import get_logger
from app.domain.enums import AuditAction, EntityType
from app.repositories.sqlite.connection import Database
from app.services.audit_service import AuditService

logger = get_logger(__name__)

#: Filename stamp. Colons are avoided so backups stay valid names on Windows.
_STAMP_FORMAT = "%Y%m%d-%H%M%S"


@dataclass
class BackupInfo:
    """A backup file on disk."""

    path: Path
    created_at: datetime
    size_bytes: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_label(self) -> str:
        """Human-readable size, so the settings view does not format bytes itself."""
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"  # pragma: no cover - unreachable


class BackupService:
    """Creates, lists and restores database backups."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        audit: AuditService,
        clock: Clock,
    ) -> None:
        self._database = database
        self._settings = settings
        self._audit = audit
        self._clock = clock

    # ---------- backups ----------

    def create_backup(self, *, actor: str, label: str = "") -> BackupInfo:
        """Take a snapshot of the database and return where it landed."""
        directory = self._settings.backup_directory
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackupError(f"Could not create the backup directory: {exc}") from exc

        stem = self._settings.database_path.stem
        stamp = self._clock.timestamp().replace(" ", "-").replace(":", "")
        suffix = f"-{_sanitise(label)}" if label else ""
        destination = directory / f"{stem}-{stamp}{suffix}.db"

        # Two backups inside the same second would otherwise collide.
        counter = 1
        while destination.exists():
            destination = directory / f"{stem}-{stamp}{suffix}-{counter}.db"
            counter += 1

        try:
            self._database.backup_to(destination)
        except Exception as exc:  # noqa: BLE001 - surfaced as a BackupError below
            raise BackupError(f"Backup failed: {exc}") from exc

        info = _describe(destination)

        self._audit.record(
            AuditAction.BACKUP,
            entity_type=EntityType.DATABASE,
            entity_id=info.name,
            actor=actor,
            details={"size_bytes": info.size_bytes, "label": label},
        )
        logger.info("Backup written to %s", destination)

        return info

    def list_backups(self) -> list[BackupInfo]:
        """Every backup on disk, newest first."""
        directory = self._settings.backup_directory
        if not directory.is_dir():
            return []

        backups = [
            _describe(path)
            for path in directory.glob("*.db")
            if path.is_file()
        ]
        backups.sort(key=lambda info: info.created_at, reverse=True)
        return backups

    def restore_backup(self, path: Path, *, actor: str) -> BackupInfo:
        """Replace the live database with a backup.

        The application must be restarted afterwards: the running process holds an
        open connection to the old file. That is reported to the caller rather than
        attempted here, because silently swapping a database underneath live views
        is exactly the kind of surprise a clinical tool should not spring.
        """
        source = Path(path)
        if not source.is_file():
            raise BackupError(f"No backup found at {source}")

        # Take a safety copy before overwriting anything.
        safety = self.create_backup(actor=actor, label="pre-restore")

        try:
            self._database.close()
            source.replace(self._settings.database_path)
            _remove_stale_journal_files(self._settings.database_path)
        except OSError as exc:
            raise BackupError(f"Could not restore the backup: {exc}") from exc

        self._audit.record(
            AuditAction.RESTORE_BACKUP,
            entity_type=EntityType.DATABASE,
            entity_id=source.name,
            actor=actor,
            details={"safety_backup": safety.name},
        )
        logger.warning("Database restored from %s", source)

        return safety


# ---------- helpers ----------


def _describe(path: Path) -> BackupInfo:
    stat = path.stat()
    return BackupInfo(
        path=path,
        created_at=datetime.fromtimestamp(stat.st_mtime),
        size_bytes=stat.st_size,
    )


def _sanitise(label: str) -> str:
    """Reduce a free-text label to something safe for a filename."""
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in label.strip()
    )
    return cleaned.strip("-")[:40]


def _remove_stale_journal_files(database_path: Path) -> None:
    """Delete ``-wal`` and ``-shm`` siblings of a replaced database.

    They belong to the database that was just overwritten. Leaving them behind
    would let SQLite apply the old write-ahead log to the new file.
    """
    for suffix in ("-wal", "-shm"):
        companion = database_path.with_name(database_path.name + suffix)
        if companion.exists():
            try:
                companion.unlink()
            except OSError:  # pragma: no cover - best effort
                logger.warning("Could not remove stale journal file %s", companion)
