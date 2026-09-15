"""FastAPI application factory: one codebase, two faces.

The API exposes exactly the service layer the desktop UI binds to — no
parallel logic. Permission checks use the same vocabulary as the desktop
menus, so a role change reshapes both faces at once.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.runtime_config import Config, SessionConfig
from app.errors import (
    MedFlowError,
    NotFoundError,
    ValidationError,
)
from app.server.deps import (
    current_user,
    get_patient_service,
    get_records_service,
    get_reports_service,
    require,
)
from app.server.pairing import PairingError, pairing
from app.server import sessions as sessions_policy
from app.server.tokens import issue
from app.services.offsite import (
    OffsiteBackupService,
    OffsiteError,
    load_keys,
    save_keys,
)

OPENAPI_METADATA = dict(
    title="MedFlow API",
    description=(
        "Local-first clinic management: patients, clinical records, "
        "appointments, reports, exports, and sync."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# request models


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False   # "keep me signed in"


class SignupRequest(BaseModel):
    username: str
    display_name: str
    password: str
    email: str | None = None


class GoogleLoginRequest(BaseModel):
    id_token: str
    remember: bool = False


class PairingStart(BaseModel):
    """Body for creating a one-time desktop pairing code."""

    label: str = "Desktop workstation"


class PairingRedeem(BaseModel):
    """Body for redeeming a pairing code (desktop side)."""

    code: str
    device_id: str = "workstation-01"


class AutomationRuleIn(BaseModel):
    name: str
    fact: str
    operator: str
    threshold: float
    action: str


class SessionPolicyIn(BaseModel):
    """Admin-settable session lifetimes (all optional, partial updates)."""

    token_ttl_hours: int | None = None
    remember_me_days: int | None = None
    sliding_refresh: bool | None = None


class UnitRename(BaseModel):
    name: str


class CloudBackupIn(BaseModel):
    """Off-site backup settings; credential fields are write-only."""

    enabled: bool | None = None
    provider: str | None = None          # none | s3 | webdav
    endpoint: str | None = None
    bucket: str | None = None
    prefix: str | None = None
    region: str | None = None
    auto_upload: bool | None = None
    keep_last_uploads: int | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    username: str | None = None
    password: str | None = None


class CloudPassphrase(BaseModel):
    passphrase: str


class TempUserRequest(BaseModel):
    label: str
    hours: float = 24
    patient_ids: list[int] = []


class PatientCreate(BaseModel):
    name: str
    age: int | None = None
    sex: str | None = None
    date_of_birth: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    blood_pressure: str | None = None
    heart_rate: int | None = None
    weight: float | None = None
    medical_history: str | None = None
    diagnosis: str | None = None
    notes: str | None = None
    department_id: str | int | None = None
    department: str | None = None


class PatientUpdate(BaseModel):
    name: str | None = None
    age: int | None = None
    sex: str | None = None
    date_of_birth: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    blood_pressure: str | None = None
    heart_rate: int | None = None
    weight: float | None = None
    medical_history: str | None = None
    diagnosis: str | None = None
    notes: str | None = None
    department_id: str | int | None = None
    department: str | None = None


class VitalsCreate(BaseModel):
    blood_pressure: str | None = None
    heart_rate: int | None = None
    temperature_c: float | None = None
    respiratory_rate: int | None = None
    oxygen_saturation: float | None = None


class DiagnosisCreate(BaseModel):
    description: str
    code: str | None = None
    status: str = "active"


class MedicationCreate(BaseModel):
    name: str
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None


class AllergyCreate(BaseModel):
    substance: str
    reaction: str | None = None
    severity: str = "unknown"


class LabResultCreate(BaseModel):
    panel: str
    analyte: str
    value: str | None = None
    unit: str | None = None
    reference_range: str | None = None
    flag: str = "normal"


class NoteCreate(BaseModel):
    body: str
    category: str = "progress"


class AppointmentCreate(BaseModel):
    scheduled_at: str                  # "YYYY-MM-DDTHH:MM"
    provider: str | None = None
    reason: str | None = None
    duration_minutes: int = 30


class AppointmentStatus(BaseModel):
    status: str


class UnitCreate(BaseModel):
    name: str
    kind: str = "department"
    parent_id: int | None = None


class UserCreate(BaseModel):
    username: str
    display_name: str
    password: str
    role: str
    unit_id: int | None = None


class UserPatch(BaseModel):
    active: bool | None = None
    role: str | None = None
    password: str | None = None


class SyncPush(BaseModel):
    device_id: str
    change_id: str | None = None
    sent_at: str | None = None
    patients: list[dict] = []


# ---------------------------------------------------------------------------
# error translation


def error_handler(request: Request, exc: MedFlowError) -> JSONResponse:
    from app.errors import AuthorizationError
    if isinstance(exc, NotFoundError):
        status = 404
    elif isinstance(exc, ValidationError):
        status = 422
    elif isinstance(exc, AuthorizationError):
        status = 403
    else:
        status = 400
    detail: dict = {"message": exc.message}
    if isinstance(exc, ValidationError):
        detail["fields"] = exc.errors
    return JSONResponse(status_code=status, content={"error": detail})


# ---------------------------------------------------------------------------
# factory


def create_app(config: Config | None = None, db=None, repos=None,
               google_client_id: str | None = None) -> FastAPI:
    app = FastAPI(**OPENAPI_METADATA)
    app.state.config = config
    app.state.db = db
    app.state.repos = repos
    app.state.google_client_id = google_client_id
    from app.services.reports import ReportsService
    app.state.report_service = ReportsService(repos) if repos else None
    # Automation rules live for the server's lifetime (same as a desktop
    # session); the engine is created once, not per request.
    from app.services.automation import AutomationEngine
    app.state.automation = AutomationEngine(
        repos, log_sink=lambda msg: None) if repos else None

    app.add_exception_handler(MedFlowError, error_handler)

    # --------------------------------------------------------------- auth

    @app.post("/api/auth/login", tags=["auth"])
    def login(body: LoginRequest, request: Request):
        users = request.app.state.repos["users"]
        from app.services.security import SecurityService
        security = SecurityService(users)
        try:
            user = security.authenticate(body.username, body.password)
        except MedFlowError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        secret = request.app.state.token_secret
        policy = sessions_policy.policy_from(
            request.app.state.config.session if request.app.state.config else None)
        ttl = sessions_policy.ttl_for(policy, body.remember)
        token = issue({
            "sub": user.user_id,
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "remember": body.remember,
        }, secret, ttl=ttl)
        return {
            "token": token,
            "session": {"remember": body.remember, "expires_in": ttl},
            "user": {
                "id": user.user_id, "username": user.username,
                "display_name": user.display_name, "role": user.role,
                "permissions": sorted(security.permissions(user)),
            },
        }

    @app.post("/api/auth/signup", status_code=201, tags=["auth"])
    def signup(body: SignupRequest, request: Request = None):
        """Open self-service registration.

        The first account ever created becomes the administrator; everyone
        after that signs up as a viewer pending staff promotion. Temporarily
        closable via config for private deployments.
        """
        cfg = request.app.state.config
        if cfg and not getattr(cfg, "allow_open_signup", True):
            raise HTTPException(status_code=403, detail="Signup is disabled here")
        from app.services.security import SecurityService
        security = SecurityService(request.app.state.repos["users"])
        try:
            user = security.signup(body.username, body.display_name,
                                   body.password, body.email)
        except MedFlowError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        secret = request.app.state.token_secret
        policy = sessions_policy.policy_from(
            request.app.state.config.session if request.app.state.config else None)
        token = issue({"sub": user.user_id, "username": user.username,
                       "role": user.role}, secret,
                      ttl=policy.normal_ttl)
        return {"token": token, "user": {
            "id": user.user_id, "username": user.username,
            "display_name": user.display_name, "role": user.role,
            "permissions": sorted(security.permissions(user)),
        }}

    @app.get("/api/auth/config", tags=["auth"])
    def auth_config(request: Request = None):
        """Public: what the login/signup pages should render."""
        cfg = request.app.state.config
        return {
            "google_enabled": request.app.state.google_client_id is not None,
            "open_signup": bool(getattr(cfg, "allow_open_signup", True)) if cfg else True,
        }

    @app.post("/api/auth/google", tags=["auth"])
    def google_login(body: GoogleLoginRequest, request: Request = None):
        """Verify a Google ID token and sign in (or provision) the user."""
        if not request.app.state.google_client_id:
            raise HTTPException(status_code=501, detail="Google sign-in not configured")
        from app.server.google import verify_google_token
        info = verify_google_token(body.id_token, request.app.state.google_client_id)
        from app.services.security import SecurityService
        security = SecurityService(request.app.state.repos["users"])
        try:
            user = security.authenticate_google(
                info["sub"], info["email"], info.get("name") or "")
        except MedFlowError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        secret = request.app.state.token_secret
        policy = sessions_policy.policy_from(
            request.app.state.config.session if request.app.state.config else None)
        ttl = sessions_policy.ttl_for(policy, body.remember)
        token = issue({"sub": user.user_id, "username": user.username,
                       "role": user.role, "remember": body.remember}, secret, ttl=ttl)
        return {"token": token, "user": {
            "id": user.user_id, "username": user.username,
            "display_name": user.display_name, "role": user.role,
            "permissions": sorted(security.permissions(user)),
        }}

    # ------------------------------------------------- desktop pairing

    @app.post("/api/pairing/code", status_code=201, tags=["auth"])
    def pairing_code(body: PairingStart, user=Depends(current_user),
                     request: Request = None):
        """Create a one-time code so the desktop app can pair with this server.

        The signed-in user runs the desktop app, types this code there, and the
        workstation inherits the identity that created it — including a session
        established through Google on the web. Codes live 10 minutes and are
        consumed on first use.
        """
        repos = request.app.state.repos
        record = repos["users"].get(int(user["sub"]))
        email = (record.email if record else None) or \
            f"{user['username']}@paired.local"
        try:
            entry = pairing.issue_code(
                {
                    "sub": user["sub"],
                    "username": user["username"],
                    "email": email,
                    "display_name": user.get("display_name") or user["username"],
                    "role": user["role"],
                    "auth_provider": record.auth_provider if record else "password",
                },
                label=body.label,
            )
        except PairingError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        from app.models import AuditEvent
        repos["audit"].record(AuditEvent(
            action="pairing", entity_type="session", entity_id=user["username"],
            actor=user["username"], device_id="web"))
        return entry

    @app.post("/api/pairing/redeem", tags=["auth"])
    def pairing_redeem(body: PairingRedeem, request: Request = None):
        """Exchange a one-time pairing code for a session (desktop side)."""
        try:
            identity = pairing.redeem_code(body.code)
        except PairingError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        from app.services.security import SecurityService
        security = SecurityService(request.app.state.repos["users"])
        try:
            user = security.pair_workstation(identity)
        except MedFlowError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        secret = request.app.state.token_secret
        policy = sessions_policy.policy_from(
            request.app.state.config.session if request.app.state.config else None)
        token = issue({"sub": user.user_id, "username": user.username,
                       "role": user.role}, secret, ttl=policy.remember_ttl)
        return {"token": token, "identity": identity, "user": {
            "id": user.user_id, "username": user.username,
            "display_name": user.display_name, "role": user.role,
            "permissions": sorted(security.permissions(user)),
        }}

    # ------------------------------------------------- temporary access

    @app.get("/api/temp-users", tags=["access"])
    def list_temp_users(user=Depends(current_user), request: Request = None):
        require(user, "users.manage")
        return [{
            "id": u.user_id, "username": u.username, "label": u.display_name,
            "expires_at": u.expires_at, "active": u.active,
            "patient_ids": u.scoped_patient_ids(),
            "expired": u.is_expired(
                __import__("app.utils.dates", fromlist=["to_iso"]).to_iso(
                    __import__("app.utils.dates", fromlist=["utcnow"]).utcnow())),
        } for u in request.app.state.repos["users"].list(active_only=False)
          if u.role == "temporary"]

    @app.post("/api/temp-users", status_code=201, tags=["access"])
    def create_temp_user(body: TempUserRequest, user=Depends(current_user),
                         request: Request = None):
        require(user, "users.manage")
        from app.services.security import SecurityService
        security = SecurityService(request.app.state.repos["users"])
        creator = request.app.state.repos["users"].get(user["sub"])
        try:
            guest, password = security.create_temporary_user(
                creator, body.label, body.hours, body.patient_ids)
        except MedFlowError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"username": guest.username, "password": password,
                "expires_at": guest.expires_at, "label": guest.display_name}

    @app.delete("/api/temp-users/{user_id}", tags=["access"])
    def revoke_temp_user(user_id: int, user=Depends(current_user),
                         request: Request = None):
        require(user, "users.manage")
        target = request.app.state.repos["users"].get(user_id)
        if not target or target.role != "temporary":
            raise HTTPException(status_code=404, detail="No such temporary user")
        target.active = False
        request.app.state.repos["users"].update(target, ["active"])
        return {"ok": True}

    @app.get("/api/auth/me", tags=["auth"])
    def me(user=Depends(current_user)):
        return {
            "id": user["sub"], "username": user["username"],
            "display_name": user["display_name"], "role": user["role"],
        }

    @app.post("/api/auth/refresh", tags=["auth"])
    def refresh_session(request: Request = None, user=Depends(current_user)):
        """Roll the session's expiry forward while the user stays active.

        The web workspace calls this hourly; a clinic on a long shift is
        never logged out mid-visit. Remembered sessions always renew;
        ordinary ones follow the operator's sliding-refresh setting.
        """
        policy = sessions_policy.policy_from(
            request.app.state.config.session if request.app.state.config else None)
        remember = bool(user.get("remember"))
        record = request.app.state.repos["users"].get(int(user["sub"]))
        payload = {
            "sub": record.user_id if record else user["sub"],
            "username": user["username"],
            "role": user["role"],
            "remember": remember,
        }
        rolled = sessions_policy.refreshed_payload(payload, policy)
        ttl = sessions_policy.ttl_for(policy, remember)
        token = issue(payload, request.app.state.token_secret, ttl=ttl)
        return {"token": token, "refreshed": bool(rolled), "expires_in": ttl}

    @app.get("/api/settings/session", tags=["settings"])
    def get_session_policy(request: Request = None):
        """Public summary so the login page can explain its checkbox."""
        cfg = request.app.state.config
        s = cfg.session if cfg else SessionConfig()
        return {"token_ttl_hours": s.token_ttl_hours,
                "remember_me_days": s.remember_me_days,
                "sliding_refresh": bool(s.sliding_refresh)}

    @app.patch("/api/settings/session", tags=["settings"])
    def set_session_policy(body: SessionPolicyIn, user=Depends(current_user),
                           request: Request = None):
        """Administrator sets how long sign-ins last. Applies to new logins."""
        require(user, "users.manage")
        cfg = request.app.state.config
        if cfg is None:
            raise HTTPException(status_code=503, detail="No runtime config")
        s = cfg.session
        if body.token_ttl_hours is not None:
            if not 1 <= body.token_ttl_hours <= 8760:
                raise HTTPException(status_code=400,
                                    detail="Session hours must be 1-8760")
            s.token_ttl_hours = int(body.token_ttl_hours)
        if body.remember_me_days is not None:
            if not 1 <= body.remember_me_days <= 365:
                raise HTTPException(status_code=400,
                                    detail="Remember-me days must be 1-365")
            s.remember_me_days = int(body.remember_me_days)
        if body.sliding_refresh is not None:
            s.sliding_refresh = bool(body.sliding_refresh)
        cfg.save()
        from app.models import AuditEvent
        request.app.state.repos["audit"].record(AuditEvent(
            action="updated", entity_type="session_policy",
            entity_id=user["username"],
            details=(f"Session policy: {s.token_ttl_hours}h sign-ins, "
                     f"{s.remember_me_days}d remember-me, "
                     f"rolling {'on' if s.sliding_refresh else 'off'}"),
            actor=user["username"], device_id="server"))
        return {"token_ttl_hours": s.token_ttl_hours,
                "remember_me_days": s.remember_me_days,
                "sliding_refresh": bool(s.sliding_refresh)}

    # ------------------------------------------------------------ patients

    @app.get("/api/patients", tags=["patients"])
    def search_patients(
        q: str = "",
        limit: int = 200,
        user=Depends(current_user),
        patients=Depends(get_patient_service),
    ):
        require(user, "patients.view")
        return [s.to_row() for s in patients.search(q, limit)]

    @app.post("/api/patients", status_code=201, tags=["patients"])
    def create_patient(
        body: PatientCreate,
        user=Depends(current_user),
        patients=Depends(get_patient_service),
    ):
        require(user, "patients.create")
        patient = patients.register(body.model_dump())
        return patient.to_row()

    @app.get("/api/patients/deleted", tags=["patients"])
    def deleted_patients(user=Depends(current_user),
                         request: Request = None):
        """Recycle bin: soft-deleted records, for restore (staff only)."""
        require(user, "settings.manage")
        patients = get_patient_service(request, user)
        return [s.to_row() for s in patients.deleted_patients()]

    @app.get("/api/patients/{patient_id}", tags=["patients"])
    def get_patient(
        patient_id: int,
        user=Depends(current_user),
        patients=Depends(get_patient_service),
    ):
        require(user, "patients.view")
        return patients.get(patient_id).to_row()

    @app.patch("/api/patients/{patient_id}", tags=["patients"])
    def update_patient(
        patient_id: int,
        body: PatientUpdate,
        user=Depends(current_user),
        patients=Depends(get_patient_service),
    ):
        require(user, "patients.edit")
        # exclude_unset keeps PATCH semantics: omitted = unchanged, null = clear.
        data = body.model_dump(exclude_unset=True)
        patient = patients.update(patient_id, data)
        return patient.to_row()

    @app.delete("/api/patients/{patient_id}", tags=["patients"])
    def delete_patient(
        patient_id: int,
        user=Depends(current_user),
        patients=Depends(get_patient_service),
    ):
        require(user, "patients.delete")
        if not patients.delete(patient_id):
            raise HTTPException(status_code=409, detail="Already deleted")
        return {"ok": True}

    @app.post("/api/patients/{patient_id}/restore", tags=["patients"])
    def restore_patient(
        patient_id: int,
        user=Depends(current_user),
        patients=Depends(get_patient_service),
    ):
        require(user, "patients.delete")
        return {"ok": patients.restore(patient_id)}

    @app.get("/api/patients/{patient_id}/chart", tags=["patients"])
    def patient_chart(
        patient_id: int,
        user=Depends(current_user),
        patients=Depends(get_patient_service),
    ):
        require(user, "patients.view")
        chart = patients.chart(patient_id)
        p = chart.pop("patient")
        return {
            "patient": p.to_row(),
            **{k: [i.to_row() if hasattr(i, "to_row") else i
                   for i in v] for k, v in chart.items()},
        }

    # -------------------------------------------------- clinical records

    @app.post("/api/patients/{patient_id}/vitals", status_code=201, tags=["records"])
    def add_vitals(patient_id: int, body: VitalsCreate, user=Depends(current_user),
                   records=Depends(get_records_service)):
        require(user, "records.edit")
        v = records.add_vitals(patient_id, body.model_dump())
        return v.to_row()

    @app.post("/api/patients/{patient_id}/diagnoses", status_code=201, tags=["records"])
    def add_diagnosis(patient_id: int, body: DiagnosisCreate,
                      user=Depends(current_user), records=Depends(get_records_service)):
        require(user, "records.edit")
        return records.add_diagnosis(
            patient_id, body.description, body.code, body.status
        ).to_row()

    @app.post("/api/patients/{patient_id}/medications", status_code=201, tags=["records"])
    def add_medication(patient_id: int, body: MedicationCreate,
                       user=Depends(current_user), records=Depends(get_records_service)):
        require(user, "records.edit")
        return records.add_medication(
            patient_id, body.name, body.dose, body.route, body.frequency
        ).to_row()

    @app.post("/api/patients/{patient_id}/medications/{medication_id}/discontinue",
              tags=["records"])
    def discontinue_medication(medication_id: int, user=Depends(current_user),
                               records=Depends(get_records_service)):
        require(user, "records.edit")
        return records.discontinue_medication(medication_id).to_row()

    @app.post("/api/patients/{patient_id}/allergies", status_code=201, tags=["records"])
    def add_allergy(patient_id: int, body: AllergyCreate,
                    user=Depends(current_user), records=Depends(get_records_service)):
        require(user, "records.edit")
        return records.add_allergy(
            patient_id, body.substance, body.reaction, body.severity
        ).to_row()

    @app.post("/api/patients/{patient_id}/lab-results", status_code=201, tags=["records"])
    def add_lab_result(patient_id: int, body: LabResultCreate,
                       user=Depends(current_user), records=Depends(get_records_service)):
        require(user, "records.edit")
        return records.add_lab_result(
            patient_id, body.panel, body.analyte, body.value, body.unit,
            body.reference_range, body.flag,
        ).to_row()

    @app.post("/api/patients/{patient_id}/notes", status_code=201, tags=["records"])
    def add_note(patient_id: int, body: NoteCreate, user=Depends(current_user),
                 records=Depends(get_records_service)):
        require(user, "records.edit")
        return records.add_note(patient_id, body.body, body.category).to_row()

    # ------------------------------------------------------- appointments

    @app.get("/api/appointments", tags=["appointments"])
    def list_appointments(scope: str = "upcoming", user=Depends(current_user),
                          records=Depends(get_records_service)):
        require(user, "appointments.view")
        if scope == "today":
            return records.todays_schedule()
        return records.upcoming_appointments()

    @app.post("/api/appointments", status_code=201, tags=["appointments"])
    def schedule_appointment(body: AppointmentCreate, patient_id: int,
                             user=Depends(current_user),
                             records=Depends(get_records_service)):
        require(user, "appointments.manage")
        return records.schedule_appointment(
            patient_id, body.scheduled_at, body.provider, body.reason,
            body.duration_minutes,
        )

    @app.patch("/api/appointments/{appointment_id}/status", tags=["appointments"])
    def set_appointment_status(appointment_id: int, body: AppointmentStatus,
                               user=Depends(current_user),
                               records=Depends(get_records_service)):
        require(user, "appointments.manage")
        return records.set_appointment_status(appointment_id, body.status)

    # ---------------------------------------------------------------- org

    @app.get("/api/org/units", tags=["org"])
    def list_units(user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        repos = request.app.state.repos
        return [u.to_row() for u in repos["units"].list()]

    @app.post("/api/org/units", status_code=201, tags=["org"])
    def create_unit(body: UnitCreate, user=Depends(current_user),
                    request: Request = None):
        require(user, "settings.manage")
        repos = request.app.state.repos
        from app.services.org import OrgService
        from app.services.security import SecurityService
        svc = OrgService(repos, SecurityService(repos["users"]))
        return svc.create_unit(body.name, body.kind, body.parent_id).to_row()

    @app.get("/api/departments", tags=["org"])
    def list_departments(user=Depends(current_user), request: Request = None):
        """Departments for dropdowns and lists — needs only patient visibility.

        Returns id/name plus a live count of patients filed under each, so
        managers can see the shape of their facility at a glance.
        """
        require(user, "patients.view")
        repos = request.app.state.repos
        counts = repos["units"].patient_counts()
        return [
            {"id": u.unit_id, "name": u.name, "kind": u.kind,
             "patient_count": counts.get(u.unit_id, 0)}
            for u in repos["units"].list()
        ]

    @app.patch("/api/org/units/{unit_id}", tags=["org"])
    def rename_unit(unit_id: int, body: UnitRename,
                    user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        repos = request.app.state.repos
        from app.services.org import OrgService
        from app.services.security import SecurityService
        svc = OrgService(repos, SecurityService(repos["users"]))
        try:
            return svc.rename_unit(unit_id, body.name).to_row()
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        # ValidationError bubbles to the global handler (422 + field errors).

    @app.delete("/api/org/units/{unit_id}", tags=["org"])
    def delete_unit(unit_id: int, user=Depends(current_user),
                    request: Request = None):
        require(user, "settings.manage")
        repos = request.app.state.repos
        from app.services.org import OrgService
        from app.services.security import SecurityService
        svc = OrgService(repos, SecurityService(repos["users"]))
        try:
            svc.delete_unit(unit_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        # ValidationError bubbles to the global handler (422 + field errors).
        return {"deleted": unit_id}

    @app.get("/api/org/users", tags=["org"])
    def list_users(user=Depends(current_user), request: Request = None):
        require(user, "users.manage")
        repos = request.app.state.repos
        return [u.to_row() for u in repos["users"].list(active_only=False)]

    @app.post("/api/org/users", status_code=201, tags=["org"])
    def create_user(body: UserCreate, user=Depends(current_user),
                    request: Request = None):
        require(user, "users.manage")
        repos = request.app.state.repos
        from app.services.org import OrgService
        from app.services.security import SecurityService
        svc = OrgService(repos, SecurityService(repos["users"]))
        return svc.create_user(
            body.username, body.display_name, body.password, body.role,
            body.unit_id,
        ).to_row()

    @app.patch("/api/org/users/{user_id}", tags=["org"])
    def patch_user(user_id: int, body: UserPatch, user=Depends(current_user),
                   request: Request = None):
        require(user, "users.manage")
        repos = request.app.state.repos
        from app.services.org import OrgService
        from app.services.security import SecurityService
        svc = OrgService(repos, SecurityService(repos["users"]))
        if body.password:
            svc.change_password(user_id, body.password)
        if body.role:
            svc.change_role(user_id, body.role)
        if body.active is not None:
            svc.set_user_active(user_id, body.active)
        return repos["users"].get(user_id).to_row()

    # ------------------------------------------------------------ backups

    def _automation_engine(request: Request):
        engine = request.app.state.automation
        if engine is None:
            raise HTTPException(status_code=503, detail="Automation unavailable")
        return engine

    def _backup_service(request: Request):
        """A BackupService bound to the same dirs the server was started with."""
        cfg = request.app.state.config
        data_dir = Path(cfg.data_dir) if cfg and cfg.data_dir else Path("data")
        base = data_dir.parent
        from app.services.backup import BackupService
        return BackupService(
            cfg.resolve_database_path(base) if cfg else "data/medflow.db",
            cfg.resolve_backup_dir(base) if cfg else "data/backups",
        )

    @app.get("/api/backups", tags=["settings"])
    def list_backups(user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        return _backup_service(request).list_backups()

    @app.post("/api/backups", status_code=201, tags=["settings"])
    def create_backup(user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        path = _backup_service(request).create_backup(label="manual")
        return {"created": path.name, "path": str(path)}

    @app.post("/api/backups/prune", tags=["settings"])
    def prune_backups(user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        return {"removed": _backup_service(request).prune()}

    # ----------------------------------------------------- off-site backups

    def _offsite(request: Request):
        """Service + data dir for off-site operations."""
        cfg = request.app.state.config
        if cfg is None:
            raise HTTPException(status_code=503, detail="No runtime config")
        data_dir = Path(cfg.data_dir) if cfg.data_dir else Path("data")
        return OffsiteBackupService(cfg.cloud_backup, load_keys(data_dir)), cfg

    def _cloud_summary(request: Request) -> dict:
        cfg = request.app.state.config
        c = cfg.cloud_backup
        svc, _ = _offsite(request)
        return {
            "enabled": c.enabled,
            "provider": c.provider,
            "endpoint": c.endpoint,
            "bucket": c.bucket,
            "prefix": c.prefix,
            "region": c.region,
            "auto_upload": c.auto_upload,
            "keep_last_uploads": c.keep_last_uploads,
            "has_credentials": svc.credentials != ("", ""),
            "configured": svc.configured(),
            "last_upload_at": c.last_upload_at,
            "last_upload_status": c.last_upload_status,
        }

    @app.get("/api/settings/cloud-backup", tags=["settings"])
    def get_cloud_backup(user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        return _cloud_summary(request)

    @app.put("/api/settings/cloud-backup", tags=["settings"])
    def set_cloud_backup(body: CloudBackupIn, user=Depends(current_user),
                         request: Request = None):
        """Point MedFlow at the clinic's own bucket or WebDAV share.

        Credential fields are write-only: they are stored in
        ``offsite_keys.json`` (0600) and never echoed back.
        """
        require(user, "settings.manage")
        cfg = request.app.state.config
        c = cfg.cloud_backup
        changed = []
        if body.provider is not None:
            if body.provider not in ("none", "s3", "webdav"):
                raise HTTPException(status_code=400,
                                    detail="Provider must be none, s3 or webdav")
            c.provider = body.provider
            changed.append(f"provider={body.provider}")
        for field in ("endpoint", "bucket", "prefix", "region"):
            value = getattr(body, field)
            if value is not None:
                if field == "endpoint" and value.strip() and not \
                        value.startswith(("http://", "https://")):
                    raise HTTPException(
                        status_code=400,
                        detail="Endpoint must start with http:// or https://")
                setattr(c, field, value.strip() or None)
                changed.append(f"{field} set")
        if body.enabled is not None:
            c.enabled = body.enabled
            changed.append("enabled" if body.enabled else "disabled")
        if body.auto_upload is not None:
            c.auto_upload = body.auto_upload
            changed.append("auto_upload" if body.auto_upload else "manual upload")
        if body.keep_last_uploads is not None:
            if not 1 <= body.keep_last_uploads <= 365:
                raise HTTPException(status_code=400,
                                    detail="Keep 1-365 uploads")
            c.keep_last_uploads = int(body.keep_last_uploads)
            changed.append(f"keep last {c.keep_last_uploads}")

        if body.access_key_id or body.secret_access_key or body.username or body.password:
            data_dir = Path(cfg.data_dir) if cfg.data_dir else Path("data")
            keys = load_keys(data_dir)
            if body.access_key_id:
                keys["access_key_id"] = body.access_key_id.strip()
            if body.secret_access_key:
                keys["secret_access_key"] = body.secret_access_key.strip()
            if body.username:
                keys["username"] = body.username.strip()
            if body.password:
                keys["password"] = body.password
            save_keys(data_dir, keys)
            changed.append("credentials saved")

        cfg.save()
        from app.models import AuditEvent
        request.app.state.repos["audit"].record(AuditEvent(
            action="updated", entity_type="cloud_backup",
            entity_id=c.provider, details="; ".join(changed) or "no change",
            actor=user["username"], device_id="server"))
        return _cloud_summary(request)

    @app.post("/api/settings/cloud-backup/test", tags=["settings"])
    def test_cloud_backup(user=Depends(current_user), request: Request = None):
        """Check the storage is reachable and credentials work."""
        require(user, "settings.manage")
        svc, _ = _offsite(request)
        if not svc.configured():
            return {"ok": False,
                    "error": "Fill in provider, endpoint and credentials first."}
        try:
            objects = svc.list_remote()
            return {"ok": True, "objects": len(objects)}
        except OffsiteError as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/settings/cloud-backup/upload", tags=["settings"])
    def upload_cloud_backup(body: CloudPassphrase,
                            user=Depends(current_user), request: Request = None):
        """Create a local backup, encrypt it, and push it off-site.

        The passphrase never leaves this server unencrypted: it derives the
        AES key locally, and only the ciphertext travels. Losing it means
        losing the remote copies — it is never stored anywhere.
        """
        require(user, "settings.manage")
        if len(body.passphrase) < 8:
            raise HTTPException(status_code=400,
                                detail="Use a passphrase of at least 8 characters")
        svc, cfg = _offsite(request)
        if not svc.configured():
            raise HTTPException(status_code=400,
                                detail="Cloud backup is not fully configured")
        path = _backup_service(request).create_backup(label="offsite")
        try:
            result = svc.upload(path, body.passphrase)
        except OffsiteError as exc:
            cfg.cloud_backup.last_upload_status = f"failed: {exc}"
            cfg.save()
            raise HTTPException(status_code=502, detail=str(exc))
        cfg.cloud_backup.last_upload_at = result["uploaded"]
        cfg.cloud_backup.last_upload_status = "ok"
        cfg.save()
        try:
            pruned = svc.prune_remote()
        except OffsiteError:
            pruned = 0
        from app.models import AuditEvent
        request.app.state.repos["audit"].record(AuditEvent(
            action="created", entity_type="cloud_backup",
            entity_id=result["key"],
            details=f"Encrypted backup uploaded ({result['bytes']} bytes)",
            actor=user["username"], device_id="server"))
        return {**result, "pruned": pruned}

    # ---------------------------------------------------------- automation

    @app.get("/api/automation/rules", tags=["settings"])
    def list_rules(user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        engine = _automation_engine(request)
        return [r.to_row() for r in engine.list_rules()]

    @app.post("/api/automation/rules", status_code=201, tags=["settings"])
    def create_rule(body: AutomationRuleIn, user=Depends(current_user),
                    request: Request = None):
        require(user, "settings.manage")
        engine = _automation_engine(request)
        try:
            rule = engine.add_rule(body.name, body.fact, body.operator,
                                   body.threshold, body.action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return rule.to_row()

    @app.delete("/api/automation/rules/{rule_id}", tags=["settings"])
    def delete_rule(rule_id: str, user=Depends(current_user),
                    request: Request = None):
        require(user, "settings.manage")
        engine = _automation_engine(request)
        if not engine.remove_rule(rule_id):
            raise HTTPException(status_code=404, detail="No such rule")
        return {"removed": rule_id}

    @app.post("/api/automation/run", tags=["settings"])
    def run_rules(user=Depends(current_user), request: Request = None):
        require(user, "settings.manage")
        return _automation_engine(request).run_once()

    # ------------------------------------------------------------ reports

    @app.get("/api/reports/dashboard", tags=["reports"])
    def dashboard(user=Depends(current_user), reports=Depends(get_reports_service)):
        require(user, "reports.view")
        return reports.dashboard()

    @app.get("/api/reports/{name}", tags=["reports"])
    def report(name: str, user=Depends(current_user),
               reports=Depends(get_reports_service)):
        require(user, "reports.view")
        return reports.dataset(name)

    @app.get("/api/export/{name}.csv", tags=["export"])
    def export_csv(name: str, user=Depends(current_user), request: Request = None):
        require(user, "export.data")
        from app.services.export import ExportService
        exporter = ExportService(request.app.state.report_service)
        return PlainTextResponse(
            exporter.dataset_csv(name),
            media_type="text/csv",
            headers={"Content-Disposition":
                     f'attachment; filename="medflow_{name}.csv"'},
        )

    @app.get("/api/export/{name}.json", tags=["export"])
    def export_json(name: str, user=Depends(current_user), request: Request = None):
        require(user, "export.data")
        from app.services.export import ExportService
        exporter = ExportService(request.app.state.report_service)
        return PlainTextResponse(
            exporter.dataset_json(name),
            media_type="application/json",
            headers={"Content-Disposition":
                     f'attachment; filename="medflow_{name}.json"'},
        )

    @app.get("/api/patients/{patient_id}/chart.html", tags=["export"])
    def patient_chart_html(patient_id: int, user=Depends(current_user),
                           patients=Depends(get_patient_service),
                           request: Request = None):
        require(user, "export.data")
        from app.services.export import ExportService
        chart = patients.chart(patient_id)
        exporter = ExportService(request.app.state.report_service)
        return HTMLResponse(exporter.patient_chart_html(chart))

    # --------------------------------------------------------------- sync

    @app.post("/api/sync/push", tags=["sync"])
    def sync_push(body: SyncPush, user=Depends(current_user),
                  request: Request = None):
        require(user, "sync.manage")
        repos = request.app.state.repos
        from app.services.sync import SyncEngine
        engine = SyncEngine(repos, device_id=body.device_id)
        report = engine.apply_pull_payload({"patients": body.patients})
        return {"accepted": len(body.patients), "report": {
            "pushed": report.pushed, "pulled": report.pulled,
            "conflicts": [c.describe() for c in report.conflicts],
        }}

    @app.get("/api/sync/pull", tags=["sync"])
    def sync_pull(request: Request = None, user=Depends(current_user)):
        require(user, "sync.manage")
        repos = request.app.state.repos
        since = None
        return {"patients": [p.to_row() for p in
                             repos["patients"].changes_since(since)]}

    # ----------------------------------------------------------- exchange

    @app.post("/api/exchange/{patient_id}/export", tags=["exchange"])
    def exchange_export(patient_id: int, user=Depends(current_user),
                        patients=Depends(get_patient_service),
                        request: Request = None):
        require(user, "export.data")
        from app.services.exchange import ExchangeService
        svc = ExchangeService(
            patients, facility_name=request.app.state.config.facility_name
            if request.app.state.config else "MedFlow Facility",
        )
        return svc.build_bundle(patient_id)

    # ------------------------------------------------------------- system

    @app.get("/api/health", tags=["system"])
    def health(request: Request = None):
        repos = request.app.state.repos
        return {
            "ok": True,
            "facility": request.app.state.config.facility_name
            if request.app.state.config else "MedFlow",
            "patients": repos["patients"].count(),
        }

    # -------------------------------------------------------- web client

    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

        def _page(name: str):
            def handler():
                return HTMLResponse(
                    (web_dir / name).read_text(encoding="utf-8"))
            return handler

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def index():
            return _page("index.html")()

        app.get("/features", response_class=HTMLResponse,
                include_in_schema=False)(_page("features.html"))
        app.get("/security", response_class=HTMLResponse,
                include_in_schema=False)(_page("security.html"))
        app.get("/guide", response_class=HTMLResponse,
                include_in_schema=False)(_page("guide.html"))
        app.get("/login", response_class=HTMLResponse,
                include_in_schema=False)(_page("login.html"))
        app.get("/signup", response_class=HTMLResponse,
                include_in_schema=False)(_page("signup.html"))
        app.get("/app", response_class=HTMLResponse,
                include_in_schema=False)(_page("app.html"))

        @app.get("/auth/google/client-id", include_in_schema=False)
        def google_client_id_endpoint():
            return {"client_id": app.state.google_client_id or ""}

    return app
