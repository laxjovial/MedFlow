"""API server behavior through TestClient."""

from __future__ import annotations


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_login_rejects_bad_credentials(client):
    response = client.post("/api/auth/login",
                           json={"username": "admin", "password": "nope"})
    assert response.status_code == 401


def test_protected_routes_require_token(client):
    assert client.get("/api/patients").status_code == 401
    assert client.get("/api/reports/dashboard").status_code == 401


def test_full_patient_flow(client, auth):
    created = client.post("/api/patients", headers=auth, json={
        "name": "API Patient", "age": 50, "phone": "+234 803 000 1111"})
    assert created.status_code == 201
    pid = created.json()["patient_id"]
    assert created.json()["patient_number"] == "MF-000001"

    # true PATCH semantics: omitted fields survive
    patched = client.patch(f"/api/patients/{pid}", headers=auth,
                           json={"phone": "+234 803 000 2222"})
    body = patched.json()
    assert patched.status_code == 200
    assert body["name"] == "API Patient"
    assert body["phone"] == "+234 803 000 2222"

    chart = client.get(f"/api/patients/{pid}/chart", headers=auth).json()
    assert chart["patient"]["patient_id"] == pid
    assert chart["timeline"]

    deleted = client.delete(f"/api/patients/{pid}", headers=auth)
    assert deleted.status_code == 200
    assert client.get(f"/api/patients/{pid}", headers=auth).status_code == 404
    assert client.post(f"/api/patients/{pid}/restore",
                       headers=auth).json()["ok"] is True


def test_validation_error_maps_fields(client, auth):
    response = client.post("/api/patients", headers=auth,
                           json={"name": "", "age": 999})
    assert response.status_code == 422
    fields = response.json()["error"]["fields"]
    assert "name" in fields and "age" in fields


def test_records_endpoints(client, auth, patient):
    pid = patient.patient_id
    assert client.post(f"/api/patients/{pid}/vitals", headers=auth,
                       json={"blood_pressure": "118/76",
                             "heart_rate": 70}).status_code == 201
    assert client.post(f"/api/patients/{pid}/vitals", headers=auth,
                       json={"heart_rate": 9999}).status_code == 422
    assert client.post(f"/api/patients/{pid}/diagnoses", headers=auth,
                       json={"description": "Flu"}).status_code == 201
    assert client.post(f"/api/patients/{pid}/notes", headers=auth,
                       json={"body": "Advised rest."}).status_code == 201


def test_appointment_flow(client, auth, patient):
    pid = patient.patient_id
    created = client.post(f"/api/appointments?patient_id={pid}", headers=auth,
                          json={"scheduled_at": "2026-09-25T09:30",
                                "provider": "Dr. Who"})
    assert created.status_code == 201
    aid = created.json()["appointment_id"]
    moved = client.patch(f"/api/appointments/{aid}/status", headers=auth,
                         json={"status": "completed"})
    assert moved.json()["status"] == "completed"
    assert client.get("/api/appointments?scope=upcoming",
                      headers=auth).status_code == 200


def test_reports_and_exports(client, auth, patient):
    dashboard = client.get("/api/reports/dashboard", headers=auth).json()
    assert dashboard["total_patients"] >= 1

    csv_response = client.get("/api/export/patients.csv", headers=auth)
    assert "text/csv" in csv_response.headers["content-type"]
    assert patient.name.encode() in csv_response.content

    html = client.get(f"/api/patients/{patient.patient_id}/chart.html",
                      headers=auth)
    assert patient.name in html.text


def test_exchange_bundle_endpoint(client, auth, patient):
    bundle = client.post(f"/api/exchange/{patient.patient_id}/export",
                         headers=auth).json()
    assert bundle["format"] == "medflow-exchange"
    assert "checksum" in bundle
    assert bundle["patient"]["name"] == patient.name


def _bind_sync_test_session(client, auth, repos, device_id="workstation-A"):
    from app.server.tokens import verify
    token = auth["Authorization"].split(" ", 1)[1]
    claims = verify(token, client.app.state.token_secret)
    repos["patients"].db.execute(
        "UPDATE auth_sessions SET client_type = 'desktop', device_id = ? WHERE jti = ?",
        (device_id, claims["jti"]),
    )


def test_sync_pull_returns_patients(client, auth, repos, patient):
    _bind_sync_test_session(client, auth, repos)
    response = client.get("/api/sync/pull", headers=auth)
    numbers = [p["patient_number"] for p in response.json()["patients"]]
    assert patient.patient_number in numbers


def test_index_page_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "MedFlow" in response.text


def test_public_health_exposes_only_liveness(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_system_metrics_requires_authentication(client):
    response = client.get("/api/system/metrics")
    assert response.status_code == 401


def test_system_metrics_requires_reports_permission(client, repos):
    from app.services.security import SecurityService

    viewer = SecurityService(repos["users"]).create_user(
        "viewer", "Viewer User", "password123", "viewer"
    )
    response = client.post(
        "/api/auth/login",
        json={"username": viewer.username, "password": "password123"},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    metrics = client.get(
        "/api/system/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metrics.status_code == 403


def test_system_metrics_returns_counts_to_authorized_user(client, auth, patient):
    response = client.get("/api/system/metrics", headers=auth)
    assert response.status_code == 200
    assert "facility" in response.json()
    assert response.json()["patients"] >= 1


def test_login_rate_limit_returns_429_and_retry_after(client):
    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "incorrect"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "incorrect"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_signup_rate_limit_returns_429(client):
    for i in range(5):
        response = client.post(
            "/api/auth/signup",
            json={"username": f"signup-{i}", "display_name": "Signup User",
                  "password": "a-long-enough-password"},
        )
        assert response.status_code == 201
    limited = client.post(
        "/api/auth/signup",
        json={"username": "signup-extra", "display_name": "Signup User",
              "password": "a-long-enough-password"},
    )
    assert limited.status_code == 429


def test_pairing_redeem_rate_limit_returns_429(client):
    for _ in range(5):
        response = client.post(
            "/api/pairing/redeem",
            json={"code": "invalid-code", "device_id": "test-device"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/pairing/redeem",
        json={"code": "invalid-code", "device_id": "test-device"},
    )
    assert limited.status_code == 429



def test_sync_pull_uses_incremental_cursor_and_echo_suppression(client, auth, repos, patient):
    _bind_sync_test_session(client, auth, repos, "workstation-A")
    local = repos["patients"].get(patient.patient_id)
    local.device_id = "workstation-A"
    repos["patients"].update(local, ["device_id"], bump_version=False)
    first = client.get(
        "/api/sync/pull?since=0&limit=100&device_id=workstation-A",
        headers=auth,
    )
    assert first.status_code == 200
    payload = first.json()
    assert patient.patient_number not in {
        row["patient_number"] for row in payload["patients"]
    }
    assert payload["cursor"] >= 1
    assert payload["has_more"] is False

    local = repos["patients"].get(patient.patient_id)
    local.device_id = "workstation-B"
    repos["patients"].update(local, ["device_id"], bump_version=False)
    second = client.get(
        f"/api/sync/pull?since={payload['cursor']}&device_id=workstation-A",
        headers=auth,
    )
    assert second.status_code == 200
    assert patient.patient_number in {
        row["patient_number"] for row in second.json()["patients"]
    }


def test_sync_pull_validates_cursor_and_page_size(client, auth, repos):
    _bind_sync_test_session(client, auth, repos)
    assert client.get("/api/sync/pull?since=-1", headers=auth).status_code == 422
    assert client.get("/api/sync/pull?limit=0", headers=auth).status_code == 422
    assert client.get("/api/sync/pull?limit=501", headers=auth).status_code == 422


def test_sync_push_reports_conflicts_separately_from_accepted(client, auth, repos, patient):
    _bind_sync_test_session(client, auth, repos, "workstation-A")
    from datetime import datetime
    from app.models import Patient

    local = repos["patients"].get(patient.patient_id)
    local.device_id = "workstation-A"
    local.version = 2
    repos["patients"].update(
        local, ["device_id", "version"], bump_version=False
    )
    repos["patients"].db.connection().execute(
        "UPDATE patients SET updated_at = ? WHERE patient_id = ?",
        ("2026-10-28T10:00:00", patient.patient_id),
    )
    repos["patients"].db.connection().commit()
    local = repos["patients"].get(patient.patient_id)
    remote = Patient.from_row(local.to_row())
    remote.name = "Remote conflicting name"
    remote.version = 3
    remote.updated_at = datetime(2026, 10, 29, 10, 0, 0)
    remote.device_id = "workstation-A"

    response = client.post("/api/sync/push", headers=auth, json={
        "device_id": "workstation-A",
        "batch_id": "batch-conflict-1",
        "patients": [remote.to_row()],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 0
    assert body["accepted_patient_numbers"] == []
    assert body["conflicted_patient_numbers"] == [patient.patient_number]
    assert body["batch_id"] == "batch-conflict-1"
    assert isinstance(body["server_cursor"], int)



def test_sync_rejects_device_id_spoofing(client, auth, repos):
    _bind_sync_test_session(client, auth, repos, "workstation-A")
    response = client.get(
        "/api/sync/pull?device_id=workstation-B", headers=auth
    )
    assert response.status_code == 403
    response = client.post("/api/sync/push", headers=auth, json={
        "device_id": "workstation-B",
        "batch_id": "spoofed-batch",
        "patients": [],
    })
    assert response.status_code == 403


def test_sync_push_batch_is_idempotent(client, auth, repos, patient):
    _bind_sync_test_session(client, auth, repos, "workstation-A")
    from app.models import Patient
    remote = Patient.from_row(patient.to_row())
    remote.patient_id = None
    remote.patient_number = "MF-998877"
    remote.name = "First delivery"
    remote.device_id = "workstation-A"
    payload = {
        "device_id": "workstation-A",
        "batch_id": "stable-batch-001",
        "patients": [remote.to_row()],
    }
    first = client.post("/api/sync/push", headers=auth, json=payload)
    assert first.status_code == 200, first.text
    changed_retry = dict(payload)
    changed_retry["patients"] = []
    second = client.post("/api/sync/push", headers=auth, json=changed_retry)
    assert second.status_code == 200
    assert second.json() == first.json()
    stored = repos["patients"].get_by_number("MF-998877")
    assert stored is not None
    assert stored.name == "First delivery"
    receipt_count = repos["patients"]._query_one(
        "SELECT COUNT(*) AS n FROM sync_batches WHERE device_id = ? AND batch_id = ?",
        ("workstation-A", "stable-batch-001"),
    )["n"]
    assert receipt_count == 1


def test_sync_pull_returns_immutable_revision_snapshots(client, auth, repos, patient):
    _bind_sync_test_session(client, auth, repos, "workstation-A")
    start = repos["patients"]._query_one(
        "SELECT COALESCE(MAX(seq), 0) AS seq FROM sync_change_log"
    )["seq"]
    local = repos["patients"].get(patient.patient_id)
    local.name = "Revision one"
    repos["patients"].update(local, ["name"])
    local = repos["patients"].get(patient.patient_id)
    local.name = "Revision two"
    repos["patients"].update(local, ["name"])
    first = client.get(
        f"/api/sync/pull?since={start}&limit=1&device_id=workstation-A",
        headers=auth,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["has_more"] is True
    assert body["patients"][0]["name"] == "Revision one"
    second = client.get(
        f"/api/sync/pull?since={body['cursor']}&limit=10&device_id=workstation-A",
        headers=auth,
    )
    assert second.status_code == 200
    assert second.json()["patients"][0]["name"] == "Revision two"


def test_sync_pull_propagates_patient_tombstone(client, auth, repos, patient):
    _bind_sync_test_session(client, auth, repos, "workstation-A")
    start = repos["patients"]._query_one(
        "SELECT COALESCE(MAX(seq), 0) AS seq FROM sync_change_log"
    )["seq"]
    assert repos["patients"].soft_delete(patient.patient_id, actor="tester",
                                         device_id="server")
    response = client.get(
        f"/api/sync/pull?since={start}&device_id=workstation-A",
        headers=auth,
    )
    assert response.status_code == 200
    rows = response.json()["patients"]
    tombstone = next(row for row in rows
                     if row["patient_number"] == patient.patient_number)
    assert tombstone["deleted"] == 1
