"""Signup, temporary access, and Google verification."""

from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest


# --------------------------------------------------------------------------- #
# signup


def test_first_signup_becomes_admin(client, repos):
    # a fresh database: drop the seeded fixture user first
    repos["users"].db.execute("DELETE FROM users")
    response = client.post("/api/auth/signup", json={
        "username": "owner", "display_name": "Doc",
        "password": "longenough1"})
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "administrator"


def test_second_signup_is_viewer(client, admin_user):
    response = client.post("/api/auth/signup", json={
        "username": "second", "display_name": "Second",
        "password": "longenough1"})
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "viewer"


def test_duplicate_signup_rejected(client, admin_user):
    response = client.post("/api/auth/signup", json={
        "username": "admin", "display_name": "X", "password": "longenough1"})
    assert response.status_code == 400


def test_short_password_rejected_at_signup(client, admin_user):
    response = client.post("/api/auth/signup", json={
        "username": "shorty", "display_name": "X", "password": "short"})
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# temporary users


def test_temp_user_lifecycle_and_scope(client, auth, repos):
    p1 = client.post("/api/patients", headers=auth,
                     json={"name": "In Scope"}).json()
    p2 = client.post("/api/patients", headers=auth,
                     json={"name": "Out of Scope"}).json()

    created = client.post("/api/temp-users", headers=auth, json={
        "label": "Consultant", "hours": 2, "patient_ids": [p1["patient_id"]]})
    assert created.status_code == 201
    guest = created.json()

    login = client.post("/api/auth/login", json={
        "username": guest["username"], "password": guest["password"]})
    assert login.status_code == 200
    guest_auth = {"Authorization": f"Bearer {login.json()['token']}"}

    # scoped search sees only the allowed patient
    results = client.get("/api/patients", headers=guest_auth).json()
    assert [r["patient_id"] for r in results] == [p1["patient_id"]]

    # out-of-scope direct access is 403
    assert client.get(f"/api/patients/{p2['patient_id']}",
                      headers=guest_auth).status_code == 403
    # writes are forbidden
    assert client.post("/api/patients", headers=guest_auth,
                       json={"name": "Nope"}).status_code == 403

    # revocation cuts the live session
    listing = client.get("/api/temp-users", headers=auth).json()
    assert client.delete(f"/api/temp-users/{listing[0]['id']}",
                         headers=auth).json()["ok"] is True
    assert client.get("/api/patients", headers=guest_auth).status_code == 401


def test_expired_temp_user_refused_at_login(client, auth, repos):
    created = client.post("/api/temp-users", headers=auth, json={
        "label": "Short window", "hours": 1, "patient_ids": [1]}).json()
    user = repos["users"].get_by_username(created["username"])
    repos["users"].db.execute(
        "UPDATE users SET expires_at = ? WHERE user_id = ?",
        ("2020-01-01T00:00:00", user.user_id))
    response = client.post("/api/auth/login", json={
        "username": created["username"], "password": created["password"]})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_temp_user_requires_users_manage(client, repos, admin_user):
    from app.errors import AuthorizationError
    from app.services.security import SecurityService
    service = SecurityService(repos["users"])
    viewer = service.signup("plainview", "Plain View", "longenough1")
    with pytest.raises(AuthorizationError):
        service.create_temporary_user(viewer, "x", 1, [1])


def test_temp_user_validation(client, auth):
    assert client.post("/api/temp-users", headers=auth, json={
        "label": "No patients", "hours": 2, "patient_ids": []}).status_code == 400
    assert client.post("/api/temp-users", headers=auth, json={
        "label": "Too long", "hours": 10_000, "patient_ids": [1]}).status_code == 400


# --------------------------------------------------------------------------- #
# google token verification (local RSA key, no network)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_google_token_verification(tmp_path):
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding as apad, rsa

    import app.server.google as google

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = priv.private_numbers()
    n_int = numbers.public_numbers.n
    e_int = numbers.public_numbers.e
    kid = "test-key"

    cache = tmp_path / "jwks.json"
    cache.write_text(json.dumps({"keys": [dict(
        kty="RSA", alg="RS256", use="sig", kid=kid,
        n=_b64(n_int.to_bytes((n_int.bit_length() + 7) // 8, "big")),
        e=_b64(e_int.to_bytes(3, "big")))]}))

    payload = {"sub": "abc", "email": "doc@clinic.test", "email_verified": True,
               "name": "Doc", "aud": "my-client",
               "iss": "https://accounts.google.com",
               "exp": int(time.time()) + 600}
    signing_input = f"{_b64(json.dumps({'alg': 'RS256', 'kid': kid}).encode())}." \
                    f"{_b64(json.dumps(payload).encode())}".encode()
    signature = priv.sign(signing_input, apad.PKCS1v15(), hashes.SHA256())
    token = f"{signing_input.decode()}.{_b64(signature)}"

    info = google.verify_google_token(token, "my-client", jwks_cache=cache)
    assert info["email"] == "doc@clinic.test"

    # unverified-email and wrong-audience tokens are rejected
    payload_bad = dict(payload, aud="other-client")
    bad_input = f"{signing_input.decode().split('.')[0]}." \
                f"{_b64(json.dumps(payload_bad).encode())}".encode()
    bad_sig = priv.sign(bad_input, apad.PKCS1v15(), hashes.SHA256())
    with pytest.raises(google.GoogleAuthError):
        google.verify_google_token(f"{bad_input.decode()}.{_b64(bad_sig)}",
                                   "my-client", jwks_cache=cache)

    payload_unverified = dict(payload, email_verified=False)
    unv_input = f"{signing_input.decode().split('.')[0]}." \
                f"{_b64(json.dumps(payload_unverified).encode())}".encode()
    unv_sig = priv.sign(unv_input, apad.PKCS1v15(), hashes.SHA256())
    with pytest.raises(google.GoogleAuthError):
        google.verify_google_token(f"{unv_input.decode()}.{_b64(unv_sig)}",
                                   "my-client", jwks_cache=cache)


def test_auth_config_endpoint(client):
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    body = response.json()
    assert body["google_enabled"] is False
    assert body["open_signup"] is True
