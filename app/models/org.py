"""Identity and organization models.

Units form a configurable tree — Organization → Branch → Department → any
custom kind — instead of hardcoded department names. Users, devices, and
shift assignments attach to any node of that tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models._serial import serializable

KIND_ORG = "organization"
KIND_BRANCH = "branch"
KIND_DEPARTMENT = "department"

ROLE_ADMIN = "administrator"
ROLE_PHYSICIAN = "physician"
ROLE_NURSE = "nurse"
ROLE_TECHNICIAN = "technician"
ROLE_RECEPTION = "reception"
ROLE_VIEWER = "viewer"
ALL_ROLES = (ROLE_ADMIN, ROLE_PHYSICIAN, ROLE_NURSE, ROLE_TECHNICIAN,
             ROLE_RECEPTION, ROLE_VIEWER)


@serializable("created_at")
@dataclass
class Unit:
    """A node in the facility tree (organization, branch, department...)."""

    name: str
    kind: str = KIND_DEPARTMENT
    parent_id: int | None = None
    unit_id: int | None = None
    created_at: datetime | None = None


@serializable(None)
@dataclass
class User:
    """A staff account. Roles are coarse; permissions refine them later."""

    username: str
    display_name: str
    role: str = ROLE_VIEWER
    unit_id: int | None = None
    password_hash: str | None = None
    active: bool = True
    created_at: datetime | None = None
    user_id: int | None = None


@serializable("registered_at")
@dataclass
class Device:
    """A workstation known to MedFlow; used for sync attribution."""

    device_id: str
    label: str | None = None
    unit_id: int | None = None
    last_seen_at: datetime | None = None
    registered_at: datetime | None = None
    row_id: int | None = None


@serializable("starts_at", "ends_at")
@dataclass
class ShiftAssignment:
    """Places a user inside a unit for a time window (shift work)."""

    user_id: int
    unit_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    shift_id: int | None = None
