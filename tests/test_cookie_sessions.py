"""Browser cookie-session contract and desktop bearer compatibility tests."""

from __future__ import annotations

WEB = {
    "X-MedFlow-Web-Session": "1",
    "Origin": "http://testserver",
}


def _browser_login(client):
    response = client.post(
        "/api/auth/login",
        headers=WEB,
        json={"username": "admin", "password": "password123", "remember": False},
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
