"""FastAPI dependencies: authentication and service wiring.

Every route receives fully constructed services bound to the requesting
user's identity, so business code never parses headers or touches raw
connection state.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.errors import AuthorizationError, NotFoundError
from app.server.tokens import TokenError, verify
from app.services.patients import PatientService
from app.services.records import RecordsService
from app.services.reports import ReportsService
from app.services.security import permissions_for
from app.utils.dates import to_iso, utcnow


def current_user(request: Request) -> dict:
    """Validate the bearer token, load the live user, derive permissions.

    Permissions are resolved from the database on every request (not baked
    into the token), so a role change applies immediately, a deactivated
    account loses access instantly, and an expired temporary account is
    cut off mid-session rather than at next login.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = verify(token, request.app.state.token_secret)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    user = request.app.state.repos["users"].get(payload.get("sub", 0))
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Account is inactive")
    if user.is_expired(to_iso(utcnow())):
        raise HTTPException(status_code=401, detail="Temporary access has expired")
    return {
        "sub": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "temporary": user.role == "temporary",
        "scope_patient_ids": user.scoped_patient_ids() if user.role == "temporary" else None,
        "expires_at": user.expires_at,
        "permissions": sorted(permissions_for(user.role)),
    }


def require(user: dict, permission: str) -> None:
    """403 unless the user's live role carries the permission."""
    if permission not in set(user.get("permissions", [])):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.get('role')}' lacks '{permission}'",
        )


def _actor(user: dict) -> str:
    return user.get("username") or "unknown"


def _device(request: Request) -> str:
    return request.app.state.config.device_id if request.app.state.config else "server"


def get_patient_service(request: Request, user=Depends(current_user)) -> PatientService:
    return PatientService(
        request.app.state.repos, actor=_actor(user), device_id=_device(request),
        temporary_user=request.app.state.repos["users"].get(user["sub"])
        if user.get("temporary") else None,
    )


def get_records_service(request: Request, user=Depends(current_user)) -> RecordsService:
    return RecordsService(
        request.app.state.repos, actor=_actor(user), device_id=_device(request)
    )


def get_reports_service(request: Request, user=Depends(current_user)) -> ReportsService:
    return ReportsService(request.app.state.repos)
