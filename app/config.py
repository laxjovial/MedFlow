"""Runtime configuration — nothing about the environment is hardcoded.

Every mutable path, identity, storage mode, and integration knob lives in a
``Config`` instance backed by ``config.json`` next to the database. Defaults
are sensible; users can change everything through Settings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from app.utils.dates import utcnow
from app.utils.json_utils import dumps

CONFIG_VERSION = 1

STORAGE_LOCAL = "local"
STORAGE_NETWORK = "network"


@dataclass
class SyncConfig:
    enabled: bool = False
    mode: str = "manual"            # manual | automatic | auto_plus_manual
    frequency_minutes: int = 15
    sync_on_startup: bool = False
    sync_before_exit: bool = False
    last_sync_at: str | None = None


@dataclass
class CloudBackupConfig:
    enabled: bool = False
    provider: str = "none"          # none | s3 | gdrive | webdav
    bucket: str | None = None
    auto_upload: bool = False
    last_upload_at: str | None = None


@dataclass
class AutomationConfig:
    enabled: bool = True
    run_on_startup: bool = True
    interval_minutes: int = 30


@dataclass
class Config:
    """Serializable application settings persisted to ``config.json``."""

    config_version: int = CONFIG_VERSION
    facility_name: str = "Independent Practice"
    storage_mode: str = STORAGE_LOCAL
    api_base_url: str | None = None
    device_id: str = "workstation-01"
    database_path: str | None = None
    data_dir: str | None = None
    backup_dir: str | None = None
    export_dir: str | None = None
    log_dir: str | None = None
    theme: str = "system"           # system | light | dark
    allow_open_signup: bool = True  # /api/auth/signup toggle for private deployments
    sync: SyncConfig = field(default_factory=SyncConfig)
    cloud_backup: CloudBackupConfig = field(default_factory=CloudBackupConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)

    # ---------- persistence ----------

    @classmethod
    def config_path(cls, data_dir: Path) -> Path:
        return data_dir / "config.json"

    @classmethod
    def load(cls, data_dir: Path) -> "Config":
        path = cls.config_path(data_dir)
        cfg = cls()
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                known = asdict(cls())
                _merge_known(cfg, raw, known)
            except (json.JSONDecodeError, OSError):
                pass
        cfg.data_dir = str(data_dir)
        return cfg

    def save(self, data_dir: Path | None = None) -> None:
        data_dir = Path(data_dir or self.data_dir or ".")
        data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path(data_dir).write_text(dumps(asdict(self)), encoding="utf-8")

    # ---------- derived paths (never hardcoded at call sites) ----------

    def resolve_data_dir(self, base: Path) -> Path:
        return Path(self.data_dir) if self.data_dir else base / "data"

    def resolve_database_path(self, base: Path) -> Path:
        if self.database_path:
            return Path(self.database_path)
        return self.resolve_data_dir(base) / "medflow.db"

    def resolve_backup_dir(self, base: Path) -> Path:
        if self.backup_dir:
            return Path(self.backup_dir)
        return self.resolve_data_dir(base) / "backups"

    def resolve_export_dir(self, base: Path) -> Path:
        if self.export_dir:
            return Path(self.export_dir)
        return self.resolve_data_dir(base) / "exports"

    def resolve_log_dir(self, base: Path) -> Path:
        if self.log_dir:
            return Path(self.log_dir)
        return self.resolve_data_dir(base) / "logs"

    def mark_synced(self, when: str | None = None) -> None:
        self.sync.last_sync_at = when or utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    def is_network_mode(self) -> bool:
        return self.storage_mode == STORAGE_NETWORK and bool(self.api_base_url)


def _merge_known(cfg: "Config", raw: dict, known: dict) -> None:
    """Copy only known keys from raw into cfg, recursing into dataclasses."""
    for key, value in raw.items():
        if key not in known:
            continue
        current = getattr(cfg, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_known(current, value, asdict(type(current)()))
        else:
            setattr(cfg, key, value)
