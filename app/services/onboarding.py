"""Notifications and the staff onboarding flow (invite → pending → approve).

The bell feed, appointment-to-user assignment notices, and the approval
chain: an administrator mints an invite code, the new hire signs up
through it, and the account stays *pending* — unable to see anything —
until an administrator approves it. Every step (invite created, account
pending, approved, declined) is stamped in the audit trail, so "who
approved whom, and who appointed that approver" is always answerable.
"""

from __future__ import annotations

from datetime import timedelta

from app.errors import NotFoundError, ValidationError
from app.models import AuditEvent, User
from app.models.org import ALL_ROLES
from app.utils.dates import to_iso, utcnow

PENDING_ROLE = "__pending__"  # sentinel: not a real role, blocks all access


class NotificationService:
    """Create and read the per-user notification feed."""

    def __init__(self, repos, actor: str = "system"):
        self.repos = repos
        self.notifs = repos["notifications"]
        self.actor = actor

    def send(self, user_id: int, title: str, body: str = "",
             kind: str = "general", link: str | None = None) -> dict:
        return self.notifs.insert(user_id=user_id, title=title, body=body,
                                  kind=kind, link=link, created_by=self.actor)

    def send_to_role(self, role: str, title: str, body: str = "",
                     kind: str = "general", link: str | None = None) -> int:
        return self.notifs.notify_role(role, title=title, body=body,
                                       kind=kind, link=link,
                                       created_by=self.actor)

    def feed(self, user_id: int, limit: int = 50) -> list[dict]:
        return self.notifs.list_for_user(user_id, limit)

    def unread_count(self, user_id: int) -> int:
        return self.notifs.unread_count(user_id)

    def mark(self, user_id: int, notification_id: int,
             read: bool) -> dict | None:
        row = self.notifs.get(notification_id)
        if not row or row["user_id"] != user_id:
            raise NotFoundError("Notification not found.")
        return self.notifs.mark_read(notification_id, user_id, read)

    def mark_all(self, user_id: int) -> int:
        return self.notifs.mark_all_read(user_id)

    def notify_assignment(self, appointment: dict, patient_name: str) -> None:
        """An appointment was booked naming a provider — tell every
        account whose display name matches, plus administrators."""
        provider = (appointment.get("provider") or "").strip()
        title = f"Appointment: {patient_name}"
        body = (f"{appointment.get('scheduled_at', '')} — "
                f"{appointment.get('reason') or 'no reason recorded'}")
        link = f"/app?view=appointments&patient={appointment.get('patient_id')}"
        told = 0
        if provider:
            for user in self.repos["users"].list(active_only=True):
                if user.display_name.lower() == provider.lower():
                    self.send(user.user_id, title, body, kind="appointment",
                              link=link)
                    told += 1
        if told == 0:
            # nobody matched by name — let administrators route it
            self.send_to_role("administrator", f"Unassigned appointment: "
                              f"{patient_name}", body, kind="appointment",
                              link=link)


class OnboardingService:
    """Invite codes, pending accounts, and the approval chain."""

    def __init__(self, repos, actor: str = "system"):
        self.repos = repos
        self.invites = repos["invites"]
        self.users = repos["users"]
        self.audit = repos["audit"]
        self.actor = actor

    # ------------------------------------------------------------------ #
    # invites

    def create_invite(self, role: str, unit_id: int | None = None,
                      label: str | None = None, days_valid: int = 14,
                      max_uses: int = 1) -> dict:
        if role not in ALL_ROLES:
            raise ValidationError({"role": [f"Unknown role '{role}'."]})
        if days_valid < 1 or days_valid > 90:
            raise ValidationError({"days_valid": [
                "Invites last between 1 and 90 days."]})
        if max_uses < 1 or max_uses > 100:
            raise ValidationError({"max_uses": [
                "An invite can be used 1 to 100 times."]})
        invite = self.invites.insert(
            role=role, unit_id=unit_id, label=(label or "").strip() or None,
            created_by=self.actor,
            expires_at=to_iso(utcnow() + timedelta(days=days_valid)),
            max_uses=max_uses)
        self._audit("created", "invite", invite["code"],
                    f"Invite for a {role} — '{label or 'no note'}', "
                    f"valid {days_valid} day(s)")
        return invite

    def revoke_invite(self, invite_id: int) -> None:
        if not self.invites.revoke(invite_id):
            raise NotFoundError("Invite not found.")
        self._audit("updated", "invite", str(invite_id), "Invite revoked")

    def list_invites(self) -> list[dict]:
        return self.invites.list_all()

    def peek(self, code: str) -> dict | None:
        """Check a code without consuming a use (signup-page pre-check)."""
        invite = self.invites.get_by_code((code or "").strip())
        if not invite or invite["revoked"]:
            return None
        now = to_iso(utcnow())
        if invite["expires_at"] <= now or \
                invite["used_count"] >= invite["max_uses"]:
            return None
        return invite

    def redeem(self, code: str) -> dict:
        """Validate an invite code for the signup page (no account made)."""
        invite = self.invites.consume(code.strip())
        if not invite:
            raise ValidationError({"code": [
                "This invite code is not valid (expired, used up, or "
                "withdrawn). Ask your administrator for a new one."]})
        return invite

    # ------------------------------------------------------------------ #
    # pending accounts & approval

    def signup_with_invite(self, code: str, username: str,
                           display_name: str, password: str,
                           email: str | None = None) -> User:
        """Redeem an invite: account is created but stays pending."""
        from app.services.security import SecurityService
        invite = self.redeem(code)
        security = SecurityService(self.users, actor=self.actor)
        user = security.create_user(
            username=username, display_name=display_name,
            password=password, role=invite["role"],
            unit_id=invite["unit_id"], job_title=None, phone=None)
        # email is optional extra
        if email and not user.email:
            user.email = email
            self.users.update(user, ["email"])
        user.role = PENDING_ROLE
        self.users.update(user, ["role"])
        self._audit("created", "user", str(user.user_id),
                    f"Signed up with invite '{invite['label'] or invite['code'][:6]}…' "
                    f"— awaiting approval (role {invite['role']})")
        self.notifs_admins(f"New staff waiting approval: {user.display_name}",
                           f"Username {user.username} signed up with an "
                           "invite and needs an administrator's approval.")
        return user

    def approve(self, user_id: int, note: str = "") -> User:
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError(f"User #{user_id} does not exist.")
        if user.role != PENDING_ROLE:
            raise ValidationError({"user": [
                f"{user.display_name} is not waiting for approval."]})
        intended = self._intended_role(user)
        user.role = intended
        user.active = True
        self.users.update(user, ["role", "active"])
        self._audit("approved", "user", str(user_id),
                    f"Approved '{user.username}' as {intended}"
                    + (f" — {note}" if note else ""))
        self.repos["notifications"].insert(
            user_id=user_id, title="Your account was approved",
            body="You can now sign in and start working.",
            kind="account", created_by=self.actor)
        return user

    def decline(self, user_id: int, note: str = "") -> User:
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError(f"User #{user_id} does not exist.")
        if user.role != PENDING_ROLE:
            raise ValidationError({"user": [
                f"{user.display_name} is not waiting for approval."]})
        user.active = False
        self.users.update(user, ["active"])
        self._audit("declined", "user", str(user_id),
                    f"Declined '{user.username}'"
                    + (f" — {note}" if note else ""))
        return user

    def pending_accounts(self) -> list[User]:
        return [u for u in self.users.list(active_only=False)
                if u.role == PENDING_ROLE]

    # ------------------------------------------------------------------ #
    # helpers

    def _intended_role(self, user: User) -> str:
        """The role the invite promised, recovered from the audit trail."""
        for event in self.audit.history_for_entity("user", str(user.user_id)):
            text = str(getattr(event, "details", ""))
            if "awaiting approval (role" in text:
                return text.split("awaiting approval (role", 1)[1] \
                           .split(")", 1)[0].strip()
        return "viewer"

    def notifs_admins(self, title: str, body: str) -> None:
        self.repos["notifications"].notify_role(
            "administrator", title=title, body=body, kind="account",
            created_by=self.actor)

    def _audit(self, action: str, entity_type: str, entity_id, details: str):
        self.audit.record(AuditEvent(
            action=action, entity_type=entity_type,
            entity_id=str(entity_id), details=details, actor=self.actor))
