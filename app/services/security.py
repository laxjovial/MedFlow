"""Security: password hashing, role permissions, and login checks.

Roles are coarse-grained; permissions are the vocabulary both the desktop
UI (menu visibility) and the API (route guards) consume. Nothing else in
the codebase decides "can this user do this" — they ask here.
"""

from __future__ import annotations

from passlib.context import CryptContext

from app.errors import AuthenticationError, AuthorizationError
from app.models.org import (
    ROLE_ADMIN,
    ROLE_NURSE,
    ROLE_PHYSICIAN,
    ROLE_RECEPTION,
    ROLE_TECHNICIAN,
    ROLE_VIEWER,
    User,
)
from app.storage.repositories import UserRepository

# Argon2 is the primary scheme; bcrypt remains readable for migrations.
_pwd = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

# The full permission vocabulary. UI navigation and API guards both key
# off these names so a role change instantly re-shapes the whole app.
PERMISSIONS = {
    "patients.view",
    "patients.create",
    "patients.edit",
    "patients.delete",
    "records.view",
    "records.edit",
    "appointments.view",
    "appointments.manage",
    "reports.view",
    "export.data",
    "users.manage",
    "settings.manage",
    "sync.manage",
    "audit.view",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_ADMIN: PERMISSIONS,
    ROLE_PHYSICIAN: {
        "patients.view", "patients.create", "patients.edit",
        "records.view", "records.edit",
        "appointments.view", "appointments.manage",
        "reports.view", "export.data", "audit.view",
    },
    ROLE_NURSE: {
        "patients.view", "patients.create", "patients.edit",
        "records.view", "records.edit",
        "appointments.view", "appointments.manage", "reports.view",
    },
    ROLE_TECHNICIAN: {
        "patients.view", "records.view", "records.edit",
        "appointments.view", "reports.view",
    },
    ROLE_RECEPTION: {
        "patients.view", "patients.create", "patients.edit",
        "appointments.view", "appointments.manage", "reports.view",
    },
    ROLE_VIEWER: {"patients.view", "records.view", "appointments.view"},
}


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS[ROLE_VIEWER])


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _pwd.verify(plain, hashed)
    except Exception:
        return False


class SecurityService:
    """Login, user administration, and permission checks."""

    def __init__(self, users: UserRepository, actor: str = "system"):
        self.users = users
        self.actor = actor

    # ------------------------------------------------------------------ #
    # users

    def create_user(self, username: str, display_name: str, password: str,
                    role: str, unit_id: int | None = None) -> User:
        if role not in ROLE_PERMISSIONS:
            raise AuthorizationError(f"Unknown role: {role}")
        if len(password) < 8:
            raise AuthenticationError("Password must be at least 8 characters.")
        if self.users.get_by_username(username):
            raise AuthenticationError(f"Username '{username}' is already taken.")
        user = User(
            username=username,
            display_name=display_name,
            role=role,
            unit_id=unit_id,
            password_hash=hash_password(password),
        )
        return self.users.insert(user)

    def change_password(self, user_id: int, new_password: str) -> None:
        if len(new_password) < 8:
            raise AuthenticationError("Password must be at least 8 characters.")
        user = self.users.get(user_id)
        if not user:
            raise AuthenticationError("User not found.")
        user.password_hash = hash_password(new_password)
        self.users.update(user, ["password_hash"])

    def authenticate(self, username: str, password: str) -> User:
        user = self.users.get_by_username(username)
        if not user or not user.active:
            raise AuthenticationError("Invalid username or password.")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid username or password.")
        return user

    # ------------------------------------------------------------------ #
    # permissions

    def can(self, user: User | None, permission: str) -> bool:
        if user is None or not user.active:
            return False
        return permission in permissions_for(user.role)

    def require(self, user: User | None, permission: str) -> None:
        if not self.can(user, permission):
            raise AuthorizationError(
                f"Role '{getattr(user, 'role', 'anonymous')}' lacks '{permission}'."
            )

    def permissions(self, user: User | None) -> set[str]:
        if user is None:
            return set()
        return permissions_for(user.role)
