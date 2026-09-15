"""Security: password hashing, role permissions, and login checks.

Roles are coarse-grained; permissions are the vocabulary both the desktop
UI (menu visibility) and the API (route guards) consume. Nothing else in
the codebase decides "can this user do this" — they ask here.
"""

from __future__ import annotations

import json
import secrets
from datetime import timedelta

from passlib.context import CryptContext

from app.errors import AuthenticationError, AuthorizationError
from app.models.org import (
    ROLE_ADMIN,
    ROLE_NURSE,
    ROLE_PHYSICIAN,
    ROLE_RECEPTION,
    ROLE_TEMPORARY,
    ROLE_TECHNICIAN,
    ROLE_VIEWER,
    User,
)
from app.storage.repositories import UserRepository
from app.utils.dates import to_iso, utcnow

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
    ROLE_TEMPORARY: {
        "patients.view",
    },
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


def _generate_password(length: int = 10) -> str:
    """Pronounceable-enough temporary password, no ambiguous characters."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


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
    """Login, signup, user administration, and permission checks."""

    def __init__(self, users: UserRepository, actor: str = "system"):
        self.users = users
        self.actor = actor

    # ------------------------------------------------------------------ #
    # signup

    def signup(self, username: str, display_name: str, password: str,
               email: str | None = None) -> User:
        """Self-service registration: the first account, or a viewer account
        when any administrator already exists."""
        if len(password or "") < 8:
            raise AuthenticationError("Password must be at least 8 characters.")
        if self.users.get_by_username(username):
            raise AuthenticationError(f"Username '{username}' is already taken.")
        if email and self.users.get_by_email(email):
            raise AuthenticationError(
                "An account with that email already exists — sign in instead.")
        role = ROLE_ADMIN if not self.users.list() else ROLE_VIEWER
        user = User(
            username=username,
            display_name=display_name or username,
            role=role,
            email=email or None,
            password_hash=hash_password(password),
        )
        return self.users.insert(user)

    # ------------------------------------------------------------------ #
    # users

    def create_user(self, username: str, display_name: str, password: str,
                    role: str, unit_id: int | None = None,
                    job_title: str | None = None,
                    phone: str | None = None) -> User:
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
            job_title=job_title or None,
            phone=phone or None,
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

    # ------------------------------------------------------------------ #
    # temporary access

    def create_temporary_user(self, creator: User | None, label: str,
                              hours: float, patient_ids: list[int],
                              password: str | None = None) -> tuple[User, str]:
        """Create a scoped, time-limited viewer account; returns (user, password)."""
        if creator is not None:
            self.require(creator, "users.manage")
        if hours <= 0 or hours > 24 * 30:
            raise AuthenticationError("Access window must be 1 hour to 30 days.")
        if not patient_ids:
            raise AuthenticationError(
                "Pick at least one patient the visitor may see.")
        generated = password or _generate_password()
        username = "guest_" + secrets.token_hex(3)
        while self.users.get_by_username(username):
            username = "guest_" + secrets.token_hex(3)
        expires = utcnow() + timedelta(hours=hours)
        user = User(
            username=username,
            display_name=label.strip() or "Visitor",
            role=ROLE_TEMPORARY,
            email=None,
            password_hash=hash_password(generated),
            expires_at=to_iso(expires),
            scope_patient_ids=json.dumps(patient_ids),
        )
        return self.users.insert(user), generated

    def authenticate(self, username: str, password: str) -> User:
        user = self.users.get_by_username(username)
        if not user or not user.active:
            raise AuthenticationError("Invalid username or password.")
        if user.is_expired(to_iso(utcnow())):
            raise AuthenticationError(
                "This temporary access has expired. Ask the staff member who "
                "created it for a new one.")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid username or password.")
        return user

    def authenticate_google(self, google_sub: str, email: str,
                            display_name: str) -> User:
        """Sign in (and provision on first use) a Google-verified account.

        Email is taken from the verified Google profile, never self-reported.
        Temporary accounts must use the credentials created for them.
        """
        existing = self.users.get_by_email(email)
        if existing:
            if existing.auth_provider == "password":
                raise AuthenticationError(
                    "This email has a password account — sign in with your "
                    "password instead.")
            if existing.is_expired(to_iso(utcnow())):
                raise AuthenticationError(
                    "This temporary access has expired.")
            if not existing.active:
                raise AuthenticationError("Account is inactive.")
            return existing

        username = email.split("@")[0].replace(".", "_").lower()
        if self.users.get_by_username(username):
            username = f"{username}_{google_sub[-4:]}"
        user = User(
            username=username,
            display_name=display_name or email,
            role=ROLE_ADMIN if not self.users.list() else ROLE_VIEWER,
            email=email,
            auth_provider="google",
        )
        return self.users.insert(user)

    def pair_workstation(self, identity: dict) -> User:
        """Admit a desktop workstation using a one-time pairing code.

        The identity was authenticated by the web server (password or Google);
        this mirrors the account here so the workstation has a real local user
        with the same role. A Google-paired account carries no password — it
        signs in through pairing — while the first-ever pairing may bootstrap
        the administrator when the database has no accounts yet.
        """
        email = identity.get("email") or ""
        google_sub = str(identity.get("sub") or "")

        if identity.get("auth_provider") == "google":
            existing = self.users.get_by_email(email) if email else None
            if existing:
                if not existing.active:
                    raise AuthenticationError("Account is inactive.")
                if existing.is_expired(to_iso(utcnow())):
                    raise AuthenticationError("This temporary access has expired.")
                return existing
            username = email.split("@")[0].replace(".", "_").lower() if email \
                else f"paired_{google_sub[-4:]}"
            if self.users.get_by_username(username):
                username = f"{username}_{google_sub[-4:]}"
            user = User(
                username=username,
                display_name=identity.get("display_name") or email or username,
                role=ROLE_ADMIN if not self.users.list() else ROLE_VIEWER,
                email=email or None,
                auth_provider="google",
            )
            return self.users.insert(user)

        existing = self.users.get_by_username(identity.get("username") or "")
        if existing:
            if not existing.active:
                raise AuthenticationError("Account is inactive.")
            if existing.is_expired(to_iso(utcnow())):
                raise AuthenticationError("This temporary access has expired.")
            return existing
        raise AuthenticationError(
            "Paired account no longer exists on this server.")

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
