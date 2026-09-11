"""Storage layer: SQLite engine, migrations, and repositories.

Only this package imports sqlite3. Everything above it works against
domain models, which is what keeps the local/network switch a one-line
configuration change instead of a rewrite.
"""

from app.storage.engine import Database, connect
from app.storage.repositories import (
    AppointmentRepository,
    AuditRepository,
    ClinicalRecordRepository,
    DeviceRepository,
    PatientRepository,
    StatsRepository,
    UnitRepository,
    UserRepository,
    build_repositories,
)
from app.storage.schema import SCHEMA_VERSION

__all__ = [
    "Database",
    "connect",
    "SCHEMA_VERSION",
    "PatientRepository",
    "ClinicalRecordRepository",
    "AppointmentRepository",
    "UserRepository",
    "UnitRepository",
    "DeviceRepository",
    "AuditRepository",
    "StatsRepository",
    "build_repositories",
]
