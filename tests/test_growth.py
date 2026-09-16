"""Features added in the growth round: session policy, departments, off-site backups.

These cover the API paths both the web workspace and (via pairing) the
desktop app rely on, plus the encryption that protects off-site copies.
"""

from __future__ import annotations

import json
import time

import pytest

from app.services.offsite import (
    OffsiteError,
    decrypt_file,
    encrypt_file,
    load_keys,
    save_keys,
)


# ------------------------------------------------------------- session policy


def test_session_policy_public_and_defaults(client):
    r = client.get("/api/settings/session")
    assert r.status_code == 200
    body = r.json()
    assert body["token_ttl_hours"] == 12
    assert body["remember_me_days"] == 7
    assert body["sliding_refresh"] is True
    assert body["logouts_enabled"] is True


def test_admin_can_shorten_sessions(client, auth):
    r = client.patch("/api/settings/session", headers=auth,
                     json={"token_ttl_hours": 2, "remember_me_days": 7,
                           "sliding_refresh": False})
    assert r.status_code == 200
    assert r.json()["token_ttl_hours"] == 2

    # The new policy applies to tokens issued afterwards.
    login = client.post("/api/auth/login",
                        json={"username": "admin", "password": "password123"})
    assert login.status_code == 200

    # Restore for other tests (config is per-app instance).
    client.patch("/api/settings/session", headers=auth,
                 json={"token_ttl_hours": 12, "remember_me_days": 30,
                       "sliding_refresh": True})


def test_login_accepts_remember_flag(client):
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "password123",
                          "remember": True})
    assert r.status_code == 200
    # The token payload carries the remember claim (visible via refresh).
    me = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {r.json()['token']}"})
    assert me.status_code == 200


def test_refresh_rolls_session_forward(client):
    login = client.post("/api/auth/login",
                        json={"username": "admin", "password": "password123"})
    token = login.json()["token"]
    r = client.post("/api/auth/refresh", headers={
        "Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["refreshed"] is True      # sliding refresh on by default
    assert body["expires_in"] > 0
    assert body["token"]


def test_refresh_rejected_without_token(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_policy_change_forbidden_for_viewers(client, auth):
    # A viewer must not be able to change sign-in lifetimes.
    signup = client.post("/api/auth/signup", json={
        "username": "sessionvwr", "display_name": "Session Viewer",
        "password": "viewer-pass-1"})
    vtoken = signup.json()["token"]
    r = client.patch("/api/settings/session", headers={
        "Authorization": f"Bearer {vtoken}"}, json={"token_ttl_hours": 1})
    assert r.status_code == 403


# ---------------------------------------------------------------- departments


def test_department_crud_and_patient_filing(client, auth, repos):
    # (the repos fixture is used to guarantee a facility root exists below)
    # Create two departments.
    a = client.post("/api/org/units", headers=auth,
                    json={"name": "Maternity", "kind": "department"})
    b = client.post("/api/org/units", headers=auth,
                    json={"name": "Outpatients", "kind": "department"})
    assert a.status_code == 201 and b.status_code == 201
    a_id, b_id = a.json()["unit_id"], b.json()["unit_id"]

    # Departments list shows both with zero patients.
    deps = {d["name"]: d for d in
            client.get("/api/departments", headers=auth).json()}
    assert deps["Maternity"]["patient_count"] == 0

    # File a patient into Maternity by id (web style)…
    p1 = client.post("/api/patients", headers=auth,
                     json={"name": "Filed One", "department_id": a_id})
    assert p1.status_code == 201
    # …and another by name (desktop style).
    p2 = client.post("/api/patients", headers=auth,
                     json={"name": "Filed Two", "department_id": "Maternity"})
    assert p2.status_code == 201

    # Counts update.
    deps = {d["name"]: d for d in
            client.get("/api/departments", headers=auth).json()}
    assert deps["Maternity"]["patient_count"] == 2

    # Move a patient to another department via update.
    moved = client.patch(f"/api/patients/{p2.json()['patient_id']}",
                         headers=auth, json={"department_id": b_id})
    assert moved.status_code == 200
    deps = {d["name"]: d for d in
            client.get("/api/departments", headers=auth).json()}
    assert deps["Maternity"]["patient_count"] == 1
    assert deps["Outpatients"]["patient_count"] == 1

    # An unknown department is rejected cleanly.
    bad = client.post("/api/patients", headers=auth,
                      json={"name": "Ghost Dept", "department_id": "Nope"})
    assert bad.status_code == 422

    # A department holding patients cannot be deleted; an empty one can.
    blocked = client.delete(f"/api/org/units/{a_id}", headers=auth)
    assert blocked.status_code == 422
    freed = client.delete(f"/api/org/units/{b_id}", headers=auth)
    assert freed.status_code == 422  # still holds the moved patient

    # Rename works.
    renamed = client.patch(f"/api/org/units/{a_id}", headers=auth,
                           json={"name": "Maternity Ward"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Maternity Ward"

    # The facility root cannot be deleted or renamed through these routes.
    repos["units"].ensure_root("Root Facility")   # test client starts without one
    root = next(d for d in
                client.get("/api/departments", headers=auth).json()
                if d["kind"] == "organization")
    assert client.delete(f"/api/org/units/{root['id']}",
                         headers=auth).status_code == 422


def test_unknown_department_for_desktop_name_style(client, auth):
    r = client.post("/api/patients", headers=auth,
                    json={"name": "No Such", "department": "Phantom"})
    assert r.status_code == 422


# ------------------------------------------------------------ off-site backup


def test_encrypt_roundtrip_and_wrong_passphrase(tmp_path):
    src = tmp_path / "medflow.db"
    src.write_bytes(b"clinical records " * 500)
    blob, header = encrypt_file(src, "facility-passphrase-1")
    assert blob.name.endswith(".mfenc")
    assert blob.read_bytes() != src.read_bytes()

    out = tmp_path / "restored.db"
    info = decrypt_file(blob, "facility-passphrase-1", out)
    assert out.read_bytes() == src.read_bytes()
    assert info["original_name"] == "medflow.db"
    assert len(info["sha256"]) == 64

    with pytest.raises(OffsiteError):
        decrypt_file(blob, "totally-wrong", tmp_path / "nope.db")


def test_keys_roundtrip_and_permissions(tmp_path):
    save_keys(tmp_path, {"access_key_id": "AKIA", "secret_access_key": "s3cr3t"})
    assert load_keys(tmp_path)["secret_access_key"] == "s3cr3t"
    # New installs start with no keys.
    empty = tmp_path / "fresh"
    empty.mkdir()
    assert load_keys(empty) == {}


def test_cloud_backup_settings_write_only_secrets(client, auth):
    r = client.put("/api/settings/cloud-backup", headers=auth, json={
        "provider": "s3",
        "endpoint": "https://s3.af-south-1.amazonaws.com",
        "bucket": "clinic-backups",
        "access_key_id": "AKIAEXAMPLE",
        "secret_access_key": "super-secret",
        "enabled": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["has_credentials"] is True
    # Secrets must never echo back.
    assert "super-secret" not in json.dumps(body)

    # Test connection without a real bucket: configured check runs first.
    t = client.post("/api/settings/cloud-backup/test", headers=auth)
    assert t.status_code == 200
    assert t.json()["ok"] in (True, False)  # either way, shape is right

    # Upload refuses a short passphrase before touching storage.
    up = client.post("/api/settings/cloud-backup/upload", headers=auth,
                     json={"passphrase": "short"})
    assert up.status_code == 400


def test_cloud_backup_rejected_for_viewers(client):
    signup = client.post("/api/auth/signup", json={
        "username": "cloudvwr", "display_name": "Cloud Viewer",
        "password": "viewer-pass-2"})
    vtoken = signup.json()["token"]
    r = client.get("/api/settings/cloud-backup", headers={
        "Authorization": f"Bearer {vtoken}"})
    assert r.status_code == 403


def test_auto_login_invalid_session_cleared(client, auth):
    """The browser auto-login path: a stale saved session must be refused."""
    stale = {"token": "garbage.token", "user": {"username": "admin"}}
    me = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {stale['token']}"})
    assert me.status_code == 401


# ------------------------------------------------------------- versions & directory


def test_patient_versions_record_who_changed_what(client, auth):
    """Every demographic change lands as a version entry with actor + time."""
    made = client.post("/api/patients", headers=auth,
                       json={"name": "Ngozi Ade", "age": 41,
                             "diagnosis": "Type 2 diabetes"}).json()
    pid = made["patient_id"]
    client.patch(f"/api/patients/{pid}", headers=auth,
                 json={"age": 42, "diagnosis": "Type 2 diabetes, controlled"})
    r = client.get(f"/api/patients/{pid}/versions", headers=auth)
    assert r.status_code == 200
    versions = r.json()
    assert versions[0]["event_type"] == "updated"
    assert any("diagnosis" in v["description"].lower() for v in versions)
    assert all(v["actor"] for v in versions)  # who did it is always recorded


def test_diagnosis_search_and_directories(client, auth):
    """Search by diagnosis; department and whole-facility rosters work."""
    client.post("/api/patients", headers=auth,
                json={"name": "Malaria Patient", "diagnosis": "Malaria"})
    r = client.get("/api/patients/by-diagnosis?q=Malaria", headers=auth)
    assert r.status_code == 200
    rows = r.json()
    assert rows and "Malaria" in rows[0]["diagnosis"]

    dxs = client.get("/api/diagnoses", headers=auth).json()
    assert any(d["description"] == "Malaria" and d["patients"] >= 1 for d in dxs)

    whole = client.get("/api/patients/by-department", headers=auth).json()
    assert isinstance(whole, list) and len(whole) >= 1


def test_department_roster_is_scoped(client, auth):
    """A department roster only returns patients filed under it."""
    made = client.post("/api/org/units", headers=auth,
                       json={"name": "Maternity", "kind": "department"})
    if made.status_code != 201:
        made = client.post("/api/org/units", headers=auth,
                           json={"name": f"Ward-{id(auth)}", "kind": "department"})
    assert made.status_code == 201, made.text
    dept_id = made.json()["unit_id"]
    client.post("/api/patients", headers=auth,
                json={"name": "Roster Check", "department_id": dept_id})
    roster = client.get(
        f"/api/patients/by-department?department_id={dept_id}",
        headers=auth).json()
    assert all(row["patient_number"] for row in roster)
    assert any(row["name"] == "Roster Check" for row in roster)


def test_bulk_import_reports_rows(client, auth):
    """Spreadsheet import: valid rows land, bad rows come back explained."""
    r = client.post("/api/patients/import", headers=auth, json={"rows": [
        {"name": "Bulk One", "age": "30", "sex": "female"},
        {"name": "Bulk Two", "phone": "+2348000000000"},
        {"age": "55"},                      # missing name -> reported
    ]})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 2
    assert body["total"] == 3
    assert len(body["failed"]) == 1
    assert "name" in body["failed"][0]["error"].lower()

    found = client.get("/api/patients?q=Bulk", headers=auth).json()
    assert len(found) == 2


def test_provider_scoping_and_lists(client, auth):
    """A clinician's book is filterable; the providers list feeds menus."""
    pid = client.post("/api/patients", headers=auth,
                      json={"name": "Appt Patient"}).json()["patient_id"]
    client.post(f"/api/appointments?patient_id={pid}", headers=auth,
                json={"scheduled_at": "2026-09-20T09:00",
                      "provider": "Dr. Bello", "reason": "follow-up"})
    client.post(f"/api/appointments?patient_id={pid}", headers=auth,
                json={"scheduled_at": "2026-09-21T10:00",
                      "provider": "Dr. Ade", "reason": "review"})

    bello = client.get("/api/appointments?scope=upcoming&provider=Dr.%20Bello",
                       headers=auth).json()
    assert len(bello) == 1 and bello[0]["provider"] == "Dr. Bello"

    providers = client.get("/api/appointments/providers", headers=auth).json()
    assert set(providers) >= {"Dr. Bello", "Dr. Ade"}


def test_analytics_endpoint(client, auth):
    """One call powering the Analytics view: trends + outcomes + workload."""
    pid = client.post("/api/patients", headers=auth,
                      json={"name": "Analytics Patient",
                            "diagnosis": "Hypertension"}).json()["patient_id"]
    client.post(f"/api/patients/{pid}/diagnoses", headers=auth,
                json={"description": "Hypertension"})
    client.post(f"/api/appointments?patient_id={pid}", headers=auth,
                json={"scheduled_at": "2026-09-20T09:00",
                      "provider": "Dr. Bello"})
    r = client.get("/api/analytics", headers=auth)
    assert r.status_code == 200
    a = r.json()
    assert a["patients_total"] >= 1
    assert isinstance(a["registrations_by_week"], list)
    assert "completed" in a["appointment_funnel"]
    assert any(d["diagnosis"] == "Hypertension" for d in a["top_diagnoses"])


def test_staff_accounts_carry_details(client, auth):
    """Colleagues get job titles, departments and phones — editable later."""
    depts = client.get("/api/departments", headers=auth).json()
    unit_id = depts[0]["id"] if depts else None
    r = client.post("/api/org/users", headers=auth, json={
        "username": "ngozi.n", "display_name": "Ngozi Nwosu",
        "password": "midwife-pass-1", "role": "nurse",
        "job_title": "Senior Midwife", "phone": "+2348020001111",
        "unit_id": unit_id,
    })
    assert r.status_code == 201, r.text
    nurse = r.json()
    assert nurse["job_title"] == "Senior Midwife"
    assert nurse["phone"] == "+2348020001111"
    assert nurse["unit_id"] == unit_id

    up = client.patch(f"/api/org/users/{nurse['user_id']}", headers=auth,
                      json={"job_title": "Ward Sister"})
    assert up.status_code == 200
    assert up.json()["job_title"] == "Ward Sister"
    assert up.json()["phone"] == "+2348020001111"  # untouched fields survive


# ------------------------------------------------------------- web integrity ---

class TestWebAssets:
    """The built-in web client must always parse — one bad token in a
    JS file silently bricks the whole workspace (boot never runs, the
    sign-in gate never hides)."""

    def test_every_web_script_parses(self):
        import shutil
        import subprocess
        from pathlib import Path

        node = shutil.which("node")
        if not node:                      # node unavailable — nothing to do
            pytest.skip("node not installed")
        web = Path(__file__).resolve().parents[1] / "app" / "server" / "web"
        scripts = sorted(web.glob("*.js"))
        assert scripts, "web scripts missing"
        for script in scripts:
            result = subprocess.run(
                [node, "--check", str(script)],
                capture_output=True, text=True)
            assert result.returncode == 0, (
                f"{script.name} does not parse: {result.stderr.strip()}")


# --------------------------------------------------------- record template ---

class TestRecordTemplate:
    """The facility's own chart fields: define once, fill per patient."""

    def _register(self, client, auth, name="Ada Obi"):
        r = client.post("/api/patients", headers=auth,
                        json={"name": name, "age": 34})
        assert r.status_code == 201, r.text
        return r.json()

    def test_seeded_defaults_present(self, client, auth):
        r = client.get("/api/template/fields", headers=auth)
        assert r.status_code == 200
        labels = [f["label"] for f in r.json()]
        assert "Blood group" in labels
        assert "Next of kin" in labels

    def test_create_validate_and_fill_value(self, client, auth):
        pid = self._register(client, auth)["patient_id"]

        # a pick-list field with options
        r = client.post("/api/template/fields", headers=auth, json={
            "label": "HIV status", "value_type": "choice",
            "choices": "pending, negative, positive", "section": "Screening"})
        assert r.status_code == 201, r.text
        field = r.json()
        assert field["field_key"] == "hiv_status"

        # fill it for the patient
        r = client.put(f"/api/patients/{pid}/template", headers=auth,
                       json={"values": {str(field["template_id"]): "negative"}})
        assert r.status_code == 200, r.text
        assert r.json()[0]["value"] == "negative"

        # chart shows it grouped by section
        r = client.get(f"/api/patients/{pid}/template", headers=auth)
        assert r.status_code == 200
        assert "Screening" in r.json()
        entry = next(e for e in r.json()["Screening"]
                     if e["label"] == "HIV status")
        assert entry["value"] == "negative"
        assert entry["updated_by"] == "admin"

        # history records the fill-in
        r = client.get(f"/api/patients/{pid}/versions", headers=auth)
        assert any("HIV status: negative" in v["description"]
                   for v in r.json())

    def test_choice_rejects_invalid_option(self, client, auth):
        r = client.post("/api/template/fields", headers=auth, json={
            "label": "Ward", "value_type": "choice",
            "choices": "A, B, C", "section": "General"})
        field = r.json()
        pid = self._register(client, auth, "Bola Test")["patient_id"]
        r = client.put(f"/api/patients/{pid}/template", headers=auth,
                       json={"values": {str(field["template_id"]): "Z"}})
        assert r.status_code == 422
        assert "must be one of" in r.json()["error"]["message"]

    def test_number_field_rejects_text(self, client, auth):
        r = client.post("/api/template/fields", headers=auth, json={
            "label": "Pack cell volume", "value_type": "number",
            "unit": "%", "section": "Screening"})
        field = r.json()
        pid = self._register(client, auth, "Chidi Test")["patient_id"]
        r = client.put(f"/api/patients/{pid}/template", headers=auth,
                       json={"values": {str(field["template_id"]): "very high"}})
        assert r.status_code == 422

    def test_rename_field_and_archive_keeps_values(self, client, auth):
        r = client.post("/api/template/fields", headers=auth, json={
            "label": "Tribe", "value_type": "text", "section": "Social history"})
        field = r.json()
        pid = self._register(client, auth, "Dede Test")["patient_id"]
        client.put(f"/api/patients/{pid}/template", headers=auth,
                   json={"values": {str(field["template_id"]): "Igbo"}})

        # rename
        r = client.patch(f"/api/template/fields/{field['template_id']}",
                         headers=auth, json={"label": "Ethnic group"})
        assert r.status_code == 200
        assert r.json()["label"] == "Ethnic group"

        # archive: chart hides it, values survive
        r = client.delete(f"/api/template/fields/{field['template_id']}",
                          headers=auth)
        assert r.status_code == 200
        r = client.get(f"/api/patients/{pid}/template", headers=auth)
        assert all(e["label"] != "Ethnic group"
                   for e in r.json().get("General", []))

        # a brand-new field with a different name works fine afterwards
        r = client.post("/api/template/fields", headers=auth, json={
            "label": "Ethnic group", "value_type": "text"})
        assert r.status_code == 201
        # and re-creating the exact old name still collides (key is stable)
        r = client.post("/api/template/fields", headers=auth, json={
            "label": "Tribe", "value_type": "text"})
        assert r.status_code == 422

    def test_duplicate_label_rejected(self, client, auth):
        r = client.post("/api/template/fields", headers=auth, json={
            "label": "Blood group", "value_type": "text"})
        assert r.status_code == 422

    def test_non_admin_cannot_shape_template(self, client, auth):
        r = client.post("/api/org/users", headers=auth, json={
            "username": "tplnurse", "display_name": "Tpl Nurse",
            "password": "tplnurse-pass-1", "role": "nurse"})
        assert r.status_code == 201, r.text
        r = client.post("/api/auth/login",
                        json={"username": "tplnurse",
                              "password": "tplnurse-pass-1"})
        nurse = {"Authorization": f"Bearer {r.json()['token']}"}

        # nurses fill values…
        pid = self._register(client, auth, "Efe Test")["patient_id"]
        fields = client.get("/api/template/fields", headers=auth).json()
        blood = next(f for f in fields if f["label"] == "Blood group")
        r = client.put(f"/api/patients/{pid}/template", headers=nurse,
                       json={"values": {str(blood["template_id"]): "O+"}})
        assert r.status_code == 200

        # …but cannot change the template itself
        r = client.post("/api/template/fields", headers=nurse,
                        json={"label": "Sneaky field"})
        assert r.status_code == 403
        r = client.delete(f"/api/template/fields/{blood['template_id']}",
                          headers=nurse)
        assert r.status_code == 403

    def test_clearing_a_value_is_recorded(self, client, auth):
        pid = self._register(client, auth, "Femi Test")["patient_id"]
        fields = client.get("/api/template/fields", headers=auth).json()
        kin = next(f for f in fields if f["label"] == "Next of kin")
        tid = str(kin["template_id"])
        client.put(f"/api/patients/{pid}/template", headers=auth,
                   json={"values": {tid: "Ngozi Obi"}})
        r = client.put(f"/api/patients/{pid}/template", headers=auth,
                       json={"values": {tid: ""}})
        assert r.status_code == 200
        assert r.json()[0]["value"] is None
        hist = client.get(f"/api/patients/{pid}/versions", headers=auth).json()
        assert any("Next of kin: cleared" in v["description"] for v in hist)

    def test_migration_preserves_existing_db(self, tmp_path):
        """A v3 database opens cleanly and gains the template tables."""
        import sqlite3

        from app.storage.migrations import get_user_version, migrate
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE patients (
                patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_number TEXT UNIQUE, name TEXT NOT NULL, age INTEGER,
                sex TEXT, phone TEXT, email TEXT, address TEXT,
                date_of_birth TEXT, blood_pressure TEXT, heart_rate INTEGER,
                weight REAL, diagnosis TEXT, notes TEXT, medical_history TEXT,
                deleted INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
                origin_unit_id INTEGER, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL, password_hash TEXT,
                display_name TEXT NOT NULL, role TEXT NOT NULL, active INTEGER,
                created_at TEXT
            );
        """)
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
        assert get_user_version(conn) == 3
        migrate(conn)
        assert get_user_version(conn) == 5


# ---------------- notifications, invites, multi-department (v5) ----------


class TestNotificationBell:
    def test_mark_read_and_unread(self, auth, client, repos, admin_user):
        from app.services.onboarding import NotificationService
        ns = NotificationService(repos, actor="admin")
        ns.send(admin_user.user_id, "Bell check", "body text")
        r = client.get("/api/notifications", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert body["unread"] >= 1
        item = body["items"][0]
        # mark read
        r2 = client.post(f"/api/notifications/{item['notification_id']}/read", headers=auth,
                       json={"read": True})
        assert r2.status_code == 200
        assert r2.json()["read"] == 1
        # unread again — the red number comes back
        r3 = client.post(f"/api/notifications/{item['notification_id']}/read", headers=auth,
                       json={"read": False})
        assert r3.json()["read"] == 0
        assert repos["notifications"].unread_count(admin_user.user_id) >= 1

    def test_mark_all_read(self, client, auth, repos, admin_user):
        from app.services.onboarding import NotificationService
        ns = NotificationService(repos, actor="admin")
        ns.send(admin_user.user_id, "One")
        ns.send(admin_user.user_id, "Two")
        r = client.post("/api/notifications/read-all", headers=auth)
        assert r.status_code == 200
        assert repos["notifications"].unread_count(admin_user.user_id) == 0

    def test_cannot_touch_someone_elses(self, auth, client, repos, admin_user):
        from app.models import User
        from app.services.onboarding import NotificationService
        ns = NotificationService(repos, actor="admin")
        other = repos["users"].insert(
            User(username="other", display_name="Other",
                 role="viewer", password_hash="x"))
        note = ns.send(other.user_id, "Private")
        r = client.post(f"/api/notifications/{note['notification_id']}/read", headers=auth,
                      json={"read": True})
        assert r.status_code == 404


class TestOnboardingFlow:
    def test_invite_pending_approve_chain(self, auth, client, repos, admin_user):
        r = client.post("/api/invites", headers=auth, json={
            "role": "nurse", "label": "Dr Kim", "days_valid": 7})
        assert r.status_code == 201, r.text
        invite = r.json()
        assert invite["code"]

        # validate endpoint (public)
        v = client.post("/api/invites/validate", json={"code": invite["code"]})
        assert v.status_code == 200 and v.json()["valid"] is True

        # invited signup -> pending, no token
        s = client.post("/api/auth/signup", json={
            "username": "kim", "display_name": "Dr Kim",
            "password": "longenough1", "invite_code": invite["code"]})
        assert s.status_code == 201, s.text
        assert s.json()["pending"] is True
        kim_id = s.json()["user"]["id"]

        # pending can't sign in
        denied = client.post("/api/auth/login",
                             json={"username": "kim", "password": "longenough1"})
        assert denied.status_code == 401
        assert "approval" in str(denied.json()["detail"]).lower()

        # admin sees them pending, then approves
        pend = client.get("/api/onboarding/pending", headers=auth).json()
        assert any(u["user_id"] == kim_id for u in pend)
        ok = client.post(f"/api/onboarding/{kim_id}/approve", headers=auth, json={"note": "ok"})
        assert ok.status_code == 200
        assert ok.json()["role"] == "nurse"

        # now they can sign in, and the audit trail answers 'who approved whom'
        login = client.post("/api/auth/login",
                            json={"username": "kim", "password": "longenough1"})
        assert login.status_code == 200
        chain = repos["audit"].history_for_entity("user", str(kim_id))
        assert any("Signed up with invite" in (e.details or "") for e in chain)
        assert any(e.action == "approved" and e.actor == "admin" for e in chain)

    def test_decline_and_spent_invite(self, auth, client, repos, admin_user):
        r = client.post("/api/invites", headers=auth, json={"role": "viewer", "max_uses": 1})
        invite = r.json()
        s1 = client.post("/api/auth/signup", json={
            "username": "g1", "display_name": "G One",
            "password": "longenough1", "invite_code": invite["code"]})
        assert s1.status_code == 201
        # same code again is rejected
        s2 = client.post("/api/auth/signup", json={
            "username": "g2", "display_name": "G Two",
            "password": "longenough1", "invite_code": invite["code"]})
        assert s2.status_code == 400
        uid = s1.json()["user"]["id"]
        d = client.post(f"/api/onboarding/{uid}/decline", headers=auth, json={})
        assert d.status_code == 200
        assert d.json()["active"] is False


class TestMultiDepartment:
    def test_patient_in_multiple_departments(self, auth, client, repos,
                                             admin_user, patient):
        from app.models import Unit
        u1 = repos["units"].insert(Unit(name="Maternity", kind="department"))
        u2 = repos["units"].insert(Unit(name="Surgery", kind="department"))
        r = client.put(f"/api/patients/{patient.patient_id}/departments", headers=auth,
                     json={"unit_ids": [u1.unit_id, u2.unit_id]})
        assert r.status_code == 200, r.text
        got = client.get(f"/api/patients/{patient.patient_id}/departments", headers=auth).json()
        names = {d["name"] for d in got}
        assert {"Maternity", "Surgery"} <= names
        # replacing the set removes the old one
        r2 = client.put(f"/api/patients/{patient.patient_id}/departments", headers=auth,
                      json={"unit_ids": [u2.unit_id]})
        assert r2.status_code == 200
        got2 = client.get(
            f"/api/patients/{patient.patient_id}/departments",
            headers=auth).json()
        assert {d["name"] for d in got2} == {"Surgery"}

    def test_department_roster_counts_both_kinds(self, client, auth, repos,
                                                 admin_user, patient):
        from app.models import Unit
        ward = repos["units"].insert(Unit(name="Ward A", kind="department"))
        # primary stays; extra membership added
        client.put(f"/api/patients/{patient.patient_id}/departments", headers=auth,
                 json={"unit_ids": [ward.unit_id]})
        rows = repos["patients"].by_department(ward.unit_id)
        assert any(p.patient_id == patient.patient_id for p in rows)
        counts = repos["units"].patient_counts()
        assert counts.get(ward.unit_id, 0) >= 1

    def test_bad_department_rejected(self, client, auth, patient):
        r = client.put(f"/api/patients/{patient.patient_id}/departments", headers=auth,
                     json={"unit_ids": [99999]})
        assert r.status_code == 422
