"""Browser cookie and CSRF helpers.

Bearer tokens remain the API/desktop contract. Browser sessions use the same
signed token in an HttpOnly cookie, paired with a session-bound CSRF cookie.
The CSRF value is HMAC-authenticated against the HttpOnly session token, so
an attacker who can only inject a cookie cannot mint a valid token.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response

SESSION_COOKIE = "medflow_session"
CSRF_COOKIE = "medflow_csrf"
WEB_SESSION_HEADER = "X-MedFlow-Web-Session"
CSRF_HEADER = "X-CSRF-Token"


def is_web_session_request(request: Request) -> bool:
    """Explicit opt-in used by first-party browser clients only."""
    return request.headers.get(WEB_SESSION_HEADER) == "1"


def _csrf_value(session_token: str, secret: bytes) -> str:
    nonce = secrets.token_urlsafe(32)
    message = f"medflow-csrf:v1:{session_token}:{nonce}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{nonce}.{signature}"


def valid_csrf(session_token: str, value: str, secret: bytes) -> bool:
    try:
        nonce, supplied = value.rsplit(".", 1)
    except (AttributeError, ValueError):
        return False
    if not nonce or not supplied:
        return False
    message = f"medflow-csrf:v1:{session_token}:{nonce}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def set_browser_session(
    response: Response, request: Request, token: str, ttl: int
) -> None:
    """Issue a fresh HttpOnly session cookie and session-bound CSRF cookie."""
    configured = getattr(getattr(request.app.state.config, "session", None), "cookie_secure", None)
    secure = request.url.scheme == "https" if configured is None else bool(configured)
    common = {
        "max_age": max(0, int(ttl)),
        "path": "/",
        "secure": secure,
        "httponly": False,
        "samesite": "lax",
    }
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, **{k: v for k, v in common.items() if k != "httponly"}
    )
    response.set_cookie(
        CSRF_COOKIE,
        _csrf_value(token, request.app.state.token_secret),
        **common,
    )


def clear_browser_session(response: Response, request: Request) -> None:
    secure = request.url.scheme == "https"
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax"
    )


def require_cookie_csrf(request: Request, session_token: str) -> None:
    """Require a valid session-bound double-submit token for unsafe methods."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    cookie_value = request.cookies.get(CSRF_COOKIE, "")
    header_value = request.headers.get(CSRF_HEADER, "")
    if (
        not cookie_value
        or not header_value
        or not hmac.compare_digest(cookie_value, header_value)
        or not valid_csrf(session_token, cookie_value, request.app.state.token_secret)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
