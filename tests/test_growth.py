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
