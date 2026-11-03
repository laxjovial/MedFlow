"""Browser cookie-session contract and desktop bearer compatibility tests."""

from __future__ import annotations

WEB = {
    "X-MedFlow-Web-Session": "1",
    "Origin": "http://testserver",
}


def _browser_login(client, username="admin", password="password123"):
    response = client.post(
        "/api/auth/login",
        headers=WEB,
        json={"username": username, "password": password, "remember": False},
    )
    assert response.status_code == 200, response.text
    return response


def _csrf(client):
    return client.cookies.get("medflow_csrf")


def test_browser_login_sets_httponly_session_and_signed_csrf_cookie(client):
    response = _browser_login(client)
    assert "token" not in response.json()
    assert response.json()["user"]["id"]
    cookies = response.headers.get_list("set-cookie")
    session = next(value for value in cookies if value.startswith("medflow_session="))
    csrf = next(value for value in cookies if value.startswith("medflow_csrf="))
    assert "httponly" in session.lower()
    assert "samesite=lax" in session.lower()
    assert "httponly" not in csrf.lower()
    assert _csrf(client)


def test_browser_cookie_authenticates_protected_get(client):
    _browser_login(client)
    response = client.get("/api/patients", headers={"X-MedFlow-Web-Session": "1"})
    assert response.status_code == 200


def test_cookie_auth_rejects_missing_or_mismatched_csrf(client):
    _browser_login(client)
    missing = client.post(
        "/api/patients",
        headers={"X-MedFlow-Web-Session": "1"},
        json={"name": "Blocked"},
    )
    assert missing.status_code == 403

    mismatch = client.post(
        "/api/patients",
        headers={"X-MedFlow-Web-Session": "1", "X-CSRF-Token": "attacker"},
        json={"name": "Blocked"},
    )
    assert mismatch.status_code == 403


def test_cookie_auth_accepts_valid_csrf_for_mutation(client):
    _browser_login(client)
    response = client.post(
        "/api/patients",
        headers={
            "X-MedFlow-Web-Session": "1",
            "X-CSRF-Token": _csrf(client),
        },
        json={"name": "Browser Patient"},
    )
    assert response.status_code == 201


def test_bearer_api_auth_does_not_require_csrf(client, auth):
    response = client.post(
        "/api/patients",
        headers=auth,
        json={"name": "Desktop API Patient"},
    )
    assert response.status_code == 201


def test_invalid_bearer_does_not_fall_back_to_valid_browser_cookie(client):
    _browser_login(client)
    response = client.get(
        "/api/patients",
        headers={
            "X-MedFlow-Web-Session": "1",
            "Authorization": "Bearer invalid-token",
        },
    )
    assert response.status_code == 401


def test_browser_login_rejects_cross_origin_submission(client):
    response = client.post(
        "/api/auth/login",
        headers={
            "X-MedFlow-Web-Session": "1",
            "Origin": "https://attacker.example",
        },
        json={"username": "admin", "password": "password123"},
    )
    assert response.status_code == 403
    assert "medflow_session" not in client.cookies


def test_browser_refresh_rotates_both_cookies_without_returning_token(client):
    _browser_login(client)
    old_csrf = _csrf(client)
    response = client.post(
        "/api/auth/refresh",
        headers={
            "X-MedFlow-Web-Session": "1",
            "X-CSRF-Token": old_csrf,
        },
    )
    assert response.status_code == 200
    assert "token" not in response.json()
    assert _csrf(client) != old_csrf


def test_browser_logout_requires_auth_and_clears_both_cookies(client):
    _browser_login(client)
    response = client.post(
        "/api/auth/logout",
        headers={
            "X-MedFlow-Web-Session": "1",
            "X-CSRF-Token": _csrf(client),
        },
    )
    assert response.status_code == 200
    assert client.cookies.get("medflow_session") is None
    assert client.cookies.get("medflow_csrf") is None
    denied = client.get("/api/patients", headers={"X-MedFlow-Web-Session": "1"})
    assert denied.status_code == 401


def test_browser_identity_includes_live_permissions(client):
    _browser_login(client)
    response = client.get("/api/auth/me", headers={"X-MedFlow-Web-Session": "1"})
    assert response.status_code == 200
    assert "patients.view" in response.json()["permissions"]



def test_logout_revokes_a_copied_cookie_token(client):
    _browser_login(client)
    token = client.cookies.get("medflow_session")
    csrf = _csrf(client)
    logout = client.post(
        "/api/auth/logout",
        headers={"X-MedFlow-Web-Session": "1", "X-CSRF-Token": csrf},
    )
    assert logout.status_code == 200

    # Simulate a copied credential being replayed after logout.
    replay = client.get(
        "/api/patients", headers={"Authorization": f"Bearer {token}"}
    )
    assert replay.status_code == 401


def test_refresh_revokes_the_previous_cookie_token(client):
    _browser_login(client)
    old_token = client.cookies.get("medflow_session")
    old_csrf = _csrf(client)
    refreshed = client.post(
        "/api/auth/refresh",
        headers={"X-MedFlow-Web-Session": "1", "X-CSRF-Token": old_csrf},
    )
    assert refreshed.status_code == 200
    new_token = client.cookies.get("medflow_session")
    assert new_token != old_token

    # Replay through the bearer contract so the test exercises the token's
    # jti registry directly, without relying on cookie-jar replacement rules.
    replay = client.get(
        "/api/patients", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert replay.status_code == 401

    accepted = client.get(
        "/api/patients", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert accepted.status_code == 200


def test_account_deactivation_permanently_revokes_existing_sessions(
    client, repos, admin_user, auth
):
    from app.services.security import SecurityService

    viewer = SecurityService(repos["users"]).create_user(
        "session-viewer", "Session Viewer", "password123", "viewer"
    )
    _browser_login(client, viewer.username, "password123")
    old_token = client.cookies.get("medflow_session")
    old_csrf = _csrf(client)

    disabled = client.patch(
        f"/api/org/users/{viewer.user_id}",
        headers=auth,
        json={"active": False},
    )
    assert disabled.status_code == 200, disabled.text
    reenabled = client.patch(
        f"/api/org/users/{viewer.user_id}",
        headers=auth,
        json={"active": True},
    )
    assert reenabled.status_code == 200, reenabled.text

    # Reactivating the account must not resurrect credentials issued before
    # deactivation.
    client.cookies.set("medflow_session", old_token)
    client.cookies.set("medflow_csrf", old_csrf)
    replay = client.get("/api/patients", headers={"X-MedFlow-Web-Session": "1"})
    assert replay.status_code == 401


def test_temporary_account_expiry_invalidates_an_existing_cookie_session(
    client, repos, admin_user, patient
):
    from datetime import timedelta
    from app.services.security import SecurityService
    from app.utils.dates import to_iso, utcnow

    security = SecurityService(repos["users"])
    guest, password = security.create_temporary_user(
        admin_user, "Temporary visitor", 2, [patient.patient_id],
        password="temporary-pass-123",
    )
    _browser_login(client, guest.username, password)
    guest = repos["users"].get(guest.user_id)
    guest.expires_at = to_iso(utcnow() - timedelta(minutes=1))
    repos["users"].update(guest, ["expires_at"])

    response = client.get("/api/patients", headers={"X-MedFlow-Web-Session": "1"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_desktop_pairing_redemption_issues_independent_registered_bearer(client):
    _browser_login(client)
    code_response = client.post(
        "/api/pairing/code",
        headers={
            "X-MedFlow-Web-Session": "1",
            "X-CSRF-Token": _csrf(client),
        },
        json={"label": "Test desktop"},
    )
    assert code_response.status_code == 201, code_response.text

    redeemed = client.post(
        "/api/pairing/redeem",
        json={"code": code_response.json()["code"], "device_id": "test-desktop"},
    )
    assert redeemed.status_code == 200, redeemed.text
    token = redeemed.json()["token"]

    # The paired desktop bearer remains independent of browser cookie logout.
    logout = client.post(
        "/api/auth/logout",
        headers={
            "X-MedFlow-Web-Session": "1",
            "X-CSRF-Token": _csrf(client),
        },
    )
    assert logout.status_code == 200
    desktop_response = client.get(
        "/api/patients", headers={"Authorization": f"Bearer {token}"}
    )
    assert desktop_response.status_code == 200


def test_session_registry_migration_upgrades_schema_v5_to_v6(db):
    from app.storage.engine import connect

    connection = db.connection()
    connection.execute("DROP TABLE auth_sessions")
    connection.execute("PRAGMA user_version = 5")
    connection.commit()
    db.close()

    migrated = connect(db.db_path)
    try:
        version = migrated.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row["name"]
            for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert version == 7
        assert {"auth_sessions", "sync_conflicts"} <= tables
    finally:
        migrated.close()
