"""Organization service: the facility tree, staff accounts, and devices.

The unit tree is configurable rather than hardcoded — an independent
practice is a single root; a hospital adds branches and departments
without schema changes.
"""

from __future__ import annotations

from app.errors import NotFoundError, ValidationError
from app.models import AuditEvent, Device, Unit, User
from app.models.audit import EVENT_CREATED, EVENT_UPDATED
from app.models.org import ALL_ROLES
from app.services.security import SecurityService
from app.utils.dates import utcnow


class OrgService:
    """Manage units, staff users, and known workstations."""

    def __init__(self, repos, security: SecurityService,
                 actor: str = "system", device_id: str = "workstation-01"):
        self.repos = repos
        self.security = security
        self.actor = actor
        self.device_id = device_id

    # ------------------------------------------------------------------ #
    # units

    def ensure_root(self, name: str = "Main Facility") -> Unit:
        return self.repos["units"].ensure_root(name)

    def list_units(self) -> list[Unit]:
        return self.repos["units"].list()

    def create_unit(self, name: str, kind: str = "department",
                    parent_id: int | None = None) -> Unit:
        name = (name or "").strip()
        if not name:
            raise ValidationError({"name": ["Unit name is required."]})
        if kind not in ("organization", "branch", "department"):
            raise ValidationError({"kind": [f"Unknown unit kind '{kind}'."]})
        if parent_id and not self.repos["units"].get(parent_id):
            raise NotFoundError(f"Parent unit #{parent_id} does not exist.")
        unit = self.repos["units"].insert(Unit(name=name, kind=kind, parent_id=parent_id))
        self.repos["audit"].record(AuditEvent(
            action=EVENT_CREATED, entity_type="unit", entity_id=str(unit.unit_id),
            details=f"Created {kind} '{name}'", actor=self.actor,
        ))
        return unit

    # ------------------------------------------------------------------ #
    # users

    def list_users(self) -> list[User]:
        return self.repos["users"].list(active_only=False)

    def create_user(self, username: str, display_name: str, password: str,
                    role: str, unit_id: int | None = None) -> User:
        user = self.security.create_user(username, display_name, password, role, unit_id)
        self.repos["audit"].record(AuditEvent(
            action=EVENT_CREATED, entity_type="user", entity_id=str(user.user_id),
            details=f"Created {role} account '{username}'", actor=self.actor,
        ))
        return user

    def set_user_active(self, user_id: int, active: bool) -> User:
        user = self.repos["users"].get(user_id)
        if not user:
            raise NotFoundError(f"User #{user_id} does not exist.")
        user.active = bool(active)
        self.repos["users"].update(user, ["active"])
        self.repos["audit"].record(AuditEvent(
            action=EVENT_UPDATED, entity_type="user", entity_id=str(user.user_id),
            details=f"Account {'enabled' if active else 'disabled'}: {user.username}",
            actor=self.actor,
        ))
        return user

    def change_role(self, user_id: int, role: str) -> User:
        if role not in ALL_ROLES:
            raise ValidationError({"role": [f"Unknown role '{role}'."]})
        user = self.repos["users"].get(user_id)
        if not user:
            raise NotFoundError(f"User #{user_id} does not exist.")
        old = user.role
        user.role = role
        self.repos["users"].update(user, ["role"])
        self.repos["audit"].record(AuditEvent(
            action=EVENT_UPDATED, entity_type="user", entity_id=str(user.user_id),
            details=f"Role changed {old} -> {role} for {user.username}",
            actor=self.actor,
        ))
        return user

    def change_password(self, user_id: int, new_password: str) -> None:
        self.security.change_password(user_id, new_password)
        self.repos["audit"].record(AuditEvent(
            action=EVENT_UPDATED, entity_type="user", entity_id=str(user_id),
            details="Password changed", actor=self.actor,
        ))

    # ------------------------------------------------------------------ #
    # devices

    def register_device(self, device_id: str, label: str | None = None,
                        unit_id: int | None = None) -> Device:
        device_id = (device_id or "").strip()
        if not device_id:
            raise ValidationError({"device_id": ["Device ID is required."]})
        device = Device(
            device_id=device_id, label=label, unit_id=unit_id,
            registered_at=utcnow(), last_seen_at=utcnow(),
        )
        self.repos["devices"].register(device)
        return device

    def list_devices(self) -> list[Device]:
        return self.repos["devices"].list()

    def touch_device(self, device_id: str) -> None:
        device = self.repos["devices"].get(device_id)
        if device:
            device.last_seen_at = utcnow()
            self.repos["devices"].register(device)
