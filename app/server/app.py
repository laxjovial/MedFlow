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

from app.config import Config
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
from app.server.tokens import issue

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
    status = 404 if isinstance(exc, NotFoundError) else (
        422 if isinstance(exc, ValidationError) else 400
    )
    detail: dict = {"message": exc.message}
    if isinstance(exc, ValidationError):
        detail["fields"] = exc.errors
    return JSONResponse(status_code=status, content={"error": detail})


# ---------------------------------------------------------------------------
# factory


def create_app(config: Config | None = None, db=None, repos=None) -> FastAPI:
    app = FastAPI(**OPENAPI_METADATA)
    app.state.config = config
    app.state.db = db
    app.state.repos = repos
    from app.services.reports import ReportsService
    app.state.report_service = ReportsService(repos) if repos else None

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
        token = issue({
            "sub": user.user_id,
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
        }, secret)
        return {
            "token": token,
            "user": {
                "id": user.user_id, "username": user.username,
                "display_name": user.display_name, "role": user.role,
                "permissions": sorted(security.permissions(user)),
            },
        }

    @app.get("/api/auth/me", tags=["auth"])
    def me(user=Depends(current_user)):
        return {
            "id": user["sub"], "username": user["username"],
            "display_name": user["display_name"], "role": user["role"],
        }

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

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def index():
            return (web_dir / "index.html").read_text(encoding="utf-8")

    return app
