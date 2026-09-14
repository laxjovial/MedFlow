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


def test_sync_pull_returns_patients(client, auth, patient):
    response = client.get("/api/sync/pull", headers=auth)
    numbers = [p["patient_number"] for p in response.json()["patients"]]
    assert patient.patient_number in numbers


def test_index_page_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "MedFlow" in response.text
